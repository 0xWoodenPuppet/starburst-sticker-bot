import logging
import base64
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from services.gemini import call_gemini

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "You are a helpful, concise AI assistant integrated into a Telegram bot. Keep responses clear and well-structured."

async def call_gemini_multimodal(parts: list) -> str | None:
    """Calls the Gemini API with multimodal parts (text, images, audio, video)."""
    contents = [{"role": "user", "parts": parts}]
    return await call_gemini(
        contents=contents,
        system_prompt=SYSTEM_PROMPT
    )


async def _download_telegram_file(file_obj) -> bytes | None:
    """Downloads a Telegram file object and returns its bytes."""
    try:
        tg_file = await file_obj.get_file()
        return await tg_file.download_as_bytearray()
    except Exception as e:
        logger.error(f"Error downloading Telegram file: {e}")
        return None


def _make_inline_data_part(data: bytes, mime_type: str) -> dict:
    """Creates a Gemini inline_data part from raw bytes."""
    return {
        "inline_data": {
            "mime_type": mime_type,
            "data": base64.b64encode(data).decode("utf-8")
        }
    }


async def _extract_media_parts(reply_msg, context) -> list:
    """
    Extracts media from a replied Telegram message and returns Gemini-compatible parts.
    Supports: photos, voice notes, video notes (circles), videos, audio, and stickers.
    """
    parts = []

    # Photo (grab the highest resolution version)
    if reply_msg.photo:
        photo = reply_msg.photo[-1]  # highest res
        data = await _download_telegram_file(photo)
        if data:
            parts.append(_make_inline_data_part(data, "image/jpeg"))

    # Sticker (converted to image)
    if reply_msg.sticker and not reply_msg.sticker.is_animated and not reply_msg.sticker.is_video:
        data = await _download_telegram_file(reply_msg.sticker)
        if data:
            parts.append(_make_inline_data_part(data, "image/webp"))
            parts.append({"text": "(This is a Telegram sticker)"})

    # Video sticker
    if reply_msg.sticker and reply_msg.sticker.is_video:
        data = await _download_telegram_file(reply_msg.sticker)
        if data:
            parts.append(_make_inline_data_part(data, "video/webm"))
            parts.append({"text": "(This is a video sticker)"})

    # Voice note
    if reply_msg.voice:
        data = await _download_telegram_file(reply_msg.voice)
        if data:
            parts.append(_make_inline_data_part(data, reply_msg.voice.mime_type or "audio/ogg"))

    # Audio file
    if reply_msg.audio:
        data = await _download_telegram_file(reply_msg.audio)
        if data:
            parts.append(_make_inline_data_part(data, reply_msg.audio.mime_type or "audio/mpeg"))

    # Video
    if reply_msg.video:
        data = await _download_telegram_file(reply_msg.video)
        if data:
            parts.append(_make_inline_data_part(data, reply_msg.video.mime_type or "video/mp4"))

    # Video note (circle message)
    if reply_msg.video_note:
        data = await _download_telegram_file(reply_msg.video_note)
        if data:
            parts.append(_make_inline_data_part(data, "video/mp4"))

    # Document (only if it's an image, audio, or video)
    if reply_msg.document:
        mime = reply_msg.document.mime_type or ""
        if mime.startswith(("image/", "audio/", "video/")):
            data = await _download_telegram_file(reply_msg.document)
            if data:
                parts.append(_make_inline_data_part(data, mime))

    return parts


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /ask <prompt> — supports text, photos, voice, video, stickers via reply."""
    prompt = " ".join(context.args) if context.args else ""
    
    gemini_parts = []
    reply_msg = update.message.reply_to_message
    has_media = False

    if reply_msg:
        # Extract any text/caption from the replied message
        replied_text = reply_msg.text or reply_msg.caption
        if replied_text:
            gemini_parts.append({"text": f"Context from replied message:\n{replied_text}"})
        
        # Extract any media from the replied message
        media_parts = await _extract_media_parts(reply_msg, context)
        if media_parts:
            has_media = True
            gemini_parts.extend(media_parts)

    if not prompt and not gemini_parts:
        await update.message.reply_text(
            "Please provide a prompt or reply to a message!\nExample: `/ask summarize this`",
            parse_mode="Markdown"
        )
        return

    # Add the user's prompt
    if prompt:
        gemini_parts.append({"text": prompt})
    elif has_media and not any(p.get("text") for p in gemini_parts if "text" in p and "Context" not in p.get("text", "")):
        # If they replied to media with just /ask and no prompt, ask Gemini to describe it
        gemini_parts.append({"text": "Describe or analyze this."})

    # Send a typing action
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    answer = await call_gemini_multimodal(gemini_parts)
    
    # Telegram messages can be max 4096 characters long
    if answer:
        if len(answer) > 4090:
            answer = answer[:4090] + "..."
        try:
            await update.message.reply_text(answer, parse_mode="Markdown")
        except BadRequest as e:
            logger.warning(f"Failed to send /ask response with Markdown formatting: {e}. Retrying without formatting.")
            await update.message.reply_text(answer, parse_mode=None)
