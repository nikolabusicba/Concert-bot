import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ---------- Configuration ----------
load_dotenv()  # reads the .env file next to the script
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

PROGRAM_URL = "https://www.daswerk.org/program"
VENUE = "Das Werk"
CHECK_INTERVAL_SECONDS = 30 * 60   # check every 30 minutes
SEND_ON_FIRST_RUN = True           # False = silently remember current events
STATE_FILE = Path(__file__).with_name("seen_events.json")

# Matches date labels like "SA. 21.11. // 23:00"
DATE_RE = re.compile(r"^[A-Za-zÄÖÜäöü]{2}\.\s*(\d{1,2})\.(\d{1,2})\.\s*//\s*(\d{1,2}:\d{2})$")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ---------- 1. Scraping ----------
def get_soup():
    """Download the program page and return it as a parsed HTML tree."""
    response = requests.get(
        PROGRAM_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; WerkBot/1.0)"},
        timeout=20,
    )
    response.raise_for_status()
    response.encoding = "utf-8"  # makes sure "Ä" in TÄRA is read correctly
    return BeautifulSoup(response.text, "html.parser")


def parse_events(soup):
    """Each event card has a <p> with the date label, followed by a <p> with the title."""
    events = []
    for p in soup.find_all("p"):
        match = DATE_RE.match(p.get_text(strip=True))
        if not match:
            continue
        title_tag = p.find_next_sibling("p")  # the title is the next <p> in the same card
        if title_tag is None:
            continue
        day, month, clock = match.groups()
        events.append({
            "title": title_tag.get_text(strip=True),
            "date": f"{int(day):02d}.{int(month):02d} {clock}",
        })
    return events


# ---------- 2. Remembering what was already sent ----------
def event_key(event):
    return f"{event['date']}|{event['title']}"


def load_seen():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    return None  # None means "first run"


def save_seen(seen):
    STATE_FILE.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------- 3. Telegram ----------
def format_message(event):
    return (
        "🎵 DAS WERK EVENT\n\n"
        f"Event: {VENUE}\n"
        f"Title: {event['title']}\n"
        f"Date: {event['date']}"
    )


def send_telegram(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=20)
    if not response.ok:
        raise RuntimeError(f"Telegram error {response.status_code}: {response.text}")


# ---------- 4. Main logic ----------
def check_once():
    events = parse_events(get_soup())
    logging.info("Found %d events on the page", len(events))
    if not events:
        logging.warning("No events parsed. Run with --debug to inspect.")
        return

    seen = load_seen()
    first_run = seen is None
    seen = seen or set()

    new_events = [e for e in events if event_key(e) not in seen]
    should_send = SEND_ON_FIRST_RUN or not first_run

    for event in new_events:
        if should_send:
            send_telegram(format_message(event))
            logging.info("Sent: %s (%s)", event["title"], event["date"])
            time.sleep(1)  # stay well below Telegram's rate limits
        seen.add(event_key(event))

    save_seen(seen)
    logging.info("%d new event(s)", len(new_events))


def main():
    if "--debug" in sys.argv:
        for e in parse_events(get_soup()):
            print(e)
        return

    while True:
        try:
            check_once()
        except Exception:
            logging.exception("Check failed, will retry next round")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
