"""Games — shared state, constants, and helpers.

Used by both tictactoe.py and connect4.py.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

from telegram import InlineKeyboardMarkup
from telegram.error import BadRequest, RetryAfter
from telegram.ext import ContextTypes

from db import games as games_collection, games_active as active_games_collection

logger = logging.getLogger(__name__)

# ── In-memory stores ──────────────────────────────────────────────────
# Game state:  "chatId_msgId" -> game dict
_games: dict[str, dict] = {}
# Setup state: "chatId_msgId" -> (challenger_id, created_at)
_setup: dict[str, tuple[int, float]] = {}

# ── Constants ─────────────────────────────────────────────────────────
INACTIVITY_TIMEOUT = 300   # 5 minutes
AI_MOVE_DELAY = 0.5        # seconds before computer responds

DIFF_LABELS = {"easy": "😊 Easy", "medium": "😐 Medium", "evil": "Evil"}


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
        from .tictactoe import _ttt_build_text
        return _ttt_build_text(game, game_over)
    from .connect4 import _c4_build_text
    return _c4_build_text(game, game_over)


def _build_markup(game, game_over=False):
    if game["type"] == "ttt":
        from .tictactoe import _ttt_build_markup
        return _ttt_build_markup(game, game_over)
    from .connect4 import _c4_build_markup
    return _c4_build_markup(game, game_over)


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
        await delete_active_game(key)
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


# ── Database Persistence Helpers ──────────────────────────────────────

async def save_active_game(key: str, game: dict):
    """Upsert the active game state to MongoDB."""
    try:
        await active_games_collection.replace_one({"_id": key}, game, upsert=True)
    except Exception as e:
        logger.error(f"Failed to save active game {key} to MongoDB: {e}")


async def delete_active_game(key: str):
    """Delete the active game state from MongoDB."""
    try:
        await active_games_collection.delete_one({"_id": key})
    except Exception as e:
        logger.error(f"Failed to delete active game {key} from MongoDB: {e}")


async def load_active_games(app):
    """Load all in-progress active games from MongoDB on startup."""
    global _games
    try:
        count = 0
        async for doc in active_games_collection.find({}):
            key = doc["_id"]
            # Restore the raw dictionary without the MongoDB _id key
            game = dict(doc)
            del game["_id"]
            _games[key] = game
            count += 1
        if count:
            logger.info(f"🔄 Restored {count} active game(s) from MongoDB")
    except Exception as e:
        logger.error(f"Failed to load active games from MongoDB: {e}")
