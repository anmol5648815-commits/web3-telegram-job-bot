"""
Production-grade scrapers for Web3 job sources.

Sources:
1) CryptoJobsList
2) Web3.career (HTML fallback)
3) Remote3
4) Solana Jobs

Improvements:
- follow_redirects=True
- Browser-like headers
- Structured logging
- Safer JSON handling
- Per-source health visibility
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15.0

CRYPTOJOBSLIST_URL = "https://cryptojobslist.com/jobs-json"
WEB3_CAREER_URL = "https://web3.career"
REMOTE3_URL = "https://www.remote3.co/web3-jobs"
SOLANA_JOBS_URL = "https://jobs.solana.com"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


# ---------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------

def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _category_tag_from_text(title: str, company: str, source: str) -> str:
    blob = f"{title} {company} {source}".lower()
    if any(token in blob for token in ("solidity", "smart contract", "evm")):
        return "solidity"
    if any(token in blob for token in ("rust", "solana", "anchor")):
        return "solana"
    if any(token in blob for token in ("frontend", "react", "typescript")):
        return "frontend"
    if any(token in blob for token in ("python", "backend", "infra", "devops")):
        return "backend"
    if any(token in blob for token in ("marketing", "growth", "community")):
        return "marketing"
    return "general"


def _normalize_job(
    *,
    title: str,
    company: str,
    location: str,
    salary: str,
    url: str,
    source: str,
    posted_at: str | None = None,
) -> dict[str, str | None]:

    clean_title = _safe_str(title, "Untitled role")
    clean_company = _safe_str(company, "Unknown company")
    clean_location = _safe_str(location, "Remote")
    clean_salary = _safe_str(salary, "Not disclosed")
    clean_url = _safe_str(url)

    return {
        "title": clean_title,
        "company": clean_company,
        "location": clean_location,
        "salary": clean_salary,
        "url": clean_url,
        "category_tag": _category_tag_from_text(clean_title, clean_company, source),
        "source": source,
        "posted_at": _safe_str(posted_at) if posted_at else None,
    }


def _fetch(url: str) -> httpx.Response | None:
    try:
        with httpx.Client(
            timeout=TIMEOUT_SECONDS,
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            LOGGER.info("Fetched %s bytes from %s", len(response.content), response.url)
            return response
    except Exception as exc:
        LOGGER.exception("Fetch failed for %s: %s", url, exc)
        return None


# ---------------------------------------------------------
# Scrapers
# ---------------------------------------------------------

def scrape_cryptojobslist() -> list[dict[str, str | None]]:
    try:
        response = _fetch(CRYPTOJOBSLIST_URL)
        if not response:
            return []

        payload = response.json()

        if isinstance(payload, dict):
            LOGGER.info("CryptoJobsList JSON keys: %s", payload.keys())
            records = payload.get("jobs") or payload.get("data") or []
        else:
            records = payload

        jobs = []

        for item in records:
            if not isinstance(item, dict):
                continue

            raw_url = (
                item.get("url")
                or item.get("jobUrl")
                or item.get("slug")
            )

            job_url = _safe_str(raw_url)
            if job_url and not job_url.startswith("http"):
                job_url = urljoin("https://cryptojobslist.com/", job_url)

            jobs.append(
                _normalize_job(
                    title=item.get("title") or item.get("jobTitle"),
                    company=item.get("company") or item.get("companyName"),
                    location=item.get("location"),
                    salary=item.get("salary") or item.get("salaryRange"),
                    url=job_url,
                    source="cryptojobslist",
                    posted_at=item.get("publishedAt") or item.get("date"),
                )
            )

        return [job for job in jobs if job["url"]]
    except Exception as exc:
        LOGGER.exception("scrape_cryptojobslist failed: %s", exc)
        return []


def scrape_web3_career() -> list[dict[str, str | None]]:
    try:
        response = _fetch(WEB3_CAREER_URL)
        if not response:
            return []

        html = response.text
        soup = BeautifulSoup(html, "html.parser")

        jobs = []
        job_links = soup.select("a[href*='/job']")

        seen = set()

        for link in job_links:
            href = _safe_str(link.get("href"))
            job_url = urljoin(WEB3_CAREER_URL, href)

            if not job_url or job_url in seen:
                continue
            seen.add(job_url)

            title = _safe_str(link.get_text(" ", strip=True))

            jobs.append(
                _normalize_job(
                    title=title,
                    company="Unknown company",
                    location="Remote",
                    salary="Not disclosed",
                    url=job_url,
                    source="web3career",
                )
            )

        return jobs
    except Exception as exc:
        LOGGER.exception("scrape_web3_career failed: %s", exc)
        return []


def scrape_remote3() -> list[dict[str, str | None]]:
    try:
        response = _fetch(REMOTE3_URL)
        if not response:
            return []

        soup = BeautifulSoup(response.text, "html.parser")

        jobs = []
        links = soup.select("a[href*='/job']")

        seen = set()

        for link in links:
            href = _safe_str(link.get("href"))
            job_url = urljoin(REMOTE3_URL, href)

            if not job_url or job_url in seen:
                continue
            seen.add(job_url)

            title = _safe_str(link.get_text(" ", strip=True))

            jobs.append(
                _normalize_job(
                    title=title,
                    company="Unknown company",
                    location="Remote",
                    salary="Not disclosed",
                    url=job_url,
                    source="remote3",
                )
            )

        return jobs
    except Exception as exc:
        LOGGER.exception("scrape_remote3 failed: %s", exc)
        return []


def scrape_solana_jobs() -> list[dict[str, str | None]]:
    try:
        response = _fetch(SOLANA_JOBS_URL)
        if not response:
            return []

        soup = BeautifulSoup(response.text, "html.parser")

        jobs = []
        links = soup.select("a[href*='job']")

        seen = set()

        for link in links:
            href = _safe_str(link.get("href"))
            job_url = urljoin(SOLANA_JOBS_URL, href)

            if not job_url or job_url in seen:
                continue
            seen.add(job_url)

            title = _safe_str(link.get_text(" ", strip=True))

            jobs.append(
                _normalize_job(
                    title=title,
                    company="Unknown company",
                    location="Remote",
                    salary="Not disclosed",
                    url=job_url,
                    source="solana",
                )
            )

        return jobs
    except Exception as exc:
        LOGGER.exception("scrape_solana_jobs failed: %s", exc)
        return []


# ---------------------------------------------------------
# Aggregator
# ---------------------------------------------------------

def scrape_all_jobs() -> list[dict[str, str | None]]:
    jobs: list[dict[str, str | None]] = []

    for name, fn in [
        ("cryptojobslist", scrape_cryptojobslist),
        ("web3career", scrape_web3_career),
        ("remote3", scrape_remote3),
        ("solana", scrape_solana_jobs),
    ]:
        try:
            source_jobs = fn()
            LOGGER.info("Source %s returned %d jobs", name, len(source_jobs))
            jobs.extend(source_jobs)
        except Exception as exc:
            LOGGER.exception("Source %s crashed: %s", name, exc)

    LOGGER.info("Total jobs before dedupe: %d", len(jobs))
    return jobs
