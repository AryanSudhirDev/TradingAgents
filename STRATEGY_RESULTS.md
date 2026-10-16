# Initial sector-strategy findings — 2026-10-16

Completed 564 price-only simulations across 23 ETFs, including all eleven sector
funds, US size/style and international equity exposures, three Treasury
durations, gold and commodities. The fixed protocol is in
[EXPERIMENTS.md](EXPERIMENTS.md). Full results are available in the local
[Strategy lab](http://127.0.0.1:8000/experiments).

All 564 calculations reproduced from their frozen price CSVs; 23 data hashes
and the plan hash verified. The maximum difference across checked equity,
return, drawdown, exposure and volatility figures was below 0.000001. Inputs
and full curves remain private locally, not in this repository.

## What the price comparisons show

At 20 basis points of adverse slippage per fill, the number of timing/rotation
configurations with positive excess over their matching hold control was:

| Retrospective slice | Positive excess | Compared configurations |
| --- | ---: | ---: |
| 2022-11-01 to 2024-12-31 | 1 | 70 |
| 2025-01-02 to 2025-12-31 | 7 | 70 |
| 2026-01-02 to 2026-10-15 | 10 | 70 |

Each slice has 69 single-fund timing combinations plus sector rotation. Most
tested timing rules lagged buy-and-hold; the winners changed across slices.
This is evidence against assuming that an elaborate rule must beat holding.
It does not establish what will work in a new market regime.

Only **XLY weekly reversal** passed the predeclared descriptive screen:
positive excess in both later slices at the higher cost, with no worse drawdown
in either. It holds a long sleeve after a completed down week and otherwise
holds cash, subject to the disclosed calendar-publication lag.

| Slice | Reversal portfolio return | Matching hold return | Reversal drawdown | Hold drawdown | Reversal average exposure |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2025 | +5.12% | +2.85% | -5.05% | -9.88% | 15.7% |
| 2026 through October 15 | +0.50% | -2.06% | -4.72% | -6.11% | 24.3% |

These are cumulative whole-portfolio simulations starting at $100,000 with
40% maximum entry exposure, not the underlying fund's return. The hold control
had average exposure of roughly 40%; the reversal rule's lower exposure matters.
This is one selected candidate among many correlated comparisons, not a
significant discovery, a recommendation or an automatically promoted strategy.
It did not beat holding in the development slice.

Monthly sector rotation beat the all-sector hold control by 2.33 percentage
points in the 2026 slice at the higher cost, but failed the consistency screen
across both later slices. Its different concentration and drifting exposure
also matter. No universal best sector or strategy has been established.

## What remains under test

- Two native agent studies are running independently: 80 plus 50 decisions,
  covering 13 companies and all eleven current sector labels. The dashboard
  reports live saved counts and scores only resolved company/date pairs
  shared by both teams. These are historical direction scores, not fills or
  portfolio returns. Their historical text and model-training biases remain.
- The prospective journal records all fixed fund/rule forecasts, not just XLY,
  before their future outcomes. It scores next-open forecasts at 5, 20 and 63
  sessions without orders, model calls, costs, sizing or compounding.
- The separate existing Alpaca paper baseline continues testing full-agent
  recommendations under its original execution constraints. That is a
  different experiment from the price-rule forecast journal.

These runs have not established which sector benefits from LLM agents. That
requires fresh, sufficiently long paired tests with matched inputs and risk.
The current four-year price sample also cannot establish robustness across
earlier crises, delistings, small-cap individual companies or HFT execution.
