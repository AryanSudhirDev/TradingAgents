# Weather-market feasibility pilot — 2026-10-17

This separate, read-only experiment tests the temperature-probability versus
contract-price idea. It does not copy PolyTemp's proprietary forecasts, connect
a wallet, trade, create a subscription, run models, or change Alpaca settings.

## Data assessment

[warproxxx/poly_data](https://github.com/warproxxx/poly_data) is a GPL-3.0 data
retriever, not a weather forecasting strategy. Inspected main revision:
`136e129735c73bce3a3d59f20354417b188e47fd`. It fetches market metadata and
on-chain fills, with a free HyperSync token required for the current pipeline.
The older `v1-final` README also links compressed historical snapshots; both
linked S3 objects returned HTTP 404 when checked on October 17, 2026. These
fills do not reconstruct executable historical asks, depth, canceled orders,
queue position or weather forecasts. No upstream code is incorporated here;
the external checkout and any downloaded data stay private.

For this small pilot, public Gamma resolved metadata, CLOB price history and
Open-Meteo archived individual GFS runs supply a keyless alternative. This
tests the idea without a full-chain backfill. A last recorded price is never
presented as a verified available fill.

## Fixed protocol

- One station: LaGuardia, KLGA. All 14 calendar dates, October 1–14, 2026.
  This is a selected retrospective pilot, not an unseen holdout. October 1
  metadata and one price-history series were inspected for availability
  before freezing the protocol; no strategy payoff was calculated then.
- Use the preceding day's 12:00 UTC GFS initialization. Decide at 20:00 UTC,
  allowing eight hours for distribution. Actual historical delivery times
  are not verified. Use only the target local day's 24 forecast hours.
- A Normal distribution centered on the hourly forecast maximum, with a
  fixed, **uncalibrated 3°F standard deviation**, assigns probabilities to
  the market's rounded integer-temperature bins. Select the three adjacent
  bins with highest total probability. This is an independent toy hypothesis,
  not a reconstruction of PolyTemp's model or accuracy.
- Use the latest recorded price at/before the decision, at most five minutes
  old, for every bin. Missing coverage invalidates the date. Add 2¢ per share
  (capped at $1) and the assumed fee `0.05 × price × (1 − price)`.
  These are stress assumptions; neither historical spreads nor fee versions
  are verified, and actual costs/fills could be worse.
- Enter the equal-share basket only when modeled probability exceeds total
  cost by at least 5¢. Hold to reported resolution. Actual resolution delays
  are reported; this does not enforce a one-week exit.
- Normalize hypothetical payoffs per dollar staked, without compounding or
  asserting feasible portfolio sizing. Compare the market-favourite adjacent
  three-bin window and the exact mean over every possible random adjacent
  three-bin window on **the same entry dates**, with identical cost assumptions
  and normalized budgets. Also report unfiltered comparisons and all omissions.
- Compare forecast Brier scores with normalized market-price probabilities.
  Report ladder coverage separately from hypothetical return. No parameter
  sweep, retuning, significance claim, annualization or strategy promotion.

## Reproduce

```sh
.venv/bin/python -m tradingagents.weather_replay \
  ~/.tradingagents/experiments/weather/nyc-20261001-20261014 --fetch
# Subsequently replay without any network calls:
.venv/bin/python -m tradingagents.weather_replay \
  ~/.tradingagents/experiments/weather/nyc-20261001-20261014
```

The protocol is saved before requests. Inputs, request parameters, capture
times and hashes stay private under that folder. Existing responses (including
failures) are not fetched again. Changed input hashes or protocol are rejected.
No historical book or archived PolyTemp call is invented to fill a gap.

Interpretation: a promising result would justify further prospective testing;
it would not verify an executable edge. An unprofitable result would reject
this fixed toy rule on this sample, not all weather-market strategies.

Aggregate pilot findings are recorded separately in
[STRATEGY_RESULTS.md](STRATEGY_RESULTS.md#separate-weather-market-pilot--2026-10-17).
