# Metric and Alignment Definitions

These definitions were agreed before implementing the curated transformation.
They are the business contract for the dashboard and its tests.

## Analytical grain

The curated dataset contains one row for each S&P/ASX 200 trading date. Market
data is authoritative for the row set; non-trading dates are not generated.

## Date and timezone treatment

Yahoo Finance daily timestamps are converted to `Australia/Sydney` before the
trading date is derived. RBA F1 observations are published as Australian
business dates and are stored directly as observation dates.

The RBA series is aligned to each market date with an as-of join: use the most
recent valid RBA observation whose date is on or before the market trading date.
This explicitly forward-fills a previously known macro value across dates when
the RBA publishes no new observation. A future RBA value must never be
backfilled into an earlier market date.

The curated dataset retains the actual RBA observation date and its age in
calendar days so that forward-filling remains visible and auditable.

## Metric 1: 20-trading-day rolling average

For each trading date, calculate the arithmetic mean of the current S&P/ASX 200
closing value and the previous 19 trading-day closing values.

The metric is null until all 20 observations are available.

## Metric 2: 20-trading-day return

For each trading date, calculate the percentage change between the current
closing value and the closing value 20 trading observations earlier:

```text
((current close / close 20 observations earlier) - 1) * 100
```

The metric is null until the required earlier observation is available.

## Metric 3: 14-trading-day annualised realised volatility

First calculate the daily logarithmic return:

```text
ln(current close / previous trading-day close)
```

Then calculate the sample standard deviation of the latest 14 daily logarithmic
returns and annualise it using 252 trading days:

```text
standard deviation * sqrt(252) * 100
```

The metric is expressed as an annualised percentage and is null until 14 daily
returns are available.

## Market Stress RAG signal

For each trading date, the RAG signal uses only valid 14-day annualised
volatility observations available on or before that date, within the preceding
five years. This makes historical signals point-in-time correct when the
dashboard analysis date changes.

- Green: volatility is below the 75th percentile.
- Amber: volatility is at or above the 75th percentile and below the 90th
  percentile.
- Red: volatility is at or above the 90th percentile.
- Insufficient data: the volatility or thresholds cannot yet be calculated.

At least 60 valid volatility observations are required before a signal is
assigned. The thresholds are recalculated when the curated dataset refreshes.
They are descriptive monitoring thresholds, not predictive trading signals or
formal risk limits.

## Dashboard window

The curated table retains the five-year calculation history. The management
dashboard displays the 90 calendar days ending on a user-selected date. The
selected date resolves to the latest available trading date on or before it, so
weekends and market holidays do not create empty views.
