"""Tests for scrape.py.

Scoped to the failure modes that plausibly occur here: the Fed changing its
calendar HTML, and the merge logic losing, duplicating, or reordering rows in a
dataset that is published to Kaggle and Hugging Face.
"""

import os
from datetime import date

import pandas as pd
import pytest

import scrape

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "fomc_calendar.html")
REAL_CSV = os.path.join(REPO_ROOT, "communications.csv")

COLUMNS = ["Date", "Release Date", "Type", "Text"]


@pytest.fixture
def panels():
    with open(FIXTURE, "r", encoding="utf-8") as f:
        return scrape.parse_fomc_page(f.read())


@pytest.fixture
def existing():
    """A tiny existing dataset: one statement and its minutes."""
    return pd.DataFrame(
        [
            {
                "Date": "2026-01-28",
                "Release Date": "2026-01-28",
                "Type": "Statement",
                "Text": "January statement.",
            },
            {
                "Date": "2026-01-28",
                "Release Date": "2026-02-18",
                "Type": "Minute",
                "Text": "January minutes.",
            },
        ]
    )


def dates_of(df, comm_type):
    return set(df.loc[df["Type"] == comm_type, "Date"].dt.strftime("%Y-%m-%d"))


def test_parses_calendar_page(panels, monkeypatch):
    """Every field we take off the page, in one pass: meeting dates (including
    a month that spans two calendars, "Oct/Nov"), and the fact that minutes
    carry their own release date rather than the meeting date."""
    monkeypatch.setattr(scrape, "fetch_page", lambda url, headers: "<html></html>")
    monkeypatch.setattr(
        scrape, "parse_communication_page", lambda page, doc_type: f"{doc_type} body"
    )

    # "Oct/Nov 3-4" must resolve to November, not October.
    assert scrape.scrape_meeting_dates(panels, today=date(2000, 1, 1)) == [
        "2026-01-28",
        "2026-09-17",
        "2026-11-04",
    ]

    comms = {c["Type"]: c for c in scrape.scrape_communications(panels, pd.Timestamp("2000-01-01"))}
    assert comms["Statement"]["Date"] == "2026-01-28"
    assert comms["Statement"]["Release Date"] == "2026-01-28"
    assert comms["Minute"]["Date"] == "2026-01-28"
    assert comms["Minute"]["Release Date"] == "2026-02-18"


def test_only_upcoming_meetings_are_scheduled(panels):
    """A meeting today still counts as upcoming; yesterday's does not. Guards
    both the filter existing at all and its boundary."""
    assert scrape.scrape_meeting_dates(panels, today=date(2026, 9, 17)) == [
        "2026-09-17",
        "2026-11-04",
    ]
    assert scrape.scrape_meeting_dates(panels, today=date(2026, 9, 18)) == ["2026-11-04"]


def test_merge_reconciles_scheduled_and_real(existing):
    """Scheduled rows appear for upcoming meetings, vanish once real content
    exists for that date, and the result keeps the published shape: newest
    first, columns in order."""
    new = [
        {
            "Date": "2026-03-18",
            "Release Date": "2026-03-18",
            "Type": "Statement",
            "Text": "March statement.",
        }
    ]
    merged = scrape.merge_communications(new, existing, ["2026-01-28", "2026-09-17"])

    # 2026-01-28 already has content, so only the future meeting stays scheduled.
    assert dates_of(merged, "Scheduled Meeting") == {"2026-09-17"}
    assert dates_of(merged, "Statement") == {"2026-01-28", "2026-03-18"}
    assert dates_of(merged, "Minute") == {"2026-01-28"}
    assert merged["Date"].is_monotonic_decreasing
    assert list(merged.columns) == COLUMNS


def test_rescrape_replaces_rather_than_duplicates(existing):
    """Dedup is keyed on (Date, Type). A re-scraped statement replaces the old
    row instead of adding a second one -- and must not swallow that date's
    minutes along with it."""
    revised = [
        {
            "Date": "2026-01-28",
            "Release Date": "2026-01-28",
            "Type": "Statement",
            "Text": "January statement, revised.",
        }
    ]
    merged = scrape.merge_communications(revised, existing, [])

    statements = merged[merged["Type"] == "Statement"]
    assert len(statements) == 1
    assert statements.iloc[0]["Text"] == "January statement, revised."
    # The minutes for the same date are a different Type and must survive.
    assert len(merged[merged["Type"] == "Minute"]) == 1


def test_real_csv_survives_a_no_op_merge():
    """The guard that matters most: reconciling the real 467-row dataset with
    nothing new must return it intact. Synthetic fixtures cannot model its
    mixed date formats and encoding artifacts."""
    original = pd.read_csv(REAL_CSV)
    merged = scrape.merge_communications([], original, [])

    assert len(merged) == len(original)
    assert merged["Type"].value_counts().to_dict() == original["Type"].value_counts().to_dict()

    def content(df):
        d = df.copy()
        d["Date"] = pd.to_datetime(d["Date"]).dt.strftime("%Y-%m-%d")
        return set(zip(d["Date"], d["Type"], d["Text"].fillna("")))

    assert content(merged) == content(original)


def test_watermark_tracks_communications_not_schedule(tmp_path, monkeypatch):
    """The watermark drives which pages get fetched next run. It must advance
    on a new communication and hold still on a schedule-only run."""
    monkeypatch.chdir(tmp_path)
    pd.DataFrame(
        [
            {
                "Date": "2026-01-28",
                "Release Date": "2026-01-28",
                "Type": "Statement",
                "Text": "January statement.",
            }
        ]
    ).to_csv("communications.csv", index=False)
    watermark = tmp_path / "most-recent-communication-date.txt"
    watermark.write_text("2026-01-28")

    scrape.update_communications(
        [
            {
                "Date": "2026-03-18",
                "Release Date": "2026-03-18",
                "Type": "Statement",
                "Text": "March statement.",
            }
        ],
        ["2026-09-17"],
    )

    written = pd.read_csv("communications.csv")
    assert "2026-03-18" in set(written["Date"].astype(str))
    assert "Scheduled Meeting" in set(written["Type"])
    assert watermark.read_text() == "2026-03-18"

    # A run that only refreshes the schedule must not move the watermark.
    scrape.update_communications([], ["2026-09-17", "2026-10-28"])
    assert watermark.read_text() == "2026-03-18"


def test_main_reconciles_on_every_run(monkeypatch):
    """The Fed's schedule shifts independently of statements, so main() must
    reconcile even when nothing new was scraped. The old code returned early
    here, which would freeze the scheduled rows."""
    calls = []
    monkeypatch.setattr(scrape, "read_most_recent_date", lambda path: pd.Timestamp("2026-01-01"))
    monkeypatch.setattr(scrape, "fetch_page", lambda url, headers: "<html></html>")
    monkeypatch.setattr(scrape, "parse_fomc_page", lambda html: [])
    monkeypatch.setattr(scrape, "scrape_communications", lambda panels, date: [])
    monkeypatch.setattr(scrape, "scrape_meeting_dates", lambda panels: ["2026-09-17"])
    monkeypatch.setattr(
        scrape, "update_communications", lambda comms, dates: calls.append((comms, dates))
    )

    scrape.main()

    assert calls == [([], ["2026-09-17"])]
