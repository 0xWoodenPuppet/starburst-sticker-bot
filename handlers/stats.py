"""Game stats — /stats command handler."""

from telegram import Update
from telegram.ext import ContextTypes
from db import games as games_collection

DIFF_LABELS = {"easy": "Easy", "medium": "Medium", "evil": "Evil"}


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stats — Show game history and win/loss record."""
    user = update.effective_user
    user_id = user.id

    cursor = games_collection.find({
        "$or": [
            {"player1_id": user_id},
            {"player2_id": user_id},
        ]
    })
    all_games = await cursor.to_list(length=1000)

    if not all_games:
        await update.message.reply_text(
            "📊 <b>Game Stats</b>\n\n"
            "No games played yet.\n"
            "Use /fight to start a game.",
            parse_mode="HTML",
        )
        return

    total = len(all_games)
    wins = losses = draws = 0
    ttt_total = ttt_wins = c4_total = c4_wins = 0
    difficulty_counts: dict[str, int] = {}

    for g in all_games:
        is_ttt = g.get("game_type") == "tictactoe"
        is_c4 = g.get("game_type") == "connect4"

        if is_ttt:
            ttt_total += 1
        elif is_c4:
            c4_total += 1

        if g.get("draw"):
            draws += 1
        elif g.get("winner_id") == user_id:
            wins += 1
            if is_ttt:
                ttt_wins += 1
            elif is_c4:
                c4_wins += 1
        else:
            losses += 1

        if g.get("vs_computer") and g.get("difficulty"):
            d = g["difficulty"]
            difficulty_counts[d] = difficulty_counts.get(d, 0) + 1

    win_rate = (wins / total * 100) if total > 0 else 0

    text = f"<b>{user.first_name}</b>\n"
    text += "─────────────────────\n"
    text += f"Total games: <b>{total}</b>\n"
    text += f"Wins: <b>{wins}</b>\n"
    text += f"Losses: <b>{losses}</b>\n"
    text += f"Draws: <b>{draws}</b>\n"
    text += f"Win rate: <b>{win_rate:.0f}%</b>\n"
    text += "─────────────────────\n"

    if ttt_total > 0:
        ttt_wr = (ttt_wins / ttt_total * 100) if ttt_total else 0
        text += f"Tic Tac Toe: {ttt_total} games ({ttt_wins}W / {ttt_wr:.0f}%)\n"
    if c4_total > 0:
        c4_wr = (c4_wins / c4_total * 100) if c4_total else 0
        text += f"Connect 4: {c4_total} games ({c4_wins}W / {c4_wr:.0f}%)\n"

    if difficulty_counts:
        fav = max(difficulty_counts, key=difficulty_counts.get)
        text += f"\nMost played difficulty: {DIFF_LABELS.get(fav, fav)}"

    await update.message.reply_text(text, parse_mode="HTML")
