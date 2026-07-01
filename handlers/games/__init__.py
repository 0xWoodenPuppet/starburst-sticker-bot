"""Games package — Tic Tac Toe & Connect 4.

Public API re-exported for main.py:
  fight_command, game_callback_handler, cleanup_inactive_games, load_active_games
"""

from .fight import fight_command, game_callback_handler
from .common import cleanup_inactive_games, load_active_games
