"""One-off backfill for the 29 minutes rows that had no Release Date.

All 29 are unscheduled meetings / conference calls. The Fed does not publish
their minutes separately -- they are appended to the next regular meeting's
minutes document, so the Fed's calendar page shows no "(Released ...)" text for
them and the scraper had nothing to record. The Fed states this explicitly on
its 2020 page for the March 2 meeting:

    "Minutes: See end of minutes of March 15 meeting"

The correct Release Date is therefore that of the document the row actually
carries. Because the scraper stored the full text of that shared document on
both rows, the date can be recovered from the identical-text twin that does
have one. 27 of 29 resolve that way, each with exactly one twin.

The remaining two (2020-03-03, 2020-03-15) share text with each other and have
no dated twin; their document is fomcminutes20200315.htm, which the Fed's
historical page lists as "Minutes (Released April 08, 2020)".

Every derived date was cross-checked against
https://www.federalreserve.gov/monetarypolicy/fomchistorical<year>.htm
"""

import pandas as pd

CSV = "communications.csv"

# Rows whose text has no dated twin, resolved directly from the Fed's page.
EXPLICIT = {
    "2020-03-03": "2020-04-08",
    "2020-03-15": "2020-04-08",
}


def derive_backfill(df):
    """Return {index: release_date} for every row missing a Release Date."""
    missing = df["Release Date"].isna()
    minutes = df[df["Type"] == "Minute"]
    filled, unresolved = {}, []

    for idx, row in df[missing].iterrows():
        twins = minutes[(minutes["Text"] == row["Text"]) & minutes["Release Date"].notna()]
        dates = sorted(set(twins["Release Date"]))
        if len(dates) == 1:
            filled[idx] = dates[0]
        elif row["Date"] in EXPLICIT:
            filled[idx] = EXPLICIT[row["Date"]]
        else:
            unresolved.append((idx, row["Date"], dates))

    return filled, unresolved


def main():
    df = pd.read_csv(CSV)
    before_missing = int(df["Release Date"].isna().sum())
    before_rows = len(df)

    filled, unresolved = derive_backfill(df)
    if unresolved:
        raise SystemExit(f"unresolved rows, refusing to write: {unresolved}")

    for idx, release_date in filled.items():
        df.at[idx, "Release Date"] = release_date

    # A minutes release can never precede its meeting.
    check = df[df["Type"] == "Minute"].copy()
    bad = check[pd.to_datetime(check["Release Date"]) < pd.to_datetime(check["Date"])]
    if not bad.empty:
        raise SystemExit(f"release date precedes meeting date:\n{bad[['Date', 'Release Date']]}")

    assert len(df) == before_rows, "row count changed"
    assert df["Release Date"].isna().sum() == 0, "still missing release dates"

    df.to_csv(CSV, index=False)
    print(f"filled {len(filled)} of {before_missing} missing release dates; {len(df)} rows intact")


if __name__ == "__main__":
    main()
