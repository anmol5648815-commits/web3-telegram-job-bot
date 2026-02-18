"""Scrapers for Web3 job sources.

This module fetches jobs from:
1) https://cryptojobslist.com/jobs.json
2) https://web3.career/api/jobs
3) https://remote3.co/web3-jobs
4) https://solana.com/jobs

Rules from project spec:
- Use httpx with 10-second timeout.
- Use BeautifulSoup4 for HTML sources.
- Wrap every scraper in try/except and return [] on failure.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0
CRYPTOJOBSLIST_URL = "https://cryptojobslist.com/jobs.json"
WEB3_CAREER_URL = "https://web3.career/api/jobs"
REMOTE3_URL = "https://remote3.co/web3-jobs"
SOLANA_JOBS_URL = "https://solana.com/jobs"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}


def _safe_str(value: Any, default: str = "") -> str:
    """Convert any value to a stripped string with fallback."""
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _category_tag_from_text(title: str, company: str, source: str) -> str:
    """Infer a simple category tag for hashtags."""
    blob = f"{title} {company} {source}".lower()
    if any(token in blob for token in ("solidity", "smart contract", "evm")):
        return "solidity"
    if any(token in blob for token in ("rust", "solana", "anchor")):
        return "solana"
    if any(token in blob for token in ("frontend", "react", "typescript", "ui")):
        return "frontend"
    if any(token in blob for token in ("python", "backend", "api", "infra", "devops")):
        return "backend"
    if any(token in blob for token in ("marketing", "growth", "community", "content")):
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
    """Normalize job fields to a consistent shape."""
    clean_title = _safe_str(title, "Untitled role")
    clean_company = _safe_str(company, "Unknown company")
    clean_location = _safe_str(location, "Remote")
    clean_salary = _safe_str(salary, "Not disclosed")
    clean_url = _safe_str(url)
    category_tag = _category_tag_from_text(clean_title, clean_company, source)

    return {
        "title": clean_title,
        "company": clean_company,
        "location": clean_location,
        "salary": clean_salary,
        "url": clean_url,
        "category_tag": category_tag,
        "source": source,
        "posted_at": _safe_str(posted_at) if posted_at else None,
    }


def scrape_cryptojobslist() -> list[dict[str, str | None]]:
    """Scrape jobs from CryptoJobsList JSON feed."""
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, headers=DEFAULT_HEADERS) as client:
            response = client.get(CRYPTOJOBSLIST_URL)
            response.raise_for_status()
            payload = response.json()

        records = payload if isinstance(payload, list) else payload.get("jobs", [])
        jobs: list[dict[str, str | None]] = []

        for item in records:
            if not isinstance(item, dict):
                continue

            job_url = _safe_str(item.get("url") or item.get("jobUrl") or item.get("slug"))
            if job_url and not job_url.startswith("http"):
                job_url = urljoin("https://cryptojobslist.com/", job_url)

            jobs.append(
                _normalize_job(
                    title=_safe_str(item.get("title") or item.get("jobTitle")),
                    company=_safe_str(item.get("company") or item.get("companyName")),
                    location=_safe_str(item.get("location"), "Remote"),
                    salary=_safe_str(
                        item.get("salary")
                        or item.get("salaryRange")
                        or item.get("compensation"),
                        "Not disclosed",
                    ),
                    url=job_url,
                    source="cryptojobslist",
                    posted_at=_safe_str(item.get("publishedAt") or item.get("date")),
                )
            )

        return [job for job in jobs if job["url"]]
    except Exception as exc:
        LOGGER.exception("scrape_cryptojobslist failed: %s", exc)
        return []


def scrape_web3_career() -> list[dict[str, str | None]]:
    """Scrape jobs from web3.career API."""
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, headers=DEFAULT_HEADERS) as client:
            response = client.get(WEB3_CAREER_URL)
            response.raise_for_status()
            payload = response.json()

        records = payload if isinstance(payload, list) else payload.get("jobs", [])
        jobs: list[dict[str, str | None]] = []

        for item in records:
            if not isinstance(item, dict):
                continue

            raw_url = _safe_str(
                item.get("url")
                or item.get("job_url")
                or item.get("jobUrl")
                or item.get("slug")
            )
            job_url = urljoin("https://web3.career/", raw_url) if raw_url else ""

            jobs.append(
                _normalize_job(
                    title=_safe_str(item.get("title") or item.get("job_title")),
                    company=_safe_str(item.get("company") or item.get("company_name")),
                    location=_safe_str(item.get("location"), "Remote"),
                    salary=_safe_str(
                        item.get("salary") or item.get("salary_range"),
                        "Not disclosed",
                    ),
                    url=job_url,
                    source="web3career",
                    posted_at=_safe_str(item.get("published_at") or item.get("created_at")),
                )
            )

        return [job for job in jobs if job["url"]]
    except Exception as exc:
        LOGGER.exception("scrape_web3_career failed: %s", exc)
        return []


def scrape_remote3() -> list[dict[str, str | None]]:
    """Scrape jobs from Remote3 HTML page with BeautifulSoup."""
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, headers=DEFAULT_HEADERS) as client:
            response = client.get(REMOTE3_URL)
            response.raise_for_status()
            html = response.text

        soup = BeautifulSoup(html, "html.parser")
        jobs: list[dict[str, str | None]] = []

        job_links = soup.select("a[href*='/job']") or soup.select("a[href*='jobs']")
        seen_urls: set[str] = set()

        for link in job_links:
            href = _safe_str(link.get("href"))
            job_url = urljoin(REMOTE3_URL, href) if href else ""
            if not job_url or job_url in seen_urls:
                continue
            seen_urls.add(job_url)

            title = _safe_str(link.get_text(" ", strip=True), "Untitled role")
            card = link.find_parent(["article", "li", "div"]) or link

            company_node = card.select_one("[class*='company'], [data-company]")
            location_node = card.select_one("[class*='location'], [data-location]")
            salary_node = card.select_one("[class*='salary'], [data-salary]")

            jobs.append(
                _normalize_job(
                    title=title,
                    company=_safe_str(
                        company_node.get_text(" ", strip=True) if company_node else "Unknown company"
                    ),
                    location=_safe_str(
                        location_node.get_text(" ", strip=True) if location_node else "Remote"
                    ),
                    salary=_safe_str(
                        salary_node.get_text(" ", strip=True) if salary_node else "Not disclosed"
                    ),
                    url=job_url,
                    source="remote3",
                )
            )

        return jobs
    except Exception as exc:
        LOGGER.exception("scrape_remote3 failed: %s", exc)
        return []


def scrape_solana_jobs() -> list[dict[str, str | None]]:
    """Scrape jobs from Solana jobs page with BeautifulSoup."""
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, headers=DEFAULT_HEADERS) as client:
            response = client.get(SOLANA_JOBS_URL)
            response.raise_for_status()
            html = response.text

        soup = BeautifulSoup(html, "html.parser")
        jobs: list[dict[str, str | None]] = []

        job_links = soup.select("a[href*='job']") or soup.select("a[href*='jobs']")
        seen_urls: set[str] = set()

        for link in job_links:
            href = _safe_str(link.get("href"))
            job_url = urljoin(SOLANA_JOBS_URL, href) if href else ""
            if not job_url or job_url in seen_urls:
                continue
            seen_urls.add(job_url)

            title = _safe_str(link.get_text(" ", strip=True), "Untitled role")
            card = link.find_parent(["article", "li", "div"]) or link

            company_node = card.select_one("[class*='company']")
            location_node = card.select_one("[class*='location']")
            salary_node = card.select_one("[class*='salary'], [class*='compensation']")

            jobs.append(
                _normalize_job(
                    title=title,
                    company=_safe_str(
                        company_node.get_text(" ", strip=True) if company_node else "Unknown company"
                    ),
                    location=_safe_str(
                        location_node.get_text(" ", strip=True) if location_node else "Remote"
                    ),
                    salary=_safe_str(
                        salary_node.get_text(" ", strip=True) if salary_node else "Not disclosed"
                    ),
                    url=job_url,
                    source="solana",
                )
            )

        return jobs
    except Exception as exc:
        LOGGER.exception("scrape_solana_jobs failed: %s", exc)
        return []


def scrape_all_jobs() -> list[dict[str, str | None]]:
    """Fetch and combine jobs from all configured sources."""
    jobs: list[dict[str, str | None]] = []
    jobs.extend(scrape_cryptojobslist())
    jobs.extend(scrape_web3_career())
    jobs.extend(scrape_remote3())
    jobs.extend(scrape_solana_jobs())
    return jobs
