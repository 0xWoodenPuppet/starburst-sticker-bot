# Starburst Bot

A multi-functional Telegram bot built to manage productivity groups, track challenges, moderate chats using AI, and gamify the Forest app experience.

## Features

### 🌲 Forest App Integration
- **Automated Stickers:** Automatically replies with specific tree stickers when a user shares a Forest app link matching configured triggers. Includes an anti-spam cooldown mechanism.
- **Session Countdowns:** Users can send Forest links via DM to schedule group focus sessions. The bot posts a live, updating countdown in the group.
- **AI Productivity Coach (Gemini):** After a focus session ends, the bot's AI coach (Toothless) sends a DM to the user asking how the session went, providing encouraging and actionable feedback.
- **Forest Mentions:** Users can subscribe to be notified when someone shares a Forest link in the group.

### 🏆 7-Day Challenge Management
- **Daily Check-ins:** Automatically posts and pins a daily check-in message to a designated channel/group at a specific time.
- **Automated Mentions:** When the check-in post is forwarded to the group, the bot automatically tags all participating users (dynamically pulled from the `challenge_scores.csv` database).
- **Admin Scoring (`/s`):** Admins can reply to a user's check-in message with `/s <points>` to assign a score. The bot intelligently calculates the correct challenge day based on the timestamp of the user's message.
- **Leaderboard (`/leaderboard`):** A public command that generates a sorted leaderboard of all participants and their total points.
- **Database Backup:** Every time a score is added or updated, the bot automatically uploads the latest `challenge_scores.csv` file to a private Admin database channel for safe keeping and version history.

### 🛡️ AI Moderation
- **Smart Reports (`/report`):** Users can reply to a toxic or rule-breaking message with `/report`. The bot uses the Gemini AI to analyze the message against a strict set of group rules.
- **Automated Actions:** Based on the AI's verdict, the bot can automatically MUTE (1 hour) or BAN the offending user.
- **Audit Logs:** All AI moderation decisions and reasoning are forwarded to a private Mod Log channel for human review.

### ⏰ Scheduled Daily Broadcasts
- **Morning To-Do:** Sends a daily morning check-in prompt.
- **Nightly Forest:** Sends a daily reminder for the final group Forest session of the day.

## Commands

### User Commands
- `/ask <prompt>` - Ask the Gemini AI a question or prompt. Works in DMs and groups.
- `/leaderboard` - View the current 7-Day Challenge standings.
- `/sleep` - Sends a sticker telling the replied user to go to sleep.
- `/addmention [@username]` - Subscribe to general Forest session mentions.
- `/removemention [@username]` - Unsubscribe from Forest session mentions.
- `/report` - Reply to an inappropriate message to trigger the AI Moderator.

### Admin Commands
- `/s <points>` - Reply to a message to assign or update points for the challenge.
- `/removeallmentions` - Clears the entire Forest session mention list.
- `/test_challenge` - Manually triggers the daily challenge check-in post.

## Architecture & Configuration
- **No External Database Required:** The bot uses local CSV files to track scores, combined with automated Telegram channel document uploads to act as a resilient, free database with version history.
- **Keep-Alive Server:** Includes a lightweight Flask web server running on port 3000 to keep the bot alive on cloud hosting environments (like Render or Replit).
- **Timezone:** All daily messages and logical score day calculations are strictly bound to the `Asia/Kolkata` (IST) timezone.