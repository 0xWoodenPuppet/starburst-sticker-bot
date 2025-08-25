import os
import re
import time
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# ✅ Get token from environment variable
BOT_TOKEN = "8278841870:AAFG2D9dBcU6QXR6lctmnfeNRvJnrzXh-WA"
# ✅ Replace these with your actual chat IDs
ALLOWED_CHAT_IDS = {
    -1003013260570,  # Deku(testing channel)
    -1002511165129,  # notebookofdeku
    -1002606388153,  # academically cooked weapons chat
}

# Dictionary: trigger text → sticker file_id
TRIGGERS = {
    "starburst tree": "CAACAgIAAxkBAAMGaKyCpXsGlmRGQlX9gymsHZB7WyMAAuYrAAI89FFK_CXxCmOlEwABNgQ",
    "iris": "CAACAgIAAxkBAAMMaKyFvWWZ54z75Iw3G2VJWq4FiuIAAvduAAL2c6lLTAxa3J26Cwc2BA",
    "epiphyllum": "CAACAgUAAxkBAAMOaKyGI-SAjYReC4efF0OYkwX-rEIAAowUAAIRm9lW-J2u67fR8Tk2BA",
    "golden wings": "CAACAgIAAxkBAAMWaKyW0iE_4kz3y0T3d1KaiVE7o9kAAsYuAAL1X1FKqfY0U8pUW0M2BA",
}

# Precompile regex patterns for efficiency
TRIGGER_PATTERNS = {
    trigger: re.compile(rf"\b{re.escape(trigger)}\b", re.IGNORECASE)
    for trigger in TRIGGERS
}

# --- Per-user Cooldown System ---
COOLDOWN = 5  # seconds
last_trigger_time = {}  # {(chat_id, user_id): timestamp}

async def check_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.id not in ALLOWED_CHAT_IDS:
        return  # ❌ Ignore all other chats

    # --- Case 1: Messages in groups ---
    if update.message and update.message.text:
        if update.message.forward_from_chat:  # Skip forwarded channel posts
            return

        user = update.message.from_user
        key = (chat.id, user.id)
        now = time.time()
        last_time = last_trigger_time.get(key, 0)

        if now - last_time < COOLDOWN:
            return  # ⏳ Still in cooldown for this user

        text = update.message.text
        for trigger, pattern in TRIGGER_PATTERNS.items():
            if pattern.search(text):
                await update.message.reply_sticker(sticker=TRIGGERS[trigger])
                last_trigger_time[key] = now  # ✅ Save per-user trigger time
                break   # only ONE sticker

    # --- Case 2: Channel posts ---
    if update.channel_post and update.channel_post.text:
        # Channel posts don’t have individual users → treat as chat-level cooldown
        key = (chat.id, 0)  # use user_id=0 for channel posts
        now = time.time()
        last_time = last_trigger_time.get(key, 0)

        if now - last_time < COOLDOWN:
            return

        text = update.channel_post.text
        for trigger, pattern in TRIGGER_PATTERNS.items():
            if pattern.search(text):
                await update.channel_post.reply_sticker(sticker=TRIGGERS[trigger])
                last_trigger_time[key] = now
                break   # only ONE sticker

app = Application.builder().token(BOT_TOKEN).build()

# Catch text messages everywhere (groups + channels)
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_text))

print("🤖 Bot is running... exclusive to your channel + group only (with per-user cooldown)")
app.run_polling()
