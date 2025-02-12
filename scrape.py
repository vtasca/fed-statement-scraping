import re
import csv

import pandas as pd
import requests
from bs4 import BeautifulSoup
from dateutil import parser

BASE_URL = "https://www.federalreserve.gov"
MONETARY_POLICY_URL = "/monetarypolicy/fomccalendars.htm"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/100.0.4896.127 Safari/537.36"
}


def tag_has_statement(tag):
    return tag.name == "div" and "Statement:" in tag.text


def tag_has_minutes(tag):
    return tag.name == "div" and "Minutes:" in tag.text


def format_date(date):
    return date.strftime("%Y-%m-%d")


def read_most_recent_date(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        most_recent_date_string = f.read()
        most_recent_date = parser.parse(most_recent_date_string)
        return most_recent_date


def write_most_recent_date(file_path, date):
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(date)


def fetch_page(url, headers):
    response = requests.get(url, headers=headers)
    if response.ok:
        return response.text
    return None


def parse_communication_page(html_content, doc_type):
    doc = BeautifulSoup(html_content, features="html5lib")
    if doc_type == "Statement":
        comm_text = doc.find("div", id="article").find_all("div")[2].text.strip()
    else:
        comm_text = doc.find("div", id="article").text.strip()
    return comm_text


def parse_fomc_page(html_content):
    doc = BeautifulSoup(html_content, features="html5lib")
    panels = doc.find_all("div", {"class": "panel panel-default"})
    return panels


def extract_year_from_panel(panel):
    panel_title = panel.find("div", {"class": "panel-heading"}).text
    numbers_in_title = re.findall(r"\d+", panel_title)
    year = numbers_in_title[-1]
    return year


def assemble_meeting_timestamp(row, year):
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
    return meeting_timestamp


def scrape_communications(panels, most_recent_date):
    new_comms = []
    for panel in panels:
        year = extract_year_from_panel(panel)
        for row in panel.select('div[class*="row fomc-meeting"]'):
            meeting_timestamp = assemble_meeting_timestamp(row, year)
            process_meeting_row(row, meeting_timestamp, most_recent_date, new_comms)
    return new_comms


def process_meeting_row(row, meeting_timestamp, most_recent_date, new_comms):
    statement_div = row.find(tag_has_statement)
    if statement_div and meeting_timestamp > most_recent_date:
        all_statement_links = statement_div.find_all("a")
        if all_statement_links:
            html_statement_link = [
                link for link in all_statement_links if link.text == "HTML"
            ][0]
            statement_url = BASE_URL + html_statement_link.get("href")
            statement_page = fetch_page(statement_url, HEADERS)
            communication = parse_communication_page(statement_page, "Statement")
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
            minutes_date = [x for x in minutes_texts if x.startswith("(Released")][0]
            minutes_date = minutes_date.split("(Released")[-1].replace(")", "")
            minutes_timestamp = parser.parse(minutes_date)

            if minutes_timestamp > most_recent_date:
                minute_page = fetch_page(minute_url, HEADERS)
                communication = parse_communication_page(minute_page, "Minute")

                new_comms.append(
                    {
                        "Date": format_date(meeting_timestamp),
                        "Release Date": format_date(minutes_timestamp),
                        "Type": "Minute",
                        "Text": communication,
                    }
                )


def update_communications(new_comms, meeting_dates):
    new_comms_df = pd.DataFrame(new_comms)
    
    try:
        # Read existing data with flexible datetime parsing
        communications = pd.read_csv("communications.csv")
        communications['Date'] = pd.to_datetime(
            communications['Date'], format='mixed'
        ).dt.date
        communications['Release Date'] = pd.to_datetime(
            communications['Release Date'], format='mixed'
        ).dt.date
    except FileNotFoundError:
        communications = pd.DataFrame(columns=["Date", "Release Date", "Type", "Text"])

    # Process new communications
    if not new_comms_df.empty:
        # Convert new data using known format
        new_comms_df['Date'] = pd.to_datetime(
            new_comms_df['Date'], format='%Y-%m-%d'
        ).dt.date
        new_comms_df['Release Date'] = pd.to_datetime(
            new_comms_df['Release Date'], format='%Y-%m-%d'
        ).dt.date
        communications = pd.concat([new_comms_df, communications], ignore_index=True)

    # Process meeting dates
    meeting_dates_df = pd.DataFrame([{"Date": d["Date"]} for d in meeting_dates])
    meeting_dates_df['Date'] = pd.to_datetime(meeting_dates_df['Date']).dt.date
    meeting_dates_df['Release Date'] = meeting_dates_df['Date']
    meeting_dates_df['Type'] = "Scheduled Meeting"
    meeting_dates_df['Text'] = None

    # Merge and clean data
    combined = pd.concat([communications, meeting_dates_df])
    
    # After merging but before deduplication
    # Create mask to remove scheduled meetings when real data exists
    has_real_data = combined['Type'].isin(['Statement', 'Minute'])
    scheduled_mask = (combined['Type'] == 'Scheduled Meeting') & \
                     combined['Date'].isin(combined.loc[has_real_data, 'Date'])
    
    # Keep only relevant rows
    combined = combined[~scheduled_mask]
    
    # Then proceed with existing deduplication
    combined = combined.drop_duplicates(
        subset=["Date", "Type"], 
        keep='first'
    )
    
    # Before saving, fill NaN/None with empty strings
    combined['Text'] = combined['Text'].fillna("None")
    
    # Sort and save
    combined.sort_values("Date", ascending=False) \
            .to_csv("communications.csv", index=False)

    # Update most recent date if new comms exist
    if not new_comms_df.empty:
        write_most_recent_date(
            "most-recent-communication-date.txt", 
            new_comms_df["Release Date"].max().strftime('%Y-%m-%d')
        )


def scrape_meeting_dates(panels):
    meeting_dates = []
    for panel in panels:
        year = extract_year_from_panel(panel)
        for row in panel.select('div[class*="row fomc-meeting"]'):
            meeting_timestamp = assemble_meeting_timestamp(row, year)
            meeting_dates.append({
                "Date": format_date(meeting_timestamp)
            })
    return meeting_dates


def main():
    most_recent_date = read_most_recent_date("most-recent-communication-date.txt")
    html_content = fetch_page(BASE_URL + MONETARY_POLICY_URL, HEADERS)
    if html_content:
        panels = parse_fomc_page(html_content)
        new_comms = scrape_communications(panels, most_recent_date)
        meeting_dates = scrape_meeting_dates(panels)
        update_communications(new_comms, meeting_dates)


if __name__ == "__main__":
    main()
