import re
import time
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import COOLDOWN, BOT_USERNAME, SESSION_BUFFER_MINUTES
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
                keyboard, duration = await _create_task_button(msg, text, trigger, context)

                sent_msg = await msg.reply_sticker(
                    sticker=TRIGGERS[trigger],
                    reply_markup=keyboard,
                    disable_notification=True,
                )
                last_trigger_time[key] = now
                
                if keyboard and duration:
                    context.application.job_queue.run_once(
                        remove_task_button,
                        when=10 * 60,
                        data={"chat_id": sent_msg.chat_id, "message_id": sent_msg.message_id},
                        name=f"remove_btn_{sent_msg.message_id}"
                    )
                break

        # No tree matched, but Forest link is present — still offer task tracking
        if not tree_matched:
            keyboard, duration = await _create_task_button(msg, text, "unknown", context)
            if keyboard:
                sent_msg = await msg.reply_text(
                    "‌ ‌ㅤ",
                    reply_markup=keyboard,
                    disable_notification=True,
                )
                if duration:
                    context.application.job_queue.run_once(
                        remove_task_button,
                        when=10 * 60,
                        data={"chat_id": sent_msg.chat_id, "message_id": sent_msg.message_id},
                        name=f"remove_btn_{sent_msg.message_id}"
                    )

    # Group / private messages
    if update.message and update.message.text:
        if update.message.forward_origin or update.message.sender_chat:
            return
        await process_message(update.message)

    # Channel posts
    if update.channel_post and update.channel_post.text:
        await process_message(update.channel_post)


async def remove_task_button(context: ContextTypes.DEFAULT_TYPE):
    """Job to remove the inline task button after 1/3 of the session duration."""
    data = context.job.data
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=data["chat_id"],
            message_id=data["message_id"],
            reply_markup=None
        )
    except Exception:
        pass


def _extract_duration(text: str) -> int | None:
    """Extract the session duration strictly by proximity to the room code token."""
    # Find token
    token_match = re.search(r"token=([A-Z0-9]+)", text)
    if not token_match:
        # Fallback to the old logic if no URL
        matches = DURATION_PATTERN.findall(text)
        if not matches:
            return None
        return int(matches[-1])

    token = token_match.group(1)
    
    # Find token in body (not in URL)
    body_token_idx = text.find(token)
    url_token_idx = text.rfind(token)
    ref_idx = body_token_idx if body_token_idx != url_token_idx and body_token_idx != -1 else url_token_idx
    if ref_idx == -1:
        ref_idx = 0
        
    best_dur = None
    min_dist = float('inf')
    
    # Iterate all matches of the broad duration pattern
    for m in DURATION_PATTERN.finditer(text):
        try:
            val = int(m.group(1))
            # Validate it's a reasonable Forest duration
            if 10 <= val <= 120 and val % 5 == 0:
                dist = abs(m.start() - ref_idx)
                if dist < min_dist:
                    min_dist = dist
                    best_dur = val
        except ValueError:
            pass
            
    # If no valid forest duration matched, fallback to the last match
    if best_dur is None:
        matches = DURATION_PATTERN.findall(text)
        if matches:
            return int(matches[-1])
        return None
        
    return best_dur


async def _create_task_button(msg, text: str, tree_name: str, context) -> tuple[InlineKeyboardMarkup | None, int | None]:
    """Create a session in MongoDB and return an inline keyboard with the Add Task button."""
    duration = _extract_duration(text)
    if duration is None:
        # Can't determine duration — skip task tracking
        return None, None

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
    ]]), duration