import os
import re
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

# --- ⚙️ START OF CONFIGURATION ---

# 1. BOT TOKEN
BOT_TOKEN = os.getenv("BOT_TOKEN")

# 2. ADMIN USER ID
# To find your ID, message @userinfobot on Telegram.
BOT_ADMIN_ID = 1463187459 #the wooden puppet

# 3. ALLOWED CHAT IDs
ALLOWED_CHAT_IDS = {
    -1002872422543,  #Deku
    -1002511165129,  #notebookofdeku
    -1002606388153, #academically cooked weapons chat
}

# 4. COOLDOWN PERIOD
COOLDOWN = 5

# --- END OF CONFIGURATION ---


# 📂 Load triggers from the external stickers.csv file
TRIGGERS = {}
try:
    with open("stickers.csv", mode="r", encoding="utf-8") as file:
        reader = csv.reader(file)
        for row in reader:
            if len(row) == 2:
                trigger_text, sticker_id = row[0].strip(), row[1].strip()
                TRIGGERS[trigger_text] = sticker_id
except FileNotFoundError:
    print("❌ Error: stickers.csv not found! Please create it before running.")
    sys.exit(1)

# 🚀 Precompile regex patterns for fast checking
TRIGGER_PATTERNS = {
    trigger: re.compile(rf"\b{re.escape(trigger)}\b", re.IGNORECASE)
    for trigger in TRIGGERS
}

# ⏳ Cooldown system dictionary
last_trigger_time = {}

# --- Sticker Response Logic ---

async def check_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks messages for triggers and sends a corresponding sticker."""
    chat = update.effective_chat
    if not chat or chat.id not in ALLOWED_CHAT_IDS:
        return

    # Handle group messages
    if update.message and update.message.text:
        if update.message.forward_origin or update.message.sender_chat:
            return

        user = update.message.from_user
        key = (chat.id, user.id)
        now = time.time()
        if now - last_trigger_time.get(key, 0) < COOLDOWN:
            return

        text = update.message.text
        for trigger, pattern in TRIGGER_PATTERNS.items():
            if pattern.search(text):
                await update.message.reply_sticker(sticker=TRIGGERS[trigger])
                last_trigger_time[key] = now
                break

    # Handle channel posts
    if update.channel_post and update.channel_post.text:
        key = (chat.id, 0)
        now = time.time()
        if now - last_trigger_time.get(key, 0) < COOLDOWN:
            return

        text = update.channel_post.text
        for trigger, pattern in TRIGGER_PATTERNS.items():
            if pattern.search(text):
                await update.channel_post.reply_sticker(sticker=TRIGGERS[trigger])
                last_trigger_time[key] = now
                break


# --- ✍️ Conversation Logic for /addsticker and /export commands ---

# Define states for the conversation
GET_STICKER, GET_TRIGGER = range(2)

async def start_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to add multiple stickers."""
    if update.message.from_user.id != BOT_ADMIN_ID:
        await update.message.reply_text("⛔ Sorry, this is an admin-only command.")
        return ConversationHandler.END

    await update.message.reply_text(
        "Hi! Let's add some stickers.\n\n"
        "Send me the first sticker. When you're finished, type /done."
    )
    return GET_STICKER

async def get_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives a sticker and asks for its trigger text."""
    if not update.message.sticker:
        await update.message.reply_text(
            "That's not a sticker! Please send a sticker, or type /done to finish."
        )
        return GET_STICKER

    context.user_data['new_sticker_id'] = update.message.sticker.file_id
    await update.message.reply_text("Got it! Now, what text should trigger this sticker?")
    return GET_TRIGGER

async def get_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the sticker to the temporary session file."""
    trigger_text = update.message.text.strip().lower()
    sticker_id = context.user_data.get('new_sticker_id')

    # The duplicate check must now read the file fresh each time
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

    # Append to the temporary CSV file
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
    """Ends the conversation when the user is done adding stickers."""
    await update.message.reply_text("Great! All stickers for this session have been saved. Remember to /export your changes to make them permanent.")
    context.user_data.clear()
    return ConversationHandler.END

async def export_stickers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Allows the admin to download the current temporary stickers.csv file."""
    if update.message.from_user.id != BOT_ADMIN_ID:
        await update.message.reply_text("⛔ Sorry, this is an admin-only command.")
        return

    try:
        await update.message.reply_document(
            document=open("stickers.csv", "rb"),
            filename="stickers.csv",
            caption="Here is the sticker list from the live session. Copy its contents into your main stickers.csv file and push to GitHub."
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