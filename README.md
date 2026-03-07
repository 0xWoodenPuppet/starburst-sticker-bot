# Features

**All chats:**
- Listens for messages containing a `forestapp.cc/join-room?token=` link and replies with a matching sticker based on triggers in `stickers.csv`, with a 5 second cooldown per user

**Specific chats (`DAILY_CHAT_IDS`):**
- Sends `📋 DD/MM/YYYY — Todo List` every day at 5:00 AM IST and pins it
- Sends `🌲 Today's Forest` every day at 10:30 PM IST and pins it
- Unpins the previous day's messages when new ones are sent
- Deletes the "X pinned a message" service notification when the bot pins