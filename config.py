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
    -1002911938910, # Disappearing notes (Test Channel)
]

# FOREST SESSION
SESSION_USERS = {
    1463187459: -1002511165129, # Deku -> Notebook of Deku
    1382116841: -1002999663776, # Mochi -> Mochi Nest
    5236419662: -1003302115271, # Smiley face -> Let's plant together
    5791584631: -1003726481081, # @Memoaw -> studytripfor
    8473421124: -1003470344015, # Mero -> genius hub
}

# EXPERIMENTAL FEATURES (AI Moderator & Mentions)
EXPERIMENTAL_CHAT_ID = -1003644441864 # disappearing group

# MENTIONS
MENTION_SOURCE_CHANNEL_ID = -1002911938910 # Disappearing notes
MENTION_CHAT_ID = -1003644441864 # disappearing group

# AI MODERATOR
MOD_LOG_CHAT_ID = -1002911938910 # Using disappearing group as the admin log channel for testing
GROUP_RULES = """
❗️ Group Rules
1. Please chat in English.
2. No spam or self-promotion.
3. No disrespectful behavior or insults.
4. No off-topic chats or DMs.
"""

