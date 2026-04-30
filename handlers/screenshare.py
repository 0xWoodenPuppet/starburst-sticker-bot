import asyncio
from datetime import datetime, timezone

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

CHANNEL_ID = -1002511165129
GROUP_ID = -1002606388153

GRANT_DURATION = 120  # seconds

# Active grants: { user_id: expiry_timestamp (float) }
_active_grants: dict[int, float] = {}
# Running revocation tasks: { user_id: asyncio.Task }
_revoke_tasks: dict[int, asyncio.Task] = {}


async def _revoke_after_delay(bot, user_id: int, delay: float) -> None:
    """Wait `delay` seconds then strip can_manage_video_chats from the user."""
    await asyncio.sleep(delay)
    try:
        await bot.promote_chat_member(
            chat_id=CHANNEL_ID,
            user_id=user_id,
            can_manage_video_chats=False,
        )
        print(f"🔒 Revoked screenshare permission for user {user_id}")
    except TelegramError as e:
        print(f"⚠️ Could not revoke screenshare for user {user_id}: {e}")
    finally:
        _active_grants.pop(user_id, None)
        _revoke_tasks.pop(user_id, None)


def _schedule_revocation(bot, user_id: int, delay: float) -> None:
    """Cancel any existing revocation task and schedule a new one."""
    existing = _revoke_tasks.pop(user_id, None)
    if existing and not existing.done():
        existing.cancel()

    task = asyncio.create_task(_revoke_after_delay(bot, user_id, delay))
    _revoke_tasks[user_id] = task


async def handle_screenshare(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /screenshare command."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    # Only respond in the designated group
    if chat.id != GROUP_ID:
        return

    user_id = user.id
    now = datetime.now(timezone.utc).timestamp()

    # --- User already has an active grant: reset the timer ---
    if user_id in _active_grants:
        new_expiry = now + GRANT_DURATION
        _active_grants[user_id] = new_expiry
        _schedule_revocation(context.bot, user_id, GRANT_DURATION)
        await msg.reply_text("🎥 You can now share your screen/cam in the channel!")
        return

    # --- Check channel membership ---
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in ("left", "kicked", "banned"):
            await msg.reply_text("❌ Please join the channel first.")
            return
    except TelegramError as e:
        print(f"⚠️ Could not check membership for user {user_id}: {e}")
        await msg.reply_text("❌ Please join the channel first.")
        return

    # --- Grant permission ---
    try:
        await context.bot.promote_chat_member(
            chat_id=CHANNEL_ID,
            user_id=user_id,
            can_manage_video_chats=True,
        )
    except TelegramError as e:
        print(f"⚠️ Could not grant screenshare to user {user_id}: {e}")
        await msg.reply_text("⚠️ Could not grant permission, please try again.")
        return

    # --- Record grant and start revocation timer ---
    _active_grants[user_id] = now + GRANT_DURATION
    _schedule_revocation(context.bot, user_id, GRANT_DURATION)

    await msg.reply_text("🎥 You can now share your screen/cam in the channel!")
    print(f"✅ Granted screenshare to user {user_id} for {GRANT_DURATION}s")
