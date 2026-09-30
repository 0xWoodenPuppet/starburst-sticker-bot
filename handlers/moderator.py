import html
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
    """Handles the /report command:
    - Silently deletes the /report command message in all cases.
    - If valid report: evaluates NLP toxicity and reporter credibility.
    - If toxic: mutes the user and deletes their offending message.
    - No public replies in the chat; all outcomes logged to MOD_LOG_CHAT_ID.
    """
    if not update.message:
        return

    # Delete the /report command message whether the report is valid/false or not
    try:
        await update.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete /report message: {e}")

    # Moderation only operates on group messages
    if update.effective_chat.type == "private":
        return

    reported_message = update.message.reply_to_message
    if not reported_message or not reported_message.text:
        return

    offending_user = reported_message.from_user
    reporter = update.effective_user

    if not offending_user or offending_user.is_bot:
        return

    # Ignore self-reports silently
    if offending_user.id == reporter.id:
        return

    chat_id = update.effective_chat.id

    # 1. Local NLP Pipeline Inference
    nlp_result = await classify_toxicity(reported_message.text)
    toxicity_score = nlp_result.get("toxicity_score", 0.0)

    # 2. Dynamic Credibility Retrieval
    reporter_credibility = await get_user_credibility(reporter.id)

    # 3. Composite Decision Formulation
    decision = compute_composite_score(toxicity_score, reporter_credibility)
    action = decision["action"]
    composite_score = decision["composite_score"]

    action_label = action
    # 4. Telegram Action Execution (Silent in group, delete offending message + mute)
    if action == "MUTE":
        mute_success = False
        delete_success = False

        # Mute offending user for 1 hour
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=offending_user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=update.message.date + timedelta(hours=1)
            )
            mute_success = True
        except Exception as e:
            logger.error(f"Failed to restrict member {offending_user.id}: {e}")

        # Delete the offending message
        try:
            await reported_message.delete()
            delete_success = True
        except Exception as e:
            logger.error(f"Failed to delete offending message {reported_message.message_id}: {e}")

        if mute_success and delete_success:
            action_label = "MUTED (1 Hour) & DELETED"
        elif mute_success:
            action_label = "MUTED (Message Deletion Failed)"
        else:
            action_label = "FLAGGED (Lacks Admin Permission to Mute)"

    elif action == "FLAG":
        action_label = "FLAGGED FOR ADMIN REVIEW"
    else:
        action_label = "NONE (Report Logged)"

    # Update decision dict with detailed action label for DB
    decision["action"] = action_label

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
        chat_title = html.escape(update.effective_chat.title or f"Chat {chat_id}")
        offending_name = html.escape(offending_user.first_name or "User")
        reporter_name = html.escape(reporter.first_name or "Reporter")
        safe_message = html.escape(reported_message.text)
        category_str = html.escape(nlp_result.get("category", "unknown").upper())
        ngrams_str = ", ".join([f"<code>{html.escape(g)}</code>" for g in nlp_result.get("detected_ngrams", [])]) or "None"

        log_text = (
            f"🛡️ <b>MODERATION AUDIT LOG</b>\n\n"
            f"<b>Chat:</b> {chat_title}\n"
            f"<b>Reported User:</b> {offending_name} (<code>{offending_user.id}</code>)\n"
            f"<b>Reporter:</b> {reporter_name} (<code>{reporter.id}</code>)\n"
            f"<b>Reporter Credibility:</b> <code>{reporter_credibility:.2f}</code>\n\n"
            f"<b>Message:</b>\n\"{safe_message}\"\n\n"
            f"<b>NLP Analysis:</b>\n"
            f"• Toxicity Score: <code>{toxicity_score:.2f}</code> ({category_str})\n"
            f"• Detected N-Grams: {ngrams_str}\n"
            f"• Composite Score: <code>{composite_score:.2f}</code>\n"
            f"• Enforcement Action: <b>{action_label}</b>\n\n"
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
                parse_mode="HTML"
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
    admin_name = html.escape(admin_user.first_name or "Admin")

    original_text = query.message.text or ""
    # Strip the trailing prompt if present
    if "Admin Verification:" in original_text:
        original_text = original_text.split("Admin Verification:")[0].strip()

    safe_original = html.escape(original_text)

    updated_text = (
        f"{safe_original}\n\n"
        f"<b>Admin Verdict:</b> {verdict_emoji}\n"
        f"<b>Verified By:</b> {admin_name}\n"
        f"<b>Reporter Credibility Updated:</b> <code>{old_c:.2f}</code> → <code>{new_c:.2f}</code> ({diff})"
    )

    try:
        await query.edit_message_text(
            text=updated_text,
            parse_mode="HTML"
        )
        await query.answer(f"Verdict recorded: {verdict_emoji}. Credibility updated to {new_c:.2f}.")
    except Exception as e:
        logger.error(f"Failed to update audit log message: {e}")
        await query.answer("Verdict recorded in database.")
