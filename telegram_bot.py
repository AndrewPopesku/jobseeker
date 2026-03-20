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
import json
import logging
import os
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv
from google.adk.artifacts import FileArtifactService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from langsmith.integrations.google_adk import configure_google_adk
from telegram import BotCommand, Update, constants
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
from jobseeker.cv_creator_agent import cv_creator_agent  # noqa: E402
from jobseeker.google_tools import load_cv_data_from_drive, save_cv_data_to_drive  # noqa: E402

_session_service = InMemorySessionService()
_artifact_service = FileArtifactService(root_dir=_ARTIFACTS_DIR)

# General-purpose agent runner (root_agent handles routing)
_runner = Runner(
    app_name="jobseeker",
    agent=root_agent,
    session_service=_session_service,
    artifact_service=_artifact_service,
)

# Dedicated CV runner — calls cv_creator_agent directly for /tailor
_cv_runner = Runner(
    app_name="jobseeker_tailor",
    agent=cv_creator_agent,
    session_service=_session_service,
    artifact_service=_artifact_service,
)

# One persistent session per Telegram user_id  →  agent remembers context
_sessions: dict[int, str] = {}
_cv_sessions: dict[int, str] = {}

# ---------------------------------------------------------------------------
# Conversation state machine
# Tracks per-user "waiting for input" states for multi-step commands.
# ---------------------------------------------------------------------------

class ConvState(Enum):
    NORMAL = "normal"
    WAITING_CV_DATA = "waiting_cv_data"
    WAITING_JOB_DESC = "waiting_job_desc"

_conv_state: dict[int, ConvState] = {}

# ---------------------------------------------------------------------------
# Message batch buffer
# Telegram splits long messages into multiple updates sent within milliseconds
# of each other. We buffer incoming parts for BATCH_WINDOW_SECS seconds and
# then fire the agent once with everything joined together.
# ---------------------------------------------------------------------------

BATCH_WINDOW_SECS = 0.8  # seconds to wait for more chunks before processing

# per-user buffer: list of (parts, reply_fn) tuples collected so far
_batch_parts: dict[int, list[types.Part]] = {}
# per-user: the last Update (used to send the reply)
_batch_update: dict[int, Update] = {}
# per-user: pending debounce task
_batch_tasks: dict[int, asyncio.Task] = {}


async def _flush_batch(tg_user_id: int, chat_id: int, bot) -> None:
    """Called after BATCH_WINDOW_SECS to process all buffered parts at once."""
    parts = _batch_parts.pop(tg_user_id, [])
    update = _batch_update.pop(tg_user_id, None)
    _batch_tasks.pop(tg_user_id, None)

    if not parts or update is None:
        return

    await bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)

    try:
        reply = await _run_agent(tg_user_id, parts)
    except Exception as e:
        log.exception("Agent error for user %d", tg_user_id)
        reply = f"⚠️ Agent error: {e}"

    for chunk in _split(reply, 4096):
        await update.message.reply_text(chunk)


async def _get_or_create_session(tg_user_id: int) -> str:
    if tg_user_id not in _sessions:
        session = await _session_service.create_session(
            app_name="jobseeker",
            user_id=str(tg_user_id),
        )
        _sessions[tg_user_id] = session.id
        log.info("Created ADK session %s for Telegram user %d", session.id, tg_user_id)
    return _sessions[tg_user_id]


async def _get_or_create_cv_session(tg_user_id: int) -> str:
    if tg_user_id not in _cv_sessions:
        session = await _session_service.create_session(
            app_name="jobseeker_tailor",
            user_id=str(tg_user_id),
        )
        _cv_sessions[tg_user_id] = session.id
        log.info("Created CV session %s for Telegram user %d", session.id, tg_user_id)
    return _cv_sessions[tg_user_id]


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


async def _run_tailor(tg_user_id: int, job_desc: str, update: Update, bot) -> None:
    """Load CV data from Drive and run cv_creator_agent with the job description."""
    await bot.send_chat_action(
        chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING
    )

    try:
        user_data = load_cv_data_from_drive()
    except Exception as e:
        await update.message.reply_text(f"⚠️ Could not load CV data from Drive: {e}")
        return

    if not user_data:
        await update.message.reply_text(
            "No CV data found. Use /update_cv_data to save your info first."
        )
        return

    prompt = (
        "Job description:\n"
        f"{job_desc}\n\n"
        "My CV data:\n"
        f"{json.dumps(user_data, ensure_ascii=False)}\n\n"
        "Tailor my CV for this job, compile it, upload to Drive, and log to Sheets."
    )

    session_id = await _get_or_create_cv_session(tg_user_id)
    response_parts: list[str] = []

    try:
        async for event in _cv_runner.run_async(
            user_id=str(tg_user_id),
            session_id=session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
        ):
            if event.is_final_response() and event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        response_parts.append(part.text)
    except Exception as e:
        log.exception("Tailor agent error for user %d", tg_user_id)
        await update.message.reply_text(f"⚠️ Tailor error: {e}")
        return

    reply = "\n".join(response_parts) or "_(no response)_"
    for chunk in _split(reply, 4096):
        await update.message.reply_text(chunk)


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
        "Commands:\n"
        "• /update\\_cv\\_data — save your CV data\n"
        "• /read\\_cv\\_data — view stored CV data\n"
        "• /tailor — tailor CV for a job\n"
        "• /reset — start a fresh session\n\n"
        "Just tell me what you're looking for, or use /tailor for a one-shot workflow.",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    tg_user_id = update.effective_user.id
    if tg_user_id in _sessions:
        del _sessions[tg_user_id]
    if tg_user_id in _cv_sessions:
        del _cv_sessions[tg_user_id]
    _conv_state.pop(tg_user_id, None)
    await update.message.reply_text("Session reset. Starting fresh 🔄")


async def cmd_update_cv_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    tg_user_id = update.effective_user.id
    _conv_state[tg_user_id] = ConvState.WAITING_CV_DATA
    await update.message.reply_text(
        "Send your CV data as JSON.\n\n"
        "Expected top-level keys: name, location, phone, email, linkedin, summary, "
        "skills, experience, education, hackathons (optional), certifications (optional).\n\n"
        "If you send plain text instead of JSON, it will be stored as-is and the agent "
        "will use it as context when tailoring your CV."
    )


async def cmd_read_cv_data(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    await update.message.reply_text("Fetching your CV data from Drive…")
    try:
        data = load_cv_data_from_drive()
    except Exception as e:
        await update.message.reply_text(f"⚠️ Could not load CV data: {e}")
        return

    if not data:
        await update.message.reply_text(
            "No CV data stored yet. Use /update_cv_data to save yours."
        )
        return

    text = json.dumps(data, indent=2, ensure_ascii=False)
    for chunk in _split(f"Your stored CV data:\n\n```json\n{text}\n```", 4096):
        await update.message.reply_text(chunk, parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_tailor(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    tg_user_id = update.effective_user.id

    # Support inline usage: /tailor <job description or URL>
    inline = " ".join(ctx.args) if ctx.args else ""
    if inline:
        await _run_tailor(tg_user_id, inline, update, ctx.bot)
    else:
        _conv_state[tg_user_id] = ConvState.WAITING_JOB_DESC
        await update.message.reply_text(
            "Paste the job description or a job URL (Indeed / LinkedIn) and I'll "
            "tailor your CV, upload it to Drive, and log the application to Sheets."
        )


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
    text = msg.text or msg.caption or ""

    # ------------------------------------------------------------------
    # State machine: handle responses to multi-step commands
    # ------------------------------------------------------------------
    state = _conv_state.get(tg_user_id, ConvState.NORMAL)

    if state == ConvState.WAITING_CV_DATA:
        _conv_state[tg_user_id] = ConvState.NORMAL
        if not text:
            await update.message.reply_text("Please send your CV data as text or JSON.")
            return
        # Try to parse as JSON; fall back to raw text storage
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {"raw": text}
        try:
            url = save_cv_data_to_drive(data)
            await update.message.reply_text(
                f"CV data saved to Drive ✅\n{url}"
            )
        except Exception as e:
            await update.message.reply_text(f"⚠️ Could not save CV data: {e}")
        return

    if state == ConvState.WAITING_JOB_DESC:
        _conv_state[tg_user_id] = ConvState.NORMAL
        if not text:
            await update.message.reply_text(
                "Please send the job description as text."
            )
            return
        await _run_tailor(tg_user_id, text, update, ctx.bot)
        return

    # ------------------------------------------------------------------
    # Normal flow — collect parts and send to root_agent via batch buffer
    # ------------------------------------------------------------------
    parts: list[types.Part] = []

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

    # --- Batch buffering ---
    if tg_user_id not in _batch_parts:
        _batch_parts[tg_user_id] = []
    _batch_parts[tg_user_id].extend(parts)
    _batch_update[tg_user_id] = update

    existing = _batch_tasks.get(tg_user_id)
    if existing and not existing.done():
        existing.cancel()

    loop = asyncio.get_event_loop()
    _batch_tasks[tg_user_id] = loop.create_task(
        _delayed_flush(tg_user_id, update.effective_chat.id, ctx.bot)
    )


async def _delayed_flush(tg_user_id: int, chat_id: int, bot) -> None:
    """Wait for the batch window, then flush."""
    await asyncio.sleep(BATCH_WINDOW_SECS)
    await _flush_batch(tg_user_id, chat_id, bot)


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

    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands([
            BotCommand("start", "Show welcome message"),
            BotCommand("update_cv_data", "Update your personal CV data"),
            BotCommand("read_cv_data", "View your stored CV data"),
            BotCommand("tailor", "Tailor CV for a job and upload to Drive"),
            BotCommand("reset", "Reset session and start fresh 🔄"),
        ])

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("update_cv_data", cmd_update_cv_data))
    app.add_handler(CommandHandler("read_cv_data", cmd_read_cv_data))
    app.add_handler(CommandHandler("tailor", cmd_tailor))
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
