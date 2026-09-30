import logging
from datetime import timedelta
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import MOD_LOG_CHAT_ID, BOT_ADMIN_IDS
from services.toxicity_classifier import classify_toxicity
from services.credibility import (
    get_user_credibility,
    compute_composite_score,
    save_mod_report,
    record_admin_verdict,
)

logger = logging.getLogger(__name__)


async def handle_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /report command when replied to an offending message."""
    if not update.message or not update.message.reply_to_message:
        await update.message.reply_text(
            "ℹ️ To report a message, reply directly to it with `/report`.",
            parse_mode="Markdown"
        )
        return

    reported_message = update.message.reply_to_message
    if not reported_message.text:
        await update.message.reply_text("ℹ️ Currently only text messages can be analyzed by the moderator.")
        return

    offending_user = reported_message.from_user
    reporter = update.effective_user

    if not offending_user or not reporter:
        return

    if offending_user.is_bot:
        await update.message.reply_text("ℹ️ Automated moderation cannot be run against bot accounts.")
        return

    if offending_user.id == reporter.id:
        await update.message.reply_text("⚠️ You cannot report your own messages.")
        return

    # User acknowledgement
    status_msg = await update.message.reply_text("🔍 Analyzing reported message...")

    # 1. Local NLP Pipeline Inference
    nlp_result = await classify_toxicity(reported_message.text)
    toxicity_score = nlp_result.get("toxicity_score", 0.0)

    # 2. Dynamic Credibility Retrieval
    reporter_credibility = await get_user_credibility(reporter.id)

    # 3. Composite Decision Formulation
    decision = compute_composite_score(toxicity_score, reporter_credibility)
    action = decision["action"]
    composite_score = decision["composite_score"]

    # 4. Telegram Action Execution
    chat_id = update.effective_chat.id
    rule_broken = nlp_result.get("rule_broken", "Group rule violation")

    if action == "MUTE":
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=offending_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=update.message.date + timedelta(hours=1)
            )
            await status_msg.edit_text(
                f"🛑 **Action Taken: MUTE (1 Hour)**\n\n"
                f"**User:** {offending_user.first_name}\n"
                f"**Reason:** {rule_broken}\n"
                f"**NLP Toxicity Score:** `{toxicity_score:.2f}`\n\n"
                f"_Message has been logged for moderator audit._",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Moderation mute action failed: {e}")
            await status_msg.edit_text(
                f"⚠️ **Flagged as Toxic (`{toxicity_score:.2f}`)**\n\n"
                f"The message violated community rules, but the bot lacks admin permissions in this chat to enforce the mute.",
                parse_mode="Markdown"
            )
    elif action == "FLAG":
        await status_msg.edit_text(
            f"⚠️ **Message Flagged for Admin Review**\n\n"
            f"The NLP system detected borderline content (Composite Score: `{composite_score:.2f}`). Administrators have been alerted.",
            parse_mode="Markdown"
        )
    else:  # NONE
        await status_msg.edit_text(
            f"✅ **Report Evaluated**\n\n"
            f"The automated NLP scan found insufficient evidence of a rule violation (Score: `{toxicity_score:.2f}`).",
            parse_mode="Markdown"
        )

    # 5. Persist Report to MongoDB
    report_id = await save_mod_report(
        chat_id=chat_id,
        message_id=reported_message.message_id,
        offending_user_id=offending_user.id,
        offending_user_name=offending_user.first_name or str(offending_user.id),
        reporter_id=reporter.id,
        reporter_name=reporter.first_name or str(reporter.id),
        message_text=reported_message.text,
        nlp_result=nlp_result,
        reporter_credibility=reporter_credibility,
        decision=decision
    )

    # 6. Audit Logging to MOD_LOG_CHAT_ID with Interactive Admin Feedback
    if MOD_LOG_CHAT_ID and report_id:
        chat_title = update.effective_chat.title or f"Chat {chat_id}"
        ngrams_str = ", ".join([f"`{g}`" for g in nlp_result.get("detected_ngrams", [])]) or "None"

        log_text = (
            f"🛡️ **MODERATION AUDIT LOG**\n\n"
            f"**Chat:** {chat_title}\n"
            f"**Reported User:** {offending_user.first_name} (`{offending_user.id}`)\n"
            f"**Reporter:** {reporter.first_name} (`{reporter.id}`)\n"
            f"**Reporter Credibility:** `{reporter_credibility:.2f}`\n\n"
            f"**Message:**\n\"{reported_message.text}\"\n\n"
            f"**NLP Analysis:**\n"
            f"• Toxicity Score: `{toxicity_score:.2f}` ({nlp_result.get('category', 'unknown').upper()})\n"
            f"• Detected N-Grams: {ngrams_str}\n"
            f"• Composite Score: `{composite_score:.2f}`\n"
            f"• Automated Action: **{action}**\n\n"
            f"Admin Verification:"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm Violation", callback_data=f"mod:confirm:{report_id}"),
                InlineKeyboardButton("❌ False Report", callback_data=f"mod:reject:{report_id}")
            ]
        ])

        try:
            await context.bot.send_message(
                chat_id=MOD_LOG_CHAT_ID,
                text=log_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to post to MOD_LOG_CHAT_ID: {e}")


async def moderation_feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles admin feedback clicks ([✅ Confirm Violation] / [❌ False Report])."""
    query = update.callback_query
    if not query or not query.data:
        return

    admin_user = update.effective_user
    # Admin verification: check if user is a designated bot admin or in admin group
    is_admin = admin_user.id in BOT_ADMIN_IDS
    if not is_admin and update.effective_chat:
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, admin_user.id)
            if member.status in ["administrator", "creator"]:
                is_admin = True
        except Exception:
            pass

    if not is_admin:
        await query.answer("⚠️ Only designated administrators can verify moderation reports.", show_alert=True)
        return

    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != "mod":
        return

    action_type = parts[1]  # "confirm" or "reject"
    report_id = parts[2]
    is_correct = (action_type == "confirm")

    result = await record_admin_verdict(
        report_id=report_id,
        admin_id=admin_user.id,
        is_correct=is_correct
    )

    if not result:
        await query.answer("❌ Report not found.", show_alert=True)
        return

    if result.get("already_resolved"):
        await query.answer(f"ℹ️ Report already resolved as {result.get('current_verdict')}.", show_alert=True)
        return

    # Update log message with verdict and updated credibility
    verdict_emoji = "✅ CONFIRMED" if is_correct else "❌ REJECTED (FALSE REPORT)"
    old_c = result["old_credibility"]
    new_c = result["new_credibility"]
    diff = f"+{new_c - old_c:.2f}" if new_c >= old_c else f"{new_c - old_c:.2f}"

    original_text = query.message.text or ""
    # Strip the trailing prompt if present
    if "Admin Verification:" in original_text:
        original_text = original_text.split("Admin Verification:")[0].strip()

    updated_text = (
        f"{original_text}\n\n"
        f"**Admin Verdict:** {verdict_emoji}\n"
        f"**Verified By:** {admin_user.first_name}\n"
        f"**Reporter Credibility Updated:** `{old_c:.2f}` → `{new_c:.2f}` ({diff})"
    )

    try:
        await query.edit_message_text(
            text=updated_text,
            parse_mode="Markdown"
        )
        await query.answer(f"Verdict recorded: {verdict_emoji}. Credibility updated to {new_c:.2f}.")
    except Exception as e:
        logger.error(f"Failed to update audit log message: {e}")
        await query.answer("Verdict recorded in database.")
