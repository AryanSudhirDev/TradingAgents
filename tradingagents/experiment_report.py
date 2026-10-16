"""Read-only experiment summaries for the local dashboard and saved HTML."""

import json
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from tradingagents.agent_benchmarks import compare_study, forecast_summary
from tradingagents.sector_study import ASSETS, RULE_LABELS, SOURCES, WINDOWS


def lab_snapshot():
    root = Path.home() / ".tradingagents/experiments"
    snapshot = {"as_of": datetime.now(UTC).isoformat(), "sectors": None, "agents": [], "shadow": {}, "errors": []}
    for path in sorted((root / "sectors").glob("*/results.json"), reverse=True)[:1]:
        try:
            saved = json.loads(path.read_text())
            saved["results"] = [{k: v for k, v in r.items() if k not in ("curve", "fills")} for r in saved.get("results", [])]
            snapshot["sectors"] = saved
        except (OSError, ValueError, TypeError):
            snapshot["errors"].append("The latest sector report could not be read; refresh after the write completes.")
    seen, signature = set(), None
    for path in sorted((root / "agents").glob("*/results.json")):
        try:
            manifest = json.loads(path.read_text())
            if manifest.get("planned_decisions", 0) < 50:
                continue
            if manifest.get("holding_sessions") != 5:
                snapshot["errors"].append("An experiment with a different outcome horizon was excluded from five-session comparisons.")
                continue
            settings = manifest.get("settings_hash")
            keys = {(t, d) for t in manifest["tickers"] for d in manifest["dates"]}
            if keys & seen or (signature is not None and settings != signature):
                snapshot["errors"].append("An overlapping or differently configured agent study was excluded from the pooled comparison.")
                continue
            snapshot["agents"].append(compare_study(path.parent))
            seen.update(keys)
            signature = settings
        except (OSError, ValueError, KeyError, TypeError):
            snapshot["errors"].append("A native study is unavailable or failed frozen-input validation; inspect its private logs.")
    forecasts = sorted((root / "shadow").glob("*/forecast.json"))
    try:
        completed = [json.loads(p.read_text()) for p in forecasts]
        completed = [f for f in completed if f.get("status") == "complete"]
        scores = root / "shadow/scores.json"
        score_data = json.loads(scores.read_text()) if scores.is_file() else {}
        snapshot["shadow"] = {"recorded_days": len(completed), "last_capture": completed[-1].get("created_at") if completed else None,
                              "complete": score_data.get("complete", 0), "pending": score_data.get("pending", 0),
                              "scheduled": (Path.home() / "Library/LaunchAgents/dev.tradingagents.strategy-shadow.plist").is_file()}
    except (OSError, ValueError, TypeError):
        snapshot["errors"].append("The prospective journal summary could not be read; refresh or inspect its private log.")
    return snapshot


def forward_candidates(rows):
    """Descriptive, fixed consistency screen; never promotes a strategy."""
    indexed = {(r["ticker"], r["rule"], r["window"]): r for r in rows if r["slippage_bps"] == 20}
    candidates = []
    for ticker, rule, window in indexed:
        if window != "validation" or rule in ("buy_hold", "sector_hold"):
            continue
        pair = [indexed.get((ticker, rule, w)) for w in ("validation", "evaluation")]
        if any(r is None for r in pair):
            continue
        baselines = [indexed.get((ticker, r["benchmark_rule"], r["window"])) for r in pair]
        if all(b is not None and r["excess_return_pct"] > 0 and r["max_drawdown_pct"] >= b["max_drawdown_pct"]
               for r, b in zip(pair, baselines, strict=True)):
            candidates.append({"ticker": ticker, "rule": rule, "minimum_excess_pp": min(r["excess_return_pct"] for r in pair)})
    return sorted(candidates, key=lambda c: c["minimum_excess_pp"], reverse=True)


def _number(value, suffix="%"):
    return "—" if value is None else f"{value:+.2f}{suffix}"


def _cell(value, suffix="%"):
    tone = "positive" if value is not None and value > 0 else "negative" if value is not None and value < 0 else ""
    return f'<td class="{tone}">{_number(value, suffix)}</td>'


def render_lab(snapshot, window="evaluation", cost=20, metric="excess"):
    if window not in WINDOWS or cost not in (5, 20) or metric not in ("excess", "return", "drawdown"):
        raise ValueError("Choose an available period, metric and trading-cost assumption.")
    sector = snapshot.get("sectors") or {}
    rows = sector.get("results", [])
    selected = {(r["ticker"], r["rule"]): r for r in rows if r["window"] == window and r["slippage_bps"] == cost}
    timing_rules = ("sma_50_200", "momentum_252", "weekly_reversal")
    field = {"excess": "excess_return_pct", "return": "return_pct", "drawdown": "max_drawdown_pct"}[metric]
    suffix = " pp" if metric == "excess" else "%"
    matrix = []
    for ticker, asset in ASSETS.items():
        baseline = selected.get((ticker, "buy_hold"))
        if not baseline:
            continue
        first = f'<th scope="row">{escape(ticker)}<small>{escape(asset["label"])}</small></th>'
        baseline_field = "max_drawdown_pct" if metric == "drawdown" else "return_pct"
        matrix.append("<tr>" + first + _cell(baseline[baseline_field])
                      + "".join(_cell(selected.get((ticker, r), {}).get(field), suffix) for r in timing_rules) + "</tr>")
    candidates = forward_candidates(rows)
    shortlist = "".join(f'<li><strong>{escape(c["ticker"])}</strong> · {escape(RULE_LABELS[c["rule"]])}: smaller excess across the two slices {_number(c["minimum_excess_pp"], " pp")}</li>' for c in candidates[:6])
    if not shortlist:
        shortlist = "<li>No combination passed the fixed consistency screen.</li>"
    baskets = []
    for rule in ("sector_hold", "sector_momentum_12_1"):
        row = selected.get(("SECTORS", rule))
        if row:
            baskets.append(f'<tr><th scope="row">{escape(RULE_LABELS[rule])}</th>' + _cell(row["return_pct"])
                           + _cell(row["max_drawdown_pct"]) + f'<td>{row["average_exposure_pct"]:.1f}%</td><td>{row["fill_count"]}</td></tr>')
    agent_rows, scores = [], []
    requested = saved = paired = 0
    for study in snapshot.get("agents", []):
        coverage = study["coverage"]
        requested += sum(v["requested"] for v in coverage.values())
        count = sum(v["saved"] for v in coverage.values())
        saved += count
        paired += study["paired_resolved_cells"]
        scores.extend(study["scores"])
        agent_rows.append(f'<tr><th scope="row">{escape(", ".join(study["tickers"]))}</th><td>{escape(str(study.get("status")))}</td><td>{count}/{sum(v["requested"] for v in coverage.values())}</td><td>{study["paired_resolved_cells"]}/{study["expected_cells"]}</td></tr>')
    forecasts = []
    for name in ("buy_hold", *timing_rules, "market_only", "full"):
        score = forecast_summary([s for s in scores if s["arm"] == name])
        label = RULE_LABELS.get(name, {"market_only": "Market-only agent team", "full": "Full agent team"}.get(name, name))
        forecasts.append(f'<tr><th scope="row">{escape(label)}</th><td>{score["cells"]}</td><td>{score["holds"]}</td>'
                         + _cell(score["direction_hit_rate"] * 100 if score["direction_hit_rate"] is not None else None)
                         + _cell(score["mean_signed_alpha_pct"], " pp") + "</tr>")
    sectors = []
    for label in sorted({s["sector"] for s in scores}):
        arms = {n: forecast_summary([s for s in scores if s["sector"] == label and s["arm"] == n]) for n in ("buy_hold", "market_only", "full")}
        sectors.append(f'<tr><th scope="row">{escape(label)}</th><td>{arms["full"]["cells"]}</td>'
                       + "".join(_cell(arms[n]["mean_signed_alpha_pct"], " pp") for n in arms) + "</tr>")
    details = []
    for row in selected.values():
        sharpe = "—" if row["sharpe_zero_cash"] is None else f'{row["sharpe_zero_cash"]:.2f}'
        details.append(f'<tr><th scope="row">{escape(row["ticker"])} · {escape(RULE_LABELS[row["rule"]])}</th><td>{row["average_exposure_pct"]:.1f}%</td><td>{row["fill_count"]}</td><td>{row["annualized_volatility_pct"]:.2f}%</td><td>{sharpe}</td><td>{row["traded_notional_pct_initial"]:.1f}%</td></tr>')
    def options(values, chosen):
        return "".join(f'<option value="{escape(str(v))}"{" selected" if v == chosen else ""}>{escape(str(label))}</option>' for v, label in values)
    window_options = options(((w, f'{w.title()} · {b["start"]} to {b["end"]}') for w, b in WINDOWS.items()), window)
    cost_options = options(((5, "5 bps per fill"), (20, "20 bps per fill: higher cost")), cost)
    metric_options = options((("excess", "Excess over own buy-and-hold"), ("return", "Total portfolio return"), ("drawdown", "Maximum drawdown")), metric)
    errors = "".join(f'<p class="warning">{escape(e)}</p>' for e in snapshot.get("errors", []))
    assumptions = "".join(f"<li>{escape(a)}</li>" for a in sector.get("assumptions", []))
    sources = " · ".join(f'<a href="{escape(s["url"])}" target="_blank" rel="noreferrer">{escape(s["title"])}</a>' for s in SOURCES)
    status = escape(str(sector.get("status", "not run")))
    shadow = snapshot.get("shadow", {})
    shadow_state = "Daily capture scheduled" if shadow.get("scheduled") else "Daily capture not installed"
    usage = {k: sum(a["usage"].get(k, 0) for a in snapshot.get("agents", [])) for k in ("llm_calls", "tokens_in", "tokens_out")}
    metric_heading = {"excess": "Excess return in percentage points", "return": "Cumulative portfolio return", "drawdown": "Daily-close maximum drawdown"}[metric]
    benchmark_heading = "Hold drawdown" if metric == "drawdown" else "Hold return"
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Strategy lab</title>
<style>
body{{margin:0;color:var(--foreground,#20262e);font:14px/1.5 var(--font-sans,system-ui);background:transparent}}main{{max-width:1120px;margin:auto}}h1{{font-size:24px;font-weight:550;margin:14px 0 6px}}h2{{font-size:18px;font-weight:550;margin:26px 0 8px}}p{{max-width:90ch}}a{{color:var(--accent,#1760aa)}}.muted,small{{color:var(--muted-foreground,#616873)}}small{{display:block;font-weight:400;font-size:12px}}.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}}.card{{padding:16px;background:var(--secondary,#f1f3f5);border-radius:var(--radius,9px);min-width:125px}}.card strong{{display:block;font-size:22px;font-weight:550}}form{{display:flex;align-items:end;gap:12px;flex-wrap:wrap;margin:16px 0}}label{{display:flex;flex-direction:column;gap:4px}}select,button{{font:inherit;padding:8px;max-width:100%;border:1px solid var(--border,#b8bfc9);border-radius:6px;color:inherit;background:var(--background,#fff)}}button{{cursor:pointer}}.scroll{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}}th,td{{padding:9px 8px;text-align:right;border-bottom:1px solid var(--border,#d4d9df);vertical-align:top}}th:first-child,td:first-child{{text-align:left}}th{{font-weight:550}}.positive{{color:var(--success-foreground,#176348)}}.negative{{color:var(--destructive,#a23737)}}.warning{{color:var(--warning-foreground,#855900)}}details{{margin:18px 0}}summary{{cursor:pointer;font-weight:500}}li{{margin:8px 0}}.sources{{font-size:12px}}@media(max-width:550px){{h1{{font-size:21px}}table{{font-size:12px}}th,td{{padding:8px 6px}}form,label{{max-width:100%}}.card{{min-width:100px}}}}
</style><main><nav><a href="/">Research desk</a> · <a href="/experiments">Refresh strategy lab</a></nav>
<h1>Where do automated strategies help?</h1><p>Compare fixed rules across sectors and assets, then test whether agents add useful information. These historical comparisons are exploratory. The Alpaca paper baseline continues separately.</p>{errors}
<div class="cards"><div class="card"><strong>{len(rows)}/{escape(str(sector.get("case_count", 564)))}</strong>price simulations · {status}</div><div class="card"><strong>{len(ASSETS)}</strong>funds · all 11 sectors</div><div class="card"><strong>{saved}/{requested}</strong>agent decisions saved</div><div class="card"><strong>{paired}</strong>matched resolved company/dates</div></div>
<h2>Sector and asset comparison</h2><form action="/experiments" method="get"><label>Historical slice<select name="window">{window_options}</select></label><label>Trading cost<select name="cost">{cost_options}</select></label><label>Show<select name="metric">{metric_options}</select></label><button type="submit">Compare</button></form>
<p class="muted">{metric_heading}. Each simulation starts with $100,000; single-fund entries use 40% and leave 60% cash. Hold is the matching fund control. Exposure drifts and can differ across rules. Zero cash interest; adjusted prices; no terminal sale charge.</p>
<div class="scroll"><table><thead><tr><th>Fund / exposure</th><th>{benchmark_heading}</th><th>50/200 trend</th><th>12-month momentum</th><th>Weekly reversal</th></tr></thead><tbody>{"".join(matrix) or '<tr><td colspan="5">No completed sector results yet.</td></tr>'}</tbody></table></div>
<h2>Sector rotation versus holding all sectors</h2><p class="muted">Top four positive 12–1-month momentum scores, updated monthly; up to 10% per entry. Basket entries use 40%/11. Continuing holdings are not resized, so these are not constant-weight portfolios.</p>
<div class="scroll"><table><thead><tr><th>Rule</th><th>Total return</th><th>Max drawdown</th><th>Average exposure</th><th>Fills</th></tr></thead><tbody>{"".join(baskets)}</tbody></table></div>
<h2>Descriptive candidates for a forward test</h2><p class="muted">Positive excess in both 2025 and 2026 at 20 bps, with no worse drawdown in either slice. {len(candidates)} combinations passed; showing up to six, ordered by their weaker excess. This screen is not statistical proof and submits no orders.</p><ul>{shortlist}</ul>
<h2>Do the agents improve the recommendation?</h2><p>{saved}/{requested} decisions saved across the two native studies; {paired} company/date pairs have resolved readable decisions from both teams. All six arms below use exactly those same frozen outcomes. Shared market dates are correlated observations.</p>
<p class="muted">Observed model usage: {usage["llm_calls"]:,} calls · {usage["tokens_in"]:,} input tokens · {usage["tokens_out"]:,} output tokens. These cell-boundary snapshots can omit interrupted-response usage and are not a subscription-credit conversion.</p>
<div class="scroll"><table><thead><tr><th>Companies</th><th>Study state</th><th>Saved decisions</th><th>Resolved pairs</th></tr></thead><tbody>{"".join(agent_rows)}</tbody></table></div>
<div class="scroll"><table><thead><tr><th>Forecast arm</th><th>Paired cells</th><th>Holds</th><th>Direction hit rate</th><th>Directional score</th></tr></thead><tbody>{"".join(forecasts)}</tbody></table></div>
<p class="warning">Directional score = direction × five-session SPY-relative return, averaged including zero for Hold. It is not portfolio return: bearish scores do not represent executed shorts. Historical training leakage and incomplete old text prevent a clean claim that agents add an edge.</p>
<details><summary>Agent scores by current sector label</summary><p>Very few correlated dates per company. Compare counts before comparing scores; sector labels and selected companies are chosen today.</p><div class="scroll"><table><thead><tr><th>Sector</th><th>Pairs</th><th>Always long score</th><th>Market team score</th><th>Full team score</th></tr></thead><tbody>{"".join(sectors)}</tbody></table></div></details>
<h2>Fresh signals before future outcomes</h2><p>{escape(shadow_state)} · {shadow.get("recorded_days", 0)} captured market days · {shadow.get("complete", 0)} resolved forecast/horizon cases · {shadow.get("pending", 0)} pending.</p><p class="muted">At 14:45 in this Mac's local time, capture all fixed fund-rule signals after New York's close. The first eligible price is a later session's open; outcomes use 5, 20 and 63 sessions. No orders or model calls. Overlapping forecasts are correlated and are not compounded into portfolio returns. First capture may still be waiting for today's close.</p>
<details><summary>Exposure, trading activity and risk for this slice</summary><div class="scroll"><table><thead><tr><th>Fund / rule</th><th>Avg exposure</th><th>Fills</th><th>Annual volatility</th><th>Sharpe, zero cash rate</th><th>Traded notional / initial capital</th></tr></thead><tbody>{"".join(details)}</tbody></table></div></details>
<details><summary>Methods, limitations and research sources</summary><ul>{assumptions}</ul><p>Many correlated comparisons can produce apparent winners by chance. No ranking changes execution. Daily and weekly studies do not test HFT. Fresh timestamped shadow recommendations are needed before drawing conclusions about an agent's incremental value.</p><p class="sources">{sources}</p></details>
<p class="muted">Snapshot read: {escape(snapshot.get("as_of", ""))}. Native progress updates at cell boundaries. Refresh to read current saved results.</p></main></html>'''
