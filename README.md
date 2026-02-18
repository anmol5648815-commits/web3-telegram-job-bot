# Web3 Telegram Job Bot

Automated Python bot that scrapes Web3/crypto jobs every 2 hours, deduplicates listings with SQLite, and posts new jobs to a Telegram channel.

## Features

- Scrapes these sources:
  - `https://cryptojobslist.com/jobs.json`
  - `https://web3.career/api/jobs`
  - `https://remote3.co/web3-jobs`
  - `https://solana.com/jobs`
- Deduplicates jobs using SHA-256 hash of `(company + title + url)`.
- Stores seen jobs in SQLite (`jobs.db`).
- Weekly database reset when rows exceed `50,000`.
- Telegram posting limits:
  - Max `5` messages per batch.
  - `3` second delay between posts.
- Runs immediate cycle on startup, then schedules recurring runs with APScheduler.

## Tech Stack

- Python 3.11+
- `httpx` + `BeautifulSoup4` for scraping
- `APScheduler` (`AsyncIOScheduler`) for scheduling
- SQLite for persistence
- `python-telegram-bot` (async, v20+ compatible API)
- `python-dotenv` for environment configuration

## Project Files

- `main.py` — app entrypoint, scheduler, cycle orchestration.
- `config.py` — environment loader and validation.
- `scraper.py` — source scrapers and unified collection.
- `database.py` — SQLite schema, deduplication, and prune/reset logic.
- `telegram_poster.py` — message formatting and Telegram posting.
- `.env.example` — environment variable template.
- `web3jobbot.service` — systemd service for Ubuntu VPS.

## Message Format

```text
💼 [Job Title]
🏢 Company: [Company]
🌍 Location: [Remote / City]
💰 Salary: [Range or 'Not disclosed']
🔗 Apply: [URL]

#web3jobs #crypto #[category_tag]
```

## Local Setup

### 1) Clone and enter project

```bash
git clone <your-repo-url> web3-telegram-job-bot
cd web3-telegram-job-bot
```

### 2) Create Python environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3) Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
TELEGRAM_BOT_TOKEN=<your_bot_token>
TELEGRAM_CHANNEL_ID=<your_channel_id>
JOB_CHECK_INTERVAL_HOURS=2
```

### 4) Run the bot

```bash
python main.py
```

On startup, the bot runs one scrape/dedupe/post cycle immediately and then continues at `JOB_CHECK_INTERVAL_HOURS` interval.

## Ubuntu 22.04 VPS Deployment (systemd)

### 1) Create a dedicated user

```bash
sudo adduser --disabled-password --gecos "" botuser
```

### 2) Copy project and set ownership

```bash
sudo mkdir -p /home/botuser/web3-telegram-job-bot
sudo rsync -av --delete ./ /home/botuser/web3-telegram-job-bot/
sudo chown -R botuser:botuser /home/botuser/web3-telegram-job-bot
```

### 3) Install Python and dependencies

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv
sudo -u botuser bash -lc '
  cd /home/botuser/web3-telegram-job-bot &&
  python3.11 -m venv .venv &&
  source .venv/bin/activate &&
  pip install --upgrade pip &&
  pip install -r requirements.txt
'
```

### 4) Configure environment file

```bash
sudo -u botuser cp /home/botuser/web3-telegram-job-bot/.env.example /home/botuser/web3-telegram-job-bot/.env
sudo -u botuser nano /home/botuser/web3-telegram-job-bot/.env
```

### 5) Install systemd service

```bash
sudo cp /home/botuser/web3-telegram-job-bot/web3jobbot.service /etc/systemd/system/web3jobbot.service
sudo systemctl daemon-reload
sudo systemctl enable web3jobbot.service
sudo systemctl start web3jobbot.service
```

### 6) Check service status and logs

```bash
sudo systemctl status web3jobbot.service
sudo journalctl -u web3jobbot.service -f
```

## Operations

- Restart service:

```bash
sudo systemctl restart web3jobbot.service
```

- Stop service:

```bash
sudo systemctl stop web3jobbot.service
```

- Start service:

```bash
sudo systemctl start web3jobbot.service
```

## Notes

- Never commit real `.env` values.
- Keep Telegram token/channel ID in environment variables only.
- If job source HTML structures change, update selectors in `scraper.py`.
- SQLite DB file (`jobs.db`) is created automatically in project root.
