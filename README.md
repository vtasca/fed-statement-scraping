# FOMC Meeting Statements - Diffs
This repository automatically scrapes and diffs the FOMC meeting statements - tracking US monetary policy changes through time.

It works by scraping the most recent FOMC meeting statement document from the Fed's website and writing it to `statement.txt`. The scraper runs in a scheduled GitHub Actions workflow, which is [available here](https://github.com/vtasca/fed-statement-scraping/actions/workflows/main.yml).

Monetary policy decisions shown in the FOMC meeting statements have been analyzed at length in academic research and found to have immediate effects on the volatility and direction of equity index prices[^1] and interest rates[^2].
[^1]: Rosa, C. (2011). Words that shake traders: The stock market's reaction to central bank communication in real time. Journal of Empirical Finance, 18(5), 915-934.
[^2]: Gürkaynak, R. S., Sack, B., & Swanson, E. (2005). The sensitivity of long-term interest rates to economic news: Evidence and implications for macroeconomic models. American economic review, 95(1), 425-436.

## Usage
The easiest way to analyze the diffs in the document is to look at the [file's commit history](https://github.com/vtasca/fed-statement-scraping/commits/master/statement.txt), which will highlight only the changes:
![Screenshot showing the highlighted differences between two FOMC meeting statements](https://i.imgur.com/lAPH6QT.png)

For more in-depth analysis, use a CLI tool specifically designed for the purpose of analyzing periodical snapshots of data in Git such as [`git-history`](https://github.com/simonw/git-history).

## The FOMC
The [Federal Open Market Committee (FOMC)](https://www.federalreserve.gov/monetarypolicy/fomc.htm) meets eight times during the year to make decisions regarding the implementation of monetary policy, with the aim of achieving the Federal Reserve's dual mandate: promoting maximum employment and maintaining stable prices (controlling inflation).

The FOMC meeting statement document is one of the main formal communication documents used by the Fed, and contains information about key interest rate decisions, an assessment of the economic outlook, a view on inflation as well as forward guidance. This information helps businesses, investors and the general public take monetary policy into account and make more informed economic decisions.

## Related Projects

Inspired by [Simon Willison's blog post](https://simonwillison.net/2020/Oct/9/git-scraping/) on scraping with Github Actions.
