import logging
import httpx
import asyncio
from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

async def call_gemini(
    contents: list,
    system_prompt: str | None = None,
    generation_config: dict | None = None,
    model: str = "gemini-2.5-flash",
    timeout: float = 60.0
) -> str | None:
    """Unified client for the Google Gemini API.

    Handles connection, headers, payload structuring, and automatically retries
    on common Google API server-side errors (500, 503, 529).

    Args:
        contents (list): List of message/role content dicts representing the payload.
        system_prompt (str, optional): The instruction prompt for the model's persona/rules.
        generation_config (dict, optional): Specific configurations (e.g. responseMimeType).
        model (str): Gemini model identifier. Default is 'gemini-2.5-flash'.
        timeout (float): Connection timeout in seconds. Default is 60.0.

    Returns:
        str | None: String content response from Gemini, or None on failure.
    """
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY is not set.")
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
    
    payload = {
        "contents": contents
    }
    
    if system_prompt:
        payload["system_instruction"] = {
            "parts": [{"text": system_prompt}]
        }
        
    if generation_config:
        payload["generationConfig"] = generation_config

    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=timeout)
                
                if response.status_code in [500, 503, 529] and attempt < max_retries - 1:
                    logger.warning(f"Gemini API {response.status_code} error. Retrying {attempt + 1}/{max_retries}...")
                    await asyncio.sleep(2)
                    continue
                    
                response.raise_for_status()
                
                data = response.json()
                if "candidates" in data and len(data["candidates"]) > 0:
                    candidate_parts = data["candidates"][0].get("content", {}).get("parts", [])
                    if candidate_parts:
                        return candidate_parts[0].get("text", "")
                
                return None
        except Exception as e:
            if attempt < max_retries - 1 and ("503" in str(e) or "529" in str(e)):
                await asyncio.sleep(2)
                continue
            logger.error(f"Error calling Gemini API: {e}")
            return None
            
    return None
