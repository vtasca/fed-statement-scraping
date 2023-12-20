import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.federalreserve.gov"

data_log_response = requests.get(BASE_URL + "/monetarypolicy/materials/assets/final-recent.json")
if data_log_response.ok:
    data_log = [x for x in data_log_response.json()["mtgitems"] if x["type"] in ["St", "Mn"]]

    with open("most-recent-communication-date.txt", "r", encoding="utf-8") as f:
        most_recent_date = f.read()

    # if the fed uploaded new data
    if pd.to_datetime(most_recent_date) < pd.to_datetime(data_log[0]["d"]):
        new_data = [
            x for x in data_log if pd.to_datetime(x["d"]) > pd.to_datetime(most_recent_date)
        ]

        filtered_data = []

        # filter the data for downloadable HTML
        for item in new_data:
            html_item = {
                "Date": item["d"],
                "Type": "Statement" if item["type"] == "St" else "Minute",
                "Release Date": item["dt"],
                "URL": next(
                    (file["url"] for file in item["files"] if file["name"] == "HTML"), None
                ),
            }
            filtered_data.append(html_item)

        # scrape the text of the communications
        for item in filtered_data:
            full_url = BASE_URL + item["URL"]
            response = requests.get(full_url)
            if response.ok:
                doc = BeautifulSoup(response.text, features="html5lib")
                if item["Type"] == "Statement":
                    comm_text = doc.find("div", id="article").find_all("div")[2].text.strip()
                else:
                    comm_text = doc.find("div", id="article").text.strip()
                item["Text"] = comm_text

        # turn into dataframe
        filtered_df = pd.json_normalize(filtered_data).drop(columns=["URL"])[
            ["Date", "Release Date", "Type", "Text"]
        ]

        # read in existing comms
        communications = pd.read_csv("communications.csv")

        # and append to existing data
        communications = (
            pd.concat([filtered_df, communications])
            .assign(Date=lambda df: pd.to_datetime(df["Date"]))
            .sort_values("Date", ascending=False)
            .drop_duplicates()
            .reset_index(drop=True)
        )

        # write out comms data
        communications.to_csv("communications.csv", index=False)

        # and newest date
        with open("most-recent-communication-date.txt", "w", encoding="utf-8") as f:
            f.write(communications.iloc[0, 0].strftime("%Y-%m-%d"))
