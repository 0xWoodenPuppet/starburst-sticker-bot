"""Games — /fight command and callback router."""

import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from .common import (
    _games, _setup, _safe_edit, _create_game, _render_game,
    save_active_game, DIFF_LABELS,
)
from .tictactoe import _handle_ttt_move
from .connect4 import _handle_c4_move


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
            await save_active_game(key, game)
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
        await save_active_game(key, game)
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
    await save_active_game(key, game)
    await query.answer(f"You joined! {game['player1_name']} goes first.")
    await _render_game(query, key, game)
