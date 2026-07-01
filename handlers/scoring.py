import os
import csv
from datetime import datetime, timedelta, date
from telegram import Update
from telegram.ext import ContextTypes
from config import BOT_ADMIN_IDS, TIMEZONE, DATABASE_CHAT_ID
from db import challenge_scores

CSV_FILE = "challenge_scores.csv"

# Challenge config
CHALLENGE_START_DATE = date(2026, 4, 30)
CHALLENGE_TOTAL_DAYS = 21

def init_csv():
    """Ensure the CSV file and headers exist."""
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["user_id", "username", "day_number", "points", "timestamp"])

async def read_scores():
    """Read all scores from MongoDB. Returns a list of dicts matching the CSV structure."""
    scores = []
    try:
        cursor = challenge_scores.find({})
        async for doc in cursor:
            scores.append({
                "user_id": str(doc.get("user_id")),
                "username": doc.get("username", ""),
                "day_number": str(doc.get("day_number")),
                "points": str(doc.get("points")),
                "timestamp": doc.get("timestamp", "")
            })
    except Exception as e:
        print(f"⚠️ Failed to read scores from MongoDB: {e}")
        # Fallback to local CSV if DB fails
        init_csv()
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                scores.append(row)
    return scores

async def write_scores(scores, context: ContextTypes.DEFAULT_TYPE = None):
    """Write the provided scores list back to MongoDB, sync to CSV, and optionally backup to Telegram."""
    # 1. Update MongoDB
    try:
        await challenge_scores.delete_many({})
        if scores:
            docs = []
            for s in scores:
                docs.append({
                    "user_id": str(s["user_id"]),
                    "username": s["username"],
                    "day_number": int(s["day_number"]),
                    "points": int(s["points"]),
                    "timestamp": s["timestamp"]
                })
            await challenge_scores.insert_many(docs)
    except Exception as e:
        print(f"⚠️ Failed to update MongoDB scores: {e}")

    # 2. Sync to local CSV
    try:
        with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=["user_id", "username", "day_number", "points", "timestamp"])
            writer.writeheader()
            writer.writerows(scores)
    except Exception as e:
        print(f"⚠️ Failed to write local CSV backup: {e}")
        
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


def _safe_display_name(name: str) -> str:
    """Wrap a display name with Unicode directional isolation so mixed
    RTL/LTR names (Arabic, Hebrew, etc.) render correctly in Telegram."""
    # U+2068 First Strong Isolate — lets the renderer auto-detect direction
    # U+2069 Pop Directional Isolate — closes the isolation
    safe = name.replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
    return f"\u2068{safe}\u2069"


def _dense_ranks(sorted_users):
    """Compute dense ranks for an already-sorted (desc) list of user dicts.
    Each dict must have a 'total' key.  Returns a list of (rank, user) tuples."""
    ranks = []
    current_rank = 0
    prev_total = None
    for user in sorted_users:
        if user["total"] != prev_total:
            current_rank += 1
            prev_total = user["total"]
        ranks.append((current_rank, user))
    return ranks


async def score_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /s <points...> by replying to a user's check-in."""
    if update.effective_user.id not in BOT_ADMIN_IDS:
        return

    message = update.message
    if not message.reply_to_message:
        await message.set_reaction(reaction="👎")
        return

    try:
        args = list(context.args)
        if len(args) < 1:
            await message.set_reaction(reaction="👎")
            return

        # Optional day override: /s d5 10 -> day 5, 10 points
        manual_day = None
        if args[0].lower().startswith("d") and args[0][1:].isdigit():
            manual_day = int(args[0][1:])
            args = args[1:]
            if len(args) < 1:
                await message.set_reaction(reaction="👎")
                return

        # Sum all remaining arguments as points (e.g., /s 10 5 2 -> 17)
        points = str(sum(int(x) for x in args))
    except ValueError:
        await message.set_reaction(reaction="👎")
        return

    if manual_day is not None:
        day_number = str(manual_day)
    else:
        # Calculate logical day number based on message date
        # Day boundary is 16:30 GMT+3 = 19:00 IST.
        # Subtract 19 hours so that 19:00 IST rolls over to the next logical day.
        msg_date = message.reply_to_message.date.astimezone(TIMEZONE)
        logical_date = (msg_date - timedelta(hours=19, minutes=0)).date()
        day_number = str((logical_date - CHALLENGE_START_DATE).days + 1)

    target_user = message.reply_to_message.from_user
    user_id = str(target_user.id)
    username = target_user.username or target_user.first_name

    scores = await read_scores()
    
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
    """Public command: /leaderboard — dense-ranked leaderboard."""
    scores = await read_scores()
    if not scores:
        await update.message.reply_text("🏆 <b>21-Day Challenge Leaderboard</b>\n\nNo scores have been logged yet!", parse_mode="HTML")
        return

    # Calculate totals
    # dictionary structure: { "user_id": {"username": "name", "total": 0} }
    totals = {}
    for row in scores:
        uid = row["user_id"]
        points = int(row["points"])
        if uid not in totals:
            totals[uid] = {"uid": uid, "username": row["username"], "total": 0}
        totals[uid]["total"] += points

    # Sort users by total points descending.
    # Tiebreaker: prioritise user 5534874386 when totals are equal.
    PRIORITY_UID = "5534874386"
    sorted_users = sorted(
        totals.values(),
        key=lambda x: (-x["total"], 0 if x.get("uid") == PRIORITY_UID else 1),
    )
    ranked = _dense_ranks(sorted_users)

    text = "🏆 <b>21-Day Challenge Leaderboard</b> 🏆\n\n"
    for rank, user in ranked:
        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else "🔸"
        name = _safe_display_name(user["username"])
        text += f"{medal} Rank {rank} | {name} | {user['total']} pts\n"

    await update.message.reply_text(text, parse_mode="HTML")


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Public command: /profile [username] — shows a player's day-by-day breakdown."""
    if not context.args:
        await update.message.reply_text("Usage: /profile &lt;username&gt;", parse_mode="HTML")
        return

    query = context.args[0].lstrip("@")
    scores = await read_scores()

    # Find the target user (match by username, case-insensitive)
    user_scores = {}   # day_number -> points
    matched_name = None
    matched_uid = None
    for row in scores:
        if row["username"].lower() == query.lower():
            matched_name = row["username"]
            matched_uid = row["user_id"]
            user_scores[int(row["day_number"])] = int(row["points"])

    if matched_name is None:
        safe_query = query.replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
        await update.message.reply_text(f'❌ Player "{safe_query}" not found.', parse_mode="HTML")
        return

    # Determine how many days have elapsed based on the highest day logged in the CSV
    max_day = max(int(row["day_number"]) for row in scores)
    elapsed_days = min(max_day, CHALLENGE_TOTAL_DAYS)

    # Build the profile text
    display_name = _safe_display_name(matched_name)
    total = sum(user_scores.values())

    text = f"📊 <b>Profile: {display_name}</b>\n"
    text += "─────────────────────\n"

    for day in range(1, elapsed_days + 1):
        pts = user_scores.get(day)
        pts_str = f"{pts} pts" if pts is not None else "—"
        text += f"Day {day:02d} | {pts_str}\n"

    text += "─────────────────────\n"
    text += f"<b>Total</b>  | <b>{total} pts</b>\n"

    # Calculate dense rank among all players
    totals = {}
    for row in scores:
        uid = row["user_id"]
        p = int(row["points"])
        if uid not in totals:
            totals[uid] = {"uid": uid, "username": row["username"], "total": 0}
        totals[uid]["total"] += p

    PRIORITY_UID = "5534874386"
    sorted_users = sorted(
        totals.values(),
        key=lambda x: (-x["total"], 0 if x.get("uid") == PRIORITY_UID else 1),
    )
    ranked = _dense_ranks(sorted_users)

    player_rank = None
    for rank, user in ranked:
        if user["username"] == matched_name:
            player_rank = rank
            break

    text += f"<b>Rank</b>   | <b>{player_rank}</b> out of <b>{len(sorted_users)}</b>\n"
    text += "─────────────────────"

    await update.message.reply_text(text, parse_mode="HTML")
