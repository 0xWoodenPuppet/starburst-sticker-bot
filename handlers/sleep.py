from telegram import Update
from telegram.ext import ContextTypes

async def handle_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Replies with a specific sticker to the message that was replied to."""
    if not update.message or not update.message.reply_to_message:
        return

    sticker_id = "CAACAgQAAxkBAAEQ9FBp5PY37uGxIhdcPtPkydXh2WlMdgAC7hoAAk3CGVPqbt18v28DSjsE"
    
    await update.message.reply_to_message.reply_sticker(
        sticker=sticker_id,
        disable_notification=True
    )
