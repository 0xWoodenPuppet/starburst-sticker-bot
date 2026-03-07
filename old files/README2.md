# 🌲 Forest Sticker Bot

A Telegram bot designed for **Forest App** communities. It automatically detects Forest room links and replies with a specific sticker corresponding to the tree being planted.

It supports **14+ languages** (English, Arabic, Chinese, Japanese, etc.) and handles spam protection, scheduled messages, and dynamic sticker management.

## ✨ Features

* **Auto-Reply:** Detects tree names in messages *only* if they contain a valid `forestapp.cc` room link.
* **Multilingual Support:** Recognizes tree names in every language supported by the Forest App.
* **Anti-Spam:**
  * **Cooldown:** Ignores repeated triggers from the same user for 5 seconds.
  * **Context Aware:** Ignores tree names in casual conversation unless a link is present.


* **Scheduled Messages:** Sends recurring daily reminders (e.g., "Bed 'o clock", "Drink Water") to specific groups.
* **Admin Tools:** Add new stickers directly from Telegram using `/addsticker` and export the database with `/export`.
* **Keep-Alive:** Includes a lightweight Flask server to keep the bot running on cloud platforms (Render, Replit, etc.).

## 🛠️ Installation & Setup

### 1. Prerequisites

* Python 3.9+
* A Telegram Bot Token (from [@BotFather](https://t.me/BotFather))

### 2. Install Dependencies

```bash
pip install python-telegram-bot flask pytz pandas

```

### 3. Configuration

Set your environment variables (or hardcode them in `config.py` for local testing):

* `BOT_TOKEN`: Your Telegram Bot API Token.

### 4. The Database (`stickers.csv`)

The bot relies on a `stickers.csv` file acting as the database.
**Format:** `trigger_word, sticker_file_id`

```csv
cedar, CAACAg...
white rose, CAACAg...
الوردة البيضاء, CAACAg...

```

## 🚀 Usage

### Running the Bot

```bash
python bot.py

```

### User Commands

Just paste a Forest Link!

> **User:** Join me! [https://forestapp.cc/join-room?token=xyz](https://www.google.com/search?q=https://forestapp.cc/join-room%3Ftoken%3Dxyz) I am planting a Cedar.
> **Bot:** *[Sends Cedar Sticker]*

### Admin Commands

*(Only accessible to IDs listed in `BOT_ADMIN_IDS`)*

* `/addsticker` - Starts a conversation to add a new trigger/sticker pair to the database.
* `/export` - Sends the current `stickers.csv` file to the admin.

## 🔄 Maintenance: Adding New Trees

When Forest releases a new update (e.g., new trees), follow this workflow to update the bot's vocabulary.

### Step 1: Extract New Names

1. Download the new **Forest APK**.
2. Decompile it using `apktool`.
3. Place `extract_master_list.py` in the decompiled `res` folder.
4. Run the script to generate `forest_master_list.csv`.

### Step 2: Update Sticker IDs

1. Send the new tree stickers to the bot (or @idstickerbot) to get their **File IDs**.
2. Open your current `stickers.csv` (from GitHub or `/export`).
3. Add the **English name only** at the bottom:
```csv
new tree name, CAACAg...[New_ID]

```



### Step 3: Merge Languages

1. Place `forest_master_list.csv`, `stickers.csv`, and `merge_langs.py` in the same folder.
2. Run the merge script:
```bash
python merge_langs.py

```


3. This generates `stickers_final.csv` containing the new tree in all 14 languages.
4. Rename it to `stickers.csv` and redeploy the bot.

## 📄 License

**MIT License**

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.