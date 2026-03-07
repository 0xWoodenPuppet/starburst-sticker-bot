import re
import csv
import sys

# Load triggers from CSV
all_triggers = []
try:
    with open("stickers.csv", mode="r", encoding="utf-8") as file:
        reader = csv.reader(file)
        for row in reader:
            if len(row) == 2:
                all_triggers.append((row[0].strip(), row[1].strip()))
except FileNotFoundError:
    print("❌ Error: stickers.csv not found! Please create it before running.")
    sys.exit(1)

# Longer triggers take priority
all_triggers.sort(key=lambda item: len(item[0]), reverse=True)

TRIGGERS = {trigger: sticker_id for trigger, sticker_id in all_triggers}
TRIGGER_PATTERNS = {
    trigger: re.compile(rf"(?<!\S){re.escape(trigger)}(?!\S)", re.IGNORECASE)
    for trigger in TRIGGERS
}

# Cooldown tracker: (chat_id, user_id) -> last trigger timestamp
last_trigger_time = {}
