"""Focus Session — /room command handler.

Lifecycle: host DM setup → channel post pair → /task collection → monitoring → scoring.
Two-post structure: session post (info) + task post (participants/scoring).
State is held in memory only; lost on restart.
"""

import re
import csv
from collections import OrderedDict
from datetime import datetime, timezone, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from config import BOT_ADMIN_IDS
from triggers import TRIGGERS, TRIGGER_PATTERNS

# ── Constants ──────────────────────────────────────────────────────────
CHANNEL_ID = -1002511165129
GROUP_ID = -1002606388153
GMT3 = timezone(timedelta(hours=3))

WAITING_LINK = 0

# ── English tree-name lookup (sticker_id → english name) ──────────────
_ENGLISH_NAMES: dict[str, str] = {}
try:
    with open("stickers_english.csv", mode="r", encoding="utf-8") as _f:
        for _row in csv.reader(_f):
            if len(_row) == 2:
                _ENGLISH_NAMES[_row[1].strip()] = _row[0].strip()
except FileNotFoundError:
    print("⚠️ stickers_english.csv not found – tree names will show as 'Unknown Tree'")

# ── Module-level state ─────────────────────────────────────────────────
_session: dict | None = None
_pending_setup: dict[int, dict] = {}


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _find_tree(text: str) -> tuple[str, str | None]:
    for trigger, pattern in TRIGGER_PATTERNS.items():
        if pattern.search(text):
            sid = TRIGGERS[trigger]
            return _ENGLISH_NAMES.get(sid, trigger.title()), sid
    return "Unknown Tree", None


def _parse_forest_link(text: str) -> dict | None:
    token_m = re.search(r"token=([A-Z0-9]+)", text, re.IGNORECASE)
    link_m = re.search(r"https://forestapp\.cc/join-room\?token=\w+", text, re.IGNORECASE)
    if not token_m or not link_m:
        return None
    dur = re.findall(
        r"(\d+)\s*[-–]?\s*(?:min|m\b|분|分|دقيق|دقائق|perc|dakik|мин|menit|मिनट)",
        text, re.IGNORECASE,
    )
    if not dur:
        return None
    tree_name, sticker_id = _find_tree(text)
    return {
        "tree": tree_name, "sticker_id": sticker_id,
        "duration": int(dur[-1]),
        "token": token_m.group(1).upper(),
        "join_link": link_m.group(0),
    }


# ── Post text builders ────────────────────────────────────────────────

def _build_session_text(strikethrough: bool = False) -> str:
    """Post 1 — session info."""
    s = _session
    host = f"@{s['host_username']}" if s["host_username"] else f"User {s['host_id']}"
    body = (
        f"Hosted by {host}\n\n"
        f"Tree: {s['tree']}\n\n"
        f"Duration: {s['duration']} Minutes\n\n"
        f"Starts at {s['start_time'].strftime('%H:%M')} GMT+3\n\n"
        f"Code: <code>{s['token']}</code>\n\n"
        f"Join: {s['join_link']}"
    )
    if strikethrough:
        return "\n".join(
            f"<s>{ln}</s>" if ln.strip() else ln for ln in body.split("\n")
        )
    return body


def _build_task_text() -> str:
    """Post 2 — task collection + participants."""
    s = _session
    lines = [
        "📋 Reply under this post with /task to add tasks for this session:",
        "",
        "- You'll be restricted from sending messages three minutes after the session starts.",
    ]
    if s["phase"] == "scoring":
        lines.extend([
            "- ✅: Completed",
            "- 🦦: Distracted",
            "- ⏳: Needs more time",
        ])
    lines.extend(["", "Participants:"])
    parts = []
    for uid, uname in s["participants"].items():
        emoji = s["scores"].get(uid, "")
        name = uname if uname else f"User {uid}"
        parts.append(f"{name} {emoji}".rstrip())
    if parts:
        lines.append("<blockquote expandable>")
        lines.extend(parts)
        lines.append("</blockquote>")
    return "\n".join(lines)


# ── Keyboards ──────────────────────────────────────────────────────────

def _kb_countdown(remaining: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"⏱ Starts in {remaining} min", callback_data="room_noop"),
        InlineKeyboardButton("+1 min", callback_data="room_extend"),
    ]])

def _kb_active(remaining: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"⏱ {remaining} min left", callback_data="room_noop"),
    ]])

def _kb_scoring() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅", callback_data="room_done"),
        InlineKeyboardButton("🦦", callback_data="room_distracted"),
        InlineKeyboardButton("⏳", callback_data="room_more"),
    ]])


# ── Edit helpers ───────────────────────────────────────────────────────

async def _edit_session_post(bot, keyboard=None, strikethrough=False):
    if _session is None or not _session.get("session_msg_id"):
        return
    try:
        await bot.edit_message_text(
            chat_id=CHANNEL_ID, message_id=_session["session_msg_id"],
            text=_build_session_text(strikethrough=strikethrough),
            parse_mode="HTML", reply_markup=keyboard,
            disable_web_page_preview=True,
        )
    except Exception as e:
        print(f"⚠️ Failed to edit session post: {e}")

async def _edit_task_post(bot, keyboard=None):
    if _session is None or not _session.get("task_msg_id"):
        return
    try:
        await bot.edit_message_text(
            chat_id=CHANNEL_ID, message_id=_session["task_msg_id"],
            text=_build_task_text(), parse_mode="HTML",
            reply_markup=keyboard, disable_web_page_preview=True,
        )
    except Exception as e:
        print(f"⚠️ Failed to edit task post: {e}")


def _cancel_jobs(job_queue):
    for job in job_queue.jobs():
        if job.name and job.name.startswith("room_"):
            job.schedule_removal()


async def _strip_old_buttons(bot):
    """Remove inline buttons from old session/task posts."""
    if _session is None:
        return
    for key in ("session_msg_id", "task_msg_id"):
        mid = _session.get(key)
        if mid:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=CHANNEL_ID, message_id=mid, reply_markup=None,
                )
            except Exception:
                pass


def _task_window_open() -> bool:
    if _session is None:
        return False
    if _session["phase"] == "countdown":
        return True
    if _session["phase"] == "active":
        elapsed = _session["duration"] - _session["remaining_active"]
        return elapsed <= 3
    return False


# ═══════════════════════════════════════════════════════════════════════
#  CONVERSATION HANDLER — /room DM flow
# ═══════════════════════════════════════════════════════════════════════

async def room_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    global _session
    if update.effective_user.id not in BOT_ADMIN_IDS:
        return ConversationHandler.END
    if _session is not None:
        _cancel_jobs(context.application.job_queue)
        await _strip_old_buttons(context.bot)
        _session = None
    _pending_setup.pop(update.effective_user.id, None)
    await update.message.reply_text("Paste your Forest session link:")
    return WAITING_LINK


async def room_receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    parsed = _parse_forest_link(update.message.text.strip())
    if parsed is None:
        await update.message.reply_text(
            "Couldn't read that. Please paste the original Forest invite message."
        )
        return WAITING_LINK
    user = update.effective_user
    parsed["host_id"] = user.id
    parsed["host_username"] = user.username or ""
    _pending_setup[user.id] = parsed
    buttons = [
        InlineKeyboardButton(str(n), callback_data=f"room_min_{n}")
        for n in range(3, 11)
    ]
    await update.message.reply_text(
        f"🌳 <b>{parsed['tree']}</b> — {parsed['duration']} min session\n\n"
        "In how many minutes will you start?",
        reply_markup=InlineKeyboardMarkup([buttons]),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def room_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _pending_setup.pop(update.effective_user.id, None)
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════
#  CALLBACK QUERY ROUTER
# ═══════════════════════════════════════════════════════════════════════

async def room_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    if not data.startswith("room_"):
        return
    if data.startswith("room_min_"):
        await _cb_minute(query, context)
    elif data == "room_extend":
        await _cb_extend(query, context)
    elif data == "room_noop":
        await query.answer()
    elif data in ("room_done", "room_distracted", "room_more"):
        await _cb_score(query, context, data)
    else:
        await query.answer()


async def _cb_minute(query, context):
    global _session
    setup = _pending_setup.pop(query.from_user.id, None)
    if setup is None:
        await query.answer("Session setup expired.", show_alert=True)
        return
    await query.answer()
    minutes = int(query.data.split("_")[-1])
    start_time = datetime.now(GMT3) + timedelta(minutes=minutes)

    if _session is not None:
        _cancel_jobs(context.application.job_queue)
        await _strip_old_buttons(context.bot)

    _session = {
        "host_id": setup["host_id"],
        "host_username": setup["host_username"],
        "tree": setup["tree"],
        "sticker_id": setup["sticker_id"],
        "duration": setup["duration"],
        "token": setup["token"],
        "join_link": setup["join_link"],
        "start_time": start_time,
        "extra_minutes": 0,
        "session_msg_id": None,
        "task_msg_id": None,
        "group_thread_id": None,
        "participants": OrderedDict(),
        "tasks": {},
        "phase": "countdown",
        "scores": {},
        "remaining_countdown": minutes,
        "remaining_active": setup["duration"],
    }

    # Sticker → Session post → Task post
    if setup.get("sticker_id"):
        try:
            await context.bot.send_sticker(
                chat_id=CHANNEL_ID, sticker=setup["sticker_id"],
                disable_notification=True,
            )
        except Exception as e:
            print(f"⚠️ Failed to send tree sticker: {e}")

    sm = await context.bot.send_message(
        chat_id=CHANNEL_ID, text=_build_session_text(),
        parse_mode="HTML", reply_markup=_kb_countdown(minutes),
        disable_web_page_preview=True,
    )
    _session["session_msg_id"] = sm.message_id

    tm = await context.bot.send_message(
        chat_id=CHANNEL_ID, text=_build_task_text(),
        parse_mode="HTML", disable_web_page_preview=True,
    )
    _session["task_msg_id"] = tm.message_id

    context.application.job_queue.run_repeating(
        _countdown_tick, interval=60, first=60, name="room_countdown",
    )
    await query.edit_message_text(
        f"✅ Session posted! Countdown: {minutes} min.\n"
        f"🌳 {setup['tree']} — {setup['duration']} min\n"
        f"Starts at: {start_time.strftime('%H:%M')} GMT+3"
    )


async def _cb_extend(query, context):
    if _session is None or _session["phase"] != "countdown":
        await query.answer(); return
    if query.from_user.id != _session["host_id"]:
        await query.answer(); return
    if _session["extra_minutes"] >= 10:
        await query.answer("Maximum extension reached (+10 min).", show_alert=True)
        return
    await query.answer("+1 minute added")
    _session["extra_minutes"] += 1
    _session["start_time"] += timedelta(minutes=1)
    _session["remaining_countdown"] += 1
    await _edit_session_post(context.bot, _kb_countdown(_session["remaining_countdown"]))


async def _cb_score(query, context, data: str):
    if _session is None or _session["phase"] != "scoring":
        await query.answer(); return
    uid = query.from_user.id
    if uid not in _session["participants"]:
        await query.answer(); return
    emoji = {"room_done": "✅", "room_distracted": "🦦", "room_more": "⏳"}[data]
    _session["scores"][uid] = emoji
    await query.answer(f"Recorded: {emoji}")
    await _edit_task_post(context.bot, _kb_scoring())


# ═══════════════════════════════════════════════════════════════════════
#  TIMED JOBS
# ═══════════════════════════════════════════════════════════════════════

async def _countdown_tick(context: ContextTypes.DEFAULT_TYPE):
    global _session
    if _session is None or _session["phase"] != "countdown":
        return
    _session["remaining_countdown"] -= 1
    remaining = _session["remaining_countdown"]

    if remaining <= 0:
        _session["phase"] = "active"
        _session["remaining_active"] = _session["duration"]
        # Strikethrough session post, active timer on it
        await _edit_session_post(context.bot, _kb_active(_session["duration"]), strikethrough=True)
        for job in context.job_queue.jobs():
            if job.name == "room_countdown":
                job.schedule_removal()
        context.job_queue.run_repeating(
            _session_tick, interval=60, first=60, name="room_active",
        )
        return
    await _edit_session_post(context.bot, _kb_countdown(remaining))


async def _session_tick(context: ContextTypes.DEFAULT_TYPE):
    global _session
    if _session is None or _session["phase"] != "active":
        return
    _session["remaining_active"] -= 1
    remaining = _session["remaining_active"]

    if remaining <= 0:
        _session["phase"] = "scoring"
        # Strip buttons from session post
        await _edit_session_post(context.bot, keyboard=None, strikethrough=True)
        # Scoring buttons on task post
        await _edit_task_post(context.bot, _kb_scoring())

        for job in context.job_queue.jobs():
            if job.name == "room_active":
                job.schedule_removal()

        # Post session-over in group thread
        if _session.get("group_thread_id"):
            mentions = " ".join(f"@{u}" for u in _session["participants"].values() if u)
            cid = str(CHANNEL_ID).replace("-100", "")
            link = f"https://t.me/c/{cid}/{_session['task_msg_id']}"
            try:
                await context.bot.send_message(
                    chat_id=GROUP_ID,
                    text=(
                        f"⏰ Session over! Time to score yourselves.\n"
                        f"{mentions} — how did it go?\n"
                        f'<a href="{link}">Score here</a>'
                    ),
                    message_thread_id=_session["group_thread_id"],
                    parse_mode="HTML", disable_web_page_preview=True,
                )
            except Exception as e:
                print(f"⚠️ Failed to post session-over message: {e}")

        context.job_queue.run_once(
            _deactivate_scoring, when=600, name="room_scoring_timeout",
        )
        return
    await _edit_session_post(context.bot, _kb_active(remaining), strikethrough=True)


async def _deactivate_scoring(context: ContextTypes.DEFAULT_TYPE):
    global _session
    if _session is None or _session["phase"] != "scoring":
        return
    _session["phase"] = "ended"
    await _edit_task_post(context.bot, keyboard=None)


# ═══════════════════════════════════════════════════════════════════════
#  GROUP HANDLERS
# ═══════════════════════════════════════════════════════════════════════

async def track_forwarded_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Capture auto-forwarded task post in group → store its thread ID for /task matching."""
    if _session is None:
        return
    msg = update.message
    if msg is None:
        return

    # Resolve the original channel message_id from the forwarded copy
    origin_id = None
    if hasattr(msg, "forward_origin") and msg.forward_origin:
        origin_id = getattr(msg.forward_origin, "message_id", None)
    if origin_id is None:
        origin_id = getattr(msg, "forward_from_message_id", None)

    print(f"🔍 Auto-forward in group: group_msg={msg.message_id}, origin={origin_id}, "
          f"want_task={_session.get('task_msg_id')}")

    # We specifically want the TASK post's forward (that's where /task replies go)
    if origin_id == _session.get("task_msg_id"):
        _session["group_thread_id"] = msg.message_id
        print(f"✅ Captured task thread ID: {msg.message_id}")


async def task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/task <text> — only valid inside the session's comment thread."""
    if _session is None:
        return
    msg = update.message
    if msg is None or msg.chat_id != GROUP_ID:
        return
    thread_id = getattr(msg, "message_thread_id", None)
    print(f"🔍 /task received: chat={msg.chat_id}, thread={thread_id}, "
          f"expected={_session.get('group_thread_id')}, phase={_session.get('phase')}")
    if not thread_id or thread_id != _session.get("group_thread_id"):
        return

    user = update.effective_user
    uid = user.id
    uname = user.username or user.first_name
    mention = f"@{user.username}" if user.username else user.first_name

    if not _task_window_open():
        try:
            await msg.reply_text(
                f"⚠️ Sorry {mention}, task submissions are closed. "
                "The session has already started!"
            )
        except Exception:
            pass
        return

    task_text = " ".join(context.args) if context.args else ""
    if not task_text.strip():
        await msg.reply_text("Please include your task: /task <your task>")
        return
    if len(task_text) > 60:
        await msg.reply_text(f"Please keep your task under 60 characters {mention}")
        return

    _session["tasks"][uid] = task_text
    if uid not in _session["participants"]:
        _session["participants"][uid] = uname
        # Update task post with new participant
        kb = None
        if _session["phase"] == "scoring":
            kb = _kb_scoring()
        await _edit_task_post(context.bot, kb)


async def monitor_group_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """During active phase: delete ANY message type from participants and warn."""
    if _session is None or _session["phase"] != "active":
        return
    msg = update.message
    if msg is None or msg.chat_id != GROUP_ID:
        return
    uid = msg.from_user.id
    if uid not in _session["participants"]:
        return

    uname = _session["participants"][uid]
    remaining = _session["remaining_active"]
    mention = f"@{uname}" if uname else f"User {uid}"

    try:
        await msg.delete()
    except Exception as e:
        print(f"⚠️ Could not delete message from {uid}: {e}")
    try:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=f"⏱ {remaining} minutes left in this session, stay focused {mention}!",
        )
    except Exception as e:
        print(f"⚠️ Could not send focus warning: {e}")


# ═══════════════════════════════════════════════════════════════════════
#  EXPORTED CONVERSATION HANDLER
# ═══════════════════════════════════════════════════════════════════════

room_handler = ConversationHandler(
    entry_points=[
        CommandHandler("room", room_start, filters=filters.ChatType.PRIVATE),
    ],
    states={
        WAITING_LINK: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, room_receive_link),
        ],
        ConversationHandler.TIMEOUT: [
            MessageHandler(filters.ALL, lambda u, c: ConversationHandler.END),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", room_cancel),
        MessageHandler(filters.COMMAND, room_cancel),
    ],
    conversation_timeout=300,
)
