"""Tests for scrape.py.

The most important guarantee here is the *golden round-trip*: feeding the real
committed communications.csv back through the reconciliation logic with no new
data must not lose or mangle a single Statement/Minute row. The rest exercise
the new scheduled-meeting behaviour and the HTML parsing that feeds it.
"""

import os
from datetime import date

import pandas as pd
import pytest

import scrape

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "fomc_calendar.html")
REAL_CSV = os.path.join(REPO_ROOT, "communications.csv")


@pytest.fixture
def panels():
    with open(FIXTURE, "r", encoding="utf-8") as f:
        return scrape.parse_fomc_page(f.read())


@pytest.fixture
def sample_comms():
    """A tiny existing dataset: one statement, one minute."""
    return pd.DataFrame(
        [
            {
                "Date": "2026-01-28",
                "Release Date": "2026-01-28",
                "Type": "Statement",
                "Text": "Existing statement text.",
            },
            {
                "Date": "2026-01-28",
                "Release Date": "2026-02-18",
                "Type": "Minute",
                "Text": "Existing minutes text.",
            },
        ]
    )


def test_scrape_meeting_dates_reads_all_upcoming(panels):
    # With an early "today", every meeting on the page is upcoming.
    dates = scrape.scrape_meeting_dates(panels, today=date(2000, 1, 1))
    assert dates == ["2026-01-28", "2026-09-17", "2026-11-04"]


def test_scrape_meeting_dates_excludes_past(panels):
    # As of mid-2026, the January meeting is in the past and is dropped;
    # a same-day meeting still counts as upcoming (>= today).
    dates = scrape.scrape_meeting_dates(panels, today=date(2026, 9, 17))
    assert dates == ["2026-09-17", "2026-11-04"]


def test_assemble_timestamp_handles_split_month(panels):
    # "Oct/Nov" must resolve to the second month (November).
    rows = panels[0].select('div[class*="row fomc-meeting"]')
    ts = scrape.assemble_meeting_timestamp(rows[2], "2026")
    assert scrape.format_date(ts) == "2026-11-04"


def test_scrape_communications_extracts_statement(panels, monkeypatch):
    # Avoid the network: fetch_page returns a canned document, and the parser
    # returns a fixed string so we assert on wiring, not on Fed HTML internals.
    monkeypatch.setattr(scrape, "fetch_page", lambda url, headers: "<html></html>")
    monkeypatch.setattr(
        scrape, "parse_communication_page", lambda page, doc_type: f"{doc_type} body"
    )
    old = pd.to_datetime("2000-01-01")
    new_comms = scrape.scrape_communications(panels, old)

    by_type = {c["Type"]: c for c in new_comms}
    assert by_type["Statement"]["Date"] == "2026-01-28"
    assert by_type["Statement"]["Release Date"] == "2026-01-28"
    # Minutes carry their own (later) release date.
    assert by_type["Minute"]["Date"] == "2026-01-28"
    assert by_type["Minute"]["Release Date"] == "2026-02-18"


def test_scheduled_meeting_added(sample_comms):
    merged = scrape.merge_communications([], sample_comms, ["2026-09-17"])
    sched = merged[merged["Type"] == "Scheduled Meeting"]
    assert list(sched["Date"].dt.strftime("%Y-%m-%d")) == ["2026-09-17"]


def test_scheduled_meeting_superseded_by_real_content(sample_comms):
    # 2026-01-28 already has a Statement + Minute, so its scheduled row is dropped.
    merged = scrape.merge_communications(
        [], sample_comms, ["2026-01-28", "2026-09-17"]
    )
    scheduled_dates = set(
        merged.loc[merged["Type"] == "Scheduled Meeting", "Date"].dt.strftime(
            "%Y-%m-%d"
        )
    )
    assert scheduled_dates == {"2026-09-17"}
    # And the real rows for the superseded date survive untouched.
    assert len(merged[(merged["Type"] == "Statement")]) == 1
    assert len(merged[(merged["Type"] == "Minute")]) == 1


def test_new_comms_merged_and_sorted(sample_comms):
    new = [
        {
            "Date": "2026-03-18",
            "Release Date": "2026-03-18",
            "Type": "Statement",
            "Text": "March statement.",
        }
    ]
    merged = scrape.merge_communications(new, sample_comms, [])
    assert "2026-03-18" in set(merged["Date"].dt.strftime("%Y-%m-%d"))
    # Sorted by date descending.
    assert merged["Date"].is_monotonic_decreasing


def test_output_columns_are_stable(sample_comms):
    merged = scrape.merge_communications([], sample_comms, ["2026-09-17"])
    assert list(merged.columns) == ["Date", "Release Date", "Type", "Text"]


def test_rescraped_text_replaces_rather_than_duplicates(sample_comms):
    """Dedup is keyed on (Date, Type), not the whole row. If the Fed revises a
    statement — or the parser yields slightly different text — the date must not
    end up with two Statement rows. The newly scraped text wins."""
    revised = [
        {
            "Date": "2026-01-28",
            "Release Date": "2026-01-28",
            "Type": "Statement",
            "Text": "Existing statement text, revised.",
        }
    ]
    merged = scrape.merge_communications(revised, sample_comms, [])

    statements = merged[merged["Type"] == "Statement"]
    assert len(statements) == 1
    assert statements.iloc[0]["Text"] == "Existing statement text, revised."


def test_real_csv_roundtrip_preserves_every_row():
    """No new comms, no meetings -> the reconciled frame must equal the input
    dataset row-for-row (order aside). This is the regression guard against the
    dedup-key change silently dropping data."""
    original = pd.read_csv(REAL_CSV)
    merged = scrape.merge_communications([], original, [])

    # Same number of Statement/Minute rows, nothing invented or lost.
    assert merged["Type"].value_counts().to_dict() == (
        original["Type"].value_counts().to_dict()
    )
    assert len(merged) == len(original)

    # The (Date, Type, Text) content is identical as a set.
    def key(df):
        d = df.copy()
        d["Date"] = pd.to_datetime(d["Date"]).dt.strftime("%Y-%m-%d")
        return set(zip(d["Date"], d["Type"], d["Text"].fillna("")))

    assert key(merged) == key(original)


def test_real_csv_has_no_date_type_collisions():
    """The new dedup key is (Date, Type); assert the historical data never has
    two rows sharing one, so the key can't clobber real content."""
    original = pd.read_csv(REAL_CSV)
    collisions = original.groupby(["Date", "Type"]).size()
    assert collisions.max() == 1


def test_update_communications_writes_and_advances_watermark(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pd.DataFrame(
        [
            {
                "Date": "2026-01-28",
                "Release Date": "2026-01-28",
                "Type": "Statement",
                "Text": "Old.",
            }
        ]
    ).to_csv("communications.csv", index=False)
    (tmp_path / "most-recent-communication-date.txt").write_text("2026-01-28")

    new = [
        {
            "Date": "2026-03-18",
            "Release Date": "2026-03-18",
            "Type": "Statement",
            "Text": "New.",
        }
    ]
    scrape.update_communications(new, ["2026-09-17"])

    out = pd.read_csv("communications.csv")
    assert "2026-03-18" in set(out["Date"].astype(str))
    assert "Scheduled Meeting" in set(out["Type"])
    # Watermark advanced to the newest release date.
    assert (tmp_path / "most-recent-communication-date.txt").read_text() == "2026-03-18"


def test_update_communications_scheduled_only_keeps_watermark(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pd.DataFrame(
        [
            {
                "Date": "2026-01-28",
                "Release Date": "2026-01-28",
                "Type": "Statement",
                "Text": "Old.",
            }
        ]
    ).to_csv("communications.csv", index=False)
    (tmp_path / "most-recent-communication-date.txt").write_text("2026-01-28")

    # Only scheduled meetings, no new communications -> watermark must not move.
    scrape.update_communications([], ["2026-09-17"])

    assert (tmp_path / "most-recent-communication-date.txt").read_text() == "2026-01-28"
    out = pd.read_csv("communications.csv")
    assert "Scheduled Meeting" in set(out["Type"])


def test_main_updates_even_with_no_new_communications(monkeypatch):
    """The schedule shifts independently of statements, so main() must reconcile
    on every run — not only when a new statement or minute was scraped."""
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
