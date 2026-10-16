"""Past-only signals, next-open execution, costs, coverage and experiment isolation."""

from pathlib import Path

import pandas as pd
import pytest

from tradingagents import strategy_comparison as comparison
from tradingagents.backtest import BacktestResult, BacktestSummary
from tradingagents.default_config import DEFAULT_CONFIG


@pytest.fixture
def prices():
    dates = pd.bdate_range("2024-01-02", periods=260)
    frame = pd.DataFrame({"Date": dates, "Open": 100.0, "Close": 100.0})
    return {"NVDA": frame.copy(), "SPY": frame.copy()}


def test_today_and_future_closes_cannot_change_todays_signal(prices):
    day = prices["NVDA"]["Date"].iloc[210]
    args = (["NVDA"], str(day.date()), str(prices["NVDA"]["Date"].iloc[-1].date()))
    before = comparison.prepare_prices(prices, *args)[2]
    prices["NVDA"].loc[210, "Close"] = 100_000
    after = comparison.prepare_prices(prices, *args)[2]
    for rule in ("sma_50_200", "momentum_126"):
        assert not before[rule].loc[day, "NVDA"]
        assert not after[rule].loc[day, "NVDA"]
        assert after[rule].iloc[1]["NVDA"]


def test_next_open_fills_hold_without_rebalancing_and_include_initial_drawdown():
    dates = pd.bdate_range("2024-01-02", periods=3)
    opens = pd.DataFrame({"NVDA": [100.0, 200.0, 50.0]}, index=dates)
    closes = pd.DataFrame({"NVDA": [50.0, 210.0, 60.0]}, index=dates)
    active = pd.DataFrame({"NVDA": [True, True, False]}, index=dates)
    result = comparison.simulate(opens, closes, active, 0.4, 0)
    assert result["fill_count"] == 2
    assert result["fills"][0]["price"] == 100
    assert result["fills"][1]["price"] == 50
    assert result["curve"][0]["equity"] == 80_000
    assert result["final_equity"] == 80_000
    assert result["max_drawdown_pct"] == pytest.approx((80_000 / 144_000 - 1) * 100)
    costlier = comparison.simulate(opens, closes, active, 0.4, 20)
    assert costlier["final_equity"] < result["final_equity"]
    assert costlier["fills"][0]["price"] > 100 and costlier["fills"][1]["price"] < 50


def test_first_session_loss_is_not_omitted_from_drawdown():
    dates = pd.bdate_range("2024-01-02", periods=2)
    opened = pd.DataFrame({"SPY": [100.0, 50.0]}, index=dates)
    closed = pd.DataFrame({"SPY": [50.0, 50.0]}, index=dates)
    active = pd.DataFrame(True, index=dates, columns=["SPY"])
    result = comparison.simulate(opened, closed, active, 0.4, 0)
    assert result["max_drawdown_pct"] == pytest.approx(-20)
    assert result["fill_count"] == 1


@pytest.mark.parametrize("corruption", ["gap", "warmup_gap", "nan", "duplicate"])
def test_incomplete_or_invalid_data_is_rejected(prices, corruption):
    if corruption == "gap":
        prices["NVDA"] = prices["NVDA"].drop(index=230)
    elif corruption == "warmup_gap":
        prices["NVDA"] = prices["NVDA"].drop(index=100)
    elif corruption == "nan":
        prices["NVDA"].loc[230, "Open"] = float("nan")
    else:
        prices["NVDA"] = pd.concat([prices["NVDA"], prices["NVDA"].iloc[[-2]]])
    with pytest.raises(ValueError):
        comparison.prepare_prices(prices, ["NVDA"], "2024-11-01", "2024-12-27")


def test_real_runner_freezes_data_and_cost_scenarios_without_calling_models(prices, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(comparison, "load_ohlcv", lambda ticker, *a, **k: prices[ticker].copy())
    result, folder = comparison.run_comparison(["NVDA"], "2024-11-01", "2024-12-27")
    assert len(result["results"]) == 12
    assert result["entry_allocation_pct"] == 10
    assert set(result["data_hashes"]) == {"SPY", "NVDA"}
    assert (folder / "data/NVDA.csv").exists()
    assert (folder / "results.json").stat().st_mode & 0o777 == 0o600
    assert all(r["final_equity"] == 100_000 for r in result["results"] if r["rule"] == "cash")


def test_native_variants_use_separate_memory_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    calls = []

    def native(tickers, dates, config, **kwargs):
        calls.append((config, kwargs))
        return BacktestResult(kwargs["run_id"], tmp_path / kwargs["run_id"] / "memory.md")

    monkeypatch.setattr(comparison, "run_backtest", native)
    monkeypatch.setattr(comparison, "summarize", lambda result: BacktestSummary(0, 0, {}))
    live_memory = DEFAULT_CONFIG["memory_log_path"]
    result, folder = comparison.run_agent_comparison(["NVDA"], ["2026-10-02"])
    assert len(result["variants"]) == 2
    assert calls[0][1]["selected_analysts"] == ["market"]
    assert calls[1][1]["selected_analysts"] == ["market", "social", "news", "fundamentals"]
    assert calls[0][0]["data_cache_dir"] != calls[1][0]["data_cache_dir"]
    assert all(c[0]["results_dir"] == str(folder) for c in calls)
    assert DEFAULT_CONFIG["memory_log_path"] == live_memory


def test_native_failure_reuses_the_same_run_and_checkpoint_once(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    calls = []

    def native(tickers, dates, config, **kwargs):
        calls.append((config["data_cache_dir"], kwargs["run_id"]))
        result = BacktestResult(kwargs["run_id"], tmp_path / "memory.md")
        if len(calls) == 1:
            result.failures = [("NVDA", dates[0], "interrupted response")]
        return result

    monkeypatch.setattr(comparison, "run_backtest", native)
    monkeypatch.setattr(comparison, "summarize", lambda result: BacktestSummary(0, 0, {}))
    result, _ = comparison.run_agent_comparison(["NVDA"], ["2026-10-02"])
    assert len(calls) == 3 and calls[0] == calls[1]
    assert len(result["variants"][0]["attempts"]) == 2
    assert not result["variants"][0]["failures"]


def test_resume_refuses_changed_models_and_paths_outside_the_experiment_root(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(comparison, "run_backtest", lambda *a, **k: BacktestResult(k["run_id"], tmp_path / "memory.md"))
    monkeypatch.setattr(comparison, "summarize", lambda result: BacktestSummary(0, 0, {}))
    _, folder = comparison.run_agent_comparison(["NVDA"], ["2026-10-02"])
    with pytest.raises(ValueError, match="original"):
        comparison.run_agent_comparison(["NVDA"], ["2026-10-02"], {**DEFAULT_CONFIG, "quick_think_llm": "different"}, resume=folder)
    with pytest.raises(ValueError, match="inside"):
        comparison.run_agent_comparison(["NVDA"], ["2026-10-02"], resume=tmp_path)


def test_agent_cli_exits_with_failure_when_experiments_are_incomplete(monkeypatch, tmp_path):
    monkeypatch.setattr(comparison, "run_agent_comparison", lambda *a, **k: ({"variants": [{"failures": ["interrupted"], "settlement_failures": []}]}, tmp_path))
    monkeypatch.setattr(comparison, "iter_grid", lambda *a: ["2026-10-02"])
    monkeypatch.setattr(comparison.os, "umask", lambda mask: None)
    monkeypatch.setattr("sys.argv", ["compare", "--agents", "--start", "2026-10-02", "--end", "2026-10-02"])
    with pytest.raises(SystemExit) as error:
        comparison.main()
    assert error.value.code == 1
