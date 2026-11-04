import html
import json
import os
from typing import Optional
from db import bot_state

QUOTES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "quotes.json")
QUOTE_STATE_KEY = "daily_quote_index"


def load_quotes() -> list[dict]:
    """Load the quotes list from data/quotes.json.
    
    Reading on each call ensures newly added quotes in the JSON file
    are picked up dynamically without restarting the application.
    """
    try:
        if not os.path.exists(QUOTES_FILE):
            print(f"⚠️ Quotes file not found at: {QUOTES_FILE}")
            return []
        with open(QUOTES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Error loading quotes from {QUOTES_FILE}: {e}")
        return []


async def get_current_quote(advance: bool = False) -> tuple[Optional[dict], int, int]:
    """Retrieve the current daily quote.
    
    Returns:
        (quote_dict, current_index, total_quotes)
    
    If advance is True, increments the index modulo total quotes and
    persists it into MongoDB bot_state.
    """
    quotes = load_quotes()
    if not quotes:
        return None, 0, 0

    total = len(quotes)
    doc = await bot_state.find_one({"_id": QUOTE_STATE_KEY})
    raw_index = doc.get("index", 0) if doc else 0
    current_index = raw_index % total

    selected_quote = quotes[current_index]

    if advance:
        next_index = (current_index + 1) % total
        await bot_state.replace_one(
            {"_id": QUOTE_STATE_KEY},
            {"_id": QUOTE_STATE_KEY, "index": next_index},
            upsert=True
        )

    return selected_quote, current_index, total


def format_quote_block(quote: Optional[dict]) -> str:
    """Format quote in bold text.
    
    Escapes special HTML characters (&, <, >) to preserve Telegram HTML formatting.
    """
    if not quote:
        return ""

    text = html.escape(quote.get("text", "").strip(), quote=False)
    source = html.escape(quote.get("source", "").strip(), quote=False)

    return f"\n\n<b>“{text}”</b>\n\n<b>— {source}</b>"
