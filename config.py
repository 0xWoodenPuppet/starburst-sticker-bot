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
SESSION_CHAT_ID = -1002511165129 # Notebook of Deku
SESSION_USER_ID = 1463187459 # Deku
# SESSION_CHAT_ID = -1002911938910 # disappearing

# MENTIONS
# MENTION_CHAT_ID = -1003644441864 # Deku and Tooothless
# MENTION_SOURCE_CHANNEL_ID = -1002911938910 # Diappearing notes
MENTION_CHAT_ID = -1002606388153 # Cooked Weapons Chat
MENTION_SOURCE_CHANNEL_ID = -1002511165129 # Notebook of Deku
