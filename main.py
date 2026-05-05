import threading
from datetime import time as dt_time
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler, CallbackQueryHandler
from config import BOT_TOKEN, TIMEZONE, DAILY_CHAT_IDS, MENTION_CHAT_ID, BOT_ADMIN_IDS

FOREST_CHAT_ID = -1001876174346
from handlers.messages import check_text
from handlers.daily import send_todo, send_forest, send_challenge
from handlers.session import session_handler
from handlers.mentions import add_mention, remove_mention, remove_all_mentions, watch_forestapp
from handlers.coach import handle_dm_reply
from handlers.moderator import handle_report
from handlers.scoring import score_user, leaderboard, profile
from handlers.ask import ask_command
from handlers.sleep import handle_sleep
from handlers.participants import handle_automatic_forward
from handlers.screenshare import handle_screenshare
from handlers.room import (
    room_handler, task_command, room_callback_handler,
    track_forwarded_post, monitor_group_messages,
    GROUP_ID as ROOM_GROUP_ID,
)
from server import run_web


def main():
    threading.Thread(target=run_web, daemon=True).start()

    # Set longer timeouts to prevent Telegram API disconnects on cloud hosting
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )

    # Daily messages
    job_queue = application.job_queue
    job_queue.run_daily(send_todo,   dt_time(hour=5,  minute=0,  tzinfo=TIMEZONE), name="daily_todo")
    job_queue.run_daily(send_forest, dt_time(hour=22, minute=30, tzinfo=TIMEZONE), name="daily_forest")
    job_queue.run_daily(send_challenge, dt_time(hour=19, minute=0, tzinfo=TIMEZONE), name="daily_challenge")

    application.add_handler(room_handler)
    application.add_handler(session_handler)
    application.add_handler(CommandHandler("addmention", add_mention))
    application.add_handler(CommandHandler("removemention", remove_mention))
    application.add_handler(CommandHandler("removeallmentions", remove_all_mentions))
    
    async def test_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id in BOT_ADMIN_IDS:
            from handlers.daily import send_challenge
            await update.message.reply_text("Triggering test challenge...")
            await send_challenge(context, force=True)

    application.add_handler(CommandHandler("test_challenge", test_challenge))

    application.add_handler(CommandHandler("report", handle_report))
    application.add_handler(CommandHandler("s", score_user))
    application.add_handler(CommandHandler("ask", ask_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("sleep", handle_sleep))
    application.add_handler(CommandHandler("screenshare", handle_screenshare))
    
    application.add_handler(CommandHandler("task", task_command))
    application.add_handler(CallbackQueryHandler(room_callback_handler, pattern=r"^room_"))

    application.add_handler(MessageHandler(filters.Chat(MENTION_CHAT_ID) & filters.IS_AUTOMATIC_FORWARD, handle_automatic_forward))
    application.add_handler(MessageHandler(
        filters.Chat(ROOM_GROUP_ID) & filters.IS_AUTOMATIC_FORWARD,
        track_forwarded_post
    ), group=5)
    application.add_handler(MessageHandler(
        filters.Chat(ROOM_GROUP_ID) & filters.TEXT & ~filters.COMMAND,
        monitor_group_messages
    ), group=6)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, watch_forestapp), group=1)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.ChatType.PRIVATE, check_text), group=2)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_dm_reply), group=3)

    async def delete_pin_service_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message or update.channel_post
        if msg:
            await msg.delete()

    application.add_handler(MessageHandler(
        filters.StatusUpdate.PINNED_MESSAGE & filters.Chat(DAILY_CHAT_IDS + [FOREST_CHAT_ID]),
        delete_pin_service_message
    ))

    print("🤖 Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()