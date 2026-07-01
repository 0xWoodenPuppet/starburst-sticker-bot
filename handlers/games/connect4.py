"""Connect 4 — rendering, win-check, AI, and move handler."""

import asyncio
import copy
import random
import time
from concurrent.futures import ThreadPoolExecutor

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .common import (
    _games, _safe_edit, _switch_turn, _render_game, _build_text, _build_markup,
    _save_game_history, save_active_game, delete_active_game,
    DIFF_LABELS, AI_MOVE_DELAY,
)

# ── Thread pool for CPU-intensive AI ──────────────────────────────────
_executor = ThreadPoolExecutor(max_workers=2)

# ── C4 symbols ────────────────────────────────────────────────────────
C4_SYMBOLS = {0: "⚪", 1: "🔴", 2: "🟡"}
C4_WIN_SYMBOLS = {1: "🟥", 2: "🟨"}
COL_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]

# ── Zobrist hashing for C4 transposition table (fixed seed) ───────────
_rng = random.Random(42)
_ZOBRIST = [[[_rng.getrandbits(64) for _ in range(3)] for _ in range(7)] for _ in range(6)]

_C4_DEPTH = 7
_C4_CENTER_ORDER = [3, 2, 4, 1, 5, 0, 6]


# ═══════════════════════════════════════════════════════════════════════
#  RENDERING
# ═══════════════════════════════════════════════════════════════════════

def _c4_build_text(game, game_over=False) -> str:
    parts = []
    header = "<b>Connect 4</b>"
    if game["vs_computer"] and game["difficulty"]:
        header += f" — {DIFF_LABELS.get(game['difficulty'], '')}"
    parts.append(header)
    parts.append("")
    if game_over:
        w = game["winner"]
        if w == "draw":
            parts.append("🤝 <b>Draw!</b>")
        else:
            name = game["player1_name"] if w == 1 else game["player2_name"]
            parts.append(f"🏆 <b>{name}</b>")
        parts.append("")
        parts.append(f"🔴 {game['player1_name']}")
        parts.append(f"🟡 {game['player2_name']}")
    else:
        parts.append(f"🔴 {game['player1_name']}")
        parts.append(f"🟡 {game['player2_name']}")
        parts.append("")
        if game["current_turn"] == 0:
            parts.append("turn: 🟡 Toothless")
        else:
            n = game["player1_name"] if game["current_player"] == 1 else game["player2_name"]
            s = "🔴" if game["current_player"] == 1 else "🟡"
            parts.append(f"turn: {s} {n}")
    return "\n".join(parts)


def _c4_build_markup(game, game_over=False) -> InlineKeyboardMarkup:
    board = game["board"]
    win_set = set(tuple(c) for c in (game.get("winning_cells") or []))
    rows = []
    for r in range(6):
        row = []
        for c in range(7):
            cell = board[r][c]
            if (r, c) in win_set:
                text = C4_WIN_SYMBOLS.get(cell, C4_SYMBOLS.get(cell, "⚪"))
            else:
                text = C4_SYMBOLS.get(cell, "⚪")
            
            if game_over:
                cb = "g_noop"
            elif board[0][c] != 0:
                cb = "c4_full"
            else:
                cb = f"c4_{c}"
            row.append(InlineKeyboardButton(text, callback_data=cb))
        rows.append(row)
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════
#  LOGIC
# ═══════════════════════════════════════════════════════════════════════

def _c4_drop(board, col: int, piece: int) -> int:
    """Drop piece into column. Returns the row it lands on."""
    for r in range(5, -1, -1):
        if board[r][col] == 0:
            board[r][col] = piece
            return r
    return -1


def _c4_test_drop(board, col: int) -> int:
    """Find row a piece WOULD land in (without placing)."""
    for r in range(5, -1, -1):
        if board[r][col] == 0:
            return r
    return -1


def _c4_valid_cols(board) -> list[int]:
    return [c for c in range(7) if board[0][c] == 0]


def _c4_check_winner(board):
    """Full scan. Returns (winner, winning_cells). Winner: 1, 2, 'draw', or None."""
    for r in range(6):
        for c in range(7):
            val = board[r][c]
            if val == 0:
                continue
            # Horizontal
            if c + 3 < 7 and all(board[r][c + i] == val for i in range(4)):
                return val, [(r, c + i) for i in range(4)]
            # Vertical
            if r + 3 < 6 and all(board[r + i][c] == val for i in range(4)):
                return val, [(r + i, c) for i in range(4)]
            # Diagonal ↘
            if r + 3 < 6 and c + 3 < 7 and all(board[r + i][c + i] == val for i in range(4)):
                return val, [(r + i, c + i) for i in range(4)]
            # Diagonal ↙
            if r + 3 < 6 and c - 3 >= 0 and all(board[r + i][c - i] == val for i in range(4)):
                return val, [(r + i, c - i) for i in range(4)]

    if all(board[0][c] != 0 for c in range(7)):
        return "draw", None
    return None, None


def _c4_check_win_at(board, r: int, c: int) -> bool:
    """Fast O(1) check: does the piece at (r, c) complete a 4-in-a-row?"""
    val = board[r][c]
    if val == 0:
        return False
    for dr, dc in [(0, 1), (1, 0), (1, 1), (1, -1)]:
        count = 1
        for sign in (1, -1):
            for i in range(1, 4):
                nr, nc = r + dr * sign * i, c + dc * sign * i
                if 0 <= nr < 6 and 0 <= nc < 7 and board[nr][nc] == val:
                    count += 1
                else:
                    break
        if count >= 4:
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════
#  AI
# ═══════════════════════════════════════════════════════════════════════

def _c4_ai_easy(board) -> int:
    return random.choice(_c4_valid_cols(board))


def _c4_ai_medium(board) -> int:
    valid = _c4_valid_cols(board)
    # Win
    for c in valid:
        r = _c4_test_drop(board, c)
        board[r][c] = 2
        if _c4_check_win_at(board, r, c):
            board[r][c] = 0
            return c
        board[r][c] = 0
    # Block
    for c in valid:
        r = _c4_test_drop(board, c)
        board[r][c] = 1
        if _c4_check_win_at(board, r, c):
            board[r][c] = 0
            return c
        board[r][c] = 0
    # Prefer center columns
    center = [c for c in _C4_CENTER_ORDER if c in valid]
    return random.choice(center[:3]) if center else random.choice(valid)


# ── C4 Evil AI (minimax + alpha-beta + transposition table) ───────────

def _c4_hash(board) -> int:
    h = 0
    for r in range(6):
        for c in range(7):
            h ^= _ZOBRIST[r][c][board[r][c]]
    return h


def _c4_evaluate(board) -> int:
    """Heuristic. Positive = good for P2 (AI)."""
    score = 0
    for r in range(6):
        for c in range(7):
            v = board[r][c]
            # Horizontal window
            if c + 3 < 7:
                score += _c4_score_window([board[r][c + i] for i in range(4)])
            # Vertical window
            if r + 3 < 6:
                score += _c4_score_window([board[r + i][c] for i in range(4)])
            # Diagonal ↘
            if r + 3 < 6 and c + 3 < 7:
                score += _c4_score_window([board[r + i][c + i] for i in range(4)])
            # Diagonal ↙
            if r + 3 < 6 and c - 3 >= 0:
                score += _c4_score_window([board[r + i][c - i] for i in range(4)])
    # Center column bonus
    for r in range(6):
        if board[r][3] == 2:
            score += 3
        elif board[r][3] == 1:
            score -= 3
    return score


def _c4_score_window(w) -> int:
    p1, p2, empty = w.count(1), w.count(2), w.count(0)
    if p2 == 4:
        return 1000
    if p1 == 4:
        return -1000
    if p2 == 3 and empty == 1:
        return 50
    if p2 == 2 and empty == 2:
        return 5
    if p1 == 3 and empty == 1:
        return -40
    if p1 == 2 and empty == 2:
        return -4
    return 0


def _c4_minimax(board, depth, alpha, beta, maximizing, tt) -> int:
    if depth == 0:
        return _c4_evaluate(board)

    valid = [c for c in _C4_CENTER_ORDER if board[0][c] == 0]
    if not valid:
        return 0  # draw — board full, no winner (checked before recursing)

    h = _c4_hash(board)
    tt_key = (h, depth, maximizing)
    if tt_key in tt:
        return tt[tt_key]

    if maximizing:
        best = float("-inf")
        for c in valid:
            r = _c4_test_drop(board, c)
            board[r][c] = 2
            if _c4_check_win_at(board, r, c):
                score = 100000 + depth
            else:
                score = _c4_minimax(board, depth - 1, alpha, beta, False, tt)
            board[r][c] = 0
            best = max(best, score)
            alpha = max(alpha, score)
            if beta <= alpha:
                break
    else:
        best = float("inf")
        for c in valid:
            r = _c4_test_drop(board, c)
            board[r][c] = 1
            if _c4_check_win_at(board, r, c):
                score = -100000 - depth
            else:
                score = _c4_minimax(board, depth - 1, alpha, beta, True, tt)
            board[r][c] = 0
            best = min(best, score)
            beta = min(beta, score)
            if beta <= alpha:
                break

    tt[tt_key] = best
    return best


def _c4_ai_evil_sync(board) -> int:
    """Synchronous minimax. Called via run_in_executor."""
    valid = [c for c in _C4_CENTER_ORDER if board[0][c] == 0]
    if not valid:
        return 0

    # Immediate win
    for c in valid:
        r = _c4_test_drop(board, c)
        board[r][c] = 2
        if _c4_check_win_at(board, r, c):
            board[r][c] = 0
            return c
        board[r][c] = 0

    # Block immediate opponent win
    for c in valid:
        r = _c4_test_drop(board, c)
        board[r][c] = 1
        if _c4_check_win_at(board, r, c):
            board[r][c] = 0
            return c
        board[r][c] = 0

    # Full search
    tt: dict = {}
    best_col, best_score = valid[0], float("-inf")
    alpha = float("-inf")

    for c in valid:
        r = _c4_test_drop(board, c)
        board[r][c] = 2
        if _c4_check_win_at(board, r, c):
            board[r][c] = 0
            return c
        score = _c4_minimax(board, _C4_DEPTH - 1, alpha, float("inf"), False, tt)
        board[r][c] = 0
        if score > best_score:
            best_score, best_col = score, c
        alpha = max(alpha, score)

    return best_col


# ═══════════════════════════════════════════════════════════════════════
#  MOVE HANDLER
# ═══════════════════════════════════════════════════════════════════════

async def _handle_c4_move(query, context):
    key = f"{query.message.chat_id}_{query.message.message_id}"
    game = _games.get(key)
    if game is None:
        await query.answer("This game has expired.", show_alert=True)
        return
    if game["winner"] is not None:
        await query.answer()
        return

    col = int(query.data.split("_")[1])  # c4_COL
    board = game["board"]

    if board[0][col] != 0:
        await query.answer("That column is full!", show_alert=True)
        return
    if game["current_turn"] == 0:
        await query.answer("Wait for the computer!", show_alert=True)
        return
    if query.from_user.id != game["current_turn"]:
        await query.answer("It's not your turn!", show_alert=True)
        return

    # Drop piece
    piece = game["current_player"]
    _c4_drop(board, col, piece)
    game["last_activity"] = time.time()

    w, wc = _c4_check_winner(board)
    if w:
        game["winner"] = "draw" if w == "draw" else w
        game["winning_cells"] = wc
        await query.answer()
        await _render_game(query, key, game, game_over=True)
        await _save_game_history(game)
        _games.pop(key, None)
        await delete_active_game(key)
        return

    _switch_turn(game)

    # Computer's turn
    if game["vs_computer"] and game["current_player"] == 2:
        game["current_turn"] = 0
        await query.answer()
        await _render_game(query, key, game)
        await asyncio.sleep(AI_MOVE_DELAY)

        # Pick AI move
        diff = game["difficulty"]
        if diff == "evil":
            board_copy = copy.deepcopy(board)
            loop = asyncio.get_running_loop()
            ai_col = await loop.run_in_executor(_executor, _c4_ai_evil_sync, board_copy)
        elif diff == "medium":
            ai_col = _c4_ai_medium(board)
        else:
            ai_col = _c4_ai_easy(board)

        _c4_drop(board, ai_col, 2)
        game["last_activity"] = time.time()

        w, wc = _c4_check_winner(board)
        if w:
            game["winner"] = "draw" if w == "draw" else w
            game["winning_cells"] = wc
            try:
                await _safe_edit(query.edit_message_text,
                    text=_build_text(game, True), reply_markup=_build_markup(game, True), parse_mode="HTML")
            except Exception:
                pass
            await _save_game_history(game)
            _games.pop(key, None)
            await delete_active_game(key)
            return

        _switch_turn(game)
        await save_active_game(key, game)
        try:
            await _safe_edit(query.edit_message_text,
                text=_build_text(game, False), reply_markup=_build_markup(game), parse_mode="HTML")
        except Exception:
            pass
        return

    await save_active_game(key, game)
    await query.answer()
    await _render_game(query, key, game)
