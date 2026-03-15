from telegram import Update
from telegram.ext import ContextTypes
from config import MENTION_CHAT_ID, MENTION_SOURCE_CHANNEL_ID, BOT_ADMIN_IDS


async def add_mention(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adds a user to the mention list. Usage: /addmention @username or reply to a user."""
    if context.args:
        username = context.args[0].lstrip("@").lower()
    elif update.message.reply_to_message and update.message.reply_to_message.from_user:
        username = update.message.reply_to_message.from_user.username
        if not username:
            await update.message.reply_text("⚠️ That user has no username.")
            return
        username = username.lower()
    else:
        await update.message.reply_text("Usage: /addmention @username or reply to a user.")
        return

    mentions = context.bot_data.setdefault("mention_list", [])

    if username in mentions:
        await update.message.reply_text(f"⚠️ @{username} is already in the list.")
        return

    mentions.append(username)
    await update.message.reply_text(f"Added to mention list.")


async def remove_mention(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes a user from the mention list. Admins can remove anyone, users can only remove themselves."""
    if context.args:
        username = context.args[0].lstrip("@").lower()
    elif update.message.reply_to_message and update.message.reply_to_message.from_user:
        username = update.message.reply_to_message.from_user.username
        if not username:
            await update.message.reply_text("⚠️ That user has no username.")
            return
        username = username.lower()
    else:
        await update.message.reply_text("Usage: /removemention @username or reply to a user.")
        return

    # Check permission: must be admin or removing themselves
    caller_username = update.effective_user.username
    is_admin = update.effective_user.id in BOT_ADMIN_IDS
    is_self = caller_username and caller_username.lower() == username

    if not is_admin and not is_self:
        await update.message.reply_text("⛔ You can only remove yourself from the list.")
        return

    mentions = context.bot_data.get("mention_list", [])

    if username not in mentions:
        await update.message.reply_text(f"⚠️ @{username} is not in the list.")
        return

    mentions.remove(username)
    await update.message.reply_text(f"✅ @{username} removed from mention list.")


async def remove_all_mentions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clears the entire mention list. Admins only."""
    if update.effective_user.id not in BOT_ADMIN_IDS:
        await update.message.reply_text("⛔ Admins only.")
        return

    context.bot_data["mention_list"] = []
    await update.message.reply_text("✅ Mention list cleared.")


async def watch_forestapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Watches for forestapp.cc posts forwarded from the source channel into the linked group."""
    msg = update.effective_message
    if not msg or not msg.text:
        return

    if update.effective_chat.id != MENTION_CHAT_ID:
        return

    if "forestapp.cc" not in msg.text:
        return

    # Only trigger for posts forwarded from the source channel
    origin = msg.forward_origin
    if not origin or not hasattr(origin, "chat"):
        return
    if origin.chat.id != MENTION_SOURCE_CHANNEL_ID:
        return

    mentions = context.bot_data.get("mention_list", [])
    if not mentions:
        return

    mention_text = " ".join(f"@{u}" for u in mentions)
    await msg.reply_text(mention_text, disable_notification=True)