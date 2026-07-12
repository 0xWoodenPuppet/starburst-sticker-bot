import threading
from datetime import time as dt_time
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler, CallbackQueryHandler
from config import BOT_TOKEN, TIMEZONE, DAILY_CHAT_IDS, MENTION_CHAT_ID, BOT_ADMIN_IDS, FOREST_CHAT_ID, READING_CHALLENGE_CHAT_IDS, READING_TEST_CHAT_ID

from handlers.messages import check_text
from handlers.daily import send_todo, send_forest, send_challenge
# from handlers.moderator import handle_report
from handlers.scoring import score_user, leaderboard, profile
from handlers.ask import ask_command
from handlers.sleep import handle_sleep
from handlers.study import handle_study
from handlers.participants import handle_automatic_forward
from handlers.screenshare import handle_screenshare
from handlers.games import fight_command, game_callback_handler, cleanup_inactive_games
from handlers.tasks import task_conversation, skip_review_handler, history_command, restore_pending_sessions
from handlers.reading import send_reading_checkin, handle_reading_checkin
from server import run_web


async def init_on_startup(app):
    """Run initialization tasks on startup before the bot starts polling."""
    await restore_pending_sessions(app)
    from handlers.games import load_active_games
    await load_active_games(app)


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
        .post_init(init_on_startup)
        .build()
    )

    # Daily messages
    job_queue = application.job_queue
    job_queue.run_daily(send_todo,   dt_time(hour=5,  minute=0,  tzinfo=TIMEZONE), name="daily_todo")
    job_queue.run_daily(send_forest, dt_time(hour=22, minute=30, tzinfo=TIMEZONE), name="daily_forest")
    job_queue.run_daily(send_challenge, dt_time(hour=19, minute=0, tzinfo=TIMEZONE), name="daily_challenge")
    job_queue.run_daily(send_reading_checkin, dt_time(hour=5, minute=31, tzinfo=TIMEZONE), name="daily_reading")
    job_queue.run_repeating(cleanup_inactive_games, interval=60, first=60, name="game_cleanup")

    application.add_handler(task_conversation)  # catch /start deep links

    async def test_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id in BOT_ADMIN_IDS:
            from handlers.daily import send_challenge
            await update.message.reply_text("Triggering test challenge...")
            await send_challenge(context, force=True)

    async def test_reading(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id in BOT_ADMIN_IDS and update.effective_chat.id == READING_TEST_CHAT_ID:
            await update.message.reply_text("Triggering test reading check-in...")
            await send_reading_checkin(context, force=True, target_chat_id=READING_TEST_CHAT_ID)

    application.add_handler(CommandHandler("test_challenge", test_challenge))
    application.add_handler(CommandHandler("test_reading", test_reading))

    # application.add_handler(CommandHandler("report", handle_report))
    application.add_handler(CommandHandler("s", score_user))
    application.add_handler(CommandHandler("ask", ask_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("sleep", handle_sleep))
    application.add_handler(CommandHandler("study", handle_study))
    application.add_handler(CommandHandler("screenshare", handle_screenshare))
    application.add_handler(CommandHandler("fight", fight_command))
    
    application.add_handler(CallbackQueryHandler(handle_reading_checkin, pattern=r"^reading_checkin$"))
    application.add_handler(CallbackQueryHandler(game_callback_handler, pattern=r"^(g_|ttt_|c4_)"))

    application.add_handler(MessageHandler(filters.Chat(MENTION_CHAT_ID) & filters.IS_AUTOMATIC_FORWARD, handle_automatic_forward))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.ChatType.PRIVATE, check_text), group=2)
    application.add_handler(skip_review_handler)  # standalone: Skip button on session-end DMs

    application.add_handler(CommandHandler("history", history_command))

    async def delete_pin_service_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message or update.channel_post
        if msg:
            await msg.delete()

    application.add_handler(MessageHandler(
        filters.StatusUpdate.PINNED_MESSAGE & filters.Chat(DAILY_CHAT_IDS + [FOREST_CHAT_ID] + READING_CHALLENGE_CHAT_IDS),
        delete_pin_service_message
    ))

    print("🤖 Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()