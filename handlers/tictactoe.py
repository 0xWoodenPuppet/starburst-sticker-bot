"""Games — /fight command handler.

Supports Tic Tac Toe and Connect 4 with:
  • Player vs Computer — Easy / Medium / Evil difficulty.
  • Player vs Player  (1v1) — groups only.

Game state is held in memory keyed by chat_id + message_id.
Game history is persisted to MongoDB on completion.
"""

import asyncio
import copy
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, RetryAfter
from telegram.ext import ContextTypes

from db import games as games_collection

logger = logging.getLogger(__name__)

# ── Thread pool for CPU-intensive AI ──────────────────────────────────
_executor = ThreadPoolExecutor(max_workers=2)

# ── In-memory stores ──────────────────────────────────────────────────
# Game state:  "chatId_msgId" -> game dict
_games: dict[str, dict] = {}
# Setup state: "chatId_msgId" -> (challenger_id, created_at)
_setup: dict[str, tuple[int, float]] = {}

# ── Constants ─────────────────────────────────────────────────────────
INACTIVITY_TIMEOUT = 300   # 5 minutes
AI_MOVE_DELAY = 0.5        # seconds before computer responds

DIFF_LABELS = {"easy": "😊 Easy", "medium": "😐 Medium", "evil": "Evil"}

# TTT symbols
TTT_SYMBOLS = {"X": "❌", "O": "⭕", None: "·"}

# C4 symbols
C4_SYMBOLS = {0: "⚪", 1: "🔴", 2: "🟡"}
C4_WIN_SYMBOLS = {1: "🟥", 2: "🟨"}
COL_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]

# Zobrist hashing for C4 transposition table (fixed seed for consistency)
_rng = random.Random(42)
_ZOBRIST = [[[_rng.getrandbits(64) for _ in range(3)] for _ in range(7)] for _ in range(6)]

_C4_DEPTH = 7
_C4_CENTER_ORDER = [3, 2, 4, 1, 5, 0, 6]


# ═══════════════════════════════════════════════════════════════════════
#  RATE-LIMIT WRAPPER
# ═══════════════════════════════════════════════════════════════════════

async def _safe_edit(edit_func, **kwargs):
    """Call a Telegram edit function with one RetryAfter retry."""
    try:
        await edit_func(**kwargs)
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            await edit_func(**kwargs)
        except Exception as ex:
            logger.error(f"Edit retry failed: {ex}")
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Edit failed: {e}")
    except Exception as e:
        logger.error(f"Edit failed: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  /fight COMMAND
# ═══════════════════════════════════════════════════════════════════════

async def fight_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/fight — Start a game."""
    user = update.effective_user
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Tic Tac Toe", callback_data="g_type_ttt"),
        InlineKeyboardButton("Connect 4", callback_data="g_type_c4"),
    ]])
    msg = await update.message.reply_text(
        "<b>choice✨</b>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    _setup[f"{msg.chat_id}_{msg.message_id}"] = (user.id, time.time())


# ═══════════════════════════════════════════════════════════════════════
#  CALLBACK ROUTER
# ═══════════════════════════════════════════════════════════════════════

async def game_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all game-related callbacks."""
    query = update.callback_query
    data = query.data or ""

    if data in ("g_noop", "ttt_noop"):
        await query.answer()
        return
    if data == "c4_full":
        await query.answer("That column is full!", show_alert=True)
        return
    if data.startswith("g_type_") or data.startswith("g_mode_") or data.startswith("g_diff_"):
        await _handle_setup(query)
        return
    if data == "g_join":
        await _handle_join(query)
        return
    if data.startswith("ttt_"):
        await _handle_ttt_move(query, context)
        return
    if data.startswith("c4_"):
        await _handle_c4_move(query, context)
        return

    await query.answer()


# ═══════════════════════════════════════════════════════════════════════
#  SETUP FLOW  (game type → mode → difficulty)
# ═══════════════════════════════════════════════════════════════════════

async def _handle_setup(query):
    key = f"{query.message.chat_id}_{query.message.message_id}"
    entry = _setup.get(key)
    if entry is None:
        await query.answer("This setup has expired.", show_alert=True)
        return
    challenger_id, _ = entry
    if query.from_user.id != challenger_id:
        await query.answer("wait for the host to start the game.", show_alert=True)
        return

    data = query.data

    # ── Game type ──
    if data.startswith("g_type_"):
        game_type = data[7:]  # "ttt" or "c4"
        is_private = query.message.chat.type == "private"
        buttons = [[InlineKeyboardButton("vs Toothless", callback_data=f"g_mode_{game_type}_pvc")]]
        if not is_private:
            buttons.append([InlineKeyboardButton("vs Player", callback_data=f"g_mode_{game_type}_pvp")])
        name = "Tic Tac Toe" if game_type == "ttt" else "Connect 4"
        await query.answer()
        await _safe_edit(query.edit_message_text,
            text=f"<b>{name}</b>\n\nchoice✨",
            reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML")
        return

    # ── Mode ──
    if data.startswith("g_mode_"):
        parts = data[7:].split("_")  # ["ttt","pvc"] or ["c4","pvp"]
        game_type, mode = parts[0], parts[1]
        name = "Tic Tac Toe" if game_type == "ttt" else "Connect 4"

        if mode == "pvp":
            _setup.pop(key, None)
            game = _create_game(game_type, query.from_user, vs_computer=False)
            game["chat_id"] = query.message.chat_id
            _games[key] = game
            await query.answer()
            await _safe_edit(query.edit_message_text,
                text=f"<b>{name}</b>",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Join Game", callback_data="g_join")]
                ]), parse_mode="HTML")
            return

        # PvC → show difficulty
        await query.answer()
        await _safe_edit(query.edit_message_text,
            text=f"<b>{name}</b> vs Toothless\n\nchoice✨",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Easy", callback_data=f"g_diff_{game_type}_easy"),
                InlineKeyboardButton("Medium", callback_data=f"g_diff_{game_type}_medium"),
                InlineKeyboardButton("Evil", callback_data=f"g_diff_{game_type}_evil"),
            ]]), parse_mode="HTML")
        return



    # ── Difficulty ──
    if data.startswith("g_diff_"):
        parts = data[7:].split("_")  # ["ttt","easy"]
        game_type, difficulty = parts[0], parts[1]
        _setup.pop(key, None)
        game = _create_game(game_type, query.from_user, vs_computer=True, difficulty=difficulty)
        game["chat_id"] = query.message.chat_id
        _games[key] = game
        await query.answer()
        await _render_game(query, key, game)


# ── Join 1v1 ──────────────────────────────────────────────────────────

async def _handle_join(query):
    key = f"{query.message.chat_id}_{query.message.message_id}"
    game = _games.get(key)
    if game is None:
        await query.answer("This game has expired.", show_alert=True)
        return
    if game.get("player2_id") is not None:
        await query.answer("This game already has two players.", show_alert=True)
        return
    if query.from_user.id == game["player1_id"]:
        await query.answer("wait for someone else to join.", show_alert=True)
        return

    # Assign P2 atomically
    game["player2_id"] = query.from_user.id
    game["player2_name"] = query.from_user.first_name
    game["last_activity"] = time.time()
    await query.answer(f"You joined! {game['player1_name']} goes first.")
    await _render_game(query, key, game)


# ═══════════════════════════════════════════════════════════════════════
#  GAME CREATION & HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _create_game(game_type: str, user, *, vs_computer: bool, difficulty: str | None = None) -> dict:
    board = ([[None]*3 for _ in range(3)] if game_type == "ttt"
             else [[0]*7 for _ in range(6)])
    return {
        "type": game_type,
        "board": board,
        "player1_id": user.id,
        "player1_name": user.first_name,
        "player2_id": 0 if vs_computer else None,
        "player2_name": "Toothless" if vs_computer else None,
        "vs_computer": vs_computer,
        "difficulty": difficulty,
        "current_turn": user.id,
        "current_player": 1,
        "last_activity": time.time(),
        "winner": None,
        "winning_cells": None,
        "chat_id": None,
    }


def _switch_turn(game):
    if game["current_player"] == 1:
        game["current_player"] = 2
        game["current_turn"] = game["player2_id"]
    else:
        game["current_player"] = 1
        game["current_turn"] = game["player1_id"]


# ═══════════════════════════════════════════════════════════════════════
#  RENDERING
# ═══════════════════════════════════════════════════════════════════════

async def _render_game(query, key, game, game_over=False):
    text = _build_text(game, game_over)
    markup = _build_markup(game, game_over)
    await _safe_edit(query.edit_message_text, text=text, reply_markup=markup, parse_mode="HTML")


def _build_text(game, game_over=False) -> str:
    if game["type"] == "ttt":
        return _ttt_build_text(game, game_over)
    return _c4_build_text(game, game_over)


def _build_markup(game, game_over=False):
    if game["type"] == "ttt":
        return _ttt_build_markup(game, game_over)
    return _c4_build_markup(game, game_over)


# ── TTT text ──

def _ttt_build_text(game, game_over=False) -> str:
    parts = []
    if game_over:
        w = game["winner"]
        if w == "draw":
            parts.append("🤝 <b>Draw!</b>")
        else:
            name = game["player1_name"] if w == 1 else game["player2_name"]
            parts.append(f"🏆 <b>{name}</b>")
        parts.append("")
        parts.append(f"❌ {game['player1_name']}")
        parts.append(f"⭕ {game['player2_name']}")
    else:
        header = "<b>Tic Tac Toe</b>"
        if game["vs_computer"] and game["difficulty"]:
            header += f" — {DIFF_LABELS.get(game['difficulty'], '')}"
        parts.append(header)
        parts.append("")
        parts.append(f"❌ {game['player1_name']}")
        parts.append(f"⭕ {game['player2_name']}")
        parts.append("")
        if game["current_turn"] == 0:
            parts.append("turn: ⭕ Toothless")
        else:
            n = game["player1_name"] if game["current_player"] == 1 else game["player2_name"]
            s = "❌" if game["current_player"] == 1 else "⭕"
            parts.append(f"turn: {s} {n}")
    return "\n".join(parts)


def _ttt_build_markup(game, game_over=False) -> InlineKeyboardMarkup:
    board = game["board"]
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            cell = board[r][c]
            text = TTT_SYMBOLS[cell] if cell else "·"
            cb = "g_noop" if (game_over or cell) else f"ttt_{r}_{c}"
            row.append(InlineKeyboardButton(text, callback_data=cb))
        rows.append(row)
    return InlineKeyboardMarkup(rows)


# ── C4 text ──

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
#  TIC TAC TOE — LOGIC
# ═══════════════════════════════════════════════════════════════════════

def _ttt_check_winner(board):
    """Return (winner, winning_cells). Winner: 'X', 'O', 'draw', or None."""
    lines = []
    for r in range(3):
        lines.append([(r, c) for c in range(3)])
    for c in range(3):
        lines.append([(r, c) for r in range(3)])
    lines.append([(i, i) for i in range(3)])
    lines.append([(i, 2 - i) for i in range(3)])

    for cells in lines:
        vals = [board[r][c] for r, c in cells]
        if vals[0] is not None and vals[0] == vals[1] == vals[2]:
            return vals[0], cells

    if all(board[r][c] is not None for r in range(3) for c in range(3)):
        return "draw", None
    return None, None


def _ttt_available(board):
    return [(r, c) for r in range(3) for c in range(3) if board[r][c] is None]


# ── TTT AI ────────────────────────────────────────────────────────────

def _ttt_ai(board, difficulty: str):
    if difficulty == "easy":
        return random.choice(_ttt_available(board))
    if difficulty == "medium":
        return _ttt_ai_medium(board)
    return _ttt_ai_evil(board)


def _ttt_ai_medium(board):
    moves = _ttt_available(board)
    # Win
    for r, c in moves:
        board[r][c] = "O"
        w, _ = _ttt_check_winner(board)
        board[r][c] = None
        if w == "O":
            return (r, c)
    # Block
    for r, c in moves:
        board[r][c] = "X"
        w, _ = _ttt_check_winner(board)
        board[r][c] = None
        if w == "X":
            return (r, c)
    # Center
    if board[1][1] is None:
        return (1, 1)
    return random.choice(moves)


def _ttt_minimax(board, maximizing: bool) -> int:
    w, _ = _ttt_check_winner(board)
    if w == "O":
        return 1
    if w == "X":
        return -1
    if w == "draw":
        return 0
    if maximizing:
        best = -2
        for r, c in _ttt_available(board):
            board[r][c] = "O"
            best = max(best, _ttt_minimax(board, False))
            board[r][c] = None
        return best
    else:
        best = 2
        for r, c in _ttt_available(board):
            board[r][c] = "X"
            best = min(best, _ttt_minimax(board, True))
            board[r][c] = None
        return best


def _ttt_ai_evil(board):
    moves = _ttt_available(board)
    best_score, best_move = -2, moves[0]
    for r, c in moves:
        board[r][c] = "O"
        score = _ttt_minimax(board, False)
        board[r][c] = None
        if score > best_score:
            best_score, best_move = score, (r, c)
    return best_move


# ── TTT move handler ──────────────────────────────────────────────────

async def _handle_ttt_move(query, context):
    key = f"{query.message.chat_id}_{query.message.message_id}"
    game = _games.get(key)
    if game is None:
        await query.answer("This game has expired.", show_alert=True)
        return
    if game["winner"] is not None:
        await query.answer()
        return

    parts = query.data.split("_")  # ttt_R_C
    r, c = int(parts[1]), int(parts[2])
    board = game["board"]

    if board[r][c] is not None:
        await query.answer("That cell is taken!")
        return
    if game["current_turn"] == 0:
        await query.answer("Wait for the computer!", show_alert=True)
        return
    if query.from_user.id != game["current_turn"]:
        await query.answer("It's not your turn!", show_alert=True)
        return

    # Place move
    piece = "X" if game["current_player"] == 1 else "O"
    board[r][c] = piece
    game["last_activity"] = time.time()

    w, wc = _ttt_check_winner(board)
    if w:
        game["winner"] = "draw" if w == "draw" else (1 if w == "X" else 2)
        game["winning_cells"] = wc
        await query.answer()
        await _render_game(query, key, game, game_over=True)
        await _save_game_history(game)
        _games.pop(key, None)
        return

    _switch_turn(game)

    # Computer's turn
    if game["vs_computer"] and game["current_player"] == 2:
        game["current_turn"] = 0
        await query.answer()
        await _render_game(query, key, game)
        await asyncio.sleep(AI_MOVE_DELAY)

        mv = _ttt_ai(board, game["difficulty"])
        board[mv[0]][mv[1]] = "O"
        game["last_activity"] = time.time()

        w, wc = _ttt_check_winner(board)
        if w:
            game["winner"] = "draw" if w == "draw" else (1 if w == "X" else 2)
            game["winning_cells"] = wc
            try:
                await _safe_edit(query.edit_message_text,
                    text=_build_text(game, True), reply_markup=_build_markup(game, True), parse_mode="HTML")
            except Exception:
                pass
            await _save_game_history(game)
            _games.pop(key, None)
            return

        _switch_turn(game)
        try:
            await _safe_edit(query.edit_message_text,
                text=_build_text(game, False), reply_markup=_build_markup(game), parse_mode="HTML")
        except Exception:
            pass
        return

    await query.answer()
    await _render_game(query, key, game)


# ═══════════════════════════════════════════════════════════════════════
#  CONNECT 4 — LOGIC
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


# ── C4 AI ─────────────────────────────────────────────────────────────

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


# ── C4 move handler ───────────────────────────────────────────────────

async def _handle_c4_move(query, context):
    key = f"{query.message.chat_id}_{query.message.message_id}"
    game = _games.get(key)
    if game is None:
        await query.answer("This game has expired.", show_alert=True)
        return
    if game["winner"] is not None:
        await query.answer()
        return

    col = int(query.data[3:])  # "c4_N"
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
            return

        _switch_turn(game)
        try:
            await _safe_edit(query.edit_message_text,
                text=_build_text(game, False), reply_markup=_build_markup(game), parse_mode="HTML")
        except Exception:
            pass
        return

    await query.answer()
    await _render_game(query, key, game)


# ═══════════════════════════════════════════════════════════════════════
#  GAME HISTORY — MongoDB
# ═══════════════════════════════════════════════════════════════════════

async def _save_game_history(game):
    winner = game.get("winner")
    if winner == "draw":
        winner_id, is_draw = None, True
    elif winner == 1:
        winner_id, is_draw = game["player1_id"], False
    elif winner == 2:
        winner_id, is_draw = game["player2_id"], False
    else:
        return

    doc = {
        "chat_id": game.get("chat_id"),
        "game_type": "tictactoe" if game["type"] == "ttt" else "connect4",
        "vs_computer": game["vs_computer"],
        "difficulty": game["difficulty"],
        "player1_id": game["player1_id"],
        "player1_name": game["player1_name"],
        "player2_id": game["player2_id"],
        "player2_name": game["player2_name"],
        "winner_id": winner_id,
        "draw": is_draw,
        "timestamp": datetime.now(timezone.utc),
    }
    try:
        await games_collection.insert_one(doc)
    except Exception as e:
        logger.error(f"Failed to save game history: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  INACTIVITY CLEANUP (called by job_queue every 60s)
# ═══════════════════════════════════════════════════════════════════════

async def cleanup_inactive_games(context: ContextTypes.DEFAULT_TYPE):
    now = time.time()

    # Stale games
    stale = [k for k, g in _games.items() if now - g["last_activity"] > INACTIVITY_TIMEOUT]
    for key in stale:
        _games.pop(key, None)
        parts = key.split("_")
        chat_id, msg_id = int(parts[0]), int(parts[1])
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text="⏰ Game ended due to inactivity.",
            )
        except Exception:
            pass

    # Stale setups
    stale_s = [k for k, (_, t) in _setup.items() if now - t > INACTIVITY_TIMEOUT]
    for key in stale_s:
        _setup.pop(key, None)
        parts = key.split("_")
        chat_id, msg_id = int(parts[0]), int(parts[1])
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text="⏰ Game setup timed out.",
            )
        except Exception:
            pass
