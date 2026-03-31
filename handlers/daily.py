from datetime import date, datetime
from telegram.ext import ContextTypes
from config import DAILY_CHAT_IDS, TIMEZONE


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


async def send_challenge(context: ContextTypes.DEFAULT_TYPE):
    """Sends the 7-day challenge daily post at 16:00 GMT+3 and pins it."""
    # Only run from March 31, 2026 for 7 days
    today = date.today()
    start_date = date(2026, 3, 31)
    if (today - start_date).days < 0 or (today - start_date).days > 6:
        return

    day_number = (today - start_date).days + 1
    
    text = f"""🌿 Day {day_number} Check in! 🌿

How did today go? Share your progress below:
⏱️ Total study time
✅ Screenshot of today's todos (Did you hit 80%?)
🎥 Screenshot if you joined the stream for 1hr+

Let's keep growing! 🌱

---

🌿 تسجيل الحضور لليوم {day_number} 🌿

كيف كان يومك؟ شارك تقدمك أدناه:
⏱️ إجمالي وقت الدراسة
✅ لقطة شاشة لمهام اليوم (هل أنجزت 80%؟)
🎥 لقطة شاشة إذا انضممت إلى البث المباشر لساعة أو أكثر

لنمضِ قدماً معاً! 🌱"""

    for chat_id in DAILY_CHAT_IDS:
        prev = context.bot_data.get(f"pinned_challenge_{chat_id}")
        if prev:
            try:
                await context.bot.unpin_chat_message(chat_id=chat_id, message_id=prev)
            except Exception as e:
                print(f"⚠️ Could not unpin challenge message in {chat_id}: {e}")

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

        context.bot_data[f"pinned_challenge_{chat_id}"] = msg.message_id
        print(f"📌 Pinned challenge message ({msg.message_id}) in {chat_id}")