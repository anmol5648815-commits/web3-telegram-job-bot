"""Async Telegram posting utilities for Web3 job updates."""

from __future__ import annotations

import asyncio
import html
import logging
import os
from typing import Any

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

LOGGER = logging.getLogger(__name__)

MAX_JOBS_PER_BATCH = 5
DELAY_BETWEEN_POSTS_SECONDS = 3


def _safe_text(value: Any, default: str) -> str:
    """Return a clean text value with fallback."""
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def format_message(job_dict: dict[str, Any]) -> str:
    """Format a single job dictionary into the required Telegram message template."""

    title = html.escape(_safe_text(job_dict.get("title"), "Untitled role"))
    company = html.escape(_safe_text(job_dict.get("company"), "Unknown company"))
    location = html.escape(_safe_text(job_dict.get("location"), "Remote"))
    salary = html.escape(_safe_text(job_dict.get("salary"), "Not disclosed"))
    url = html.escape(_safe_text(job_dict.get("url"), ""))
    category_tag = _safe_text(job_dict.get("category_tag"), "general")
    category_tag = "".join(ch for ch in category_tag.lower() if ch.isalnum() or ch == "_")
    category_tag = category_tag or "general"

    return (
        f"💼 <b>{title}</b>\n"
        f"🏢 Company: {company}\n"
        f"🌍 Location: {location}\n"
        f"💰 Salary: {salary}\n"
        f"🔗 Apply: {url}\n\n"
        f"#web3jobs #crypto #{category_tag}"
    )


async def post_jobs(jobs: list[dict[str, Any]]) -> None:
    """Post up to 5 jobs to Telegram with a 3-second delay between messages."""

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()

    if not token or not channel_id:
        LOGGER.error(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID; skipping Telegram post batch."
        )
        return

    if not jobs:
        LOGGER.info("No jobs to post in this batch.")
        return

    bot = Bot(token=token)

    for job in jobs[:MAX_JOBS_PER_BATCH]:
        try:
            message = format_message(job)
            await bot.send_message(
                chat_id=channel_id,
                text=message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False,
            )
            LOGGER.info(
                "Posted job to Telegram: %s at %s",
                _safe_text(job.get("title"), "Untitled role"),
                _safe_text(job.get("url"), "<missing-url>"),
            )
        except TelegramError as exc:
            LOGGER.exception("TelegramError while posting job: %s", exc)
        except Exception as exc:  # pragma: no cover - defensive runtime fallback
            LOGGER.exception("Unexpected error while posting job: %s", exc)

        await asyncio.sleep(DELAY_BETWEEN_POSTS_SECONDS)
