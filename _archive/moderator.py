import logging
import httpx
import json
from datetime import timedelta
from telegram import Update, ChatPermissions
from telegram.ext import ContextTypes
from config import GEMINI_API_KEY, MOD_LOG_CHAT_ID, GROUP_RULES, EXPERIMENTAL_CHAT_ID

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""You are a strict but fair AI Telegram Moderator.
Your job is to read a reported message and decide if it breaks the group rules.

Here are the strict rules for this group:
{GROUP_RULES}

You must respond in strict JSON format with exactly three top-level keys:
"action": Must be exactly one of "MUTE", "BAN", or "NONE".
"reason": A strict 1-sentence explanation of why you made this decision.
"rule_broken": A short string explaining which rule was broken (or "None" if action is NONE).

If the message is blatant spam or a scam, action should be BAN.
If the message is disrespectful, off-topic, or non-English, action should be MUTE.
If the message does not seem to break the rules, action should be NONE."""

async def moderate_with_gemini(message_text: str) -> dict | None:
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY is missing for moderator.")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
    
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": f"Reported Message: '{message_text}'"}]}],
        # Force JSON response from Gemini
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(url, json=payload, timeout=10)
            res.raise_for_status()
            data = res.json()
            
            # Extract JSON string from Gemini's response
            text_response = data["candidates"][0]["content"]["parts"][0]["text"]
            
            # Gemini might wrap the JSON in markdown code blocks like ```json ... ```
            if text_response.startswith("```json"):
                text_response = text_response.replace("```json", "", 1).replace("```", "")
                
            return json.loads(text_response.strip())
            
    except Exception as e:
        logger.error(f"Error calling Gemini for moderation: {e}")
        return None

async def handle_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /report command when replied to a message."""
    if update.effective_chat.id != EXPERIMENTAL_CHAT_ID:
        await update.message.reply_text("⚠️ The AI Moderator is currently experimental and not active in this chat.")
        return

    if not update.message or not update.message.reply_to_message:
        await update.message.reply_text("Please reply to the specific message you want to report with /report.")
        return

    reported_message = update.message.reply_to_message
    if not reported_message.text:
        await update.message.reply_text("I can only moderate text messages right now.")
        return

    offending_user = reported_message.from_user
    if offending_user.is_bot:
        await update.message.reply_text("I cannot moderate other bots.")
        return

    # Acknowledge the report
    status_msg = await update.message.reply_text("⏳ Reviewing the reported message...")
    
    # Send to AI
    decision = await moderate_with_gemini(reported_message.text)
    
    if not decision:
        await status_msg.edit_text("Sorry, I could not reach my AI brain right now. Please notify a human admin.")
        return
        
    action = decision.get("action", "NONE").upper()
    reason = decision.get("reason", "No reason provided.")
    rule_broken = decision.get("rule_broken", "None")
    
    try:
        if action == "BAN":
            # Ban the user
            await context.bot.ban_chat_member(
                chat_id=update.effective_chat.id,
                user_id=offending_user.id
            )
            await status_msg.edit_text(f"🛑 **Action Taken: BAN**\n\nUser {offending_user.first_name} has been banned.\nReason: {reason}", parse_mode="Markdown")
            
        elif action == "MUTE":
            # Restrict the user for 1 hour
            await context.bot.restrict_chat_member(
                chat_id=update.effective_chat.id,
                user_id=offending_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=update.message.date + timedelta(hours=1)
            )
            await status_msg.edit_text(f"🔇 **Action Taken: MUTE (1 Hour)**\n\nUser {offending_user.first_name} has been muted.\nRule Broken: {rule_broken}\nReason: {reason}", parse_mode="Markdown")
            
        else:
            await status_msg.edit_text(f"✅ **Action Taken: NONE**\n\nI reviewed the message and determined it does not strictly violate the rules.\nReason: {reason}", parse_mode="Markdown")
            
    except Exception as e:
        logger.error(f"Moderation Action failed: {e}")
        await status_msg.edit_text("I've made a decision, but I lack the admin permissions in this group to enforce it!")

    # Audit Logging to the Admin Chat
    if MOD_LOG_CHAT_ID:
        log_text = (
            f"🛡️ **MODERATION AUDIT LOG**\n\n"
            f"**Chat:** {update.effective_chat.title or update.effective_chat.id}\n"
            f"**Reported User:** {offending_user.first_name} (ID: {offending_user.id})\n"
            f"**Reported By:** {update.effective_user.first_name}\n"
            f"**Message:** \"{reported_message.text}\"\n\n"
            f"**AI Decision:** {action}\n"
            f"**Rule Broken:** {rule_broken}\n"
            f"**Reasoning:** {reason}"
        )
        try:
            await context.bot.send_message(chat_id=MOD_LOG_CHAT_ID, text=log_text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send mod log: {e}")
