"""21-Day Reading Habit Challenge handler.

Self-scoring, zero-intervention reading challenge.  Users check in daily
by tapping an inline button.  The bot tracks streaks and dynamically
updates the pinned message with an expandable blockquote listing today's
readers and their current streak.

No leaderboard, no competition — purely habit-building.
"""

from datetime import date, datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import (
    READING_CHALLENGE_START_DATE,
    READING_CHALLENGE_TOTAL_DAYS,
    READING_CHALLENGE_CHAT_IDS,
    TIMEZONE,
)
from db import reading_checkins, bot_state


# ── Helpers ────────────────────────────────────────────────────────────

def _current_day() -> int:
    """Return the logical current challenge day number (1-indexed). The day rolls over at 5:31 AM IST."""
    now = datetime.now(TIMEZONE)
    # Subtract 5 hours and 31 minutes so that anything before 5:31 AM falls into the previous date.
    logical_date = (now - timedelta(hours=5, minutes=31)).date()
    delta = (logical_date - READING_CHALLENGE_START_DATE).days
    return delta + 1


def _safe_name(name: str) -> str:
    """HTML-escape a display name and wrap with bidi isolation."""
    safe = name.replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")
    return f"\u2068{safe}\u2069"


async def _compute_streak(user_id: str, up_to_day: int) -> int:
    """Compute the current consecutive-day streak for a user ending at *up_to_day*."""
    cursor = reading_checkins.find(
        {"user_id": user_id},
        {"day_number": 1, "_id": 0},
    )
    checked_days = set()
    async for doc in cursor:
        checked_days.add(doc["day_number"])

    streak = 0
    for day in range(up_to_day, 0, -1):
        if day in checked_days:
            streak += 1
        else:
            break
    return streak


async def _total_days_completed(user_id: str) -> int:
    """Return the total number of days a user has checked in."""
    return await reading_checkins.count_documents({"user_id": user_id})


# ── Message Builder ────────────────────────────────────────────────────

def _build_message_text(day_number: int, readers: list[dict] | None = None) -> str:
    """Build the full HTML message for the daily reading check-in post.

    *readers* is a list of dicts: {"name": str, "streak": int}
    sorted in chronological check-in order.
    """
    text = f"📚 <b>Reading Habit Challenge — Day {day_number} of {READING_CHALLENGE_TOTAL_DAYS}</b>\n\n"
    text += "<blockquote>Set aside 30 minutes today to read 📖\nOnce you're done, tap the button below to check in!</blockquote>\n\n"

    if not readers:
        text += "<blockquote expandable>📖 <b>Today's Readers (0)</b>\n\nNo check-ins yet — be the first! 🌟</blockquote>"
    else:
        lines = []
        for r in readers:
            name = _safe_name(r["name"])
            lines.append(f"• {name}  (🔥 {r['streak']} day streak)")
        reader_block = "\n".join(lines)
        text += (
            f"<blockquote expandable>📖 <b>Today's Readers ({len(readers)})</b>\n\n"
            f"{reader_block}</blockquote>"
        )

    return text


def _build_keyboard(day_number: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I read for 30 minutes today", callback_data=f"reading_checkin:{day_number}")]
    ])


# ── Bot State Persistence ─────────────────────────────────────────────

async def _get_state(key: str):
    doc = await bot_state.find_one({"_id": key})
    return doc.get("value") if doc else None


async def _set_state(key: str, value):
    await bot_state.replace_one(
        {"_id": key},
        {"_id": key, "value": value},
        upsert=True,
    )


# ── Refresh the Pinned Message ─────────────────────────────────────────

async def _refresh_checkin_list(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, day_number: int):
    """Re-fetch all check-ins for *day_number* and edit the pinned message."""
    cursor = reading_checkins.find(
        {"day_number": day_number},
    ).sort("timestamp", 1)  # chronological order

    readers = []
    async for doc in cursor:
        streak = await _compute_streak(doc["user_id"], day_number)
        readers.append({
            "name": doc.get("first_name") or doc.get("username") or "Unknown",
            "streak": streak,
        })

    text = _build_message_text(day_number, readers)

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=_build_keyboard(day_number),
        )
    except Exception as e:
        # "Message is not modified" is harmless — Telegram rejects no-op edits
        if "Message is not modified" not in str(e):
            print(f"⚠️ Failed to update reading check-in message: {e}")


# ── Summaries & Recaps ─────────────────────────────────────────────────

async def send_reading_summary(context: ContextTypes.DEFAULT_TYPE, target_chat_id: int | None = None):
    """Post the final end-of-challenge summary on Day 22."""
    total_checkins = await reading_checkins.count_documents({})
    # distinct isn't natively async in motor directly on the collection sometimes, but motor supports it:
    user_ids = await reading_checkins.distinct("user_id")
    readers_count = len(user_ids)

    text = (
        "📚 <b>21-Day Reading Challenge — Complete!</b> 🎉\n\n"
        f"<b>{readers_count} readers</b> checked in a total of <b>{total_checkins} times</b>\n"
        f"📖 That's <b>{total_checkins * 30} minutes</b> of reading combined!\n\n"
        "Tap the button below to get your stats."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Get My Recap", url=f"https://t.me/{context.bot.username}?start=reading_recap")]
    ])
    
    chat_ids = [target_chat_id] if target_chat_id else READING_CHALLENGE_CHAT_IDS
    for chat_id in chat_ids:
        db_key = f"pinned_reading_{chat_id}"

        # Unpin Day 21's reading message
        prev_msg_id = await _get_state(db_key)
        if prev_msg_id:
            try:
                await context.bot.unpin_chat_message(chat_id=chat_id, message_id=prev_msg_id)
            except Exception as e:
                print(f"⚠️ Could not unpin reading message in {chat_id}: {e}")

        # Send & pin summary message
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_notification=True,
        )

        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=msg.message_id,
            disable_notification=True,
        )

        await _set_state(db_key, msg.message_id)
        await _set_state(f"reading_msg_{chat_id}", msg.message_id)
        print(f"📌 Pinned reading challenge summary ({msg.message_id}) in {chat_id}")


async def send_personal_recap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the personal Option B reading recap DM."""
    user = update.effective_user
    user_id = str(user.id)
    username = f"@{user.username}" if user.username else user.first_name

    total_days = await _total_days_completed(user_id)
    
    # Calculate longest streak
    cursor = reading_checkins.find(
        {"user_id": user_id},
        {"day_number": 1, "_id": 0},
    ).sort("day_number", 1)
    
    checked_days = []
    async for doc in cursor:
        checked_days.append(doc["day_number"])
        
    longest_streak = 0
    current_streak = 0
    prev_day = -1
    for day in checked_days:
        if day == prev_day + 1:
            current_streak += 1
        else:
            current_streak = 1
        if current_streak > longest_streak:
            longest_streak = current_streak
        prev_day = day

    total_time = total_days * 30

    text = (
        "🎓 <b>Reading Challenge Recap</b> 🎓\n\n"
        f"👤 <b>Reader:</b> {username}\n\n"
        f"📖 <b>Days Read:</b> {total_days} out of {READING_CHALLENGE_TOTAL_DAYS}\n"
        f"🔥 <b>Longest Streak:</b> {longest_streak} days\n"
        f"⏳ <b>Total Time:</b> {total_time} minutes"
    )
    
    await update.message.reply_text(text, parse_mode="HTML")


# ── Daily Scheduled Post ──────────────────────────────────────────────

async def send_reading_checkin(context: ContextTypes.DEFAULT_TYPE, force: bool = False, target_chat_id: int | None = None):
    """Post the daily reading challenge message and pin it.

    If *target_chat_id* is provided (e.g. from /test_reading), only post
    to that chat instead of the configured challenge channels.
    """
    day_number = _current_day()

    if force:
        # If testing outside the valid window (1 to 22), default to Day 1
        if day_number < 1 or day_number > READING_CHALLENGE_TOTAL_DAYS + 1:
            day_number = 1
    else:
        # Normal schedule: abort if outside the valid window
        if day_number < 1 or day_number > READING_CHALLENGE_TOTAL_DAYS + 1:
            return  

    # Trigger the end-of-challenge summary on Day 22 (works for both scheduled and forced tests)
    if day_number == READING_CHALLENGE_TOTAL_DAYS + 1:
        await send_reading_summary(context, target_chat_id)
        return

    text = _build_message_text(day_number)
    keyboard = _build_keyboard(day_number)

    chat_ids = [target_chat_id] if target_chat_id else READING_CHALLENGE_CHAT_IDS
    for chat_id in chat_ids:
        db_key = f"pinned_reading_{chat_id}"

        # Unpin previous day's reading message
        prev_msg_id = await _get_state(db_key)
        if prev_msg_id:
            try:
                await context.bot.unpin_chat_message(chat_id=chat_id, message_id=prev_msg_id)
            except Exception as e:
                print(f"⚠️ Could not unpin reading message in {chat_id}: {e}")

        # Send & pin new message
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_notification=True,
        )

        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=msg.message_id,
            disable_notification=True,
        )

        await _set_state(db_key, msg.message_id)
        await _set_state(f"reading_msg_{chat_id}", msg.message_id)
        print(f"📌 Pinned reading challenge Day {day_number} ({msg.message_id}) in {chat_id}")


# ── Callback Query Handler ────────────────────────────────────────────

async def handle_reading_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle a user tapping the '✅ I read for 30 minutes today' button."""
    query = update.callback_query
    user = query.from_user
    user_id = str(user.id)

    day_number = _current_day()
    if day_number < 1:
        await query.answer("📚 The reading challenge hasn't started yet!", show_alert=True)
        return
    if day_number > READING_CHALLENGE_TOTAL_DAYS:
        await query.answer("📚 The reading challenge has ended! Great job participating.", show_alert=True)
        return

    # Day number is encoded in the callback data: "reading_checkin:<day>"
    try:
        button_day = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        await query.answer("❌ Something went wrong. Try again!", show_alert=True)
        return

    if button_day < day_number:
        await query.answer("❌ This check-in button has expired! A new day has started.", show_alert=True)
        return

    # Duplicate prevention
    existing = await reading_checkins.find_one({
        "user_id": user_id,
        "day_number": day_number,
    })

    if existing:
        streak = await _compute_streak(user_id, day_number)
        total = await _total_days_completed(user_id)
        await query.answer(
            f"You've already checked in today! ✅\n🔥 {streak}-day streak  •  {total}/{READING_CHALLENGE_TOTAL_DAYS} total",
            show_alert=True,
        )
        return

    # Log the check-in
    await reading_checkins.insert_one({
        "user_id": user_id,
        "username": user.username or "",
        "first_name": user.first_name or user.username or "Unknown",
        "day_number": day_number,
        "timestamp": datetime.now(TIMEZONE).isoformat(),
    })

    streak = await _compute_streak(user_id, day_number)
    total = await _total_days_completed(user_id)

    await query.answer(
        f"Day {day_number} logged! 📚\n🔥 {streak}-day streak  •  {total}/{READING_CHALLENGE_TOTAL_DAYS} total",
        show_alert=True,
    )

    # Update the pinned message with the new reader list
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    await _refresh_checkin_list(context, chat_id, message_id, day_number)
