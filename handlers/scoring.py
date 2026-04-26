import os
import csv
from datetime import datetime, timedelta, date
from telegram import Update
from telegram.ext import ContextTypes
from config import BOT_ADMIN_IDS, TIMEZONE, DATABASE_CHAT_ID

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

async def write_scores(scores, context: ContextTypes.DEFAULT_TYPE = None):
    """Write the provided scores list back to the CSV, and optionally backup to Telegram."""
    with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["user_id", "username", "day_number", "points", "timestamp"])
        writer.writeheader()
        writer.writerows(scores)
        
    if context and DATABASE_CHAT_ID:
        try:
            with open(CSV_FILE, 'rb') as f:
                await context.bot.send_document(
                    chat_id=DATABASE_CHAT_ID, 
                    document=f, 
                    filename=f"{datetime.now().strftime('%Y-%m-%d_%H-%M')}_scores.csv",
                    caption="🔄 Database Updated"
                )
        except Exception as e:
            print(f"⚠️ Failed to send database backup: {e}")

async def score_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /s <points...> by replying to a user's check-in."""
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
            
        # Sum all arguments as points (e.g., /s 10 5 2 -> 17)
        points = str(sum(int(x) for x in args))
    except ValueError:
        await message.set_reaction(reaction="👎")
        return

    # Calculate logical day number based on message date
    # 9:00 AM GMT+3 is 11:30 AM IST. Subtract 11.5 hours so that 11:30 AM IST rolls over at midnight.
    msg_date = message.reply_to_message.date.astimezone(TIMEZONE)
    logical_date = (msg_date - timedelta(hours=11, minutes=30)).date()
    
    start_date = date(2026, 4, 30)
    day_number = str((logical_date - start_date).days + 1)

    target_user = message.reply_to_message.from_user
    user_id = str(target_user.id)
    username = target_user.username or target_user.first_name

    scores = read_scores()
    
    # Check if a score already exists for this day to update it
    score_updated = False
    for row in scores:
        if row["user_id"] == user_id and row["day_number"] == day_number:
            row["points"] = points
            row["timestamp"] = datetime.now().isoformat()
            score_updated = True
            break

    # If it doesn't exist, append a new score
    if not score_updated:
        scores.append({
            "user_id": user_id,
            "username": username,
            "day_number": day_number,
            "points": points,
            "timestamp": datetime.now().isoformat()
        })
    
    await write_scores(scores, context)
    await message.set_reaction(reaction="👍")



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
