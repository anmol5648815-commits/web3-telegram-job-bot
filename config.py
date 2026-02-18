"""Application configuration loader for the Web3 Telegram Job Bot."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings loaded from environment variables."""

    telegram_bot_token: str
    telegram_channel_id: str
    job_check_interval_hours: int = 2


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


def load_settings() -> Settings:
    """Load and validate environment variables into a typed Settings object.

    Required variables:
    - TELEGRAM_BOT_TOKEN
    - TELEGRAM_CHANNEL_ID

    Optional variables:
    - JOB_CHECK_INTERVAL_HOURS (default: 2)
    """

    load_dotenv()

    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_channel_id = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    interval_raw = os.getenv("JOB_CHECK_INTERVAL_HOURS", "2").strip()

    if not telegram_bot_token:
        raise ConfigError("Missing required environment variable: TELEGRAM_BOT_TOKEN")

    if not telegram_channel_id:
        raise ConfigError("Missing required environment variable: TELEGRAM_CHANNEL_ID")

    try:
        job_check_interval_hours = int(interval_raw)
    except ValueError as exc:
        raise ConfigError(
            "JOB_CHECK_INTERVAL_HOURS must be a valid integer (example: 2)"
        ) from exc

    if job_check_interval_hours <= 0:
        raise ConfigError("JOB_CHECK_INTERVAL_HOURS must be greater than 0")

    return Settings(
        telegram_bot_token=telegram_bot_token,
        telegram_channel_id=telegram_channel_id,
        job_check_interval_hours=job_check_interval_hours,
    )
