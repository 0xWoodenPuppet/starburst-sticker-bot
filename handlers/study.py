from telegram import Update
from telegram.ext import ContextTypes

async def handle_study(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Replies with a study sticker to the message that was replied to."""
    if not update.message or not update.message.reply_to_message:
        return

    await update.message.reply_to_message.reply_sticker(
        sticker="CAACAgUAAxkBAAERU79qIRU3VMaSYDMGdl6zl0H68OuKNQACNRkAAr7I2VW4UAMyBUQKATsE",
        disable_notification=True
    )
