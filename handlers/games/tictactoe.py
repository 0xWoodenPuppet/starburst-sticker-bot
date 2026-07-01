"""Tic Tac Toe — rendering, win-check, AI, and move handler."""

import asyncio
import random
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .common import (
    _games, _safe_edit, _switch_turn, _render_game, _build_text, _build_markup,
    _save_game_history, save_active_game, delete_active_game,
    DIFF_LABELS, AI_MOVE_DELAY,
)

# ── TTT symbols ───────────────────────────────────────────────────────
TTT_SYMBOLS = {"X": "❌", "O": "⭕", None: "·"}


# ═══════════════════════════════════════════════════════════════════════
#  RENDERING
# ═══════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════
#  LOGIC
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


# ═══════════════════════════════════════════════════════════════════════
#  AI
# ═══════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════
#  MOVE HANDLER
# ═══════════════════════════════════════════════════════════════════════

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
        await delete_active_game(key)
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
