"""Async MongoDB client for the Starburst bot.

Uses motor (async pymongo wrapper) so database calls don't block
the Telegram event loop.
"""

from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI

_client: AsyncIOMotorClient | None = None


def _get_db():
    global _client
    if _client is None:
        if not MONGO_URI:
            raise RuntimeError("MONGODB_URI is not set in the environment.")
        _client = AsyncIOMotorClient(MONGO_URI)
    return _client.starburst  # database name


db = _get_db()

# ── Collections ────────────────────────────────────────────────────────
sessions = db.sessions              # focus session history (tasks, scores, participants)
coach_sessions = db.coach_sessions  # active AI coaching conversations
games = db.games                    # game history (tic tac toe, connect 4)
games_active = db.games_active      # active/in-progress games (survives restarts)
challenge_scores = db.challenge_scores  # daily challenge scores (points per day per user)
