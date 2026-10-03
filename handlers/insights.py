"""
/insights command handler

Pulls user engagement data from the BDA pipeline (user_analytics collection)
and uses the saved ML Random Forest model to predict the user's current
probability of completing a post-session review.
"""
import os
import joblib
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from db import user_analytics, global_analytics

# Load ML models globally on startup
MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "ml_output", "models")
try:
    clf = joblib.load(os.path.join(MODEL_DIR, "random_forest.joblib"))
    le = joblib.load(os.path.join(MODEL_DIR, "label_encoder.joblib"))
except Exception as e:
    clf, le = None, None
    print(f"Warning: Could not load ML models: {e}")

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

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

    # 2. Format basic stats
    # Convert peak hour from UTC to GMT+3
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

    # ML Prediction: What if they start a session right now?
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

    await update.message.reply_text(text, parse_mode="Markdown")
