import re
from datetime import datetime, timezone, timedelta
import pytz
from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from config import SESSION_CHAT_ID, SESSION_USER_ID
from triggers import TRIGGERS, TRIGGER_PATTERNS

GMT3 = pytz.timezone("Etc/GMT-3")
WAITING_MINUTES = 1

def _get_sticker(text: str) -> str | None:
    """Returns the sticker ID matching the tree name in the text, or None."""
    for trigger, pattern in TRIGGER_PATTERNS.items():
        if pattern.search(text):
            return TRIGGERS[trigger]
    return None


def _format_text(text: str) -> str:
    """Bolds everything, monospaces only standalone room codes, leaves URLs untouched."""
    urls = re.findall(r'https?://\S+', text)
    for i, url in enumerate(urls):
        text = text.replace(url, f"__URL{i}__")

    text = re.sub(r'([A-Z0-9]{8,})', r'</b><code>\1</code><b>', text)
    text = f"<b>{text}</b>"

    for i, url in enumerate(urls):
        text = text.replace(f"__URL{i}__", url)

    return text


def _build_message(text: str, start_time_str: str, status: str) -> str:
    return (
        f"{_format_text(text)}\n\n"
        f"<blockquote>starts at {start_time_str} (GMT+3)</blockquote>\n\n"
        f"{status}"
    )


async def countdown_tick(context: ContextTypes.DEFAULT_TYPE):
    """Runs every minute, updates the countdown message."""
    data = context.job.data
    chat_id = data["chat_id"]
    message_id = data["message_id"]
    link = data["link"]
    start_time_str = data["start_time_str"]
    remaining = data["remaining"] - 1
    data["remaining"] = remaining

    if remaining <= 0:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=_build_message(link, start_time_str, "started, good luck!"),
            parse_mode="HTML",
        )
        context.job.schedule_removal()
        return

    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=_build_message(link, start_time_str, f"starting in {remaining} minute{'s' if remaining != 1 else ''}..."),
        parse_mode="HTML",
    )


async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: detects a forestapp link in DM from the authorized user."""
    if update.effective_user.id != SESSION_USER_ID:
        return ConversationHandler.END

    link = update.message.text.strip()
    context.user_data["session_link"] = link

    await update.message.reply_text("In how many minutes will you start?")
    return WAITING_MINUTES


async def receive_minutes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the minute count, posts the session message, starts countdown."""
    text = update.message.text.strip()

    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("Please send a valid number of minutes.")
        return WAITING_MINUTES

    minutes = int(text)
    link = context.user_data.get("session_link")

    start_time = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    start_time_str = start_time.astimezone(GMT3).strftime("%H:%M")

    sticker_id = _get_sticker(link)
    reply_to = None

    if sticker_id:
        sticker_msg = await context.bot.send_sticker(
            chat_id=SESSION_CHAT_ID,
            sticker=sticker_id,
            disable_notification=True,
        )
        reply_to = sticker_msg.message_id

    msg = await context.bot.send_message(
        chat_id=SESSION_CHAT_ID,
        text=_build_message(link, start_time_str, f"starting in {minutes} minute{'s' if minutes != 1 else ''}..."),
        parse_mode="HTML",
        reply_to_message_id=reply_to,
        disable_notification=True,
    )

    context.application.job_queue.run_repeating(
        countdown_tick,
        interval=60,
        first=60,
        data={
            "chat_id": SESSION_CHAT_ID,
            "message_id": msg.message_id,
            "link": link,
            "start_time_str": start_time_str,
            "remaining": minutes,
            "dm_chat_id": update.effective_chat.id,
        },
        name=f"countdown_{msg.message_id}",
    )

    await update.message.reply_text(f"✅ Posted! Countdown started for {minutes} minute{'s' if minutes != 1 else ''}.")
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Cancelled.")
    context.user_data.clear()
    return ConversationHandler.END


session_handler = ConversationHandler(
    entry_points=[
        MessageHandler(
            filters.TEXT & filters.Regex(r"forestapp\.cc/join-room\?token=") & filters.ChatType.PRIVATE,
            receive_link,
        )
    ],
    states={
        WAITING_MINUTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_minutes)],
    },
    fallbacks=[MessageHandler(filters.COMMAND, cancel)],
)