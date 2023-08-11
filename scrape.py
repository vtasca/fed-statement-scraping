from bs4 import BeautifulSoup
import requests
import datetime

today = datetime.date.today()
formatted_date = today.strftime("%Y%m%d")

# generate URL
URL_STEM = "https://www.federalreserve.gov/newsevents/pressreleases/monetary"
date_component = f"{formatted_date}a.htm"
full_url = URL_STEM + date_component

# make request
r = requests.get(full_url)
if r.status_code == 200:
    # extract statement
    doc = BeautifulSoup(r.text, features="html5lib")
    article = doc.find("div", id="article")
    body = article.find_all("div")[2]
    body_content = body.text.strip()

    # write statement
    with open("statement.txt", "w", encoding="utf-8") as f:
        f.write(body_content)
