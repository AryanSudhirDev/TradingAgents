# Broad agent study — fixed plan, 2026-10-16

Question: does the full research team improve recommendation quality enough to
justify its extra latency and model usage compared with the smaller team?
The Alpaca paper account already uses the full team. Its models, managed
companies and deterministic execution limits stay unchanged during this study.

## Fixed sample

- Companies: AAPL, MSFT, NVDA, JPM, XOM, UNH, WMT, CAT. These cover technology,
  financials, energy, health care, consumer staples and industrials. They are
  surviving companies chosen today, not a historical index membership sample.
- Analysis dates: 2025-10-06, 2026-01-05, 2026-04-06, 2026-07-06, 2026-10-05.
  Quarterly Mondays were chosen before inspecting this study's outcomes, not
  selected to capture known winners or crashes. All five are SPY sessions with
  at least five completed subsequent sessions, verified before launch.
- Two variants: `market_only` and `full` (market, social, news, fundamentals).
  Both retain bull/bear debate, trader, risk debate and portfolio manager; this
  does not isolate the benefit of debating or compare against a single model.
- 40 company/date cells per variant, **80 decisions** in total. Each variant has
  separate memory and checkpoint storage. Dates and company ordering match.
- Existing ChatGPT subscription connection: quick `gpt-6-luna`, deep
  `gpt-6-sol`, one research round and one risk round, checkpoints enabled.
- No Jev key or live X connector is configured. Jev's existing role is relevance
  and stance screening of fetched social posts. Old social/news coverage can be
  unavailable, so this study cannot measure the incremental value of Jev or X.

## Run and track

Use the README's eight-company `--agents --every 91` command. Local outputs stay
under `~/.tradingagents/experiments/agents/`; add `--resume` with the original
folder and arguments to continue. A process lock rejects concurrent copies.
Completed recommendations are skipped and interrupted graphs reuse checkpoints.
Each invocation permits one additional attempt at failed cells/settlement.

The local one-shot LaunchAgent `dev.tradingagents.agent-study` resumes this fixed
experiment at login and restarts a process killed by a crash signal. An ordinary
nonzero exit after bounded retries stays stopped for review; there is no endless
retry loop. Check it with `launchctl print gui/$(id -u)/dev.tradingagents.agent-study`.
Private `results.json` updates at each cell start and variant completion; a long
current cell does not by itself mean the worker is dead. The native memory log
and checkpoint database provide additional progress evidence. Cell metadata and
usage are snapshots, not a continuous heartbeat; usage/time since the last saved
snapshot can be lost on a crash. Keep the Mac logged in, online and plugged in.

## Assess after completion

1. Report all 40 requested cells per variant: completed, resolved, pending,
   unreadable ratings, failed cells and attempts. Show missing coverage rather
   than averaging only convenient successes.
2. Compare recommendation distributions and direction hit rates against SPY on
   the same resolved company/date pairs, plus agreement/disagreement and alpha
   by rating. Hold has no directional claim; an underweight recommendation is
   not an executed short. Shared market dates are correlated observations.
3. Compare elapsed runtime and observed model/tool calls and tokens, including
   retries and reflection. Token counts are not subscription credits or a bill;
   providers can omit usage for incomplete responses.
4. Native outcomes measure analysis-date close to five-session-later close,
   rounded to 0.1 percentage point. They are decision scores, with no executable
   entry model or carried portfolio. Keep the earlier price-rule simulations,
   these scores and actual forward paper results distinct. Price-rule returns
   are not a matched estimate of agents' incremental return.
5. Treat results as exploratory. Current model training may know later events;
   historical text is incomplete and source snapshots are not identical across
   variants. A larger sample does not remove these biases or establish profits.
   Test any apparent advantage prospectively under fixed risk before changing
   execution. No historical winner is promoted automatically.

The working recommendation is a hybrid: agents interpret evidence; ordinary
code enforces portfolio limits, quote freshness, order validity and duplicate
protection. More agents or sources earn their place through measured improvement.

# Sector and strategy study — fixed extension, 2026-10-16

This extension was specified before calculating its ETF rankings. It adds:

- All eleven sector ETFs: XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY.
- Size/style and other assets: SPY, QQQ, IWM, IWD, IWF, EFA, EEM, SHY, IEF, TLT,
  GLD, DBC. Overlapping equity exposures are not independent asset classes.
- Fixed single-ETF rules: buy-and-hold control, 50/200-session moving-average
  trend, positive 252-session absolute momentum, and long/cash prior-week
  reversal. The last is a long-only timing adaptation, not an academic
  cross-sectional long/short replication.
- A sector basket control and monthly membership rotation into up to four
  sectors with the strongest positive return from 252 to 21 sessions ago.
  Existing holdings are not resized at each rebalance. Calendar-period labels
  are published at the first available trading close on or after the label,
  then execute at the next session open; non-session period ends can add a lag.
- Development: 2022-11-01..2024-12-31; validation: 2025-01-02..2025-12-31;
  evaluation: 2026-01-02..2026-10-15. Every slice is retrospective and resets
  capital to $100,000. Markets in the evaluation slice were previously observed;
  it is not a pristine unseen holdout. Parameters remain fixed across slices.
- 253 prior closes for a 252-session return and its execution lag, frozen
  adjusted OHLC and hashes, previous-close
  signals, next-open fills, 5/20 bps adverse slippage, no shorts or leverage.
  Single-ETF sleeves start with up to 40% exposure and 60% uninvested cash.
  Sector basket entry weights are 40%/11; rotation entries target 10% per
  selected sector under a 40% purchase ceiling. Holdings can drift; these are
  common initial maximum budgets, not constant or identical realized risk.
- 23 funds x 4 rules x 3 windows x 2 costs plus 2 sector portfolio rules x
  3 windows x 2 costs: **564 simulations**. Cash earns no interest; SHY is an
  explicit short-duration bond reference, not risk-free cash. Adjusted units,
  omitted taxes/commissions/liquidity/market impact and final exit costs follow
  the earlier simulator's limits.

Assess excess return against each fund's matching buy-and-hold sleeve, drawdown,
exposure, turnover, zero-cash-rate Sharpe, sensitivity to costs and consistency
across windows. A descriptive forward-test shortlist requires positive excess
return in both validation and evaluation at the higher cost, and no worse
drawdown in either slice. Searching many correlated cases creates selection
bias. A shortlist has no statistical significance claim and triggers no orders.

The agent extension adds GOOGL (communications), AMZN (consumer discretionary),
NEE (utilities), PLD (real estate) and LIN (materials), using the original five
dates and both configurations. This is another **50 native decisions**, bringing
the two independent studies to 130 decisions across 13 companies and all eleven
current sector labels. It cannot establish a best sector from five correlated
dates per company. Both studies keep their own frozen manifests and checkpoints.

Deterministic forecast sidecars use the saved native companies/dates and verify
their frozen price hashes. They pair resolved recommendations from both agent
variants on the same cells and use common frozen outcomes. Inactive long-only
rules are Hold, not short recommendations. Direction-times-alpha is a forecast
score, not an executable trading return. Original native outcome precision and
source snapshots can differ. The running native manifests and memory logs stay
untouched by sidecar calculation.

The hypotheses are motivated by [time-series momentum](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum),
[French's prior-2-to-12-month momentum construction](https://mba.tuck.dartmouth.edu/pages/faculty/ken.French/Data_Library/det_10_port_form_pr_12_2_daily.html),
[weekly reversal](https://www.nber.org/papers/w2533) and
[execution-cost evidence](https://pages.stern.nyu.edu/~afrazzin/pdf/Trading%20Cost%20of%20Asset%20Pricing%20Anomalies%20-%20Frazzini,%20Israel%20and%20Moskowitz.pdf).
These ETF adaptations do not replicate those papers. Sector coverage comes from
the [fund provider's eleven-sector suite](https://www.ssga.com/us/en/individual/capabilities/equities/sector-investing/select-sector-etfs).
Historical LLM [look-ahead bias](https://arxiv.org/abs/2309.17322) remains a reason
to use prospective shadow tests before attributing an economic edge to agents.

## Prospective observation phase

Record all 23 funds' four fixed single-asset signals, rather than only the
descriptive historical winner, after each newly completed New York market day.
Record sector-rotation membership separately. The daily journal freezes 320
completed bars per fund, hashes, rules, source-code identity and capture time;
forecasts are never overwritten once complete. Missing days are not backfilled.

The macOS service runs at login and daily 14:45 local time (17:45 New York with
this Mac set to Los Angeles). Capture refuses weekends, pre-16:30 New York
execution and data missing the current session. Adjust calendar jobs if the
Mac's timezone changes. First capture can be pending today's close at setup.

Evaluate forecast horizons of 5, 20 and 63 sessions beginning at the first
session strictly after the actual capture date, using its adjusted open. Entry
counts as session one. Fresh entry/exit prices use one consistent adjustment
basis. Store asset returns, the same-date SPY reference, Long/Hold direction and
raw/relative directional scores. These overlap, remain correlated, omit trading
costs and sizing, and are not a compounded portfolio or broker fills. Future
asset outcomes cannot be established at setup; the journal accumulates them.

This captures fresh **rule** forecasts. The existing Alpaca baseline separately
forward-tests full-agent recommendations. The two historical agent grids remain
diagnostics; this phase does not yet supply a prospectively paired LLM ablation
with identical archived news/filing/social inputs. No recommendation is promoted
into the paper account from the historical ranking.

## Short-horizon success criterion — 2026-10-16

The user's target is to beat random decisions on short trades. The working
horizon is **one to five trading sessions**, rather than a long-term annual
return target. This is an evaluation preference, not evidence of an edge.

A useful prospective comparison must keep the company universe, decision and
entry times, holding deadlines, position budgets, exposure limits, abstention
rate and cost assumptions matched. For a long-only strategy, random long/cash
entries are an appropriate control; a random shorting strategy changes the
trading rules. Retain an always-long reference so favorable market drift is
visible. Freeze decisions and the evaluation rule before their outcomes.

Assess net trade payoff, average winning and losing trades, drawdowns and
performance against the matched random control. A raw hit rate above 50% is
not sufficient: trade sizes, win/loss magnitudes, costs and the random
control's base rate matter. Shared market dates and overlapping positions
must remain visible when assessing uncertainty.

The completed native five-session forecast scores measure SPY-relative
direction, not profitable-trade frequency or a timed portfolio. The existing
Alpaca baseline has daily research but **no fixed maximum holding period**;
daily review does not guarantee a five-session exit. A future short-horizon
portfolio test must explicitly enforce its entry/exit policy. The current
paper account's execution rules remain unchanged. No new model grid, random
portfolio sweep or broker execution change was started by recording this goal.

The subsequently requested, separate read-only weather-market feasibility pilot
is specified in [WEATHER_EXPERIMENT.md](WEATHER_EXPERIMENT.md). It does not alter
the fixed stock protocols or the existing Alpaca account.

# Timestral work — separately authorized 2026-10-18

The broad agent and sector studies above are complete and remain frozen. Do not
relaunch them. The user's later request authorizes replacing the dashboard's
decision path with Timestral, a past-only portfolio replay and a separate
observation-only cross-market forecast comparison. These are distinct from the
original studies, not extensions to their grid or evidence for promoting an old
winner. The fixed protocols and operating limits are in [TIMESTRAL.md](TIMESTRAL.md),
and aggregate results in [STRATEGY_RESULTS.md](STRATEGY_RESULTS.md). No additional
paper symbols, leverage, live trading, subscriptions or social connectors follow
from that diagnostic comparison.
