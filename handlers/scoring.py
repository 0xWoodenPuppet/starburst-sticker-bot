import os
import csv
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from config import BOT_ADMIN_IDS

CSV_FILE = "challenge_scores.csv"

def init_csv():
    """Ensure the CSV file and headers exist."""
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["user_id", "username", "day_number", "points", "timestamp"])

def read_scores():
    """Read all scores from the CSV. Returns a list of dicts."""
    init_csv()
    scores = []
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            scores.append(row)
    return scores

def write_scores(scores):
    """Write the provided scores list back to the CSV."""
    with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["user_id", "username", "day_number", "points", "timestamp"])
        writer.writeheader()
        writer.writerows(scores)

async def score_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /score <day> <points> by replying to a user's check-in."""
    if update.effective_user.id not in BOT_ADMIN_IDS:
        return

    message = update.message
    if not message.reply_to_message:
        await message.set_reaction(reaction="👎")
        return

    try:
        args = context.args
        if len(args) < 2:
            await message.set_reaction(reaction="👎")
            return
            
        day_number = str(int(args[0]))
        # Sum all remaining arguments (e.g., /score 1 2 5 5 2 -> 14)
        points = str(sum(int(x) for x in args[1:]))
    except ValueError:
        await message.set_reaction(reaction="👎")
        return

    target_user = message.reply_to_message.from_user
    user_id = str(target_user.id)
    username = target_user.username or target_user.first_name

    scores = read_scores()
    
    # Check for duplicate
    for row in scores:
        if row["user_id"] == user_id and row["day_number"] == day_number:
            await message.set_reaction(reaction="👎")
            return

    # Append new score
    scores.append({
        "user_id": user_id,
        "username": username,
        "day_number": day_number,
        "points": points,
        "timestamp": datetime.now().isoformat()
    })
    
    write_scores(scores)
    await message.set_reaction(reaction="👍")


async def remove_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /removescore <day> by replying to a user's check-in."""
    if update.effective_user.id not in BOT_ADMIN_IDS:
        return

    message = update.message
    if not message.reply_to_message:
        await message.set_reaction(reaction="👎")
        return

    try:
        args = context.args
        if len(args) < 1:
            await message.set_reaction(reaction="👎")
            return
        day_number = str(int(args[0]))
    except ValueError:
        await message.set_reaction(reaction="👎")
        return

    target_user = message.reply_to_message.from_user
    user_id = str(target_user.id)

    scores = read_scores()
    new_scores = [row for row in scores if not (row["user_id"] == user_id and row["day_number"] == day_number)]
    
    if len(new_scores) == len(scores):
        # No score was deleted
        await message.set_reaction(reaction="👎")
        return

    write_scores(new_scores)
    await message.set_reaction(reaction="👍")


async def export_scores(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command mostly for Private Chats: /export_scores"""
    if update.effective_user.id not in BOT_ADMIN_IDS:
        return
        
    init_csv() # ensure it exists
    with open(CSV_FILE, 'rb') as f:
        # Always send to the admin's private DM, even if they ran the command in the group!
        try:
            await context.bot.send_document(chat_id=update.effective_user.id, document=f, filename=CSV_FILE)
        except Exception:
            # If the bot is blocked by the admin in DMs
            await update.message.set_reaction(reaction="👎")


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Public command: /leaderboard"""
    scores = read_scores()
    if not scores:
        await update.message.reply_text("🏆 <b>7-Day Challenge Leaderboard</b>\n\nNo scores have been logged yet!", parse_mode="HTML")
        return

    # Calculate totals
    # dictionary structure: { "user_id": {"username": "name", "total": 0} }
    totals = {}
    for row in scores:
        uid = row["user_id"]
        points = int(row["points"])
        if uid not in totals:
            totals[uid] = {"username": row["username"], "total": 0}
        totals[uid]["total"] += points

    # Sort users by total points descending
    sorted_users = sorted(totals.values(), key=lambda x: x["total"], reverse=True)

    text = "🏆 <b>7-Day Challenge Leaderboard</b> 🏆\n\n"
    for i, user in enumerate(sorted_users, start=1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🔸"
        # Sanitize HTML just in case
        safe_username = user['username'].replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
        text += f"{medal} {safe_username} — {user['total']} pts\n"

    await update.message.reply_text(text, parse_mode="HTML")
