import os
import pytz
from datetime import date
from dotenv import load_dotenv

load_dotenv()

# BOT TOKEN
BOT_TOKEN = os.getenv("BOT_TOKEN")

# GEMINI API KEY
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# MONGODB
MONGO_URI = os.getenv("MONGODB_URI")

# BOT
BOT_USERNAME = "StarburstStickerBot"

# CHANNELS & GROUPS
DEKU_CHANNEL_ID = -1002511165129    # Notebook of Deku (Channel)
COOKED_GROUP_ID = -1002606388153    # Academically Cooked Weapons Chat (Group)
FOREST_CHAT_ID = -1001876174346     # Forest Group Chat

# Buffer time (minutes) between Forest link posting and assumed session start.
# Session-end DM fires after: BUFFER + session duration.
SESSION_BUFFER_MINUTES = 3

# ADMIN USER IDs
BOT_ADMIN_IDS = {
    1463187459,  # deku
    5534874386, # ari
}

# COOLDOWN PERIOD (seconds)
COOLDOWN = 5

# TIMEZONE
TIMEZONE = pytz.timezone("Asia/Kolkata")

# DAILY MESSAGES (Todo, Forest)
DAILY_CHAT_IDS = [
    DEKU_CHANNEL_ID,
]

# CHALLENGE MESSAGES
CHALLENGE_CHAT_IDS = [
    DEKU_CHANNEL_ID,
]

# DATABASE BACKUP
DATABASE_CHAT_ID = -5265809272 # Toothless Database

# FOREST SESSION
SESSION_USERS = {
    5534874386: DEKU_CHANNEL_ID, # Ari -> Notebook of Deku
    1382116841: -1002999663776, # Mochi -> Mochi Nest
    5236419662: -1003302115271, # Smiley face -> Let's plant together
    5791584631: -1003726481081, # @Memoaw -> studytripfor
    8473421124: -1003470344015, # Mero -> genius hub
}

# EXPERIMENTAL FEATURES (AI Moderator & Mentions)
EXPERIMENTAL_CHAT_ID = -1003644441864 # disappearing group

# MENTIONS
MENTION_SOURCE_CHANNEL_ID = DEKU_CHANNEL_ID
MENTION_CHAT_ID = COOKED_GROUP_ID

# AI MODERATOR
MOD_LOG_CHAT_ID = -1002911938910 # Using disappearing group as the admin log channel for testing
GROUP_RULES = """
❗️ Group Rules
1. Please chat in English.
2. No spam or self-promotion.
3. No disrespectful behavior or insults.
4. No off-topic chats or DMs.
"""

# READING CHALLENGE
READING_CHALLENGE_START_DATE = date(2026, 7, 13)
READING_CHALLENGE_TOTAL_DAYS = 21
READING_CHALLENGE_CHAT_IDS = [DEKU_CHANNEL_ID]
READING_TEST_CHAT_ID = MOD_LOG_CHAT_ID  # /test_reading only works here
