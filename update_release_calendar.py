"""
Build and maintain the release calendar from the Fed's calendar JSON.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

CALENDAR_URL = "https://www.federalreserve.gov/json/calendar.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/100.0.4896.127 Safari/537.36"
}
OUTPUT_DATES = Path("release_calendar.txt")


def fetch_calendar():
    response = requests.get(CALENDAR_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return json.loads(response.content.decode("utf-8-sig"))


def get_run_dates(data):
    """Return T+1 run dates for each FOMC Meeting and FOMC Minutes event."""
    run_dates = []

    for event in data.get("events") or []:
        if (event.get("title") or "").strip() not in ("FOMC Meeting", "FOMC Minutes"):
            continue
        month_str = event.get("month") or ""
        days_str = event.get("days")
        if not month_str or days_str is None:
            continue
        try:
            year, month = map(int, month_str.strip().split("-"))
        except (ValueError, AttributeError):
            continue

        # Days may be single or comma-separated (two-day meeting); use last day
        parts = [p.strip() for p in str(days_str).split(",")]
        days = []
        for p in parts:
            try:
                days.append(int(p))
            except ValueError:
                pass
        if not days:
            continue
        day = max(days)
        try:
            release = datetime(year, month, day).date()
        except ValueError:
            continue
        run_dates.append(release + timedelta(days=1))
    return sorted(set(run_dates), reverse=True)


def main():
    data = fetch_calendar()
    run_dates = get_run_dates(data)
    today = datetime.now(timezone.utc).date()

    with open(OUTPUT_DATES, "w", encoding="utf-8") as f:
        f.write(
            f"# Source: {CALENDAR_URL}\n"
            f"# Updated: {today.isoformat()}\n"
        )
        for d in run_dates:
            f.write(d.isoformat() + "\n")

    print(f"Wrote {len(run_dates)} T+1 run dates to {OUTPUT_DATES}")


if __name__ == "__main__":
    main()
