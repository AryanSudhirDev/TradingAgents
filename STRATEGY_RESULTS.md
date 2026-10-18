# Sector-strategy findings — 2026-10-16

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

## Completed native agent comparison

Neither agent team beat any of the four fixed rule controls on this sample's
matched forecast score. The full team's mean score was less negative than the
market-only team's, with more model usage and elapsed time. This does not
establish a profitable strategy, a reliable sector advantage or a reason to
change the existing paper account.

Both native studies finished with exit code 0. All **130 requested decisions**
are saved, resolved and readable: 40 per team in the original study and 25 per
team in the extension. There are no pending outcomes, horizon mismatches,
unreadable ratings, outstanding failed cells or settlement failures. Three
incomplete-response attempts in the full-team runs recovered through their
existing bounded retry; partial responses were discarded. Final exit and
coverage records remain private. Both finished one-shot LaunchAgents were
removed; dashboard, progress, forecast capture and weekday review stay enabled.

The comparison uses **65 identical resolved company/date pairs** for all six
arms, five-session horizons, 13 companies and eleven current sector labels.
Both studies have identical model/configuration signatures and analysis dates;
their frozen inputs passed their saved hashes. Their SPY files are not byte
identical, but the five scored SPY session windows and returns match exactly.
Within each cell every arm uses the same frozen, unrounded stock/SPY outcome.
This does not mean the two teams received identical archived text evidence.

The score is the mean of `direction × (stock return − SPY return)`, in
percentage points over all 65 cells. Returns run from the analysis-date close
to the close five sessions later. Direction is +1 for Buy/Overweight, −1 for
Sell/Underweight and 0 for Hold. Hold is an abstention, not a directional hit;
its score is zero. A bearish score is **not executed short P&L**. No entry
fills, sizing, costs, cash yield or portfolio path are modeled here. These
scores are distinct from the 564 price-portfolio simulations above.

| Forecast arm | Mean signed alpha score (pp) | Directional claims / 65 | Positive claims / claims |
| --- | ---: | ---: | ---: |
| Always long / hold control | +0.491 | 65 | 37/65 (56.9%) |
| 50/200-session trend | +0.037 | 54 | 28/54 (51.9%) |
| Positive 252-session momentum | +0.384 | 56 | 33/56 (58.9%) |
| Weekly reversal | +0.054 | 23 | 13/23 (56.5%) |
| Market-only agent team | −1.063 | 50 | 18/50 (36.0%) |
| Full agent team | −0.771 | 50 | 19/50 (38.0%) |

The full-minus-market-only mean difference is **+0.292 pp**, but the full team
scored higher in 16 cells, lower in 17 and equal in 32. Ratings/directions
matched in 32/65 cells, including four mutual Holds; eleven pairs opposed one
another and 22 had one team abstain. The mean improvement is not evidence that
the full team wins more often. Its mean score was higher on three of the five
shared dates and in six of eleven small sector samples, without a significance
claim. Direction hit rates are conditional on making a directional claim.

Both teams issued 15 Holds. The market-only team issued 30 Overweights and 20
Underweights; the full team issued 20 Overweights and 30 Underweights. Neither
issued Buy or Sell. The per-rating signed scores were:

| Team / rating | Cases | Positive claims | Mean signed alpha score (pp) |
| --- | ---: | ---: | ---: |
| Market-only / Overweight | 30 | 13/30 | −0.756 |
| Market-only / Underweight | 20 | 5/20 | −2.321 |
| Full / Overweight | 20 | 9/20 | −0.464 |
| Full / Underweight | 30 | 10/30 | −1.360 |

### Sector coverage and limits

These are company proxies, not representative samples of each industry.
Technology contributes three companies and 15 pairs; every other sector has
one company and five pairs. All sectors share the same five market dates, so
65 pairs are not 65 independent regimes. Positive scores in a small subset do
not identify a best sector for automation.

| Current sector | Companies | Matched pairs | Market-only mean score (pp) | Full mean score (pp) |
| --- | ---: | ---: | ---: | ---: |
| Communications | 1 | 5 | +0.505 | +0.397 |
| Consumer discretionary | 1 | 5 | −0.654 | −2.779 |
| Energy | 1 | 5 | −2.984 | −2.896 |
| Financials | 1 | 5 | −1.197 | −0.264 |
| Health care | 1 | 5 | −1.586 | −1.869 |
| Industrials | 1 | 5 | +0.757 | −0.302 |
| Materials | 1 | 5 | −0.896 | −1.254 |
| Real estate | 1 | 5 | −1.412 | −0.126 |
| Consumer staples | 1 | 5 | −3.276 | −1.785 |
| Technology | 3 | 15 | −0.552 | +0.412 |
| Utilities | 1 | 5 | −1.418 | −0.377 |

### Observed usage

| Team | Model calls | Tool calls | Input tokens | Output tokens | Summed variant minutes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Market-only | 842 | 644 | 3,001,008 | 348,719 | 135.9 |
| Full | 1,172 | 1,542 | 4,978,952 | 675,919 | 169.2 |

The full team used 1.69× observed input-plus-output tokens and 1.25× summed
variant elapsed time. Elapsed values add the variants from two concurrent
studies; they are not total Mac wall time. Counts include observed retries and
reflection, but incomplete provider responses can omit usage. Tokens are not
subscription-credit units, a dollar bill or a measured inference-cost return.

The studies remain exploratory: selected surviving companies, five correlated
dates, current sector labels, one model sampling per cell, incomplete historical
text, different evidence availability and possible model-training knowledge of
later events limit inference. Both teams retain the debate, trader and risk
stages, so this does not isolate their value against a single model. No X/Jev
increment was tested. The negative agent scores do not establish a timeless
result; the full team's less negative score does not justify an automatic
promotion.

## What remains under test

- The first prospective journal capture completed after the October 16 close:
  all 92 fixed fund/rule forecasts across 23 funds passed frozen-input checks.
  Its 276 outcomes across 5/20/63 sessions are pending; none has matured. These
  are fresh rule forecasts, not LLM decisions or compounded portfolio returns.
- The separate existing Alpaca paper baseline continues testing full-agent
  recommendations under its original execution constraints. Private weekday
  reviews check reports, broker state and consistent SQLite backups. Sampled
  intraday returns are not closing returns or exact-time SPY alpha.
- Establishing an economic benefit from extra agents requires fresh, longer
  paired tests with matched archived evidence and risk. Those tests have not
  been added or silently substituted for this completed historical study.

The working choice is to keep the existing paper baseline and observation
journal unchanged while future outcomes accumulate. No sector, rule or agent
team is promoted automatically. The current price sample also cannot establish
robustness across earlier crises, delistings, small-cap individual companies or
HFT execution.

## Separate weather-market pilot — 2026-10-17

The user's temperature-market idea received a separate read-only feasibility
test; it does not change the stock studies, rule journal or Alpaca account.
The fixed protocol, sources and reproduction commands are in
[WEATHER_EXPERIMENT.md](WEATHER_EXPERIMENT.md).

All **14 requested NYC/KLGA daily events**, October 1–14, have complete resolved
metadata, archived individual day-ahead GFS forecasts and fresh pre-decision
price-history marks for every bracket. There were **zero missing/failed dates**.
All 182 cached responses verified and reproduced identical cells and aggregate
results with network access explicitly blocked. Files remain private, mode 0600.

The independent toy model places a fixed, uncalibrated 3°F uncertainty around
the forecast hourly maximum and selects three adjacent temperature bins. This
is not PolyTemp's private model, published calls, wallet or reported profits.
With the fixed 2¢/share adverse price assumption and assumed weather taker-fee
formula, **all 14 modeled basket edges were negative**. The 5¢ value filter
therefore entered **zero baskets** and abstained on all 14 dates. There is no
active-date comparison or trading evidence from that filtered rule.

Forcing an equal-share basket purchase on every date gives this diagnostic:

| Fixed daily choice | Mean hypothetical return per dollar staked |
| --- | ---: |
| GFS model's highest-probability adjacent three bins | −8.65% |
| Market-price-favourite adjacent three bins | −1.28% |
| Uniform random adjacent three-bin window, exact mean | −55.94% |

All three use identical dates, normalized budgets, costs and recorded settlement
outcomes. These are averages of standalone hypothetical basket returns, **not
compounded account returns or executable fills**. The model ladder contained
the eventual winning bin on **12/14 dates (85.7%)**, yet lost money when forced
to enter. It beat the weak random control but lagged the simple market-favourite
choice. Its multiclass Brier score was also worse than normalized market prices:
0.761 versus 0.521 (lower is better). This sample illustrates why beating random
chance or advertising high multi-bin accuracy is insufficient to establish an
economic edge.

The latest recorded resolution among included brackets was 40.94 hours after
entry. That observed duration does not guarantee future resolution timing or
implement a weekly exit. Exact forecast publication latency, historical rule/fee
versions, station/grid discrepancies, the arbitrary uncertainty width, selected
station and 14 correlated dates limit inference. Independently sampled marks
plus a price penalty do not establish historical asks, depth, queue position,
capacity or fills; actual execution could be worse. No retuning, significance
claim, annualization, strategy promotion or automated weather trading followed.

The inspected `poly_data` main revision is a useful GPL-3.0 metadata/on-chain-fill
retriever, not a weather model or a bundled executable-book archive. Its current
chain pipeline requires a HyperSync token. The two bulk archive links in its
`v1-final` README returned HTTP 404 on the check date. No upstream code, raw
research or downloaded inputs were added to this repository. The pilot used
keyless public market/forecast APIs instead; no credentials or subscription
were added. Twenty-four targeted tests and Ruff passed.

## Timestral migration and separate diagnostics — 2026-10-18

At the user's explicit request, the dashboard now uses a pinned local
Timestral-28M engine plus fixed long-only portfolio rules. The original agent
implementation is preserved in Git tag `archive/pre-timestral-20261018`; its
completed studies remain historical evidence. This supersedes the earlier
operating choice to continue full-agent paper recommendations. The existing
paper account, four symbols and execution limits are retained, with scheduled
fifth-session exits and a separate performance epoch. Carried legacy positions
remain in whole-account performance until exited. No paper cycle was forced.

The fixed past-only portfolio replay saved **548/548 forecasts** across **137
sessions**, April 1–October 15, 2026. It carries cash, whole shares and holding
ages, applies 0.5% adverse costs each side and reproduces all three arms from
frozen data/forecasts with networking and model loading blocked. Timestral plus
fixed rules returned **+0.314%**, versus −0.474% for always entering and −0.418%
for one fixed random path. Only **six positions** were entered, with **0.39% mean
exposure**, compared with 15.52% and 12.96% for those controls. These comparisons
are not exposure matched and do not establish performance above chance.

A separate observation-only panel completed **14/14 series, 402 resolved
five-observation windows**, across equity funds, bonds, metals, oil/dollar funds
and crypto. Seven series modestly beat a last-close forecast and seven lagged;
the largest relative error improvement was 2.99% for QQQ, the largest deterioration
3.59% for TLT. A single USO data timeout recovered on one bounded retry. No market,
model or policy was selected or promoted from these results. Crypto uses calendar
days; funds use NYSE sessions. This panel measures forecast error, not portfolios
or executable trades; oil and currency funds are proxies for those markets.

Unknown pretraining overlap, current adjusted data rather than a point-in-time
archive, selected survivors, correlated shocks and small samples limit both
exercises. Portfolio replay opening fills approximate the production 10:00 NY
window, not historical executable quotes. Quantile bands remain uncalibrated;
fifth-session exits are scheduled, not guaranteed fills. Future paper observations
remain separate from retrospective diagnostics and the unchanged rule journal.
See [TIMESTRAL.md](TIMESTRAL.md) for the fixed protocols, controls, CPU usage,
private reproduction commands and operating details. No raw inputs, forecasts,
credentials or account data are committed.
