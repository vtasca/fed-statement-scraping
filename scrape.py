import re

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dateutil import parser


def tag_has_statement(tag):
    return tag.name == "div" and "Statement:" in tag.text


def tag_has_minutes(tag):
    return tag.name == "div" and "Minutes:" in tag.text


def format_date(date):
    return date.strftime("%Y-%m-%d")


def scrape_page(url, headers, doc_type):
    response = requests.get(url, headers=headers)
    if response.ok:
        doc = BeautifulSoup(response.text, features="html5lib")
        if doc_type == "Statement":
            comm_text = doc.find("div", id="article").find_all("div")[2].text.strip()
        else:
            comm_text = doc.find("div", id="article").text.strip()
        return comm_text


# Only interested in content that's newer than the most_recent_date
with open("most-recent-communication-date.txt", "r", encoding="utf-8") as f:
    most_recent_date_string = f.read()
    most_recent_date = parser.parse(most_recent_date_string)

# Request the FOMC Calendars website
BASE_URL = "https://www.federalreserve.gov"
MONETARY_POLICY_URL = "/monetarypolicy/fomccalendars.htm"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/100.0.4896.127 Safari/537.36"
}
response = requests.get(BASE_URL + MONETARY_POLICY_URL, headers=HEADERS)

# Parse the raw HTML into usable components
doc = BeautifulSoup(response.text, features="html5lib")
panels = doc.find_all("div", {"class": "panel panel-default"})
new_comms = []

for panel in panels:
    panel_title = panel.find("div", {"class": "panel-heading"}).text
    numbers_in_title = re.findall(r"\d+", panel_title)
    year = numbers_in_title[-1]

    rows = panel.select('div[class*="row fomc-meeting"]')
    for row in rows:
        # Assemble the year, month and date into a meeting timestamp
        month_text = row.find("div", {"class": "fomc-meeting__month"}).text
        if "/" in month_text:
            month = month_text.split("/")[-1]
        else:
            month = month_text
        date_text = row.find("div", {"class": "fomc-meeting__date"}).text
        numbers_in_date = re.findall(r"\d+", date_text)
        date = numbers_in_date[-1]
        meeting_timestamp = parser.parse(" ".join([year, month, date]))

        # Check if that meeting has a statement or minutes to scrape
        statement_div = row.find(tag_has_statement)
        if statement_div and meeting_timestamp > most_recent_date:
            all_statement_links = statement_div.find_all("a")
            if all_statement_links:
                html_statement_link = [
                    link for link in all_statement_links if link.text == "HTML"
                ][0]
                statement_url = BASE_URL + html_statement_link.get("href")
                communication = scrape_page(statement_url, HEADERS, "Statement")
                # Now scrape that link
                new_comms.append(
                    {
                        "Date": format_date(meeting_timestamp),
                        "Release Date": format_date(meeting_timestamp),
                        "Type": "Statement",
                        "Text": communication,
                    }
                )

        minutes_div = row.find(tag_has_minutes)
        if minutes_div:
            all_minutes_links = minutes_div.find_all("a")
            if all_minutes_links:
                html_minute_link = [
                    link for link in all_minutes_links if link.text == "HTML"
                ][0]
                minute_url = BASE_URL + html_minute_link.get("href")
                # Since meetings are released after the meeting, let's get their release date
                minutes_texts = [x.strip() for x in minutes_div.text.split("\n")]
                minutes_date = [x for x in minutes_texts if x.startswith("(Released")][
                    0
                ]
                minutes_date = minutes_date.split("(Released")[-1].replace(")", "")
                minutes_timestamp = parser.parse(minutes_date)

                if minutes_timestamp > most_recent_date:
                    communication = scrape_page(minute_url, HEADERS, "Minute")

                    new_comms.append(
                        {
                            "Date": format_date(meeting_timestamp),
                            "Release Date": format_date(minutes_timestamp),
                            "Type": "Minute",
                            "Text": communication,
                        }
                    )

# Armed with new data, overwrite the existing .csv
new_comms_df = pd.DataFrame(new_comms)

communications = pd.read_csv("communications.csv")

communications = (
    pd.concat([new_comms_df, communications])
    .assign(Date=lambda df: pd.to_datetime(df["Date"]))
    .assign(ReleaseDate=lambda df: pd.to_datetime(df["Release Date"], format="mixed"))
    .drop(columns=["Release Date"])
    .rename(columns={"ReleaseDate": "Release Date"})
    .sort_values("Date", ascending=False)
    .drop_duplicates()
    .reset_index(drop=True)[["Date", "Release Date", "Type", "Text"]]
)

communications.to_csv("communications.csv", index=False)

# And overwrite most recent communication date
if new_comms_df.empty == False:
    with open("most-recent-communication-date.txt", "w", encoding="utf-8") as f:
        f.write(new_comms_df["Release Date"].max())
