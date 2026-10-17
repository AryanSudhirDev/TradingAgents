"""Weather pilot: time cutoffs, settlement validation, payoff math and frozen inputs."""

import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tradingagents import weather_replay as weather


def event():
    titles = ["69°F or below", "70-71°F", "72-73°F", "74°F or higher"]
    return {"slug": "highest-temperature-in-nyc-on-october-1-2026", "markets": [
        {"groupItemTitle": title, "description": "site=klga Hourly Data Fahrenheit",
         "createdAt": "2026-09-29T00:00:00Z", "closedTime": "2026-10-02T06:00:00Z",
         "closed": True, "umaResolutionStatus": "resolved", "outcomes": '["No","Yes"]',
         "outcomePrices": json.dumps([0, 1] if i == 1 else [1, 0]),
         "clobTokenIds": json.dumps([str(100 + i), str(200 + i)])}
        for i, title in enumerate(titles)]}


def forecast():
    return {"timezone": "America/New_York", "hourly_units": {"temperature_2m": "°F"},
            "hourly": {"time": [f"2026-10-01T{h:02d}:00" for h in range(24)],
                       "temperature_2m": [60 + h / 2 for h in range(24)]}}


@pytest.mark.parametrize(("title", "expected"), [
    ("69°F or below", (-float("inf"), 69.5)), ("70-71°F", (69.5, 71.5)),
    ("74°F or higher", (73.5, float("inf"))), ("-3--2°F", (-3.5, -1.5)),
])
def test_rounding_boundaries(title, expected):
    assert weather.bounds(title) == expected


@pytest.mark.parametrize("title", ["20°C", "bad", "72-70°F"])
def test_unsupported_brackets_fail(title):
    with pytest.raises(ValueError):
        weather.bounds(title)


def test_resolved_ladder_uses_explicit_yes_index():
    rows = weather.ladder(event(), "2026-10-01")
    assert [r["winner"] for r in rows] == [0, 1, 0, 0]
    assert rows[1]["token"] == "201"


@pytest.mark.parametrize("change", [
    {"groupItemTitle": "71-72°F"}, {"description": "wrong airport"},
    {"createdAt": "2026-10-01T00:00:00Z"}, {"closed": False},
    {"umaResolutionStatus": "proposed"}, {"outcomePrices": '[0.1,0.9]'},
    {"closedTime": "2026-09-30T19:00:00Z"},
])
def test_bad_or_unavailable_markets_fail(change):
    data = event()
    data["markets"][1].update(change)
    with pytest.raises(ValueError):
        weather.ladder(data, "2026-10-01")


def test_multiple_winners_and_wrong_date_fail():
    data = event()
    data["markets"][0]["outcomePrices"] = '[0,1]'
    with pytest.raises(ValueError):
        weather.ladder(data, "2026-10-01")
    with pytest.raises(ValueError):
        weather.ladder(event(), "2026-10-02")
    with pytest.raises(ValueError):
        weather.timestamp("2026-10-01T12:00:00")


def test_archived_forecast_requires_all_target_hours_and_units():
    assert weather.forecast_max(forecast(), "2026-10-01") == 71.5
    for mutate in (lambda f: f["hourly"]["temperature_2m"].pop(),
                   lambda f: f["hourly"]["temperature_2m"].__setitem__(0, None),
                   lambda f: f["hourly_units"].update(temperature_2m="°C")):
        data = forecast()
        mutate(data)
        with pytest.raises(ValueError):
            weather.forecast_max(data, "2026-10-01")
    initialized, decision = weather.decision_times("2026-10-01")
    assert (decision - initialized).total_seconds() == 8 * 3600


def test_prices_never_use_future_or_stale_marks():
    decision = datetime(2026, 9, 30, 20, tzinfo=UTC)
    t = int(decision.timestamp())
    assert weather.mark_at({"history": [{"t": t - 60, "p": 0.4}, {"t": t + 1, "p": 1}]}, decision) == 0.4
    for history in ([], [{"t": t + 1, "p": 1}], [{"t": t - 301, "p": 0.2}], [{"t": t, "p": -0.1}],
                    [{"t": t, "p": 0.1}, {"t": t, "p": 0.2}]):
        with pytest.raises(ValueError):
            weather.mark_at({"history": history}, decision)


def test_basket_cost_and_matched_random_are_net_of_assumptions():
    assert weather.basket_cost([0.3] * 3) == pytest.approx(3 * (0.32 + 0.05 * 0.32 * 0.68))
    rows = weather.ladder(event(), "2026-10-01")
    result = weather.score_day(rows, 71, [0.1, 0.2, 0.2, 0.5])
    costs = [weather.basket_cost([0.1, 0.2, 0.2]), weather.basket_cost([0.2, 0.2, 0.5])]
    assert result["random"]["hypothetical_return_pct"] == pytest.approx(sum((1 / c - 1) * 100 for c in costs) / 2)
    assert result["model"]["hypothetical_return_pct"] == pytest.approx((1 / costs[0] - 1) * 100)
    assert result["entered"] is True
    assert result["brier_model"] >= 0


def test_decision_does_not_depend_on_winner_and_failed_coverage_is_visible():
    rows = weather.ladder(event(), "2026-10-01")
    result = weather.score_day(rows, 71, [0.1, 0.2, 0.2, 0.5])
    other = copy.deepcopy(rows)
    for i, row in enumerate(other):
        row["winner"] = int(i == 3)
    changed = weather.score_day(other, 71, [0.1, 0.2, 0.2, 0.5])
    assert (result["entered"], result["selected_brackets"]) == (changed["entered"], changed["selected_brackets"])
    assert result["model"]["hypothetical_return_pct"] != changed["model"]["hypothetical_return_pct"]
    summary = weather.summarize([dict(result, status="complete", resolution_hours=34), {"status": "failed_or_missing"}])
    assert summary["requested"] == 2 and summary["complete"] == 1 and summary["failed_or_missing"] == 1


def test_cached_input_is_private_verified_and_never_retried(tmp_path, monkeypatch):
    calls = []

    def get(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(status_code=200, json=lambda: {"history": []})

    monkeypatch.setattr(weather.requests, "get", get)
    assert weather.snapshot(tmp_path, "test", "https://example.com", {"a": 1}, True) == {"history": []}
    assert weather.snapshot(tmp_path, "test", "https://example.com", {"a": 1}, False) == {"history": []}
    assert len(calls) == 1
    path = tmp_path / "inputs/test.json"
    assert path.stat().st_mode & 0o777 == 0o600
    data = json.loads(path.read_bytes())
    data["data"] = {"history": [1]}
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="mismatch"):
        weather.snapshot(tmp_path, "test", "https://example.com", {"a": 1}, True)
    assert len(calls) == 1


def test_http_failure_is_cached_and_missing_input_never_fetches(tmp_path, monkeypatch):
    calls = []

    def get(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(status_code=429, json=lambda: {"error": "limited"})

    monkeypatch.setattr(weather.requests, "get", get)
    for _ in range(2):
        with pytest.raises(ValueError, match="HTTP 429"):
            weather.snapshot(tmp_path, "test", "https://example.com", {}, True)
    with pytest.raises(ValueError, match="Missing frozen"):
        weather.snapshot(tmp_path, "missing", "https://example.com", {}, False)
    assert len(calls) == 1


def test_run_is_offline_by_default_and_refuses_protocol_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(weather, "ROOT", tmp_path)
    folder = tmp_path / "pilot"
    result = weather.run(folder)
    assert result["summary"]["failed_or_missing"] == 14
    assert weather.run(folder) == result
    plan = dict(weather.PLAN, sigma_f=4)
    (folder / "protocol.json").write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="protocol differs"):
        weather.run(folder)
    with pytest.raises(ValueError, match="private folder"):
        weather.run(tmp_path.parent)


def test_previous_input_hash_is_checked_before_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(weather, "ROOT", tmp_path)
    folder = tmp_path / "pilot"
    weather.run(folder)
    source = folder / "inputs/example.json"
    source.parent.mkdir()
    source.write_text("changed input")
    result = json.loads((folder / "results.json").read_bytes())
    result["input_sha256"] = {"example.json": "0" * 64}
    (folder / "results.json").write_text(json.dumps(result))
    with pytest.raises(ValueError, match="recorded input changed"):
        weather.run(folder)
