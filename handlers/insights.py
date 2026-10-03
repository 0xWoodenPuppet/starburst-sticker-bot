"""
/insights command handler

Pulls user engagement data from the BDA pipeline (user_analytics & channel_analytics collections)
and uses the saved ML Random Forest model to predict the user's current
probability of completing a post-session review.
If the user is an admin of a study channel, allows viewing their channel's focus stats.
"""
import os
import logging
import asyncio
import joblib
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db import user_analytics, channel_analytics, channel_admins, global_analytics

logger = logging.getLogger(__name__)

# Load ML models globally on startup
MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "ml_output", "models")
try:
    clf = joblib.load(os.path.join(MODEL_DIR, "random_forest.joblib"))
    le = joblib.load(os.path.join(MODEL_DIR, "label_encoder.joblib"))
except Exception as e:
    clf, le = None, None
    logger.warning(f"Could not load ML models: {e}")

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


async def sync_channel_admins(bot):
    """Caches channel administrators for all channels in channel_analytics."""
    try:
        channels = await channel_analytics.find({}).sort("total_sessions", -1).to_list(length=300)
        sem = asyncio.Semaphore(6)

        async def _check_channel(c):
            cid = c.get("channel_id")
            title = c.get("username", "Study Channel")
            if not cid:
                return
            async with sem:
                try:
                    admins = await bot.get_chat_administrators(chat_id=int(cid))
                    for a in admins:
                        if not a.user.is_bot:
                            await channel_admins.update_one(
                                {"channel_id": str(cid), "admin_user_id": a.user.id},
                                {
                                    "$set": {
                                        "channel_id": str(cid),
                                        "channel_title": title,
                                        "admin_user_id": a.user.id,
                                        "admin_name": a.user.first_name,
                                        "status": a.status,
                                        "updated_at": datetime.now(timezone.utc),
                                    }
                                },
                                upsert=True,
                            )
                except Exception:
                    pass

        await asyncio.gather(*[_check_channel(c) for c in channels], return_exceptions=True)
        count = await channel_admins.count_documents({})
        logger.info(f"Successfully synced channel administrators into MongoDB ({count} mappings).")
    except Exception as e:
        logger.warning(f"Channel admin sync encountered an issue: {e}")


def format_personal_insights(user_data: dict, global_data: dict) -> str:
    """Formats clean personal study insights."""
    peak_hour_gmt3 = (user_data.get('peak_hour', 0) + 3) % 24
    peak_hour_str = f"{peak_hour_gmt3:02d}:00 (GMT+3)"
    peak_day = DAY_NAMES[user_data.get('peak_day', 0)]
    avg_dur = user_data.get('avg_duration', 0)
    streak = user_data.get('current_streak', 0)
    best_streak = user_data.get('best_streak', 0)
    review_rate = user_data.get('review_rate', 0) or 0
    avg_review_rate = 0.41

    text = "*Your Focus Insights*\n\n"
    text += f"• Peak time: {peak_day}s around {peak_hour_str}\n"
    text += f"• Typical session: {user_data.get('top_duration', 0)} min (average: {avg_dur:.1f} min)\n"
    text += f"• Streak: {streak} days (best: {best_streak} days)\n"
    text += f"• Review rate: {review_rate*100:.0f}% (community average: {avg_review_rate*100:.0f}%)\n"

    top_tree = user_data.get('top_tree', 'unknown').title()
    sessions_count = user_data.get('total_sessions', 0)
    text += f"\n*Top tree:* {top_tree} ({sessions_count} sessions)\n"

    if global_data and "top_trees" in global_data:
        text += "\n*Community favorites:*\n"
        for i, t in enumerate(global_data["top_trees"][:3], 1):
            text += f"{i}. {t['name'].title()} ({t['sessions']} sessions)\n"

    # ML Prediction
    if clf and le:
        now = datetime.now(timezone.utc)
        hour = now.hour
        day_of_week = now.weekday()
        is_weekend = 1 if day_of_week >= 5 else 0
        days_since_last = user_data.get('days_since_last', 0)
        user_prior_sessions = user_data.get('total_sessions', 0)
        hist_review_rate = review_rate

        tree_name = user_data.get('top_tree', 'unknown')
        try:
            tree_encoded = le.transform([tree_name])[0]
        except Exception:
            tree_encoded = 0

        task_word_count = 5
        task_char_count = 30
        task_cluster = 1

        features = [[
            avg_dur, hour, day_of_week, tree_encoded,
            task_word_count, task_char_count, task_cluster,
            user_prior_sessions, hist_review_rate,
            days_since_last, is_weekend
        ]]

        prob = clf.predict_proba(features)[0][1]

        text += "\n*Prediction:*\n"
        text += (
            f"Based on your study habits and the current time, there is a "
            f"*{prob*100:.0f}% probability* you will complete a review if you start a session now."
        )

    return text


def format_channel_insights(channel_data: dict) -> str:
    """Formats clean study channel metrics."""
    title = channel_data.get("username", "Study Channel")
    peak_hour_gmt3 = (channel_data.get('peak_hour', 0) + 3) % 24
    peak_hour_str = f"{peak_hour_gmt3:02d}:00 (GMT+3)"
    peak_day = DAY_NAMES[channel_data.get('peak_day', 0)]
    avg_dur = channel_data.get('avg_duration', 0)
    best_streak = channel_data.get('best_streak', 0)
    total_sessions = channel_data.get('total_sessions', 0)
    total_focus_min = channel_data.get('total_focus_minutes', 0)
    total_focus_hrs = total_focus_min / 60
    active_days = channel_data.get('active_days', 0)
    top_tree = channel_data.get('top_tree', 'unknown').title()
    sessions_per_week = channel_data.get('sessions_per_week', 0)

    text = f"*{title} — Channel Insights*\n\n"
    text += f"• Peak time: {peak_day}s around {peak_hour_str}\n"
    text += f"• Typical session: {channel_data.get('top_duration', 0)} min (average: {avg_dur:.1f} min)\n"
    text += f"• Total sessions: {total_sessions} ({total_focus_hrs:.1f} focus hours)\n"
    text += f"• Active study days: {active_days} days\n"
    text += f"• Best streak: {best_streak} days ({sessions_per_week:.1f} sessions/week)\n"
    text += f"• Top planted tree: {top_tree}\n"

    return text


async def insights_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /insights command."""
    if update.message.chat.type != "private":
        await update.message.reply_text("Please use `/insights` in our DM! 🤫", parse_mode="Markdown")
        return

    user_id = str(update.effective_user.id)
    
    # 1. Fetch BDA data
    user_data = await user_analytics.find_one({"user_id": user_id})
    global_data = await global_analytics.find_one({})
    
    if not user_data:
        await update.message.reply_text("I don't have enough data on your focus sessions yet. Try completing a few sessions first! 🌱")
        return

    text = format_personal_insights(user_data, global_data)

    # 2. Check if user is an admin of any study channel in the database
    user_channels = []
    async for ca in channel_admins.find({"admin_user_id": update.effective_user.id}):
        user_channels.append(ca)

    keyboard = None
    if user_channels:
        buttons = []
        for ch in user_channels[:3]:
            raw_title = ch.get("channel_title", "Channel")
            clean_title = raw_title[:18] + ("…" if len(raw_title) > 18 else "")
            btn_title = f"📢 View \"{clean_title}\" Stats"
            cid = ch.get("channel_id")
            buttons.append([InlineKeyboardButton(btn_title, callback_data=f"ins:ch:{cid}:{user_id}")])
        keyboard = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


async def insights_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles toggling between personal insights and channel stats."""
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()

    parts = query.data.split(":")
    if len(parts) < 3 or parts[0] != "ins":
        return

    action = parts[1]  # "ch" (channel) or "p" (personal)

    if action == "ch":
        cid = parts[2]
        uid = parts[3] if len(parts) > 3 else str(update.effective_user.id)
        channel_data = await channel_analytics.find_one({"channel_id": cid})
        if not channel_data:
            await query.answer("Channel statistics not found in database.", show_alert=True)
            return

        text = format_channel_insights(channel_data)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 Back to Personal Insights", callback_data=f"ins:p:{uid}")]
        ])
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")

    elif action == "p":
        uid = parts[2]
        user_data = await user_analytics.find_one({"user_id": uid})
        global_data = await global_analytics.find_one({})
        if not user_data:
            return

        text = format_personal_insights(user_data, global_data)

        # Re-fetch user channels for the button
        user_channels = []
        try:
            async for ca in channel_admins.find({"admin_user_id": int(uid)}):
                user_channels.append(ca)
        except Exception:
            pass

        buttons = []
        for ch in user_channels[:3]:
            raw_title = ch.get("channel_title", "Channel")
            clean_title = raw_title[:18] + ("…" if len(raw_title) > 18 else "")
            btn_title = f"📢 View \"{clean_title}\" Stats"
            cid = ch.get("channel_id")
            buttons.append([InlineKeyboardButton(btn_title, callback_data=f"ins:ch:{cid}:{uid}")])

        keyboard = InlineKeyboardMarkup(buttons) if buttons else None
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
