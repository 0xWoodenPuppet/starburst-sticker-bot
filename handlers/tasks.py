"""Task tracking & review handler.

Deep link flows:
  - /start task_SESSION_ID  → ask for task → save
  - /start review_SESSION_ID → ask what they did → AI coach → save

Session end:
  Job fires after buffer + duration → DMs participants with review buttons.

History:
  /history [7|30|all] → past sessions (DM only).
"""

import logging
import asyncio
import httpx
from datetime import datetime, timezone, timedelta
from bson import ObjectId

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from config import GEMINI_API_KEY, BOT_USERNAME, SESSION_BUFFER_MINUTES
from db import sessions

logger = logging.getLogger(__name__)

# ── Conversation states ────────────────────────────────────────────────
WAITING_TASK = 0
WAITING_SWITCH = 1
WAITING_REVIEW = 2


# ═══════════════════════════════════════════════════════════════════════
#  DEEP LINK — /start
# ═══════════════════════════════════════════════════════════════════════

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start command. Routes deep link payloads."""
    if not context.args:
        await update.message.reply_text(
            "👋 Hey! I'm the Starburst Bot.\n\n"
            "You can add tasks to Forest sessions by clicking the "
            "✏️ Add Task button on session stickers in groups.\n\n"
            "Use /history to check your past sessions."
        )
        return ConversationHandler.END

    payload = context.args[0]

    # ── Review deep link ──
    if payload.startswith("review_"):
        return await _start_review(update, context, payload[7:])

    # ── Task deep link ──
    if payload.startswith("task_"):
        return await _start_task(update, context, payload[5:])

    await update.message.reply_text("👋 Hey! I'm the Starburst Bot.")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════
#  TASK FLOW
# ═══════════════════════════════════════════════════════════════════════

async def _start_task(update: Update, context: ContextTypes.DEFAULT_TYPE, session_id: str) -> int:
    """Entry point for adding a task to a session."""
    try:
        session = await sessions.find_one({"_id": ObjectId(session_id)})
    except Exception:
        await update.message.reply_text("⚠️ Invalid session link.")
        return ConversationHandler.END

    if session is None:
        await update.message.reply_text("⚠️ Session not found.")
        return ConversationHandler.END

    if session.get("phase") == "ended":
        await update.message.reply_text("⏰ This session has already ended.")
        return ConversationHandler.END

    user_id = str(update.effective_user.id)

    # Check if user already submitted a task for THIS session
    if user_id in session.get("participants", {}):
        existing_task = session["participants"][user_id].get("task", "")
        await update.message.reply_text(
            f"You already added a task for this session:\n\n"
            f"📝 \"{existing_task}\"\n\n"
            f"Good luck with your session! 🌱"
        )
        return ConversationHandler.END

    # Check if user is in another ACTIVE session
    existing = await sessions.find_one({
        f"participants.{user_id}": {"$exists": True},
        "phase": "active",
        "_id": {"$ne": ObjectId(session_id)},
    })

    if existing:
        # Store both session IDs for the switch flow
        context.user_data["switch_new_session"] = session_id
        context.user_data["switch_old_session"] = str(existing["_id"])

        old_tree = existing.get("tree", "unknown").title()
        old_dur = existing.get("duration", "?")
        old_task = existing["participants"][user_id].get("task", "—")

        await update.message.reply_text(
            f"⚠️ You're already in a session:\n\n"
            f"🌳 {old_tree} — {old_dur} min\n"
            f"📝 \"{old_task}\"\n\n"
            f"Do you want to switch to this new session?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Switch to new session", callback_data="task_switch_yes")],
                [InlineKeyboardButton("✅ Stay in current session", callback_data="task_switch_no")],
            ]),
        )
        return WAITING_SWITCH

    # No conflicts — ask for task
    context.user_data["task_session_id"] = session_id
    tree = session.get("tree", "unknown").title()
    duration = session.get("duration", "?")

    await update.message.reply_text(
        f"🌳 <b>{tree}</b> — {duration} min session\n\n"
        f"What's your task for this session?",
        parse_mode="HTML",
    )
    return WAITING_TASK


async def handle_switch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the switch/stay callback buttons."""
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    new_session_id = context.user_data.pop("switch_new_session", None)
    old_session_id = context.user_data.pop("switch_old_session", None)

    if query.data == "task_switch_yes" and new_session_id and old_session_id:
        # Remove from old session
        await sessions.update_one(
            {"_id": ObjectId(old_session_id)},
            {"$unset": {f"participants.{user_id}": ""}}
        )

        # Load new session info
        session = await sessions.find_one({"_id": ObjectId(new_session_id)})
        if not session or session.get("phase") == "ended":
            await query.edit_message_text("⏰ The new session has already ended.")
            return ConversationHandler.END

        context.user_data["task_session_id"] = new_session_id
        tree = session.get("tree", "unknown").title()
        duration = session.get("duration", "?")

        await query.edit_message_text(
            f"🔄 Switched!\n\n"
            f"🌳 <b>{tree}</b> — {duration} min session\n\n"
            f"What's your task for this session?",
            parse_mode="HTML",
        )
        return WAITING_TASK

    else:
        # Stay in current session
        await query.edit_message_text("👍 You're still in your current session. Good luck! 🌱")
        return ConversationHandler.END


async def receive_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the user's task text and saves it to MongoDB."""
    user = update.effective_user
    user_id = str(user.id)
    task_text = update.message.text.strip()

    if len(task_text) > 200:
        await update.message.reply_text("Please keep your task under 200 characters.")
        return WAITING_TASK

    session_id = context.user_data.pop("task_session_id", None)
    if session_id is None:
        await update.message.reply_text(
            "⚠️ Something went wrong. Please click the Add Task button again."
        )
        return ConversationHandler.END

    # Save participant + task to MongoDB
    await sessions.update_one(
        {"_id": ObjectId(session_id)},
        {"$set": {
            f"participants.{user_id}": {
                "username": user.username or user.first_name or "",
                "task": task_text,
                "note": None,
                "coach_response": None,
                "joined_at": datetime.now(timezone.utc),
                "dm_chat_id": update.effective_chat.id,
            }
        }}
    )

    await update.message.reply_text(
        f"✅ Task saved!\n\n"
        f"📝 \"{task_text}\"\n\n"
        f"I'll check in with you when the session ends. Good luck! 🌱\n\n"
        f"Use /history to check your past sessions."
    )
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════
#  REVIEW FLOW
# ═══════════════════════════════════════════════════════════════════════

async def _start_review(update: Update, context: ContextTypes.DEFAULT_TYPE, session_id: str) -> int:
    """Entry point for reviewing a completed session."""
    try:
        session = await sessions.find_one({"_id": ObjectId(session_id)})
    except Exception:
        await update.message.reply_text("⚠️ Invalid session link.")
        return ConversationHandler.END

    if session is None:
        await update.message.reply_text("⚠️ Session not found.")
        return ConversationHandler.END

    user_id = str(update.effective_user.id)

    if session.get("phase") == "ended":
        await update.message.reply_text("⏰ The review window for this session has closed.")
        return ConversationHandler.END

    participant = session.get("participants", {}).get(user_id)
    if not participant:
        await update.message.reply_text("⚠️ You weren't part of this session.")
        return ConversationHandler.END

    if participant.get("note"):
        await update.message.reply_text(
            f"You already reviewed this session:\n\n"
            f"✍️ \"{participant['note']}\""
        )
        return ConversationHandler.END

    context.user_data["review_session_id"] = session_id
    task = participant.get("task", "—")

    await update.message.reply_text(
        f"What did you actually do during this session?\n\n"
        f"Your task was: \"{task}\""
    )
    return WAITING_REVIEW


async def receive_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the user's review and triggers AI coach."""
    user_id = str(update.effective_user.id)
    note = update.message.text.strip()

    session_id = context.user_data.pop("review_session_id", None)
    if session_id is None:
        await update.message.reply_text("⚠️ Something went wrong.")
        return ConversationHandler.END

    # Save the review note
    await sessions.update_one(
        {"_id": ObjectId(session_id)},
        {"$set": {f"participants.{user_id}.note": note}}
    )

    # Get session data for AI coach
    session = await sessions.find_one({"_id": ObjectId(session_id)})
    participant = session["participants"].get(user_id, {}) if session else {}
    task = participant.get("task", "")

    # Show typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    # AI coach — single reply
    coach_response = await _get_coach_feedback(task, note, session.get("duration", 0))

    if coach_response:
        await sessions.update_one(
            {"_id": ObjectId(session_id)},
            {"$set": {f"participants.{user_id}.coach_response": coach_response}}
        )
        await update.message.reply_text(
            f"{coach_response}\n\n"
            f"Use /history to check your past sessions."
        )
    else:
        await update.message.reply_text(
            "✅ Noted! Use /history to see your session records."
        )

    return ConversationHandler.END


async def handle_review_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Standalone callback handler for the Skip button on session-end DMs."""
    query = update.callback_query
    if not query or not query.data:
        return

    if not query.data.startswith("task_skip_"):
        return

    await query.answer("⏭ Review skipped")

    # Edit the message to show it was skipped
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass


async def cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the current conversation."""
    context.user_data.pop("task_session_id", None)
    context.user_data.pop("review_session_id", None)
    context.user_data.pop("switch_new_session", None)
    context.user_data.pop("switch_old_session", None)
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════
#  SESSION END — Job Queue
# ═══════════════════════════════════════════════════════════════════════

async def schedule_session_end(context: ContextTypes.DEFAULT_TYPE, session_id: str, duration: int):
    """Schedule a job to fire when the session ends (buffer + duration)."""
    delay_seconds = (SESSION_BUFFER_MINUTES + duration) * 60

    context.job_queue.run_once(
        _session_ended_job,
        when=delay_seconds,
        data={"session_id": session_id},
        name=f"session_end_{session_id}",
    )


async def _session_ended_job(context: ContextTypes.DEFAULT_TYPE):
    """Fired when a session's duration expires. DMs all participants with review buttons."""
    session_id = context.job.data["session_id"]

    session = await sessions.find_one({"_id": ObjectId(session_id)})
    if session is None or session.get("phase") == "ended":
        return

    # Mark session as review phase
    await sessions.update_one(
        {"_id": ObjectId(session_id)},
        {"$set": {"phase": "review", "ended_at": datetime.now(timezone.utc)}}
    )

    participants = session.get("participants", {})
    if not participants:
        await sessions.update_one(
            {"_id": ObjectId(session_id)},
            {"$set": {"phase": "ended"}}
        )
        return

    tree = session.get("tree", "unknown").title()
    duration = session.get("duration", "?")

    # DM each participant with review buttons
    for user_id, data in participants.items():
        dm_chat_id = data.get("dm_chat_id")
        task = data.get("task", "—")
        if not dm_chat_id:
            continue

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "📝 Write Review",
                url=f"https://t.me/{BOT_USERNAME}?start=review_{session_id}",
            )],
            [InlineKeyboardButton(
                "⏭ Skip",
                callback_data=f"task_skip_{session_id}",
            )],
        ])

        try:
            await context.bot.send_message(
                chat_id=dm_chat_id,
                text=(
                    f"🩴 <b>Session over!</b> ({tree} — {duration} min)\n\n"
                    f"Your task was: \"{task}\"\n\n"
                    f"Use /history to check your past sessions."
                ),
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.error(f"Failed to DM user {user_id}: {e}")

    # Auto-close review after 24 hours
    context.job_queue.run_once(
        _close_review,
        when=86400,
        data={"session_id": session_id},
        name=f"close_review_{session_id}",
    )


async def _close_review(context: ContextTypes.DEFAULT_TYPE):
    """Close review window after timeout."""
    session_id = context.job.data["session_id"]
    session = await sessions.find_one({"_id": ObjectId(session_id)})
    if session and session.get("phase") == "review":
        await sessions.update_one(
            {"_id": ObjectId(session_id)},
            {"$set": {"phase": "ended"}}
        )


async def restore_pending_sessions(app):
    """Re-schedule session-end and review-close jobs after a bot restart.

    Called via Application.post_init — runs once at startup before polling.
    Any sessions still in 'active' or 'review' phase in MongoDB will have
    their lost job_queue timers re-created.
    """
    now = datetime.now(timezone.utc)
    restored = 0

    # ── Active sessions: re-schedule session-end jobs ──────────────────
    async for session in sessions.find({"phase": "active"}):
        session_id = str(session["_id"])
        created_at = session.get("created_at")
        duration = session.get("duration", 0)
        if not created_at:
            continue

        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        # Original deadline: created_at + (buffer + duration) minutes
        deadline = created_at + timedelta(minutes=SESSION_BUFFER_MINUTES + duration)
        remaining = (deadline - now).total_seconds()

        # If deadline already passed, fire in 5 seconds (give startup time)
        when = max(remaining, 5)

        app.job_queue.run_once(
            _session_ended_job,
            when=when,
            data={"session_id": session_id},
            name=f"session_end_{session_id}",
        )
        restored += 1
        logger.info(f"Restored session-end job for {session_id} (fires in {when:.0f}s)")

    # ── Review sessions: re-schedule review-close jobs ─────────────────
    async for session in sessions.find({"phase": "review"}):
        session_id = str(session["_id"])
        ended_at = session.get("ended_at")
        if not ended_at:
            continue

        if ended_at.tzinfo is None:
            ended_at = ended_at.replace(tzinfo=timezone.utc)

        # Review window: 24 hours after session ended
        close_deadline = ended_at + timedelta(hours=24)
        remaining = (close_deadline - now).total_seconds()
        when = max(remaining, 5)

        app.job_queue.run_once(
            _close_review,
            when=when,
            data={"session_id": session_id},
            name=f"close_review_{session_id}",
        )
        restored += 1
        logger.info(f"Restored review-close job for {session_id} (fires in {when:.0f}s)")

    if restored:
        logger.info(f"🔄 Restored {restored} pending session job(s) after restart")
    else:
        logger.info("No pending sessions to restore after restart")


# ═══════════════════════════════════════════════════════════════════════
#  AI COACH
# ═══════════════════════════════════════════════════════════════════════

COACH_SYSTEM_PROMPT = """You are a warm, encouraging mentor.
Review the user's focus session using:
- Duration (in minutes)
- PLANNED: their goal
- ACTUAL: what they achieved

Rules:
1. Reply in exactly 2 short sentences.
2. Focus on praising the effort, even if they didn't finish everything.
3. If they struggled, offer a gentle suggestion for next time.
4. If the duration is under 10 minutes, congratulate them on doing a quick warm-up or test.
5. Do NOT use labels, emojis, or prefixes. Output only the conversational text."""


async def _get_coach_feedback(planned_task: str, actual_outcome: str, duration: int) -> str | None:
    """Call Gemini to compare planned vs actual and give feedback."""
    if not GEMINI_API_KEY:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"

    prompt = (
        f"Session duration: {duration} minutes\n"
        f"Planned task: \"{planned_task}\"\n"
        f"What they actually did: \"{actual_outcome}\"\n\n"
        f"Give your feedback."
    )

    payload = {
        "system_instruction": {"parts": [{"text": COACH_SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
    }

    for attempt in range(3):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=30.0)

                if response.status_code in [500, 503, 529] and attempt < 2:
                    await asyncio.sleep(2)
                    continue

                response.raise_for_status()
                data = response.json()

                if "candidates" in data and data["candidates"]:
                    parts = data["candidates"][0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "")

                return None
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(2)
                continue
            logger.error(f"Coach AI error: {e}")
            return None
    return None


# ═══════════════════════════════════════════════════════════════════════
#  HISTORY COMMAND
# ═══════════════════════════════════════════════════════════════════════

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/history [days|all] — Show past session records (DM only)."""
    # DM only — don't leak personal data in groups
    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "📊 Please use /history in my DMs to keep your data private.",
        )
        return

    user_id = str(update.effective_user.id)

    # Parse argument
    days = 7  # default
    show_all = False
    if context.args:
        arg = context.args[0].lower()
        if arg == "all":
            show_all = True
        else:
            try:
                days = int(arg)
            except ValueError:
                await update.message.reply_text("Usage: /history [7|30|all]")
                return

    # Build query
    query = {f"participants.{user_id}": {"$exists": True}}
    if not show_all:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        query["created_at"] = {"$gte": cutoff}

    cursor = sessions.find(query).sort("created_at", -1).limit(10)
    results = await cursor.to_list(length=10)

    if not results:
        period = "all time" if show_all else f"the last {days} days"
        await update.message.reply_text(f"No sessions found in {period}.")
        return

    # Count total sessions for context
    total = await sessions.count_documents(query)

    # Format output — compact one-line-per-session
    lines = []
    for s in results:
        p = s["participants"].get(user_id, {})
        date = s.get("created_at", datetime.min)
        date_str = date.strftime("%b %d") if hasattr(date, "strftime") else "?"

        tree = s.get("tree", "?").title()
        dur = s.get("duration", "?")
        task = p.get("task", "—")
        note = p.get("note", "")

        line = f"📅 <b>{date_str}</b> — {tree} ({dur}m)\n   📝 {task}"
        if note:
            line += f"\n   ✍️ {note}"
        lines.append(line)

    period = "all time" if show_all else f"last {days} days"
    showing = f"Showing {len(results)} of {total}" if total > len(results) else f"{len(results)} sessions"
    header = f"📊 <b>Your sessions ({period})</b> — {showing}\n\n"
    text = header + "\n\n".join(lines)

    if total > 10:
        text += f"\n\n<i>Use /history {days * 2 if not show_all else 'all'} to see more</i>"

    # Telegram message limit
    if len(text) > 4096:
        text = text[:4090] + "\n..."

    await update.message.reply_text(text, parse_mode="HTML")


# ═══════════════════════════════════════════════════════════════════════
#  EXPORTED HANDLERS
# ═══════════════════════════════════════════════════════════════════════

# ConversationHandler for deep link task + review flows
task_conversation = ConversationHandler(
    entry_points=[
        CommandHandler("start", handle_start, filters=filters.ChatType.PRIVATE),
    ],
    states={
        WAITING_TASK: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task),
        ],
        WAITING_SWITCH: [
            CallbackQueryHandler(handle_switch, pattern=r"^task_switch_"),
        ],
        WAITING_REVIEW: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_review),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_task),
    ],
    allow_reentry=True,
    conversation_timeout=300,
    per_message=False,
)

# Standalone callback handler for Skip button on session-end DMs
skip_review_handler = CallbackQueryHandler(handle_review_skip, pattern=r"^task_skip_")
