import logging
import httpx
from telegram import Update
from telegram.ext import ContextTypes
from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Toothless, a warm, concise productivity coach embedded in a Telegram bot.
The user just finished a Forest app focus session. Ask how it went, listen, and respond with
brief, encouraging, actionable feedback. Keep responses short — 2-4 sentences max.
Consider the session duration (provided in the conversation history) when giving feedback.
A 10-25 minute session is short, so small progress is great. A 60-120 minute session should yield more substantial progress.
Don't be overly enthusiastic, but be genuine, helpful, and human."""

async def call_gemini(conversation_history: list[dict]) -> str | None:
    """
    Calls the Gemini 1.5 Pro API using httpx.
    """
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY is not set.")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
    
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": conversation_history
    }

    import asyncio
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=30.0)
                
                # If we get a 503 or 529 server error, wait and retry
                if response.status_code in [500, 503, 529] and attempt < max_retries - 1:
                    logger.warning(f"Gemini API {response.status_code} error. Retrying {attempt+1}/{max_retries}...")
                    await asyncio.sleep(2)
                    continue
                    
                response.raise_for_status()
                
                data = response.json()
                if "candidates" in data and len(data["candidates"]) > 0:
                    parts = data["candidates"][0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "")
                
                logger.error(f"Unexpected Gemini API response format: {data}")
                return None
        except Exception as e:
            if attempt < max_retries - 1 and "503" in str(e):
                await asyncio.sleep(2)
                continue
            logger.error(f"Error calling Gemini API: {e}")
            return None
    return None

async def send_coach_message(context: ContextTypes.DEFAULT_TYPE):
    """
    Called by the JobQueue after the user's session duration has elapsed.
    Sends the opening coach message to the user directly via DM.
    """
    job_data = context.job.data
    user_id = job_data["user_id"]
    dm_chat_id = job_data["dm_chat_id"]
    duration = job_data["duration"]
    
    text = f"how did your session go?\n\n({duration} minutes session)"
    
    try:
        await context.bot.send_message(
            chat_id=dm_chat_id,
            text=text,
        )
        
        # Initialize conversation state in bot_data
        context.bot_data[f"coach_dm_active_{user_id}"] = True
        # Track history, appending the assistant's initial opening phrase so the model has context
        context.bot_data[f"coach_history_{user_id}"] = [
            {"role": "model", "parts": [{"text": text}]}
        ]
        
    except Exception as e:
        logger.error(f"Failed to send coach DM to {dm_chat_id}: {e}")


async def handle_dm_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles any DM reply from the user if their coach session is active.
    """
    user_id = update.effective_user.id
    active_key = f"coach_dm_active_{user_id}"
    history_key = f"coach_history_{user_id}"
    
    # Check if coach mode is active for this user
    if not context.bot_data.get(active_key):
        return
        
    msg = update.effective_message
    if not msg or not msg.text:
        return
        
    user_text = msg.text
        
    # Get current history or initialize if missing
    history = context.bot_data.get(history_key, [])
    
    # Add user message to history
    history.append({
        "role": "user", 
        "parts": [{"text": user_text}]
    })
    
    # Show typing indicator
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    # Call Gemini
    response_text = await call_gemini(history)
    
    if response_text:
        # Add model response to history
        history.append({
            "role": "model",
            "parts": [{"text": response_text}]
        })
        context.bot_data[history_key] = history
        
        await update.message.reply_text(response_text)
    else:
        await update.message.reply_text("I'm having a little trouble thinking right now. Could you try again later?")
