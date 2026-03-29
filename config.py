import os
import pytz
from dotenv import load_dotenv

load_dotenv()

# BOT TOKEN
BOT_TOKEN = os.getenv("BOT_TOKEN")

# GEMINI API KEY
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ADMIN USER IDs
BOT_ADMIN_IDS = {
    1463187459,  # deku
}

# COOLDOWN PERIOD (seconds)
COOLDOWN = 5

# TIMEZONE
TIMEZONE = pytz.timezone("Asia/Kolkata")

# DAILY MESSAGES
DAILY_CHAT_IDS = [
    -1002511165129, # Notebook of Deku
]

# FOREST SESSION
# SESSION_CHAT_ID = -1002511165129 # Notebook of Deku
SESSION_USER_ID = 1463187459 # Deku
SESSION_CHAT_ID = -1002911938910 # disappearing

# EXPERIMENTAL FEATURES (AI Moderator & Mentions)
EXPERIMENTAL_CHAT_ID = -1003644441864 # disappearing group

# MENTIONS
# MENTION_CHAT_ID = -1003644441864 # Deku and Tooothless
# MENTION_SOURCE_CHANNEL_ID = -1002911938910 # Diappearing notes
MENTION_SOURCE_CHANNEL_ID = -1002511165129 # Notebook of Deku

# AI MODERATOR
MOD_LOG_CHAT_ID = -1002911938910 # Using disappearing group as the admin log channel for testing
GROUP_RULES = """
❗️ Group Rules
1. Please chat in English.
2. No spam or self-promotion.
3. No disrespectful behavior or insults.
4. No off-topic chats or DMs.
"""

