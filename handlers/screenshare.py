import asyncio
from datetime import datetime, timezone

from telegram import Update
from telegram.error import RetryAfter, TelegramError
from telegram.ext import ContextTypes

CHANNEL_ID = -1002511165129
GROUP_ID = -1002606388153

GRANT_DURATION = 120  # seconds

# Active grants: { user_id: expiry_timestamp (float) }
_active_grants: dict[int, float] = {}
# Running revocation tasks: { user_id: asyncio.Task }
_revoke_tasks: dict[int, asyncio.Task] = {}


async def _safe_reply(msg, text: str) -> None:
    """Send a reply, respecting Telegram flood-control by retrying once after the required delay."""
    try:
        await msg.reply_text(text)
    except RetryAfter as e:
        print(f"⏳ Flood control hit, retrying reply in {e.retry_after}s…")
        await asyncio.sleep(e.retry_after)
        try:
            await msg.reply_text(text)
        except TelegramError as inner:
            print(f"⚠️ Could not send reply after retry: {inner}")
    except TelegramError as e:
        print(f"⚠️ Could not send reply: {e}")


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
        await _safe_reply(msg, "🎥 You can now share your screen/cam in the channel!")
        return

    # --- Check channel membership ---
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in ("left", "kicked", "banned"):
            await _safe_reply(msg, "❌ Please join the channel first. @NoteOfDeku")
            return
    except TelegramError as e:
        print(f"⚠️ Could not check membership for user {user_id}: {e}")
        await _safe_reply(msg, "❌ Please join the channel first. @NoteOfDeku")
        return

    # --- Grant permission ---
    try:
        await context.bot.promote_chat_member(
            chat_id=CHANNEL_ID,
            user_id=user_id,
            can_manage_video_chats=True,
            can_restrict_members=False,
            can_promote_members=False,
        )
    except TelegramError as e:
        print(f"⚠️ Could not grant screenshare to user {user_id}: {e}")
        await _safe_reply(msg, "⚠️ You already have permission to share your screen/cam in the channel!")
        return

    # --- Record grant and start revocation timer ---
    _active_grants[user_id] = now + GRANT_DURATION
    _schedule_revocation(context.bot, user_id, GRANT_DURATION)

    await _safe_reply(msg, "🎥 You can now share your screen/cam in the channel! Please do not click on 'End live stream' when leaving.\
🎥 يمكنك الآن مشاركة شاشتك/كاميرتك في القناة! يُرجى عدم النقر على 'إنهاء البث المباشر' عند المغادرة.")   

    print(f"✅ Granted screenshare to user {user_id} for {GRANT_DURATION}s")
