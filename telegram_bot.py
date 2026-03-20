"""
Telegram bot front-end for the job-seeker agent.

Environment variables required (add to .env):
    TELEGRAM_BOT_TOKEN   — from @BotFather
    TELEGRAM_USER_ID     — your numeric Telegram user ID (bot only responds to you)
                           get it by messaging @userinfobot

Usage:
    uv run python telegram_bot.py
"""

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from google.adk.artifacts import FileArtifactService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from langsmith.integrations.google_adk import configure_google_adk
from telegram import Update, constants
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()
configure_google_adk()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ADK runner setup
# ---------------------------------------------------------------------------

_ARTIFACTS_DIR = Path(__file__).parent / "jobseeker" / ".adk" / "artifacts"
_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

from jobseeker.agent import root_agent  # noqa: E402 — import after env is loaded

_session_service = InMemorySessionService()
_artifact_service = FileArtifactService(root_dir=_ARTIFACTS_DIR)

_runner = Runner(
    app_name="jobseeker",
    agent=root_agent,
    session_service=_session_service,
    artifact_service=_artifact_service,
)

# One persistent session per Telegram user_id  →  agent remembers context
_sessions: dict[int, str] = {}


async def _get_or_create_session(tg_user_id: int) -> str:
    if tg_user_id not in _sessions:
        session = await _session_service.create_session(
            app_name="jobseeker",
            user_id=str(tg_user_id),
        )
        _sessions[tg_user_id] = session.id
        log.info("Created ADK session %s for Telegram user %d", session.id, tg_user_id)
    return _sessions[tg_user_id]


async def _run_agent(tg_user_id: int, parts: list[types.Part]) -> str:
    """Send parts (text/files) to the agent and return its final text response."""
    session_id = await _get_or_create_session(tg_user_id)

    response_parts: list[str] = []
    async for event in _runner.run_async(
        user_id=str(tg_user_id),
        session_id=session_id,
        new_message=types.Content(role="user", parts=parts),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    response_parts.append(part.text)

    return "\n".join(response_parts) or "_(no response)_"


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

def _allowed(update: Update) -> bool:
    allowed_id = os.environ.get("TELEGRAM_USER_ID", "")
    if not allowed_id:
        return True  # no restriction configured
    return str(update.effective_user.id) == allowed_id


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    await update.message.reply_text(
        "👋 *Job Seeker Agent* ready.\n\n"
        "I can:\n"
        "• Search jobs on Indeed & LinkedIn\n"
        "• Create a tailored CV (LaTeX → PDF)\n"
        "• Upload it to Google Drive\n"
        "• Log the application to Google Sheets\n\n"
        "Just tell me what you're looking for, or provide your CV data and a job link.",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    tg_user_id = update.effective_user.id
    if tg_user_id in _sessions:
        del _sessions[tg_user_id]
    await update.message.reply_text("Session reset. Starting fresh 🔄")


async def _download_tg_file(file_obj, bot) -> bytes:
    """Download a Telegram file and return its bytes."""
    tg_file = await bot.get_file(file_obj.file_id)
    return bytes(await tg_file.download_as_bytearray())


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        await update.message.reply_text(
            f"⛔ Unauthorised.\n\nYour Telegram user ID is `{update.effective_user.id}` — "
            "add it as `TELEGRAM_USER_ID` in your `.env` file.",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    tg_user_id = update.effective_user.id
    msg = update.message
    parts: list[types.Part] = []

    # Text (standalone or as caption)
    text = msg.text or msg.caption or ""
    if text:
        parts.append(types.Part(text=text))

    # Voice / audio
    voice = msg.voice or msg.audio
    if voice:
        data = await _download_tg_file(voice, ctx.bot)
        mime = voice.mime_type or "audio/ogg"
        parts.append(types.Part(inline_data=types.Blob(mime_type=mime, data=data)))

    # Document (files)
    if msg.document:
        data = await _download_tg_file(msg.document, ctx.bot)
        mime = msg.document.mime_type or "application/octet-stream"
        parts.append(types.Part(inline_data=types.Blob(mime_type=mime, data=data)))
        if not text:
            parts.append(types.Part(text=f"[file: {msg.document.file_name}]"))

    # Photo (pick largest resolution)
    if msg.photo:
        photo = msg.photo[-1]
        data = await _download_tg_file(photo, ctx.bot)
        parts.append(types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=data)))

    if not parts:
        return

    # Show typing indicator while the agent works
    await ctx.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=constants.ChatAction.TYPING,
    )

    try:
        reply = await _run_agent(tg_user_id, parts)
    except Exception as e:
        log.exception("Agent error for user %d", tg_user_id)
        reply = f"⚠️ Agent error: {e}"

    # Telegram messages max out at 4096 chars — split if needed
    for chunk in _split(reply, 4096):
        await update.message.reply_text(chunk)


def _split(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start : start + max_len])
        start += max_len
    return chunks


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in environment / .env")

    app = (
        Application.builder()
        .token(token)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.Document.ALL | filters.VOICE | filters.AUDIO | filters.PHOTO)
        & ~filters.COMMAND,
        handle_message,
    ))

    webhook_base = os.environ.get("WEBHOOK_URL", "").rstrip("/")
    if webhook_base:
        port = int(os.environ.get("PORT", "8080"))
        log.info("Bot starting — webhook mode on port %d", port)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=token,
            webhook_url=f"{webhook_base}/{token}",
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        log.info("Bot starting — polling for updates…")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
