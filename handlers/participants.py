import os
import json
from telegram import Update
from telegram.ext import ContextTypes

PARTICIPANTS_FILE = "participants.json"

def load_participants():
    """Load participants from the JSON file."""
    if not os.path.exists(PARTICIPANTS_FILE):
        return {}
    try:
        with open(PARTICIPANTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_participants(data):
    """Save participants to the JSON file."""
    with open(PARTICIPANTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

async def register_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /register"""
    user = update.effective_user
    if not user:
        return
        
    user_id = str(user.id)
    username = user.username or user.first_name

    participants = load_participants()
    if user_id in participants:
        await update.message.reply_text("You are already registered for daily check-in mentions!")
        return

    participants[user_id] = username
    save_participants(participants)
    await update.message.reply_text(f"✅ Registered! You ({username}) will now be mentioned in daily check-ins.")

async def unregister_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /unregister"""
    user = update.effective_user
    if not user:
        return
        
    user_id = str(user.id)

    participants = load_participants()
    if user_id not in participants:
        await update.message.reply_text("You are not registered for daily check-in mentions.")
        return

    del participants[user_id]
    save_participants(participants)
    await update.message.reply_text("❌ Unregistered! You will no longer be mentioned in daily check-ins.")

async def handle_automatic_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mentions all registered participants when the daily challenge is forwarded."""
    message = update.message
    
    # Check if this forward matches the last challenge message sent to the channel
    last_challenge_id = context.bot_data.get("last_challenge_msg_id")
    origin = message.forward_origin
    if not last_challenge_id or not origin or getattr(origin, 'message_id', None) != last_challenge_id:
        return

    participants = load_participants()
    if not participants:
        return

    # Build mentions
    # Telegram allows multiple text mentions if properly formatted
    mentions = []
    for uid, uname in participants.items():
        safe_uname = uname.replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
        mentions.append(f'<a href="tg://user?id={uid}">{safe_uname}</a>')
    
    # Group them so it's not a huge wall of text
    chunk_size = 10
    chunks = [mentions[i:i + chunk_size] for i in range(0, len(mentions), chunk_size)]
    
    for chunk in chunks:
        text = "🔔 <b>Check-in Time!</b>\n" + " ".join(chunk)
        await message.reply_text(text, parse_mode="HTML")
