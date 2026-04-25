import time
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from config import COOLDOWN
from triggers import TRIGGERS, TRIGGER_PATTERNS, last_trigger_time


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
        for trigger, pattern in TRIGGER_PATTERNS.items():
            if pattern.search(text):
                await msg.reply_sticker(sticker=TRIGGERS[trigger], disable_notification=True)
                last_trigger_time[key] = now
                break

    # Group / private messages
    if update.message and update.message.text:
        if update.message.forward_origin or update.message.sender_chat:
            return
        await process_message(update.message)

    # Channel posts
    if update.channel_post and update.channel_post.text:
        await process_message(update.channel_post)