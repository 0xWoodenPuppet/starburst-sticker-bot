from telegram import Update
from telegram.ext import ContextTypes

async def handle_sleep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Replies with a specific sticker to the message that was replied to."""
    if not update.message or not update.message.reply_to_message:
        return

    original_message = update.message.reply_to_message

    # Default sticker
    sticker_id = "CAACAgQAAxkBAAEQ9FBp5PY37uGxIhdcPtPkydXh2WlMdgAC7hoAAk3CGVPqbt18v28DSjsE"
    
    # If the original message was sent by the specified user
    if original_message.from_user and original_message.from_user.id == 1463187459:
        sticker_id = "CAACAgQAAxkBAAEQ9GRp5P1RZ_BLF-bMsxH5tQABLIA_sjoAAuwYAAI3TMFTcnY6q7oxvJw7BA"
    
    await original_message.reply_sticker(
        sticker=sticker_id,
        disable_notification=True
    )
