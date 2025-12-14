import os
import re
import pytz
import time
import threading
import csv
import sys
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
    CommandHandler,
    ConversationHandler,
)
from datetime import datetime, timezone, timedelta, time as dt_time

# --- ⚙️ START OF CONFIGURATION ---

# 1. BOT TOKEN
BOT_TOKEN = os.getenv("BOT_TOKEN")

# 2. ADMIN USER IDs
BOT_ADMIN_IDS = {
    7441793409, #non
    1463187459, # deku
}

# 3. COOLDOWN PERIOD
COOLDOWN = 5

# 4. ⏰ SCHEDULED STICKERS CONFIGURATION
SCHEDULED_MESSAGES = [
    # Example: 4:00 PM (16:00)
    (0, 0, "CAACAgQAAxkBAAEP91dpOAaVJfFYm08cmUv54NwwuHLfFAAC7hoAAk3CGVPqbt18v28DSjYE", -1002606388153), # bed'o clock
    (6, 0, "CAACAgQAAxkBAAEP919pOAc4T31gnr7DAAFUibPEXJNWzIgAAvQbAAKV4plRF2GQOU_Hds42BA", -1002606388153), # good day
    (18, 0, "CAACAgUAAxkBAAEP90FpN_F_7xQo73ADVrgXCeJlyk0HXAACwhYAAtGE6Va9bStizg302zYE", -1002606388153), # remember to drink water
]

# Set Timezone to Mumbai (IST)
TIMEZONE = pytz.timezone("Asia/Kolkata")

# --- END OF CONFIGURATION ---


# 📂 Load triggers
all_triggers = []
try:
    with open("stickers.csv", mode="r", encoding="utf-8") as file:
        reader = csv.reader(file)
        for row in reader:
            if len(row) == 2:
                all_triggers.append((row[0].strip(), row[1].strip()))
except FileNotFoundError:
    print("❌ Error: stickers.csv not found! Please create it before running.")
    sys.exit(1)

all_triggers.sort(key=lambda item: len(item[0]), reverse=True)

TRIGGERS = {trigger: sticker_id for trigger, sticker_id in all_triggers}
TRIGGER_PATTERNS = {
    trigger: re.compile(rf"(?<!\S){re.escape(trigger)}(?!\S)", re.IGNORECASE)
    for trigger in TRIGGERS
}

# ⏳ Cooldown system dictionary
last_trigger_time = {}

# --- Sticker Response Logic ---

async def check_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks messages for triggers and sends a corresponding sticker only if the special link is present."""

    message = update.effective_message
    if not message:
        return

    # Ignore messages older than 3 minutes
    message_age = datetime.now(timezone.utc) - message.date
    if message_age > timedelta(minutes=3):
        return
 
    chat = update.effective_chat
    if not chat:
        return

    # Helper to test and reply for a given message
    async def process_message(msg):
        key = (chat.id, msg.from_user.id if msg.from_user else 0)
        now = time.time()
        if now - last_trigger_time.get(key, 0) < COOLDOWN:
            return

        text = msg.text
        # ✅ NEW CONDITION: trigger must match AND link must be present
        if "forestapp.cc/join-room?token=" not in text:
            return

        for trigger, pattern in TRIGGER_PATTERNS.items():
            if pattern.search(text):
                await msg.reply_sticker(sticker=TRIGGERS[trigger], disable_notification=True)
                last_trigger_time[key] = now
                break

    # Handle group/private messages
    if update.message and update.message.text:
        if update.message.forward_origin or update.message.sender_chat:
            return
        await process_message(update.message)

    # Handle channel posts
    if update.channel_post and update.channel_post.text:
        await process_message(update.channel_post)


# --- ⏰ Scheduled Job Callback (MOVED OUTSIDE) ---

async def send_scheduled_sticker(context: ContextTypes.DEFAULT_TYPE):
    """Sends the sticker at the scheduled time."""
    job_data = context.job.data
    sticker_id = job_data.get("sticker_id")
    chat_id = job_data.get("chat_id")

    try:
        await context.bot.send_sticker(chat_id=chat_id, sticker=sticker_id)
        print(f"✅ Sent scheduled sticker to {chat_id}")
    except Exception as e:
        print(f"❌ Failed to send scheduled sticker: {e}")


# --- ✍️ Conversation Logic for /addsticker and /export commands ---

GET_STICKER, GET_TRIGGER = range(2)

async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.from_user.id not in BOT_ADMIN_IDS:
        await update.message.reply_text("⛔ Sorry, this is an admin-only command.")
        return ConversationHandler.END

    await update.message.reply_text(
        "Hi! Let's add some stickers.\n\n"
        "Send me the first sticker. When you're finished, type /done."
    )
    return GET_STICKER

async def get_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.sticker:
        await update.message.reply_text(
            "That's not a sticker! Please send a sticker, or type /done to finish."
        )
        return GET_STICKER

    context.user_data['new_sticker_id'] = update.message.sticker.file_id
    await update.message.reply_text("Got it! Now, what text should trigger this sticker?")
    return GET_TRIGGER

async def get_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    trigger_text = update.message.text.strip().lower()
    sticker_id = context.user_data.get('new_sticker_id')

    current_triggers = {}
    with open("stickers.csv", mode='r', encoding='utf-8') as file:
        reader = csv.reader(file)
        for row in reader:
            if len(row) == 2:
                current_triggers[row[0].strip()] = row[1].strip()

    if trigger_text in current_triggers:
        await update.message.reply_text(
            f"⚠️ The trigger '{trigger_text}' already exists! Please try a different name."
        )
        return GET_TRIGGER

    with open("stickers.csv", mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow([trigger_text, sticker_id])
        file.flush()
        os.fsync(file.fileno())

    await update.message.reply_text(
        f"✅ Success! Trigger '{trigger_text}' has been saved to this session.\n\n"
        "Send the next sticker, or type /done to finish."
    )
    return GET_STICKER

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Use /export and forward the file to @TheWoodenPuppet.")
    context.user_data.clear()
    return ConversationHandler.END

async def export_stickers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.from_user.id not in BOT_ADMIN_IDS:
        await update.message.reply_text("⛔ Sorry, this is an admin-only command.")
        return

    try:
        await update.message.reply_document(
            document=open("stickers.csv", "rb"),
            filename="stickers.csv"
        )
    except FileNotFoundError:
        await update.message.reply_text("Could not find stickers.csv to send.")

# --- 🌐 Keep-Alive Web Server & Bot Startup ---

app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot is alive!"

def run_web():
    app_web.run(host="0.0.0.0", port=3000)

def main():
    threading.Thread(target=run_web, daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()

    # --- ⏰ INITIALIZE SCHEDULER ---
    job_queue = application.job_queue

    for h, m, sticker, chat_id in SCHEDULED_MESSAGES:
        # Create a time object with timezone info
        target_time = dt_time(hour=h, minute=m, tzinfo=TIMEZONE)
        
        job_queue.run_daily(
            send_scheduled_sticker,
            target_time,
            data={"sticker_id": sticker, "chat_id": chat_id},
            name=f"sticker_{h}_{m}"
        )
        print(f"📅 Scheduled sticker for {h}:{m:02d} in chat {chat_id}")
    # -------------------------------

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('addsticker', start_add)],
        states={
            GET_STICKER: [MessageHandler(filters.Sticker.ALL, get_sticker)],
            GET_TRIGGER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_trigger)],
        },
        fallbacks=[CommandHandler('done', done)]
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('export', export_stickers))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_text))

    print("🤖 Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()