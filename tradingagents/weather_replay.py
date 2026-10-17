"""Read-only, fixed NYC weather-market pilot; indicative prices are not fills."""

import argparse
import hashlib
import json
import math
import os
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import NormalDist, mean

import requests

from tradingagents.dashboard.operations import private_write

ROOT = Path.home() / ".tradingagents/experiments/weather"
PLAN = {
    "version": 1,
    "start": "2026-10-01",
    "end": "2026-10-14",
    "station": "KLGA",
    "latitude": 40.7769,
    "longitude": -73.8740,
    "timezone": "America/New_York",
    "model": "gfs_global",
    "run_hour_utc_previous_day": 12,
    "decision_hour_utc_previous_day": 20,
    "sigma_f": 3.0,
    "brackets": 3,
    "adverse_price_per_share": 0.02,
    "assumed_taker_fee_rate": 0.05,
    "minimum_basket_edge": 0.05,
    "maximum_mark_age_seconds": 300,
    "external_repository": "https://github.com/warproxxx/poly_data",
    "inspected_revision": "136e129735c73bce3a3d59f20354417b188e47fd",
}
LIMITS = (
    "Retrospective, one selected station and 14 correlated dates; no significance claim. "
    "This is an independent fixed GFS/Normal(3F) hypothesis, not PolyTemp's model or trades. "
    "The uncertainty width is assumed, not calibrated. Archived model initialization plus "
    "eight hours approximates publication availability; exact historical arrival is unknown. "
    "Gridpoint hourly maxima differ from station observations. Current resolved metadata "
    "does not establish historical rule/fee versions. Price-history marks plus 2c/share and "
    "a fixed 5% fee-rate formula are cost assumptions, not executable asks, depth, trades or "
    "guaranteed conservative bounds. Prices are independently sampled within five minutes. "
    "Equal shares per basket are normalized per dollar staked; no broker, portfolio, "
    "minimum size, capital overlap, queue position or partial fills are modeled. "
    "Hold to recorded resolution; no forced weekly exit. Random control averages all "
    "adjacent three-bracket windows on identical model-entry dates and normalized budgets. "
    "No random path, confidence interval or evidence of replicable net profits is supplied."
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include its timezone")
    return parsed.astimezone(UTC)


def decision_times(day):
    previous = date.fromisoformat(day) - timedelta(days=1)
    return (datetime.combine(previous, datetime.min.time(), UTC).replace(hour=PLAN["run_hour_utc_previous_day"]),
            datetime.combine(previous, datetime.min.time(), UTC).replace(hour=PLAN["decision_hour_utc_previous_day"]))


def snapshot(folder, name, url, params, fetch):
    """Cache responses once, including failures; replay verifies content and request."""
    path = folder / "inputs" / (name + ".json")
    if not path.exists():
        if not fetch:
            raise ValueError(f"Missing frozen input: {name}")
        record = {"url": url, "params": params, "captured_at": datetime.now(UTC).isoformat()}
        try:
            response = requests.get(url, params=params, timeout=35)
            record["status"] = response.status_code
            record["data"] = response.json()
        except (requests.RequestException, ValueError) as exc:
            record.update(status=0, data={"error": type(exc).__name__})
        record["sha256"] = hashlib.sha256(canonical(record["data"])).hexdigest()
        private_write(path, canonical(record))
    record = json.loads(path.read_bytes())
    if (record["url"] != url or record["params"] != params
            or record["sha256"] != hashlib.sha256(canonical(record["data"])).hexdigest()):
        raise ValueError(f"Frozen input/request mismatch: {name}")
    if record["status"] != 200:
        raise ValueError(f"Frozen input failed: {name}, HTTP {record['status']}; no automatic retry")
    return record["data"]


def bounds(title):
    match = re.fullmatch(r"(-?\d+)°F or (below|higher)", title)
    if match:
        number = int(match[1])
        return (-math.inf, number + 0.5) if match[2] == "below" else (number - 0.5, math.inf)
    match = re.fullmatch(r"(-?\d+)-(-?\d+)°F", title)
    if not match or int(match[1]) > int(match[2]):
        raise ValueError("Unsupported temperature bracket")
    return int(match[1]) - 0.5, int(match[2]) + 0.5


def ladder(event, day):
    """Require one resolved, exhaustive, non-overlapping station/date ladder."""
    expected_slug = f"highest-temperature-in-nyc-on-october-{date.fromisoformat(day).day}-2026"
    if event.get("slug") != expected_slug:
        raise ValueError("Wrong market date or station")
    _, decision = decision_times(day)
    rows = []
    for market in event["markets"]:
        description = market.get("description", "")
        if not all(s in description for s in ("site=klga", "Hourly Data", "Fahrenheit")):
            raise ValueError("Unverified station, units or observation rule")
        if (market.get("closed") is not True or market.get("umaResolutionStatus") != "resolved"
                or timestamp(market["createdAt"]) > decision):
            raise ValueError("Market unresolved or created after decision")
        outcomes = json.loads(market["outcomes"])
        tokens = json.loads(market["clobTokenIds"])
        prices = [float(p) for p in json.loads(market["outcomePrices"])]
        if len(tokens) != 2 or sorted(outcomes) != ["No", "Yes"] or sorted(prices) != [0, 1]:
            raise ValueError("No unambiguous binary settlement")
        yes = outcomes.index("Yes")
        lo, hi = bounds(market["groupItemTitle"])
        closed = timestamp(market["closedTime"])
        if closed <= decision:
            raise ValueError("Market resolved before decision")
        rows.append({"lower": lo, "upper": hi, "title": market["groupItemTitle"],
                     "token": tokens[yes], "winner": prices[yes], "closed_at": closed})
    rows.sort(key=lambda r: r["lower"])
    if (len(rows) < 3 or rows[0]["lower"] != -math.inf or rows[-1]["upper"] != math.inf
            or any(a["upper"] != b["lower"] for a, b in zip(rows, rows[1:], strict=False))
            or len({r["token"] for r in rows}) != len(rows)
            or sum(r["winner"] for r in rows) != 1):
        raise ValueError("Incomplete, overlapping or ambiguous settlement ladder")
    return rows


def forecast_max(forecast, day):
    if (forecast.get("timezone") != PLAN["timezone"]
            or forecast.get("hourly_units", {}).get("temperature_2m") != "°F"):
        raise ValueError("Wrong forecast timezone or units")
    hours = forecast["hourly"]["time"]
    values = forecast["hourly"]["temperature_2m"]
    pairs = [(t, v) for t, v in zip(hours, values, strict=True) if t.startswith(day + "T")]
    expected = {f"{day}T{hour:02d}:00" for hour in range(24)}
    if len(pairs) != 24 or {t for t, _ in pairs} != expected:
        raise ValueError("Incomplete target-day forecast")
    if any(type(v) not in (float, int) or not math.isfinite(v) for _, v in pairs):
        raise ValueError("Invalid target-day forecast")
    return max(v for _, v in pairs)


def mark_at(history, decision):
    eligible = []
    seen = {}
    for point in history["history"]:
        t, p = point["t"], point["p"]
        if (type(t) not in (int, float) or not math.isfinite(t)
                or type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1):
            raise ValueError("Invalid price history")
        age = decision.timestamp() - t
        if 0 <= age <= PLAN["maximum_mark_age_seconds"]:
            if t in seen and seen[t] != p:
                raise ValueError("Conflicting same-time prices")
            seen[t] = p
            eligible.append((t, p))
    if not eligible:
        raise ValueError("Missing fresh pre-decision price history")
    return max(eligible)[1]


def basket_cost(marks):
    if not marks or any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in marks):
        raise ValueError("Invalid basket prices")
    prices = [min(1, p + PLAN["adverse_price_per_share"]) for p in marks]
    return sum(p + PLAN["assumed_taker_fee_rate"] * p * (1 - p) for p in prices)


def score_day(rows, maximum, marks):
    distribution = NormalDist(maximum, PLAN["sigma_f"])
    probabilities = [distribution.cdf(r["upper"]) - distribution.cdf(r["lower"]) for r in rows]
    if len(marks) != len(rows) or any(not math.isfinite(p) or not 0 <= p <= 1 for p in marks):
        raise ValueError("Incomplete or invalid market marks")
    if sum(marks) <= 0:
        raise ValueError("Cannot normalize zero market probabilities")
    width = PLAN["brackets"]
    windows = [list(range(i, i + width)) for i in range(len(rows) - width + 1)]
    model = max(windows, key=lambda w: sum(probabilities[i] for i in w))
    favorite = max(windows, key=lambda w: sum(marks[i] for i in w))

    def payoff(window):
        cost = basket_cost([marks[i] for i in window])
        won = sum(rows[i]["winner"] for i in window)
        return {"cost_per_equal_share_basket": cost, "covered": bool(won),
                "hypothetical_return_pct": (won / cost - 1) * 100}

    model_payoff = payoff(model)
    edge = sum(probabilities[i] for i in model) - model_payoff["cost_per_equal_share_basket"]
    entered = edge >= PLAN["minimum_basket_edge"]
    normalized = [p / sum(marks) for p in marks]
    return {"forecast_max_f": maximum, "selected_brackets": [rows[i]["title"] for i in model],
            "model_coverage_probability": sum(probabilities[i] for i in model),
            "modeled_edge_per_basket": edge, "entered": entered,
            "model": model_payoff, "market_favorite": payoff(favorite),
            "random": {"hypothetical_return_pct": mean(payoff(w)["hypothetical_return_pct"] for w in windows),
                       "coverage_probability": mean(payoff(w)["covered"] for w in windows)},
            "brier_model": sum((p - r["winner"]) ** 2 for p, r in zip(probabilities, rows, strict=True)),
            "brier_market": sum((p - r["winner"]) ** 2 for p, r in zip(normalized, rows, strict=True))}


def summarize(cells):
    available = [c for c in cells if c["status"] == "complete"]
    entered = [c for c in available if c["entered"]]
    return {"requested": len(cells), "complete": len(available), "failed_or_missing": len(cells) - len(available),
            "entered": len(entered), "abstentions": len(available) - len(entered),
            "matched_entry_date_mean_return_pct": {
                arm: mean(c[arm]["hypothetical_return_pct"] for c in entered) if entered else None
                for arm in ("model", "market_favorite", "random")},
            "all_complete_date_mean_return_pct": {
                arm: mean(c[arm]["hypothetical_return_pct"] for c in available) if available else None
                for arm in ("model", "market_favorite", "random")},
            "unfiltered_model_ladder_coverage": mean(c["model"]["covered"] for c in available) if available else None,
            "mean_brier_model": mean(c["brier_model"] for c in available) if available else None,
            "mean_brier_market": mean(c["brier_market"] for c in available) if available else None,
            "maximum_resolution_hours_after_entry": max((c["resolution_hours"] for c in available), default=None)}


def run(folder, fetch=False):
    source_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    folder = Path(folder).expanduser().resolve()
    if not folder.is_relative_to(ROOT.resolve()) or folder == ROOT.resolve():
        raise ValueError("Choose a private folder under ~/.tradingagents/experiments/weather/")
    protocol = folder / "protocol.json"
    if protocol.exists() and json.loads(protocol.read_bytes()) != PLAN:
        raise ValueError("Existing protocol differs; do not retune a saved study")
    if not protocol.exists():
        private_write(protocol, canonical(PLAN))
    saved = folder / "results.json"
    if saved.exists():
        for name, digest in json.loads(saved.read_bytes())["input_sha256"].items():
            path = folder / "inputs" / name
            if path.parent != folder / "inputs" or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("Previously recorded input changed")
    cells = []
    day = date.fromisoformat(PLAN["start"])
    while day <= date.fromisoformat(PLAN["end"]):
        text = day.isoformat()
        cell = {"date": text, "status": "failed_or_missing"}
        try:
            slug = f"highest-temperature-in-nyc-on-october-{day.day}-2026"
            events = snapshot(folder, text + "-event", "https://gamma-api.polymarket.com/events", {"slug": slug}, fetch)
            if len(events) != 1:
                raise ValueError("Expected exactly one daily NYC event")
            rows = ladder(events[0], text)
            initialized, decision = decision_times(text)
            forecast = snapshot(folder, text + "-forecast", "https://single-runs-api.open-meteo.com/v1/forecast",
                                {"latitude": PLAN["latitude"], "longitude": PLAN["longitude"],
                                 "models": PLAN["model"], "run": initialized.strftime("%Y-%m-%dT%H:%M"),
                                 "hourly": "temperature_2m", "temperature_unit": "fahrenheit",
                                 "timezone": PLAN["timezone"], "forecast_days": 3}, fetch)
            maximum = forecast_max(forecast, text)
            marks = []
            for i, row in enumerate(rows):
                history = snapshot(folder, f"{text}-price-{i}", "https://clob.polymarket.com/prices-history",
                                   {"market": row["token"], "startTs": int(decision.timestamp()) - 7200,
                                    "endTs": int(decision.timestamp()), "fidelity": 1}, fetch)
                marks.append(mark_at(history, decision))
            cell.update(score_day(rows, maximum, marks), status="complete",
                        initialized_at=initialized.isoformat(), decision_at=decision.isoformat(),
                        resolution_hours=max((r["closed_at"] - decision).total_seconds() / 3600 for r in rows))
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            cell["error"] = str(exc)
        cells.append(cell)
        print(text, cell["status"], flush=True)
        day += timedelta(days=1)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((folder / "inputs").glob("*.json"))}
    result = {"plan": PLAN, "limits": LIMITS, "source_sha256": source_hash,
              "input_sha256": hashes, "cells": cells, "summary": summarize(cells)}
    private_write(folder / "results.json", json.dumps(result, indent=2, allow_nan=False).encode())
    return result


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder")
    parser.add_argument("--fetch", action="store_true", help="Fetch missing public inputs once; default is offline replay")
    args = parser.parse_args()
    result = run(args.folder, args.fetch)
    print(json.dumps(result["summary"], indent=2))
    if result["summary"]["failed_or_missing"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
