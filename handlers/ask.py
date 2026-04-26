import logging
import httpx
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

async def call_gemini_ask(prompt: str) -> str | None:
    """
    Calls the Gemini API to answer a general query.
    """
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY is not set.")
        return "I'm sorry, my AI features are currently disabled (missing API key)."

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
    
    payload = {
        "system_instruction": {
            "parts": [{"text": "You are a helpful, concise AI assistant integrated into a Telegram bot."}]
        },
        "contents": [{"role": "user", "parts": [{"text": prompt}]}]
    }

    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=30.0)
                
                if response.status_code in [500, 503, 529] and attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                    
                response.raise_for_status()
                
                data = response.json()
                if "candidates" in data and len(data["candidates"]) > 0:
                    parts = data["candidates"][0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "")
                
                return "I couldn't generate a response."
        except Exception as e:
            if attempt < max_retries - 1 and "503" in str(e):
                await asyncio.sleep(2)
                continue
            logger.error(f"Error calling Gemini API for /ask: {e}")
            return "There was an error communicating with the AI. Please try again later."
            
    return "The AI service is currently unavailable."

async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /ask <prompt>"""
    if not context.args:
        await update.message.reply_text("Please provide a prompt! Example: `/ask What is the capital of France?`", parse_mode="Markdown")
        return

    prompt = " ".join(context.args)
    
    # Send a typing action to let the user know the bot is thinking
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    answer = await call_gemini_ask(prompt)
    
    # Telegram messages can be max 4096 characters long
    if answer:
        if len(answer) > 4090:
            answer = answer[:4090] + "..."
        await update.message.reply_text(answer, parse_mode="Markdown")
