# Timestral paper desk

The dashboard now runs **Timestral-28M locally on CPU**, followed by fixed
portfolio and execution rules. No LLM, ChatGPT subscription, news, social feed
or agent debate participates in this path. The original agent CLI and all
previous experiments remain available. Git tag `archive/pre-timestral-20261018`
preserves the complete previous implementation; this change is stacked above
PR #5. It does not merge or delete the previous work.

## Setup and operating rules

```bash
pip install -e ".[dashboard,timestral]"
python -m tradingagents.timestral_engine  # explicit weight download
tradingagents-dashboard
```

Open <http://127.0.0.1:8000>. Model code is pinned to Mistral commit
`a534bdbd244d64f3d9d743f46c7bf6fc330ed4ff`; weights are pinned to
`mistralai/Timestral-28M` revision `180698bbf5a50dda3516aa6419798437fb03a430`.
The runtime uses eight CPU threads and cached weights; it never downloads weights
silently. See the [official model card](https://huggingface.co/mistralai/Timestral-28M)
and [code](https://github.com/mistralai/timestral). Code and model licenses differ:
code is Apache-2.0; the weights have a Modified MIT license with commercial revenue
conditions. Consult the model's license before commercial use.

For a decision day, use at most 512 completed adjusted daily closes **strictly
before that day** (minimum 128). Missing required sessions block forecasting.
Forecast log prices five sessions ahead and transform its 21 quantiles back to
prices. Inputs, dates, model revision and outputs are privately saved with hashes.
Future calendar labels are available; future prices never enter the model.
Alpaca supplies the connected account's calendar; keyless mode uses XNYS from
`exchange-calendars`.

The numerical model does not reason about money. The fixed policy receives the
forecast and whether shares are held; the decision reference includes the adverse
execution-price allowance. Sizing receives current cash, equity and
positions. Flat positions enter at a 5% equity target only if the terminal median
exceeds the reference by 1% and its estimated q10 loss is within 3%. Held positions
are never topped up. A non-positive median return exits early; otherwise an exit
is scheduled by session five, counting the entry session. Confirmed journal-owned
fills preserve the holding age across restarts and partial fills.

Automation retains AAPL/MSFT/NVDA/JPM, whole long shares, a 40% invested ceiling,
10% cash reserve and no leverage. Daily cycles begin at 10:00 New York on exchange
sessions. Fresh IEX quotes are checked again before orders, with existing spread,
quote-age and 0.5% DAY-limit allowances. No additional order is sent in the final
30 minutes, while an order is open, or while a prior submission is uncertain.
There is one durable attempt per account/symbol/day; failed research is not retried
that day. Unknown orders are never blindly resubmitted. Unowned positions or
splits block execution until reconciled.

**Five sessions is a scheduled exit, not a guaranteed maximum realized holding
period.** Pauses, sleeping/offline hardware, stale quotes, closed sessions, unknown
orders, rejections and unfilled limits can delay it. There is no automatic
stop-loss. Quantiles are estimates, not calibrated probabilities or loss limits.
Manual Analyze uses the separate manual simulator's book; only an automated
cycle uses the Alpaca book. Manual buttons never submit broker orders.

Migration pauses old automation once and establishes a new performance epoch;
old reports, equity samples and fill journals stay saved. The existing paper
account was explicitly enabled during setup; later dashboard control changes
paused it. The current dashboard state is authoritative; honor a user pause. Existing owned
positions retain their original fill ages and remain in the new whole-account
return until exited. That return is not a clean, flat-start Timestral portfolio.

## Fixed past-only portfolio replay

```bash
.venv/bin/python -m tradingagents.timestral_backtest \
  ~/.tradingagents/experiments/timestral/20261018-fixed-replay
```

Protocol: AAPL/MSFT/NVDA/JPM, April 1–October 15, 2026; daily origins; identical
resolved sessions; carried cash, whole shares and entry ages; $100,000 virtual
start; adverse **0.5% per side**; shared sizing and signal policy. Decisions see
only prior closes and a next-open execution-price proxy. Positions are marked at
that day's close only after decisions. Explicit boundary liquidation closes the
last day's holdings. Calendar and raw price inputs are frozen privately.

All **548/548 forecasts** across **137 sessions** were saved and readable; no
forecast or decision failed. Every arm reproduced identically from frozen inputs
and forecasts with network access and model loading blocked. Perturbation tests
also verify that changing later prices cannot change earlier decisions or cash.

| Fixed arm | Net return | Sampled max drawdown | Fills | Mean exposure |
| --- | ---: | ---: | ---: | ---: |
| Timestral + fixed rules | +0.314% | −0.336% | 12 | 0.39% |
| Always enter when flat; same five-session exit | −0.474% | −3.800% | 224 | 15.52% |
| One predeclared random-entry path; same exit | −0.418% | −2.163% | 184 | 12.96% |

Timestral entered **six positions**, held existing shares on 5 decisions and
abstained while flat on 531 decisions. The controls carry much more exposure;
these are diagnostic references, not exposure-matched significance tests. A single
random path does **not** establish performance above chance. The fixed thresholds
were not retuned after these results. CPU inference median was **14.1 ms**, p95
**24.9 ms**, across 548 saved calls (8.76 seconds total model inference; about
13.2 seconds initial replay including loading/data). There were zero LLM calls
or token/subscription charges.

Historical training overlap is unknown. Current adjusted prices are not a
point-in-time corporate-action archive. Selected survivors, one recent period,
shared market dates and overlapping forecast horizons limit inference. Opening
fills do not reproduce the production 10:00 execution time, historical spreads,
capacity, halts or queue position. Costs are assumptions; taxes, cash yield and
intraday drawdown are omitted. This is a historical simulation, not Alpaca results.

## Across markets: forecasting, separate from trading

```bash
.venv/bin/python -m tradingagents.timestral_markets \
  ~/.tradingagents/experiments/timestral/cross-market-20261018
```

The fixed 14-series panel covers SPY/QQQ/IWM, EFA/EEM, TLT/IEF/LQD, GLD/SLV,
USO/UUP and BTC-USD/ETH-USD. It compares terminal five-observation forecast error
against the last completed close and 20-observation log drift. Origins are spaced
five observations apart within a series. Funds use NYSE sessions; crypto uses
calendar days. All input prefixes end before their forecast origin. No positions,
orders, execution costs or trading returns are modeled in this separate diagnostic.
Oil and dollar funds are product proxies, not spot FX or directly traded futures.

All **14/14 series**, **402 resolved windows**, completed with zero outstanding
failures. One initial USO download timeout recovered through one bounded read-only
retry, reusing the other series' frozen inputs/forecasts. No model or policy search
was performed. Seven series modestly beat repeating the last close, seven lagged.
QQQ had the largest improvement (2.99% lower absolute percentage error); TLT had
the largest deterioration (3.59% higher). Those small differences and 27 windows
per fund / 39 per cryptocurrency do not establish a best market or a tradable edge.
Cross-series shocks remain correlated. General forecasting benchmarks also do
not establish stock, FX or crypto profitability. Electricity, demand and weather
were not evaluated by this panel.

Read-only aggregate results appear on the main dashboard and
`/api/timestral/backtest` / `/api/timestral/markets`. Inputs, individual decisions,
account observations and raw research remain private outside Git.

## Startup and review

The existing `dev.tradingagents.dashboard`, `.progress` and `.strategy-shadow`
LaunchAgents are enabled. Dashboard recovery was checked with a controlled process
restart and an unchanged order journal. Startup is per-user **at login**, with
KeepAlive for the dashboard; physical reboot/login was not exercised. The Mac must
stay online and awake; the installed AC-power sleep prevention does not guarantee
battery/wake/network availability. The normal daily schedule is configured; later dashboard control changes left
paper execution paused pending clarification. No paper cycle was forced during setup. The weekday review remains at 14:55 Mac local time.
Completed historical study workers stay removed. The separate fixed-rule shadow
journal is unchanged and must not be confused with Timestral forecasts.

Progress checks are read-only broker inspections plus private SQLite backups:
`python -m tradingagents.dashboard.operations check`. Keep credentials, account
values, inputs, predictions and logs under `~/.tradingagents/` private. Pause from
the dashboard before maintenance. Future observation reviews must not retune rules,
promote a market, expand paper symbols or enable live trading automatically.
