<p align="center">
  <img src="tradingagents/assets/tauric-logo.svg" width="60%" alt="Tauric Research">
</p>

<div align="center" style="line-height: 1;">
  <a href="https://arxiv.org/abs/2412.20138" target="_blank"><img alt="arXiv" src="https://img.shields.io/badge/arXiv-2412.20138-B31B1B?logo=arxiv"/></a>
  <a href="https://discord.com/invite/hk9PGKShPK" target="_blank"><img alt="Discord" src="https://img.shields.io/badge/Discord-TradingResearch-7289da?logo=discord&logoColor=white&color=7289da"/></a>
  <a href="https://x.com/TauricResearch" target="_blank"><img alt="X Follow" src="https://img.shields.io/badge/X-TauricResearch-white?logo=x&logoColor=white"/></a>
  <a href="https://github.com/TauricResearch/" target="_blank"><img alt="Community" src="https://img.shields.io/badge/GitHub_Community-TauricResearch-14C290?logo=discourse"/></a>
</div>
<br>
<div align="center">
  <a href="https://github.com/TauricResearch" target="_blank"><img alt="TradingAgents #1 Repository of the Day" src="https://trendshift.io/api/badge/repositories/16192" width="250" height="55"/></a>
</div>
<br>
<div align="center">
  <!-- Keep these links. Translations will automatically update with the README. -->
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=de">Deutsch</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=es">Español</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=fr">français</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ja">日本語</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ko">한국어</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=pt">Português</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ru">Русский</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=zh">中文</a>
</div>

---

# TradingAgents: Multi-Agents LLM Financial Trading Framework

## News

<!-- news:start -->
- [2026-10] **TradingAgents v0.6.0** released with reports saved as one HTML page, a provider per model tier so the managers and analysts can run on different models, past decisions settled for every ticker while the analysts work, and company news read from Yahoo search while Yahoo's news feed is down.
- [2026-09] **TradingAgents v0.5.2** released with parallel analysts for a faster analysis, a CLI that runs without prompts from flags such as `--ticker` and `--date`, the run's settings recorded in every report, and backtests that see only data published by each analysis date.
- [2026-09] **TradingAgents v0.5.1** released with a package layout organised by what each module holds (import paths moved), optional Jev screening of social posts, GPT-6 Sol and Luna as the default models, and fixes to run isolation and SEC EDGAR statements.

Full release notes are in [CHANGELOG.md](CHANGELOG.md).

<details>
<summary>Earlier news</summary>

- [2026-09] **TradingAgents v0.5.0** released with point-in-time integrity across every dated path, SEC EDGAR fundamentals served as filed, backtesting over a ticker and date grid, portfolio-aware runs, and current model lineups across every provider.
- [2026-08] **TradingAgents v0.4.0** released with look-ahead / point-in-time fixes across FRED macro, social sentiment, and the decision-log memory; clearer decision signals; working CLI checkpoint resume; Trader price grounding; and the GPT-5.6 and GLM-5.3 models.
- [2026-07] **TradingAgents v0.3.1** released with correctness and stability fixes: Alpha Vantage look-ahead filtering, graph-router crash-safety, graph-shape-aware checkpoint resume, working crypto sentiment sources, a configurable LLM retry budget, Bedrock API-key auth, and Claude Sonnet 5 / Fable 5 support.
- [2026-06] **TradingAgents v0.3.0** released with a verified data-access contract, an expanded provider registry (NVIDIA, Kimi, Groq, Mistral, Bedrock, and any OpenAI-compatible endpoint), FRED and Polymarket data vendors, a current-generation model catalog, and a CI gate.
- [2026-05] **TradingAgents v0.2.5** released with the grounded Sentiment Analyst, GPT-5.5 etc. model coverage, Qwen/GLM/MiniMax dual-region support, `TRADINGAGENTS_*` env-var configurability with API-key auto-detection, remote Ollama support, non-US alpha benchmarks, and ticker path-traversal hardening.
- [2026-04] **TradingAgents v0.2.4** released with structured-output agents (Research Manager, Trader, Portfolio Manager), LangGraph checkpoint resume, persistent decision log, DeepSeek/Qwen/GLM/Azure provider support, Docker, and a Windows UTF-8 encoding fix.
- [2026-03] **TradingAgents v0.2.3** released with multi-language support, GPT-5.4 family models, unified model catalog, backtesting date fidelity, and proxy support.
- [2026-03] **TradingAgents v0.2.2** released with GPT-5.4/Gemini 3.1/Claude 4.6 model coverage, five-tier rating scale, OpenAI Responses API, Anthropic effort control, and cross-platform stability.
- [2026-02] **TradingAgents v0.2.0** released with multi-provider LLM support (GPT-5.x, Gemini 3.x, Claude 4.x, Grok 4.x) and improved system architecture.
- [2026-01] **Trading-R1** [Technical Report](https://arxiv.org/abs/2509.11420) released, with [Terminal](https://github.com/TauricResearch/Trading-R1) expected to land soon.

</details>
<!-- news:end -->

<div align="center">

🚀 [TradingAgents](#tradingagents-framework) | ⚡ [Installation & CLI](#installation-and-cli) | 🎬 [Demo](https://www.youtube.com/watch?v=90gr5lwjIho) | 📦 [Package Usage](#tradingagents-package) | 🤝 [Contributing](#contributing) | 📄 [Citation](#citation)

</div>

> 🎉 **TradingAgents** officially released! We have received numerous inquiries about the work, and we would like to express our thanks for the enthusiasm in our community.
>
> So we decided to fully open-source the framework. Looking forward to building impactful projects with you!

## TradingAgents Framework

TradingAgents is a multi-agent trading framework that mirrors the dynamics of real-world trading firms. By deploying specialized LLM-powered agents: from fundamental analysts, sentiment experts, and technical analysts, to trader, risk management team, the platform collaboratively evaluates market conditions and informs trading decisions. Moreover, these agents engage in dynamic discussions to pinpoint the optimal strategy.

<p align="center">
  <img src="assets/schema.png" style="width: 100%; height: auto;">
</p>

> TradingAgents framework is designed for research purposes. Trading performance may vary based on many factors, including the chosen backbone language models, model temperature, trading periods, the quality of data, and other non-deterministic factors. [It is not intended as financial, investment, or trading advice.](https://tauric.ai/disclaimer/)

Our framework decomposes complex trading tasks into specialized roles.

### Analyst Team
- Fundamentals Analyst: Evaluates company financials and performance metrics, identifying intrinsic values and potential red flags.
- Sentiment Analyst: Aggregates news headlines, StockTwits, and Reddit chatter into a single sentiment read to gauge short-term market mood.
- News Analyst: Monitors global news and macroeconomic indicators, interpreting the impact of events on market conditions.
- Technical Analyst: Utilizes technical indicators (like MACD and RSI) to detect trading patterns and forecast price movements.

The selected analysts work at the same time, each on its own tools, and the research debate starts once all of their reports are in.

<p align="center">
  <img src="assets/analyst.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

### Researcher Team
- Comprises both bullish and bearish researchers who critically assess the insights provided by the Analyst Team. Through structured debates, they balance potential gains against inherent risks.

<p align="center">
  <img src="assets/researcher.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Trader Agent
- Composes reports from the analysts and researchers to make informed trading decisions, determining the timing and magnitude of trades.

<p align="center">
  <img src="assets/trader.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Risk Management and Portfolio Manager
- Continuously evaluates portfolio risk by assessing market volatility, liquidity, and other risk factors. The risk management team evaluates and adjusts trading strategies, providing assessment reports to the Portfolio Manager for final decision.
- The Portfolio Manager approves/rejects the transaction proposal. If approved, the order will be sent to the simulated exchange and executed.

<p align="center">
  <img src="assets/risk.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

## Installation and CLI

### Installation

Clone TradingAgents:
```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
```

TradingAgents needs Python 3.11 or later. Create a virtual environment in any of your favorite environment managers:
```bash
conda create -n tradingagents python=3.13
conda activate tradingagents
```

Or with [uv](https://docs.astral.sh/uv/):
```bash
uv venv --python 3.13
source .venv/bin/activate
```

Install the package and its dependencies (`uv pip install .` with uv):
```bash
pip install .
```

### Docker

Alternatively, run with Docker:
```bash
cp .env.example .env  # add your API keys
docker compose run --rm tradingagents
```

After updating the repository, rebuild the image with `docker compose build`.

Results, reports, the memory log and the cache live in the `tradingagents_data` volume. To keep them in a folder on the host instead, create the folder and point `TRADINGAGENTS_DATA_DIR` at it, in `.env` or the shell: `mkdir -p data && TRADINGAGENTS_DATA_DIR=./data docker compose run --rm tradingagents`.

For local models with Ollama:
```bash
docker compose --profile ollama run --rm tradingagents-ollama
```

### Required APIs

TradingAgents supports multiple LLM providers. Set the API key for your chosen provider:

```bash
export OPENAI_API_KEY=...          # OpenAI (GPT)
export GOOGLE_API_KEY=...          # Google (Gemini)
export ANTHROPIC_API_KEY=...       # Anthropic (Claude)
export XAI_API_KEY=...             # xAI (Grok)
export DEEPSEEK_API_KEY=...        # DeepSeek
export DASHSCOPE_API_KEY=...       # Qwen (international, dashscope-intl.aliyuncs.com)
export DASHSCOPE_CN_API_KEY=...    # Qwen (China, dashscope.aliyuncs.com)
export ZHIPU_API_KEY=...           # GLM via Z.AI (international)
export ZHIPU_CN_API_KEY=...        # GLM via BigModel (China, open.bigmodel.cn)
export MINIMAX_API_KEY=...         # MiniMax (global, api.minimax.io)
export MINIMAX_CN_API_KEY=...      # MiniMax (China, api.minimaxi.com)
export OPENROUTER_API_KEY=...      # OpenRouter
export MISTRAL_API_KEY=...         # Mistral
export MOONSHOT_API_KEY=...        # Kimi (Moonshot)
export GROQ_API_KEY=...            # Groq
export NVIDIA_API_KEY=...          # NVIDIA NIM
export FRED_API_KEY=...            # FRED macro data (free, optional)
export ALPHA_VANTAGE_API_KEY=...   # Alpha Vantage
export TYPESAFE_API_KEY=...        # Jev social-post screening (optional)
```

For Azure OpenAI, copy `.env.enterprise.example` to `.env.enterprise` and fill in your credentials.

For AWS Bedrock, install the extra with `pip install ".[bedrock]"`, set `llm_provider: "bedrock"`, configure AWS credentials (environment variables, `~/.aws/credentials`, or an IAM role) and `AWS_DEFAULT_REGION`, and use a Bedrock model ID, e.g. `us.anthropic.claude-opus-5-5`.

For local models, configure Ollama with `llm_provider: "ollama"`. The default endpoint is `http://localhost:11434/v1`; set `OLLAMA_BASE_URL` to point at a remote `ollama-serve`. Pull models with `ollama pull <name>`, and pick "Custom model ID" in the CLI for any model not listed by default.

For any other OpenAI-compatible server (vLLM, LM Studio, llama.cpp, or a custom relay), use `llm_provider: "openai_compatible"` and set the endpoint via `backend_url` (or `TRADINGAGENTS_LLM_BACKEND_URL`), e.g. `http://localhost:8000/v1` for vLLM or `http://localhost:1234/v1` for LM Studio. The model is whatever your server serves. No key is needed for local servers; set `OPENAI_COMPATIBLE_API_KEY` when the endpoint requires one.

With `TYPESAFE_API_KEY` set, the Sentiment Analyst screens StockTwits and Reddit posts with TypeSafe's Jev before reading them. Posts that are not about the company are dropped, and each source opens with a count of the remaining posts by stance: bullish, bearish, neutral, or unclear. Without the key, posts pass through unscreened. `jev-latest` moves with new releases; set `TYPESAFE_DEFAULT_MODEL` to a versioned ID such as `jev-1.13.0` to hold it fixed across runs. To reach Jev through OpenRouter, put an OpenRouter key in `TYPESAFE_API_KEY` and set `TYPESAFE_BASE_URL=https://openrouter.ai/api`.

Alternatively, copy `.env.example` to `.env` and fill in your keys:
```bash
cp .env.example .env
```

### CLI Usage

#### Use a ChatGPT Plus/Pro subscription

For a locally run open-source installation, the `chatgpt` provider uses OpenAI's
[Sign in with ChatGPT](https://developers.openai.com/siwc/token-sharing-open-source)
flow. Eligible Plus/Pro accounts can authorize requests against their ChatGPT
plan without an OpenAI API key:

```bash
pip install ".[chatgpt]"
tradingagents chatgpt login
tradingagents chatgpt models
TRADINGAGENTS_LLM_PROVIDER=chatgpt tradingagents
```

Finish sign-in and approve ChatGPT plan usage in the browser. The model picker
reads the signed-in account's available models. For unattended runs, also set
`TRADINGAGENTS_QUICK_THINK_LLM` and `TRADINGAGENTS_DEEP_THINK_LLM` to model IDs
listed by `tradingagents chatgpt models`, along with the other headless settings
below. A tier can use this provider on its own through
`TRADINGAGENTS_QUICK_THINK_PROVIDER=chatgpt` or `TRADINGAGENTS_DEEP_THINK_PROVIDER=chatgpt`.

Registrations and tokens are stored in `~/.tradingagents/chatgpt/auth.json`,
with owner-only permissions on Unix. Token refresh is automatic and serialized
across runs. `tradingagents chatgpt accounts` lists saved registrations;
`tradingagents chatgpt login --new-account` adds one, and
`tradingagents chatgpt login --account <client_id>` selects and reconnects it.
`tradingagents chatgpt logout` signs out the active account.

Requests use the public Responses API with streaming and `store=false`.
Custom backend URLs, temperature and output-token caps are unavailable on this
route. Plan usage limits still apply; manage them in
[ChatGPT Settings → Usage](https://chatgpt.com/settings/usage).
The provider never falls back to API-key billing. OpenAI's current
[preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
and account eligibility apply. Paid or remotely hosted products require
separate access from OpenAI.

#### Run an analysis

Launch the interactive CLI:
```bash
tradingagents          # installed command
python -m cli.main     # alternative: run directly from source
```
You will see a screen where you can select your desired tickers, analysis date, LLM provider, research depth, and more. Your previous run's answers come back as the defaults, so pressing Enter accepts them. The `TRADINGAGENTS_*` variables in `.env` still skip their step entirely.

To run without questions, for a scheduled job or a script, answer the per-run steps with flags and the rest with `TRADINGAGENTS_*` variables:
```bash
export TRADINGAGENTS_LLM_PROVIDER=openai TRADINGAGENTS_QUICK_THINK_LLM=gpt-6-luna TRADINGAGENTS_DEEP_THINK_LLM=gpt-6-sol
export TRADINGAGENTS_OUTPUT_LANGUAGE=English TRADINGAGENTS_MAX_DEBATE_ROUNDS=1 TRADINGAGENTS_MAX_RISK_ROUNDS=1
tradingagents --ticker NVDA --date 2026-09-23 --analysts market,news,fundamentals --save --no-show
```
Each flag skips only its own question. Run without a terminal, a missing answer stops the run before it starts and names the flag or variable to set.

A saved report also includes `complete_report.html`, the report as one page with its sections listed beside the text, for reading in a browser, on a phone or in print. Answering the save question at the prompt also asks about the page and can open it in your browser; `--no-html` skips it, and so does `ta.save_reports(state, "NVDA", html=False)` from Python.

### Local research dashboard and paper portfolio

The optional local dashboard adds a persistent US-stock/ETF watchlist, Yahoo price
charts, live analysis progress, saved daily reports, proposed trade plans, and a
local simulator plus optional automated Alpaca paper orders. It uses this checkout's engine and configured models,
including the `chatgpt` subscription provider:

```bash
pip install -e ".[chatgpt,dashboard]"
tradingagents-dashboard
```

Open `http://127.0.0.1:8000`. Use `--port 8001` if that port is occupied.
The server binds only to loopback. Adding a ticker does not call a model;
**Analyze** starts one full analysis, with one analysis allowed at a time.
Manual analyses receive the local simulator's holdings and cash; automated
cycles receive the Alpaca paper account's book. Historical CLI reports also
appear in the dashboard.

The paper portfolio starts with **$100,000 virtual USD**, supports whole-share
long positions, and records buys/sells only when you click a paper-trade button.
These manual buttons never send broker orders. Fills use the latest available Yahoo daily-bar
price, which can be a partial bar during market hours; fees and slippage are
not modeled. Price dates are shown beside charts, positions and fills. Cash,
cost basis and realized P&L use integer cents with transactional writes and
duplicate-submission protection. State lives in
`~/.tradingagents/dashboard/paper.sqlite3`; the UI shows the last 100 fills.
Daily research history follows the engine's existing one-state-per-ticker/date
logs, while complete timestamped reports are also saved on disk.

For online forward testing, enter **paper** account keys directly in the
dashboard's password fields, then choose managed watchlist symbols and **Enable
daily runs**. Credentials stay in a private `alpaca-paper.json` beside the local
database. The REST host is fixed to `https://paper-api.alpaca.markets`; there is
no live-trading mode. Use a dedicated long-only USD paper account. API connection
alone does not enable orders. No new dependencies are needed for Alpaca.

On macOS/Linux, the worker starts research at **10:00 America/New_York** on open
market days, processes symbols serially, and catches up if started later in the
session. **Run one cycle now** can start at the regular-session open. It checks
Alpaca's exchange clock, including holidays and early closes, and sends no new
orders within 30 minutes of closing. Positions carry overnight and are reviewed
daily; there is no forced holding period or automatic stop-loss. This is
multi-minute daily research, **not HFT**. Keep the server running and Mac awake.

The fixed execution policy interprets final ratings: **Buy** targets 10% of
equity, **Overweight** 5%, **Hold** keeps holdings, **Underweight** sells half
(rounded up), **Sell** exits, and unreadable decisions do nothing. Buy targets
only add shares; they do not trim positions that have appreciated. Buys use
cash, a 10% cash reserve and a 40% total invested ceiling at sizing time. Whole
shares only, no shorts/margin. Fresh IEX bid/ask quotes must be within five
minutes and have at most a 1% spread. DAY limit orders allow 0.5% around the
quoted ask/bid, with no extended-hours execution.

Each account/symbol/day gets one durable attempt and a deterministic client
order ID. A local process lock serializes workers sharing a database. Failed
research, paused or late cycles do not submit orders. Open orders block further
submissions. Uncertain network submissions are looked up by client ID and never
blindly resubmitted; an unresolved missing order blocks future cycles until
manually investigated. A failed/skipped symbol resumes on the next market day.
Do not run separate databases against the same account. Pause prevents further
submissions but leaves existing DAY orders at Alpaca; cancel those in Alpaca.

The dashboard shows actual paper account equity, positions, order statuses,
partial/full fills and a research/execution journal separately from the local
manual ledger. Alpaca's simulated fills omit some live trading costs and
liquidity effects. Measure forward outcomes against a simple benchmark
and the same models without debate before assuming the extra model calls help.
The engine's decision-memory/backtest scores are separate from the paper
portfolio's cash and fill ledger.

The execution selector also offers an **automatic local snapshot simulator**
without broker keys. It has its own $100,000 ledger in `forward.sqlite3`,
separate from both Alpaca and the card buttons' manual ledger. It uses the same
rating/sizing policy with 0.05% adverse slippage per side, rounded to cents.
Daily local cycles start at **16:30 America/New_York** and require a Yahoo bar
for that date, so weekends and holidays do not produce stale-price fills.
Run-now tests may use partial daily bars. These instant simulated fills do not
model liquidity, latency or fees and do not substitute for broker execution.
Switching modes pauses daily automation; run-once preserves an existing daily
schedule. A cycle already attempted that day is not repeated.

Each automated attempt saves an immutable research snapshot in the order
journal, even if another manual analysis later overwrites the normal daily
report. Performance samples before/after cycles persist in `paper_equity` in
the main database. The dashboard plots cumulative account and SPY price
returns, sampled P&L and sampled drawdown. SPY uses cached Yahoo snapshots,
excludes dividends and may differ in timing from broker marks. These sparse
samples cannot measure the full intraday drawdown. Run the forward test over
multiple weeks and compare drawdown, return and execution failures before
drawing conclusions; the initial run only verifies the plumbing.

Current social inputs are Yahoo headlines, StockTwits and Reddit RSS. There is
no X/Twitter feed or streaming quote connection. FRED needs its own key, and
source outages and incomplete historical social coverage still apply.

For unattended operation on **macOS**, run this from the configured checkout
with its virtual environment, after any active research has finished:

```bash
.venv/bin/python -m tradingagents.dashboard.operations install
```

This installs three private per-user LaunchAgents. `dev.tradingagents.dashboard`
starts at login and restarts after process exit; `caffeinate -s` prevents idle
system sleep while connected to AC power. The display can still sleep. After a
reboot you must log in; a powered-off Mac, closed lid, forced sleep, lost network
or expired/revoked credentials can still interrupt operation. Keep this checkout
and virtual environment at the installed location. Installing again updates the
jobs and restarts the server; it does not reset credentials, journals or daily
attempts. Completed attempts are never repeated, interrupted research is marked
as failed without an order and resumes the next market day, and uncertain broker
submissions are reconciled by their existing client IDs.

`dev.tradingagents.progress` checks the dashboard at login and daily at **14:15
in the Mac's local timezone** (17:15 New York when the Mac is set to Los Angeles).
It creates timestamped private snapshots and consistent SQLite backups under
`~/.tradingagents/dashboard/progress/`, including account equity, positions,
fills, research outcomes, model settings and the existing sampled SPY comparison.
Credentials are excluded. The check reports a stopped/stale scheduler, paused
automation, unavailable account, failed attempts, uncertain submissions, rejected
orders and missing research after an exchange trading day closes. Market holidays
come from Alpaca's calendar. It only reads broker data and never submits an order.
These are local backups, so disk loss still loses them; they are not cloud copies.
Checks and backups accumulate for the baseline test and should be archived or
pruned when extending it beyond the initial few weeks.

Run a check now, or inspect the health endpoint without calling the broker:

```bash
.venv/bin/python -m tradingagents.dashboard.operations check
curl --fail http://127.0.0.1:8000/api/health
launchctl print gui/$(id -u)/dev.tradingagents.dashboard
```

The health endpoint returns 503 if the scheduler stops, stops polling for two
minutes, or encounters a scheduler error. Temporary scheduler errors retry every
30 seconds. The paper status line also exposes scheduler failures. Runtime logs
are in `~/.tradingagents/logs/dashboard.console.log`; progress-check summaries are
in `progress.console.log` in the same directory. A healthy process does not
guarantee every upstream source is available or that an analysis will succeed.

For the initial baseline, review roughly ten market sessions of run completion,
fills, return, SPY comparison and sampled drawdown. Record any changes to models,
managed companies or sizing rules. This period checks operation, not profitability.
X remains disconnected during this baseline. A later X experiment should compare
parallel recommendations using the same inputs/cutoff except for X, initially
without changing the baseline paper account's orders.

The interface styling is adapted from
[flo007ro's community dashboard](https://github.com/flo007ro/TradingAgents/tree/06610d7aad93b6bf42528d248199a1d18c73c901)
under Apache-2.0; see `tradingagents/dashboard/NOTICE`. Its backend, paper ledger
and browser application have been replaced to use the current engine, real
outputs and this installation's saved configuration. This is a local community
interface, separate from Tauric Research's hosted services.

### Markets and tickers

TradingAgents works with any market Yahoo Finance covers, using the exchange-suffixed ticker. Company identity and the alpha benchmark resolve automatically per market.

- US: `AAPL`, `SPY`
- Hong Kong: `0700.HK` · Tokyo: `7203.T` · London: `AZN.L`
- India: `RELIANCE.NS`, `.BO` · Canada: `.TO` · Australia: `.AX`
- China A-shares: Shanghai `.SS`, Shenzhen `.SZ` (e.g. `600519.SS` for Kweichow Moutai)
- Crypto: `BTC-USD`, `ETH-USD`

<p align="center">
  <img src="assets/cli/cli_init.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

An interface will appear showing results as they load, letting you track the agent's progress as it runs.

<p align="center">
  <img src="assets/cli/cli_news.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

<p align="center">
  <img src="assets/cli/cli_transaction.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

## TradingAgents Package

### Implementation Details

We built TradingAgents with LangGraph to ensure flexibility and modularity. The framework supports multiple LLM providers: OpenAI, Google, Anthropic, xAI, DeepSeek, Qwen (Alibaba DashScope, international and China endpoints), GLM (Zhipu), MiniMax (global + China), OpenRouter, Ollama for local models, and Azure OpenAI for enterprise.

### Python Usage

To use TradingAgents inside your code, you can import the `tradingagents` module and initialize a `TradingAgentsGraph()` object. The `.propagate()` function will return a decision. You can run `main.py`, here's also a quick example:

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())

# forward propagate
state, decision = ta.propagate("NVDA", "2026-09-01")
print(decision)

# the same report tree the CLI saves, under results_dir/reports
ta.save_reports(state, "NVDA")
```

You can also adjust the default configuration to set your own choice of LLMs, debate rounds, etc.

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"        # e.g. openai, google, anthropic, deepseek, groq, ollama; openai_compatible covers any OpenAI-compatible endpoint (vLLM, LM Studio, llama.cpp, ...)
config["deep_think_llm"] = "gpt-6-sol"    # Model for complex reasoning
config["quick_think_llm"] = "gpt-6-luna"   # Model for quick tasks
config["max_debate_rounds"] = 2

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("NVDA", "2026-09-01")
print(decision)
```

The quick model serves the analysts, researchers, debaters and trader; the deep model serves the research and portfolio managers. Each can run on its own provider, for example the managers on Claude while the rest run on OpenAI:

```python
config["deep_think_provider"] = "anthropic"
config["deep_think_llm"] = "claude-opus-5-5"
```

A tier on its own provider uses that provider's key and default endpoint; set `quick_think_backend_url` or `deep_think_backend_url` for a local or relay endpoint. The `TRADINGAGENTS_DEEP_THINK_PROVIDER` and `TRADINGAGENTS_QUICK_THINK_PROVIDER` variables set them for the CLI, together with the tier's model variable.

See `tradingagents/default_config.py` for all configuration options.

### Fundamentals as filed

US company statements come from SEC EDGAR, which records the date every figure was filed. A run dated in the past reads the statements exactly as they stood that day: a fiscal year that has ended but has not been filed yet is not served, and a figure restated later still reads as first reported. Apple's 2008 total assets were filed as $39.6B and restated to $36.2B in 2010, so a run dated in between reads $39.6B. EDGAR needs no account or API key.

Other companies' statements come from Yahoo Finance, which dates a statement by the period it covers rather than by when it was published. A run dated today reads them; a run dated in the past is told they are withheld, since Yahoo cannot say which figures were public by then.

Insider trades are dated by when they happened, not when they were filed, so a run dated in the past is told they are withheld as well.

SEC asks callers to identify themselves and refuses requests that carry no contact address, so a default one is sent. Set your own so SEC can reach you rather than the project:

```bash
SEC_EDGAR_USER_AGENT="Your Name your@email.com"
```

It covers companies that file with the SEC, including foreign companies listed in the US. Anything else, such as Hong Kong or A-share listings, falls through to the next vendor in the chain. EDGAR's machine-readable filings begin in 2009, and a fourth quarter is reported as unavailable rather than derived, because filers publish it only inside the annual figure.

### Current holdings

By default the agents do not know what you hold, so their guidance is written for a reader who applies it to their own position. Pass a portfolio to have the trader, the risk analysts and the portfolio manager work against your actual book.

```python
from tradingagents.portfolio import PortfolioContext

portfolio = PortfolioContext.model_validate({
    "cash": 25000.0,
    "currency": "USD",
    "positions": [{"ticker": "NVDA", "quantity": 120, "average_price": 150.0}],
})
_, decision = ta.propagate("NVDA", "2026-09-01", portfolio=portfolio)
```

The CLI takes the same content as a JSON file: `tradingagents --portfolio my_book.json`.

An empty `positions` list means a flat book, which is different from passing nothing. A run without a portfolio is never treated as flat.

## Persistence and Recovery

TradingAgents persists two kinds of state across runs.

### Memory log

The memory log is always on. Each completed run appends its decision to `~/.tradingagents/memory/trading_memory.md`. While the analysts of a later run work, TradingAgents settles every logged decision whose holding period has passed: it fetches the realised return (raw, and alpha against the instrument's regional benchmark) and generates a one-paragraph reflection. The Portfolio Manager then reads the most recent decisions for the same ticker plus recent lessons from other tickers, so each analysis carries forward what worked and what didn't. If settling fails, the run goes on and its report says so.

Override the path with `TRADINGAGENTS_MEMORY_LOG_PATH`.

To settle decisions without running an analysis, for a scheduled job, call `ta.settle_all_pending()`; it returns the decisions it settled and any it could not.

### Checkpoint resume

Checkpoint resume is opt-in via `--checkpoint`. When enabled, LangGraph saves state after each node so a crashed or interrupted run resumes from the last successful step instead of starting over. The run view says whether it resumed a saved run or started fresh. Checkpoints are cleared automatically on successful completion.

Per-ticker SQLite databases live at `~/.tradingagents/cache/checkpoints/<TICKER>.db` (override the base with `TRADINGAGENTS_CACHE_DIR`). Use `--clear-checkpoints` to reset all of them before a run.

```bash
tradingagents --checkpoint           # enable for this run
tradingagents --clear-checkpoints    # reset before running
```

```python
config = DEFAULT_CONFIG.copy()
config["checkpoint_enabled"] = True
ta = TradingAgentsGraph(config=config)
_, decision = ta.propagate("NVDA", "2026-09-01")
```

## Evaluating decisions over time

One run gives one decision, which cannot tell you whether the system decides well. `run_backtest` runs the same pipeline over a grid of tickers and dates, writes to a memory log of its own, and scores the decisions whose holding window has since traded.

```python
from tradingagents.backtest import iter_grid, run_backtest, summarize

dates = iter_grid("2026-06-01", "2026-08-01", every_n_days=7)
result = run_backtest(["NVDA", "AAPL"], dates, config, selected_analysts=["market", "news"])
print(summarize(result).render())
```

From the CLI:

```bash
tradingagents backtest NVDA,AAPL --start 2026-06-01 --end 2026-08-01 --every 7
```

Each cell is scored on realized alpha against the instrument's regional benchmark, grouped by rating. Your own memory log is never written to, and re-running the same grid with `run_id=result.run_id` skips the cells that already ran, so an interrupted sweep continues where it stopped.

To compare portfolio behavior of simple price rules separately from the agent
decision evaluator:

```bash
.venv/bin/python -m tradingagents.strategy_comparison \
  --tickers AAPL,MSFT,NVDA,JPM --start 2023-01-03 --end 2026-10-15
```

This runs buy-and-hold, a 50/200-session moving-average trend rule, and positive
126-session momentum, plus cash and SPY references. All signals are shifted to
the following session's open. Each strategy starts with $100,000; basket entries
target up to 10% per company under a 40% purchase-exposure ceiling, with no daily
rebalancing. Holdings can drift above those percentages. SPY is shown both at
the basket's matched initial allocation and at 100% exposure. The latter has a
different risk budget. Runs compare 5 and 20 basis points of adverse slippage per
fill and report total return, CAGR, daily-close maximum drawdown, average exposure
and fill count. No parameter search or automatic strategy promotion is performed.

These are fractional **adjusted-price return simulations**, not historical
broker shares or the Alpaca limit-order policy. Yahoo dividend/split-adjusted
OHLC is used; commissions, taxes, cash interest, liquidity and market impact are
omitted. Open positions are valued at the final close without exit costs. An
entirely completed historical range and 200 warm-up sessions are required;
missing prices or benchmark sessions fail instead of being filled. The selected
companies are chosen today, so survivorship/selection bias remains. The results
do not measure TradingAgents' performance or establish future profitability.

Every run saves private input CSVs, their SHA-256 hashes, full simulated fills,
equity curves, assumptions, `results.json` and `report.html` under
`~/.tradingagents/experiments/strategies/`. The frozen CSVs support reproducing
the calculation independently of later Yahoo revisions. Paper account settings,
credentials, holdings and the live memory log are untouched.

To compare the actual native agent pipeline, add `--agents`. Start with a small
grid because this calls the configured models twice per ticker/date:

```bash
.venv/bin/python -m tradingagents.strategy_comparison --agents \
  --tickers NVDA --start 2026-10-02 --end 2026-10-02
```

This compares a market-only analyst configuration with all four analysts; both
retain the bull/bear, trader and risk/portfolio-manager stages. It uses the native
five-session decision scoring, not a carried portfolio. Experiments have separate
memory logs and checkpoint caches under `~/.tradingagents/experiments/agents/`.
Completed cells also export the engine's full research report, including its
model settings, in HTML and text beside each variant's memory log.
One bounded retry reuses the native run ID, skips completed cells and resumes a
failed cell when checkpointing is enabled. Original failures remain in the
attempt history. Historical text coverage is incomplete, model training may
contain later events, and a single model sample per cell is not a blind historical
test. Treat a small grid as an execution/coverage diagnostic; compare configurations
prospectively before changing paper execution. The existing native backtest API
can continue a saved run by reusing its experiment results directory and run ID.
After the prior process stops, the comparison command can also continue that
same folder with `--agents --resume /absolute/path/to/experiment` and the original
companies, dates and model settings. It keeps the earlier failures in the attempt
history. Remaining cell or settlement failures cause a nonzero command exit.

For a broader, fixed comparison, `--every` controls the calendar spacing of
analysis dates. This example runs eight companies at five quarterly dates
(2025-10-06, 2026-01-05, 2026-04-06, 2026-07-06 and 2026-10-05), or 80 native
decisions across the two configurations:

```bash
.venv/bin/python -m tradingagents.strategy_comparison --agents \
  --tickers AAPL,MSFT,NVDA,JPM,XOM,UNH,WMT,CAT \
  --start 2025-10-06 --end 2026-10-05 --every 91
```

Choose actual exchange sessions with completed outcome windows; the date grid
does not skip holidays automatically. Each cell start updates private
`results.json` with its active company/date, completed summary, elapsed time and
observed model/tool calls and tokens. Usage includes retries and reflection,
but interrupted responses can omit token counts; these are not dollar costs or
a conversion to ChatGPT subscription credits. Completed calls from before this
instrumentation are excluded. Only one process can hold an experiment at a time.
An interrupted process can resume its original folder with the same command plus
`--resume`; completed decisions are skipped. A wider historical study remains
exploratory: model training leakage, missing old text, selected surviving
companies and shared market dates prevent treating these cells as independent
proof of a trading edge. The daily paper account already uses the full agent
team, with fixed execution controls; comparisons do not change that account.

### Sector strategy lab and prospective journal

Open **http://127.0.0.1:8000/experiments** from the dashboard's **Strategy lab**
link. It reads saved experiments without calling models, fetching prices or
submitting orders. Choose a historical slice, cost assumption and return or
drawdown view; exposure, activity and risk details are expandable.

```bash
# Fixed 23-fund / 11-sector study: 564 simulations, no models or broker calls.
.venv/bin/python -m tradingagents.sector_study

# Read a native study's frozen inputs; write an isolated deterministic sidecar.
.venv/bin/python -m tradingagents.agent_benchmarks /absolute/native/study/folder

# Capture only after New York's close, then score previously captured signals.
.venv/bin/python -m tradingagents.strategy_shadow run
```

The fixed rules, chronological slices, costs, assumptions and research sources
are in [EXPERIMENTS.md](EXPERIMENTS.md). Price inputs, plan hashes, curves and
fills stay private under `~/.tradingagents/experiments/sectors/`. The lab compares
each single-fund rule with its own 40%-entry buy-and-hold sleeve. Sector rotation
has different entry weights from the all-sector basket, and holdings drift.
Every historical slice is exploratory; the evaluation period is not a pristine
unseen holdout. A descriptive consistency shortlist never changes execution.

The native comparison pairs both agent teams and deterministic forecasts on
identical resolved company/date cells using verified frozen prices. It reports
forecast-direction scores, not executable portfolio returns. Pending and
unreadable decisions remain visible. Mixed horizons, overlapping studies and
different model/data settings are excluded from pooled scores.

The service installer also adds `dev.tradingagents.strategy-shadow`, at login
and daily **14:45 in the Mac's local timezone** (17:45 New York when the Mac is
set to Los Angeles). It captures 92 fixed fund/rule forecasts per completed
market day plus sector membership, with private immutable daily inputs and
hashes under `~/.tradingagents/experiments/shadow/`. Before 16:30 New York,
weekends and missing current-session data produce no backdated prediction.
If the Mac's timezone changes, adjust/reinstall the calendar jobs to remain
after New York's close. A missed day is not backfilled.

Outcomes use the next session's adjusted open and 5, 20 or 63 sessions,
including entry as session one. Both endpoints use the same newly fetched
adjustment basis; rescoring may reflect vendor revisions. Overlapping forecast
scores are correlated and not compounded into portfolio P&L. Local timestamps
are not independent attestations. This journal calls no models or brokers;
it tests fresh price-rule forecasts while the separate agent-driven Alpaca
baseline continues. Broader historical agent studies are still subject to
training leakage and incomplete text. Keep this Mac logged in and online.

## Reproducibility

TradingAgents is LLM-driven, so two runs of the same ticker and date can differ. This is expected for a research tool built on language models, not a defect. The variation comes from a few distinct sources, and it helps to separate them.

Language model sampling is non-deterministic. Even at a fixed temperature, providers do not guarantee byte-identical output across calls, and reasoning models (the default GPT-6 family, and any thinking-mode model) vary the most because their internal reasoning is itself sampled.

Live data moves. News, StockTwits, and Reddit return different content as time passes, so a run today sees different inputs than a run last week even for the same historical trade date. Pin the analysis date to hold the price and indicator window fixed, but the social and news sources still reflect "now".

To reduce variation you can lower the sampling temperature. Set `temperature` in your config (or `TRADINGAGENTS_TEMPERATURE` in `.env`); lower values make models that honor it more repeatable. The current curated models are reasoning-first and largely ignore temperature, so for tighter reproducibility name a non-reasoning model in your config, or in `TRADINGAGENTS_DEEP_THINK_LLM` and `TRADINGAGENTS_QUICK_THINK_LLM`. Any model ID your provider serves is accepted, whether or not the picker lists it.

```python
config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"
config["temperature"] = 0.0
# Reasoning models ignore temperature. For tighter reproducibility, name a
# non-reasoning model in deep_think_llm / quick_think_llm.
```

What does not vary anymore: the analyzed company identity is resolved deterministically from the ticker before any agent runs, and the market analyst grounds exact price and indicator claims in a verified data snapshot. Earlier reports of "different companies" or fabricated price levels across runs are addressed by these two mechanisms.

Backtest results are not guaranteed to match any published figure. Returns depend on the model, the temperature, the date range, data quality, and the sampling above. Treat the framework as a research scaffold for studying multi-agent analysis, not as a strategy with a fixed, replicable return.

## Contributing

Contributions are welcome: bug fixes, documentation, and feature ideas; past contributions are credited per release in [`CHANGELOG.md`](CHANGELOG.md).

## Citation

Please reference our work if you find *TradingAgents* provides you with some help :)

```
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework}, 
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138}, 
}
```
