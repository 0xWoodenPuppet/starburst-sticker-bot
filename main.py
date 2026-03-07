import threading
from datetime import time as dt_time
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from config import BOT_TOKEN, TIMEZONE, DAILY_CHAT_IDS
from handlers.messages import check_text
from handlers.daily import send_todo, send_forest
from server import run_web


def main():
    threading.Thread(target=run_web, daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()

    # Daily messages
    job_queue = application.job_queue
    job_queue.run_daily(send_todo,   dt_time(hour=5,  minute=0,  tzinfo=TIMEZONE), name="daily_todo")
    job_queue.run_daily(send_forest, dt_time(hour=22, minute=30, tzinfo=TIMEZONE), name="daily_forest")

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_text))

    async def delete_pin_service_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message.from_user and update.message.from_user.id == context.bot.id:
            await update.message.delete()

    application.add_handler(MessageHandler(
        filters.StatusUpdate.PINNED_MESSAGE & filters.Chat(DAILY_CHAT_IDS),
        delete_pin_service_message
    ))

    print("🤖 Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()