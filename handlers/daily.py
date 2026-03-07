from datetime import date
from telegram.ext import ContextTypes
from config import DAILY_CHAT_IDS


async def send_todo(context: ContextTypes.DEFAULT_TYPE):
    """Sends the daily todo list message at 5:00 AM IST and pins it."""
    today = date.today().strftime("%d/%m/%Y")
    text = f"📋 {today} — Todo List"

    for chat_id in DAILY_CHAT_IDS:
        prev = context.bot_data.get(f"pinned_todo_{chat_id}")
        if prev:
            try:
                await context.bot.unpin_chat_message(chat_id=chat_id, message_id=prev)
            except Exception as e:
                print(f"⚠️ Could not unpin todo message in {chat_id}: {e}")

        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            disable_notification=True,
        )

        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=msg.message_id,
            disable_notification=True,
        )

        context.bot_data[f"pinned_todo_{chat_id}"] = msg.message_id
        print(f"📌 Pinned todo message ({msg.message_id}) in {chat_id}")


async def send_forest(context: ContextTypes.DEFAULT_TYPE):
    """Sends the daily forest message at 10:30 PM IST and pins it."""
    text = "🌲 Today's Forest"

    for chat_id in DAILY_CHAT_IDS:
        prev = context.bot_data.get(f"pinned_forest_{chat_id}")
        if prev:
            try:
                await context.bot.unpin_chat_message(chat_id=chat_id, message_id=prev)
            except Exception as e:
                print(f"⚠️ Could not unpin forest message in {chat_id}: {e}")

        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            disable_notification=True,
        )

        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=msg.message_id,
            disable_notification=True,
        )

        context.bot_data[f"pinned_forest_{chat_id}"] = msg.message_id
        print(f"📌 Pinned forest message ({msg.message_id}) in {chat_id}")