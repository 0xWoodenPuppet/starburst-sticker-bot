import re
import time
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import COOLDOWN, BOT_USERNAME, TASK_TEST_CHAT_IDS, SESSION_BUFFER_MINUTES
from triggers import TRIGGERS, TRIGGER_PATTERNS, last_trigger_time
from db import sessions

# Duration regex — supports 10+ languages (reused from session.py)
DURATION_PATTERN = re.compile(
    r"(\d+)\s*[-–]?\s*(?:min|m\b|분|分|دقيق|دقائق|perc|dakik|мін|мин|menit|मिनट)",
    re.IGNORECASE,
)


async def check_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message:
        return

    # Ignore messages older than 15 seconds
    message_age = datetime.now(timezone.utc) - message.date
    if message_age > timedelta(seconds=15):
        return

    chat = update.effective_chat
    if not chat:
        return

    async def process_message(msg):
        key = (chat.id, msg.from_user.id if msg.from_user else 0)
        now = time.time()

        text = msg.text
        if not text:
            return

        # Prevent memory leak by cleaning up the cooldown dictionary when it grows too large
        if len(last_trigger_time) > 1000:
            stale_keys = [k for k, v in last_trigger_time.items() if now - v > COOLDOWN]
            for k in stale_keys:
                del last_trigger_time[k]

        # Cooldown check
        if now - last_trigger_time.get(key, 0) < COOLDOWN:
            return

        # forestapp link must be present
        if "forestapp.cc/join-room?token=" not in text:
            return

        # Match against triggers
        tree_matched = False
        for trigger, pattern in TRIGGER_PATTERNS.items():
            if pattern.search(text):
                tree_matched = True
                # Check if this chat is in the test list for task tracking
                keyboard = None
                if chat.id in TASK_TEST_CHAT_IDS:
                    keyboard = await _create_task_button(msg, text, trigger, context)

                await msg.reply_sticker(
                    sticker=TRIGGERS[trigger],
                    reply_markup=keyboard,
                    disable_notification=True,
                )
                last_trigger_time[key] = now
                break

        # No tree matched, but Forest link is present — still offer task tracking
        if not tree_matched and chat.id in TASK_TEST_CHAT_IDS:
            keyboard = await _create_task_button(msg, text, "unknown", context)
            if keyboard:
                await msg.reply_text(
                    "🌱 Forest session detected!",
                    reply_markup=keyboard,
                    disable_notification=True,
                )

    # Group / private messages
    if update.message and update.message.text:
        if update.message.forward_origin or update.message.sender_chat:
            return
        await process_message(update.message)

    # Channel posts
    if update.channel_post and update.channel_post.text:
        await process_message(update.channel_post)


async def _create_task_button(msg, text: str, tree_name: str, context) -> InlineKeyboardMarkup | None:
    """Create a session in MongoDB and return an inline keyboard with the Add Task button."""
    # Parse duration from the Forest link text
    matches = DURATION_PATTERN.findall(text)
    if not matches:
        # Can't determine duration — skip task tracking
        return None

    duration = int(matches[-1])

    # Handle channel posts where from_user is None
    if msg.from_user:
        host_id = msg.from_user.id
        host_username = msg.from_user.username or ""
    elif msg.sender_chat:
        host_id = msg.sender_chat.id
        host_username = msg.sender_chat.title or ""
    else:
        host_id = 0
        host_username = ""

    # Create session document in MongoDB
    session_doc = await sessions.insert_one({
        "host_id": host_id,
        "host_username": host_username,
        "tree": tree_name,
        "duration": duration,
        "chat_id": msg.chat_id,
        "created_at": datetime.now(timezone.utc),
        "phase": "active",
        "participants": {},
    })

    session_id = str(session_doc.inserted_id)

    # Schedule session-end job: buffer + duration
    from handlers.tasks import schedule_session_end
    await schedule_session_end(context, session_id, duration)

    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "✏️ Add Task",
            url=f"https://t.me/{BOT_USERNAME}?start=task_{session_id}",
        )
    ]])