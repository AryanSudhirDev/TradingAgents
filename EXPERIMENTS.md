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
