"""Tic Tac Toe — /fight command handler.

Modes:
  • Player vs Computer (PvC) — works in groups and DMs.
  • Player vs Player  (PvP) — groups only (needs two users).

The computer mixes minimax with random moves so it's beatable but not trivial.
Game state is held in memory keyed by chat_id + message_id.
"""

import random
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# ── In-memory game store ──────────────────────────────────────────────
# Key: "chatId_messageId"  Value: game dict
_games: dict[str, dict] = {}

# How often (0.0–1.0) the bot plays a random move instead of optimal
_RANDOM_MOVE_CHANCE = 0.35

# Stale game threshold (seconds)
_STALE_TIMEOUT = 30 * 60  # 30 minutes

SYMBOLS = {None: "·", "X": "❌", "O": "⭕"}


# ═══════════════════════════════════════════════════════════════════════
#  BOARD HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _empty_board() -> list[list[str | None]]:
    return [[None, None, None] for _ in range(3)]


def _check_winner(board) -> str | None:
    """Return 'X', 'O', 'draw', or None."""
    lines = []
    for r in range(3):
        lines.append(board[r])                         # rows
    for c in range(3):
        lines.append([board[r][c] for r in range(3)])  # cols
    lines.append([board[i][i] for i in range(3)])      # diag
    lines.append([board[i][2 - i] for i in range(3)])  # anti-diag

    for line in lines:
        if line[0] is not None and line[0] == line[1] == line[2]:
            return line[0]

    # draw = no empty cells left
    if all(board[r][c] is not None for r in range(3) for c in range(3)):
        return "draw"
    return None


def _available_moves(board) -> list[tuple[int, int]]:
    return [(r, c) for r in range(3) for c in range(3) if board[r][c] is None]


# ── Minimax AI ────────────────────────────────────────────────────────

def _minimax(board, is_maximizing: bool) -> int:
    """Classic minimax. O is the maximiser (computer), X is the minimiser."""
    result = _check_winner(board)
    if result == "O":
        return 1
    if result == "X":
        return -1
    if result == "draw":
        return 0

    if is_maximizing:
        best = -2
        for r, c in _available_moves(board):
            board[r][c] = "O"
            best = max(best, _minimax(board, False))
            board[r][c] = None
        return best
    else:
        best = 2
        for r, c in _available_moves(board):
            board[r][c] = "X"
            best = min(best, _minimax(board, True))
            board[r][c] = None
        return best


def _computer_move(board) -> tuple[int, int]:
    """Pick a move: sometimes random, sometimes optimal."""
    moves = _available_moves(board)
    if not moves:
        raise ValueError("No moves available")

    # Random move sometimes
    if random.random() < _RANDOM_MOVE_CHANCE:
        return random.choice(moves)

    # Optimal (minimax)
    best_score = -2
    best_move = moves[0]
    for r, c in moves:
        board[r][c] = "O"
        score = _minimax(board, False)
        board[r][c] = None
        if score > best_score:
            best_score = score
            best_move = (r, c)
    return best_move


# ═══════════════════════════════════════════════════════════════════════
#  KEYBOARD / TEXT BUILDERS
# ═══════════════════════════════════════════════════════════════════════

def _render_board(game_key: str, board, game_over: bool = False) -> InlineKeyboardMarkup:
    """Build a 3×3 inline keyboard from the board state."""
    rows = []
    for r in range(3):
        row = []
        for c in range(3):
            cell = board[r][c]
            label = SYMBOLS[cell]
            # If cell is taken or game is over, callback is a no-op
            if cell is not None or game_over:
                cb = "ttt_noop"
            else:
                cb = f"ttt_move_{r}_{c}"
            row.append(InlineKeyboardButton(label, callback_data=cb))
        rows.append(row)
    return InlineKeyboardMarkup(rows)


def _status_text(game) -> str:
    """Build the status message above the board."""
    winner = _check_winner(game["board"])
    mode = game["mode"]

    if winner == "draw":
        return "🤝 <b>It's a draw!</b>"
    elif winner == "X":
        name = _player_name(game, "X")
        return f"🎉 <b>{name} (❌) wins!</b>"
    elif winner == "O":
        name = _player_name(game, "O")
        return f"🎉 <b>{name} (⭕) wins!</b>"

    # Game still going
    turn = game["turn"]  # "X" or "O"
    if mode == "pvc":
        if turn == "X":
            return "Your turn (❌)"
        else:
            return "Computer is thinking… (⭕)"
    else:
        # PvP
        name = _player_name(game, turn)
        symbol = SYMBOLS[turn]
        if game.get("player_O") is None:
            return f"❌ {_player_name(game, 'X')} is waiting for an opponent!\nAnyone can tap a cell to join as ⭕"
        return f"{name}'s turn ({symbol})"


def _player_name(game, symbol: str) -> str:
    key = f"player_{symbol}"
    uid = game.get(key)
    if uid is None:
        return "Computer" if game["mode"] == "pvc" else "???"
    name = game.get(f"name_{symbol}", f"User {uid}")
    return name


# ═══════════════════════════════════════════════════════════════════════
#  CLEANUP
# ═══════════════════════════════════════════════════════════════════════

def _prune_stale():
    """Remove games idle for over 30 minutes."""
    now = time.time()
    stale = [k for k, g in _games.items() if now - g["last_activity"] > _STALE_TIMEOUT]
    for k in stale:
        del _games[k]


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND: /fight
# ═══════════════════════════════════════════════════════════════════════

async def fight_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/fight — start a Tic Tac Toe game."""
    _prune_stale()

    is_private = update.effective_chat.type == "private"

    buttons = [[InlineKeyboardButton("🤖 vs Computer", callback_data="ttt_pvc")]]
    if not is_private:
        buttons.append([InlineKeyboardButton("👥 vs Player", callback_data="ttt_pvp")])

    await update.message.reply_text(
        "🎮 <b>Tic Tac Toe</b>\n\nChoose your game mode:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


# ═══════════════════════════════════════════════════════════════════════
#  CALLBACK ROUTER
# ═══════════════════════════════════════════════════════════════════════

async def ttt_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""

    if data == "ttt_noop":
        await query.answer()
        return
    if data == "ttt_pvc":
        await _start_pvc(query)
        return
    if data == "ttt_pvp":
        await _start_pvp(query)
        return
    if data.startswith("ttt_move_"):
        await _handle_move(query)
        return

    await query.answer()


# ── Mode starters ─────────────────────────────────────────────────────

async def _start_pvc(query):
    user = query.from_user
    game = {
        "mode": "pvc",
        "board": _empty_board(),
        "turn": "X",
        "player_X": user.id,
        "name_X": user.first_name,
        "player_O": None,  # computer
        "name_O": "Computer",
        "last_activity": time.time(),
    }
    key = f"{query.message.chat_id}_{query.message.message_id}"
    _games[key] = game

    await query.answer()
    await query.edit_message_text(
        _status_text(game),
        reply_markup=_render_board(key, game["board"]),
        parse_mode="HTML",
    )


async def _start_pvp(query):
    user = query.from_user
    game = {
        "mode": "pvp",
        "board": _empty_board(),
        "turn": "X",
        "player_X": user.id,
        "name_X": user.first_name,
        "player_O": None,   # filled when another user taps a cell
        "name_O": None,
        "last_activity": time.time(),
    }
    key = f"{query.message.chat_id}_{query.message.message_id}"
    _games[key] = game

    await query.answer()
    await query.edit_message_text(
        _status_text(game),
        reply_markup=_render_board(key, game["board"]),
        parse_mode="HTML",
    )


# ── Move handler ──────────────────────────────────────────────────────

async def _handle_move(query):
    key = f"{query.message.chat_id}_{query.message.message_id}"
    game = _games.get(key)
    if game is None:
        await query.answer("This game has expired.", show_alert=True)
        return

    # Parse row, col
    parts = query.data.split("_")  # ttt_move_R_C
    r, c = int(parts[2]), int(parts[3])
    board = game["board"]
    user = query.from_user

    # Cell already taken (shouldn't happen, but guard)
    if board[r][c] is not None:
        await query.answer("That cell is taken!")
        return

    # ── PvP: opponent joining ─────────────────────────────
    if game["mode"] == "pvp" and game["player_O"] is None:
        if user.id == game["player_X"]:
            await query.answer("Waiting for another player to join! They tap a cell to play as ⭕.", show_alert=True)
            return
        # Another user taps → they become O, and it's X's turn still but
        # since the tapper clearly wants to move, we let X go first.
        # Actually the first tap IS their move as O, but X goes first.
        # So: assign O, then let X move first. The tapper needs to wait.
        game["player_O"] = user.id
        game["name_O"] = user.first_name
        # Don't place a move yet — X goes first. Just update status.
        game["last_activity"] = time.time()
        await query.answer(f"You joined as ⭕! {game['name_X']} (❌) goes first.")
        await query.edit_message_text(
            _status_text(game),
            reply_markup=_render_board(key, board),
            parse_mode="HTML",
        )
        return

    # ── Turn validation ───────────────────────────────────
    turn = game["turn"]
    expected_player = game[f"player_{turn}"]

    if game["mode"] == "pvc" and turn == "O":
        await query.answer("Wait for the computer!")
        return

    if expected_player is not None and user.id != expected_player:
        await query.answer("It's not your turn!", show_alert=True)
        return

    # ── Place the move ────────────────────────────────────
    board[r][c] = turn
    game["last_activity"] = time.time()
    winner = _check_winner(board)

    if winner:
        # Game over
        await query.answer()
        await query.edit_message_text(
            _status_text(game),
            reply_markup=_render_board(key, board, game_over=True),
            parse_mode="HTML",
        )
        _games.pop(key, None)
        return

    # Switch turn
    game["turn"] = "O" if turn == "X" else "X"

    # ── Computer's turn (PvC) ─────────────────────────────
    if game["mode"] == "pvc" and game["turn"] == "O":
        cr, cc = _computer_move(board)
        board[cr][cc] = "O"
        game["last_activity"] = time.time()
        winner = _check_winner(board)

        if winner:
            await query.answer()
            await query.edit_message_text(
                _status_text(game),
                reply_markup=_render_board(key, board, game_over=True),
                parse_mode="HTML",
            )
            _games.pop(key, None)
            return

        game["turn"] = "X"

    await query.answer()
    await query.edit_message_text(
        _status_text(game),
        reply_markup=_render_board(key, board),
        parse_mode="HTML",
    )
