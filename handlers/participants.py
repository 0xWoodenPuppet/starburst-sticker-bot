from telegram import Update
from telegram.ext import ContextTypes
from handlers.scoring import read_scores

async def handle_automatic_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mentions all registered participants when the daily challenge is forwarded."""
    message = update.message or update.channel_post
    if not message:
        return
    
    # Check if this forward matches the last challenge message sent to the channel
    last_challenge_id = context.bot_data.get("last_challenge_msg_id")
    origin = message.forward_origin
    if not last_challenge_id or not origin or getattr(origin, 'message_id', None) != last_challenge_id:
        return

    scores = read_scores()
    
    # Extract unique users from all scoring rows
    participants = {}
    for row in scores:
        participants[row["user_id"]] = row["username"]
    
    if not participants:
        return

    # Build mentions for all participants
    mentions = []
    for uid, uname in participants.items():
        safe_uname = uname.replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
        mentions.append(f'<a href="tg://user?id={uid}">{safe_uname}</a>')
    
    text = " ".join(mentions)
    await message.reply_text(text, parse_mode="HTML", disable_notification=True)
