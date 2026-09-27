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
    peak_hour = f"{user_data.get('peak_hour', 0):02d}:00 UTC"
    peak_day = DAY_NAMES[user_data.get('peak_day', 0)]
    avg_dur = user_data.get('avg_duration', 0)
    streak = user_data.get('current_streak', 0)
    best_streak = user_data.get('best_streak', 0)
    review_rate = user_data.get('review_rate', 0) or 0
    
    avg_review_rate = 0.41 # Global average from ML training

    text = f"📊 **Your Focus Insights**\n\n"
    text += f"⏱ **Peak Focus:** {peak_day}s around {peak_hour}\n"
    text += f"⏳ **Sweet Spot:** {user_data.get('top_duration', 0)} min sessions (avg: {avg_dur:.1f}m)\n"
    text += f"🔥 **Streaks:** {streak} days (Best: {best_streak} days)\n"
    text += f"📝 **Review Rate:** {review_rate*100:.0f}% (Group avg: {avg_review_rate*100:.0f}%)\n"
    
    if review_rate > avg_review_rate:
        text += f"   _You reflect on your sessions {((review_rate/avg_review_rate)-1)*100:.0f}% more than average!_\n"

    # 3. Tree Leaderboard
    text += f"\n🌳 **Your Top Tree:**\n"
    text += f"1. {user_data.get('top_tree', 'unknown').title()} (Most planted across {user_data.get('total_sessions', 0)} sessions)\n"

    if global_data and "top_trees" in global_data:
        text += f"\n🏆 **Group Top Trees:**\n"
        for i, t in enumerate(global_data["top_trees"][:3], 1):
            text += f"{i}. {t['name'].title()} ({t['sessions']})\n"

    # 4. ML Prediction: What if they start a session right now?
    if clf and le:
        now = datetime.now(timezone.utc)
        hour = now.hour
        day_of_week = now.weekday()
        is_weekend = 1 if day_of_week >= 5 else 0
        days_since_last = user_data.get('days_since_last', 0)
        user_prior_sessions = user_data.get('total_sessions', 0)
        hist_review_rate = review_rate
        
        # Encode their top tree for the model
        tree_name = user_data.get('top_tree', 'unknown')
        try:
            tree_encoded = le.transform([tree_name])[0]
        except:
            tree_encoded = 0
            
        # Defaults for a standard task
        task_word_count = 5
        task_char_count = 30
        task_cluster = 1 # The most common cluster
        
        # Features must match ML pipeline order exactly:
        # ["duration", "hour", "day_of_week", "tree_encoded", "task_word_count", "task_char_count", "task_cluster", "user_prior_sessions", "user_historical_review_rate", "days_since_last_session", "is_weekend"]
        features = [[
            avg_dur, hour, day_of_week, tree_encoded, 
            task_word_count, task_char_count, task_cluster,
            user_prior_sessions, hist_review_rate,
            days_since_last, is_weekend
        ]]
        
        prob = clf.predict_proba(features)[0][1] # Probability of class 1
        
        text += f"\n🤖 **AI Insight:**\n"
        text += f"Based on your habits and the current time ({hour:02d}:00 UTC), if you start a session right now, our ML model predicts a **{prob*100:.1f}% probability** that you'll follow through and write a review."
        
        if prob < 0.4:
            text += " Remember to log what you accomplished!"
        elif prob > 0.7:
            text += " You're in the zone! 🚀"

    await update.message.reply_text(text, parse_mode="Markdown")
