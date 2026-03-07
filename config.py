import os
import pytz
from dotenv import load_dotenv

load_dotenv()

# BOT TOKEN
BOT_TOKEN = os.getenv("BOT_TOKEN")

# COOLDOWN PERIOD (seconds)
COOLDOWN = 5

# TIMEZONE
TIMEZONE = pytz.timezone("Asia/Kolkata")

# DAILY MESSAGES
DAILY_CHAT_IDS = [
    -1002511165129, # Notebook of Deku
]




