"""Main application entrypoint for the Web3 Telegram Job Bot."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import ConfigError, load_settings
from database import JobDatabase, JobRecord
from scraper import scrape_all_jobs
from telegram_poster import post_jobs

LOGGER = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure INFO-level logging to stdout."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )


def _to_job_record(job_dict: dict[str, Any]) -> JobRecord:
    """Convert a scraped dictionary to a JobRecord."""
    return JobRecord(
        title=str(job_dict.get("title", "Untitled role")).strip() or "Untitled role",
        company=str(job_dict.get("company", "Unknown company")).strip() or "Unknown company",
        location=str(job_dict.get("location", "Remote")).strip() or "Remote",
        salary=str(job_dict.get("salary", "Not disclosed")).strip() or "Not disclosed",
        url=str(job_dict.get("url", "")).strip(),
        category_tag=str(job_dict.get("category_tag", "general")).strip() or "general",
        source=str(job_dict.get("source", "unknown")).strip() or "unknown",
        posted_at=(
            str(job_dict.get("posted_at", "")).strip() if job_dict.get("posted_at") else None
        ),
    )


def filter_new_jobs(db: JobDatabase, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter out duplicate jobs using hash(company + title + url)."""
    new_jobs: list[dict[str, Any]] = []

    for job in jobs:
        url = str(job.get("url", "")).strip()
        if not url:
            continue

        company = str(job.get("company", "")).strip()
        title = str(job.get("title", "")).strip()
        job_hash = db.make_job_hash(company, title, url)

        if not db.has_job(job_hash):
            new_jobs.append(job)

    return new_jobs


def save_new_jobs(db: JobDatabase, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist new jobs and return only successfully inserted jobs."""
    inserted_jobs: list[dict[str, Any]] = []

    for job in jobs:
        record = _to_job_record(job)
        if not record.url:
            continue

        if db.insert_job(record):
            inserted_jobs.append(job)

    return inserted_jobs


def prune_old_jobs(db: JobDatabase) -> None:
    """Prune/reset job storage according to retention rules."""
    did_reset = db.reset_if_needed()
    if did_reset:
        LOGGER.info("Database prune/reset completed.")
    else:
        LOGGER.info("Database prune/reset not required.")


async def run_cycle(db: JobDatabase) -> None:
    """Run one full cycle: scrape -> dedupe -> save -> post -> prune."""
    LOGGER.info("Starting job cycle.")

    all_jobs = await asyncio.to_thread(scrape_all_jobs)
    LOGGER.info("Scraped %s jobs from all sources.", len(all_jobs))

    new_jobs = await asyncio.to_thread(filter_new_jobs, db, all_jobs)
    LOGGER.info("Found %s new jobs after deduplication.", len(new_jobs))

    saved_jobs = await asyncio.to_thread(save_new_jobs, db, new_jobs)
    LOGGER.info("Saved %s new jobs to database.", len(saved_jobs))

    if saved_jobs:
        await post_jobs(saved_jobs)
        LOGGER.info("Posted up to 5 jobs to Telegram (batch limit).")
    else:
        LOGGER.info("No new jobs to post to Telegram.")

    await asyncio.to_thread(prune_old_jobs, db)
    LOGGER.info("Job cycle complete.")


async def run() -> None:
    """Initialize app state, run immediate cycle, and start recurring scheduler."""
    setup_logging()

    try:
        settings = load_settings()
    except ConfigError as exc:
        LOGGER.error("Configuration error: %s", exc)
        return

    db = JobDatabase()
    await asyncio.to_thread(db.initialize)

    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        run_cycle,
        trigger=IntervalTrigger(hours=settings.job_check_interval_hours),
        kwargs={"db": db},
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    await run_cycle(db)

    scheduler.start()
    LOGGER.info(
        "Scheduler started. Running every %s hour(s).",
        settings.job_check_interval_hours,
    )

    stop_event = asyncio.Event()

    try:
        await stop_event.wait()
    finally:
        scheduler.shutdown(wait=False)
        LOGGER.info("Scheduler shut down.")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        LOGGER.info("Received KeyboardInterrupt. Exiting gracefully.")
