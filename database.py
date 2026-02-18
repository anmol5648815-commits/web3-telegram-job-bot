"""SQLite database layer for job deduplication and retention management."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Generator, Iterable

LOGGER = logging.getLogger(__name__)

DEFAULT_DB_PATH = "jobs.db"
MAX_JOB_ROWS = 50_000
RETENTION_RESET_DAYS = 7
DB_RETRY_ATTEMPTS = 3
DB_RETRY_DELAY_SECONDS = 0.5


class DatabaseError(RuntimeError):
    """Raised when a database operation fails after retries."""


@dataclass(frozen=True)
class JobRecord:
    """Normalized job record used for persistence and deduplication."""

    title: str
    company: str
    location: str
    salary: str
    url: str
    category_tag: str
    source: str
    posted_at: str | None = None


class JobDatabase:
    """SQLite wrapper for creating schema, deduplicating, and storing jobs."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield a SQLite connection with pragmatic defaults and retries."""

        last_error: sqlite3.Error | None = None

        for attempt in range(1, DB_RETRY_ATTEMPTS + 1):
            try:
                connection = sqlite3.connect(self.db_path)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA journal_mode=WAL;")
                connection.execute("PRAGMA foreign_keys=ON;")
                connection.execute("PRAGMA synchronous=NORMAL;")
                yield connection
                connection.commit()
                connection.close()
                return
            except sqlite3.Error as exc:  # pragma: no cover - defensive runtime fallback
                last_error = exc
                LOGGER.warning(
                    "Database connection attempt %s/%s failed: %s",
                    attempt,
                    DB_RETRY_ATTEMPTS,
                    exc,
                )
                time.sleep(DB_RETRY_DELAY_SECONDS)

        raise DatabaseError(f"Unable to connect to SQLite database: {last_error}")

    def initialize(self) -> None:
        """Create required tables and indexes if they do not exist."""

        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_hash TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT NOT NULL,
                    salary TEXT NOT NULL,
                    url TEXT NOT NULL,
                    category_tag TEXT NOT NULL,
                    source TEXT NOT NULL,
                    posted_at TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_created_at
                ON jobs(created_at);
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_source
                ON jobs(source);
                """
            )

            now_iso = datetime.now(UTC).isoformat()
            conn.execute(
                """
                INSERT INTO meta (key, value)
                VALUES ('last_reset_at', ?)
                ON CONFLICT(key) DO NOTHING;
                """,
                (now_iso,),
            )

    def make_job_hash(self, company: str, title: str, url: str) -> str:
        """Build a stable hash from company + title + url for deduplication."""

        normalized = "|".join(
            [company.strip().lower(), title.strip().lower(), url.strip().lower()]
        )
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def has_job(self, job_hash: str) -> bool:
        """Return True if the given job hash already exists."""

        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM jobs WHERE job_hash = ? LIMIT 1;", (job_hash,)
            ).fetchone()
            return row is not None

    def insert_job(self, job: JobRecord) -> bool:
        """Insert a job if unique. Returns True if inserted, False if duplicate."""

        job_hash = self.make_job_hash(job.company, job.title, job.url)
        created_at = datetime.now(UTC).isoformat()

        with self.connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        job_hash,
                        title,
                        company,
                        location,
                        salary,
                        url,
                        category_tag,
                        source,
                        posted_at,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        job_hash,
                        job.title,
                        job.company,
                        job.location,
                        job.salary,
                        job.url,
                        job.category_tag,
                        job.source,
                        job.posted_at,
                        created_at,
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def insert_many_unique(self, jobs: Iterable[JobRecord]) -> list[JobRecord]:
        """Insert many jobs, returning only those that were newly stored."""

        inserted_jobs: list[JobRecord] = []
        for job in jobs:
            if self.insert_job(job):
                inserted_jobs.append(job)
        return inserted_jobs

    def get_total_jobs(self) -> int:
        """Get total number of rows in the jobs table."""

        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM jobs;").fetchone()
            return int(row["count"])

    def _get_last_reset_at(self) -> datetime:
        """Read last reset timestamp from meta table."""

        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'last_reset_at' LIMIT 1;"
            ).fetchone()

            if not row:
                now = datetime.now(UTC)
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('last_reset_at', ?);",
                    (now.isoformat(),),
                )
                return now

            return datetime.fromisoformat(row["value"])

    def _set_last_reset_at(self, value: datetime) -> None:
        """Persist the last reset timestamp in meta table."""

        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO meta (key, value)
                VALUES ('last_reset_at', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value;
                """,
                (value.isoformat(),),
            )

    def reset_if_needed(self) -> bool:
        """Reset jobs table weekly if row count exceeds MAX_JOB_ROWS.

        Returns:
            bool: True if reset occurred, otherwise False.
        """

        try:
            total_jobs = self.get_total_jobs()
            if total_jobs <= MAX_JOB_ROWS:
                return False

            last_reset_at = self._get_last_reset_at()
            due_reset_at = last_reset_at + timedelta(days=RETENTION_RESET_DAYS)

            if datetime.now(UTC) < due_reset_at:
                return False

            with self.connect() as conn:
                conn.execute("DELETE FROM jobs;")

            self._set_last_reset_at(datetime.now(UTC))
            LOGGER.info(
                "Database reset executed: row count (%s) exceeded %s and weekly window elapsed.",
                total_jobs,
                MAX_JOB_ROWS,
            )
            return True
        except (DatabaseError, sqlite3.Error, ValueError) as exc:
            LOGGER.exception("Failed during reset_if_needed: %s", exc)
            return False
