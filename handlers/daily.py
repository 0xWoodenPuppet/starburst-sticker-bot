from datetime import date, datetime
from telegram.ext import ContextTypes
from config import DAILY_CHAT_IDS, CHALLENGE_CHAT_IDS, TIMEZONE


async def send_todo(context: ContextTypes.DEFAULT_TYPE):
    """Sends the daily todo list message at 5:00 AM IST and pins it."""
    today = datetime.now(TIMEZONE).strftime("%d/%m/%Y")
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


async def send_challenge(context: ContextTypes.DEFAULT_TYPE, force: bool = False):
    """Sends the 21-day challenge daily post at 16:30 GMT+3 and pins it."""
    today = date.today()
    start_date = date(2026, 4, 30)
    
    # If not forcing a test, abort if we are outside the 21-day window
    if not force:
        if (today - start_date).days < 0 or (today - start_date).days > 20:
            return

    # If forcing a test before it starts, just pretend it's Day 1
    if force and (today - start_date).days < 0:
        day_number = 1
    else:
        day_number = (today - start_date).days + 1
    
    text = f"""🌿 Day {day_number} Check in of Study Challenge

📸 Reply under this post with the <a href="https://t.me/c/2606388153/92345">specified format</a> — open 16:30 to 09:00 GMT+3

🔗 <a href="https://t.me/NotebookofDeku/6854">Click here for the challenge info</a>"""

    for chat_id in CHALLENGE_CHAT_IDS:
        prev = context.bot_data.get(f"pinned_challenge_{chat_id}")
        if prev:
            try:
                await context.bot.unpin_chat_message(chat_id=chat_id, message_id=prev)
            except Exception as e:
                print(f"⚠️ Could not unpin challenge message in {chat_id}: {e}")

        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_notification=True,
            disable_web_page_preview=True,
        )

        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=msg.message_id,
            disable_notification=True,
        )

        context.bot_data[f"pinned_challenge_{chat_id}"] = msg.message_id
        context.bot_data["last_challenge_msg_id"] = msg.message_id
        print(f"📌 Pinned challenge message ({msg.message_id}) in {chat_id}")