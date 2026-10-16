"""Fixed ETF cases, causal calendar signals, execution and private data provenance."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from tradingagents import sector_study as study
from tradingagents.dataflows.config import get_config
from tradingagents.default_config import DEFAULT_CONFIG


@pytest.fixture
def small_market(monkeypatch):
    assets = {ticker: study.ASSETS[ticker] for ticker in ("XLB", "XLE", "SPY")}
    monkeypatch.setattr(study, "ASSETS", assets)
    dates = pd.bdate_range("2023-01-02", periods=320)
    frames = {}
    for ticker, slope in (("XLB", 0.2), ("XLE", -0.1), ("SPY", 0)):
        close = pd.Series([100 + i * slope for i in range(len(dates))])
        frames[ticker] = pd.DataFrame({"Date": dates, "Open": close, "Close": close})
    return frames


@pytest.fixture
def calendar_closes():
    dates = pd.bdate_range("2023-01-02", "2024-04-05").difference(pd.DatetimeIndex(["2024-03-29"]))
    closes = pd.DataFrame({ticker: [100 * (1 + (i + 1) / 1_000) ** day for day in range(len(dates))]
                           for i, ticker in enumerate(("XLB", "XLC", "XLE", "XLF", "XLI"))}, index=dates)
    closes.loc["2024-02-20":, "XLB"] *= 100
    return closes


def test_fixed_plan_has_exactly_564_cases():
    assert len(study.ASSETS) == 23
    assert sum(asset["group"] == "sector" for asset in study.ASSETS.values()) == 11
    assert (len(study.ASSETS) * len(study.SINGLE_RULES) + 2) * len(study.WINDOWS) * len(study.COSTS) == 564
    assert study.WINDOWS["evaluation"] == {"start": "2026-01-02", "end": "2026-10-15"}


@pytest.mark.parametrize("cutoff", ["2024-03-28", "2024-04-01", "2024-04-05"])
def test_future_bar_mutations_and_truncation_cannot_change_decisions(calendar_closes, cutoff):
    original = study.make_signals(calendar_closes)
    changed = calendar_closes.copy()
    changed.loc[changed.index > cutoff] *= 1_000_000
    mutated = study.make_signals(changed)
    truncated = study.make_signals(calendar_closes.loc[:cutoff])
    for rule in study.RULE_LABELS:
        pd.testing.assert_frame_equal(original[rule].loc[:cutoff], mutated[rule].loc[:cutoff])
        pd.testing.assert_frame_equal(original[rule].loc[:cutoff], truncated[rule])


def test_friday_holiday_weekly_signal_is_not_backdated():
    dates = pd.bdate_range("2024-03-15", "2024-04-03").difference(pd.DatetimeIndex(["2024-03-29"]))
    close = pd.DataFrame({"XLB": [100.0 if day <= pd.Timestamp("2024-03-22") else 80.0 for day in dates]}, index=dates)
    signal = study.make_signals(close)["weekly_reversal"]
    assert not signal.loc["2024-03-28", "XLB"]
    assert signal.loc["2024-04-01", "XLB"]
    execution = signal.shift(1, fill_value=False)
    assert not execution.loc["2024-04-01", "XLB"]
    assert execution.loc["2024-04-02", "XLB"]


def test_month_end_weekend_membership_waits_and_persists(calendar_closes):
    signal = study.make_signals(calendar_closes)["sector_momentum_12_1"]
    assert not signal.loc["2024-03-28", "XLB"]
    assert signal.loc["2024-04-01", "XLB"]
    assert not signal.loc["2024-04-01", "XLC"]
    assert signal.loc["2024-04-01"].sum() == 4
    for day in signal.loc["2024-03-01":"2024-03-28"].index:
        pd.testing.assert_series_equal(signal.loc[day], signal.loc["2024-02-29"], check_names=False)
    assert not signal.shift(1, fill_value=False).loc["2024-04-01", "XLB"]
    assert signal.shift(1, fill_value=False).loc["2024-04-02", "XLB"]


def test_monthly_ranking_requires_positive_scores_and_breaks_ties_in_universe_order(calendar_closes):
    for ticker in calendar_closes:
        calendar_closes[ticker] = calendar_closes["XLI"]
    selected = study.make_signals(calendar_closes)["sector_momentum_12_1"].loc["2024-02-29"]
    assert selected.to_dict() == {"XLB": True, "XLC": True, "XLE": True, "XLF": True, "XLI": False}
    flat = study.make_signals(calendar_closes * 0 + 100)["sector_momentum_12_1"]
    assert not flat.any().any()


def test_non_sector_forecast_inputs_have_valid_empty_baskets():
    closes = pd.DataFrame({"AAPL": [100.0, 101.0], "SPY": [100.0, 100.0]}, index=pd.bdate_range("2024-01-02", periods=2))
    signals = study.make_signals(closes)
    assert list(signals["buy_hold"].columns) == ["AAPL", "SPY"]
    assert signals["sector_hold"].shape == (2, 0)
    assert signals["sector_momentum_12_1"].shape == (2, 0)


def test_single_session_lag_uses_following_open(small_market):
    dates = small_market["XLB"]["Date"]
    for frame in small_market.values():
        frame[["Open", "Close"]] = 100.0
    small_market["XLB"].loc[253:, "Close"] = 200.0
    small_market["XLB"].loc[254:, "Open"] = 300.0
    windows = {"test": {"start": str(dates.iloc[253].date()), "end": str(dates.iloc[255].date())}}
    rows = study.evaluate_frames(small_market, windows)
    momentum = next(row for row in rows if row["ticker"] == "XLB" and row["rule"] == "momentum_252" and row["slippage_bps"] == 5)
    assert momentum["fills"][0]["day"] == str(dates.iloc[254].date())
    assert momentum["fills"][0]["price"] == pytest.approx(300 * 1.0005)
    assert momentum["curve"][0]["equity"] == 100_000
    flat = next(row for row in rows if row["ticker"] == "SPY" and row["rule"] == "momentum_252")
    assert flat["annualized_volatility_pct"] == 0
    assert flat["sharpe_zero_cash"] is None


@pytest.mark.parametrize("warmup_sessions", [251, 252])
def test_insufficient_253_session_warmup_is_rejected(small_market, warmup_sessions):
    dates = small_market["SPY"]["Date"]
    with pytest.raises(ValueError, match="253 warm-up"):
        study.evaluate_frames(small_market, {"short": {"start": str(dates.iloc[warmup_sessions].date()), "end": str(dates.iloc[255].date())}})


def test_253_pre_window_closes_enable_first_open_momentum_decision(small_market):
    dates = small_market["SPY"]["Date"]
    windows = {"test": {"start": str(dates.iloc[253].date()), "end": str(dates.iloc[255].date())}}
    rows = study.evaluate_frames(small_market, windows)
    momentum = next(row for row in rows if row["ticker"] == "XLB" and row["rule"] == "momentum_252" and row["slippage_bps"] == 5)
    assert momentum["fills"][0]["day"] == str(dates.iloc[253].date())
    assert momentum["fills"][0]["price"] == pytest.approx(small_market["XLB"].loc[253, "Open"] * 1.0005)


def test_all_cases_have_own_benchmark_sizing_costs_and_statistics(small_market):
    dates = small_market["SPY"]["Date"]
    windows = {name: {"start": str(dates.iloc[start].date()), "end": str(dates.iloc[start + 5].date())}
               for name, start in (("first", 270), ("second", 290))}
    rows = study.evaluate_frames(small_market, windows)
    assert len(rows) == (3 * 4 + 2) * 2 * 2
    indexed = {(row["ticker"], row["rule"], row["window"], row["slippage_bps"]): row for row in rows}
    for row in rows:
        baseline = "sector_hold" if row["ticker"] == "SECTORS" else "buy_hold"
        benchmark = indexed[row["ticker"], baseline, row["window"], row["slippage_bps"]]
        assert row["benchmark_return_pct"] == benchmark["return_pct"]
        assert row["excess_return_pct"] == pytest.approx(row["return_pct"] - benchmark["return_pct"])
        assert row["traded_notional_pct_initial"] == pytest.approx(sum(fill["units"] * fill["price"] for fill in row["fills"]) / 1_000)
        if row["slippage_bps"] == 5 and row["fills"]:
            stressed = indexed[row["ticker"], row["rule"], row["window"], 20]
            assert stressed["final_equity"] < row["final_equity"]
    single = indexed["XLB", "buy_hold", "first", 5]
    assert single["fills"][0]["units"] * single["fills"][0]["price"] == pytest.approx(40_000)
    held = indexed["SECTORS", "sector_hold", "first", 5]
    rotated = indexed["SECTORS", "sector_momentum_12_1", "first", 5]
    assert held["fills"][0]["units"] * held["fills"][0]["price"] == pytest.approx(20_000)
    assert rotated["fills"][0]["units"] * rotated["fills"][0]["price"] == pytest.approx(10_000)
    assert rotated["fill_count"] == 1


@pytest.mark.parametrize("supplied_config", [None, {"data_cache_dir": "must-not-use", "results_dir": "must-not-use", "tool_vendors": {"get_stock_data": "yfinance"}}])
def test_runner_freezes_private_plan_before_fetch_and_hashes_data(small_market, tmp_path, monkeypatch, supplied_config):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    dates = small_market["SPY"]["Date"]
    windows = {"test": {"start": str(dates.iloc[270].date()), "end": str(dates.iloc[275].date())}}
    monkeypatch.setattr(study, "WINDOWS", windows)
    defaults = deepcopy(DEFAULT_CONFIG)
    before_config = get_config()
    plan_copies = []

    def fetch(ticker, end, *, fill_gaps):
        assert end == windows["test"]["end"] and fill_gaps is False
        folder = next((tmp_path / ".tradingagents/experiments/sectors").iterdir())
        plan_copies.append((folder / "plan.json").read_bytes())
        assert get_config()["data_cache_dir"] == str(folder / "cache")
        assert get_config()["results_dir"] == str(folder)
        assert get_config()["data_vendors"] == DEFAULT_CONFIG["data_vendors"]
        expected_vendor = "yfinance" if supplied_config else DEFAULT_CONFIG["tool_vendors"].get("get_stock_data")
        assert get_config()["tool_vendors"].get("get_stock_data") == expected_vendor
        return small_market[ticker].copy()

    monkeypatch.setattr(study, "load_ohlcv", fetch)
    report, folder = study.run_study(supplied_config)
    assert report["status"] == "complete"
    assert len(report["results"]) == report["case_count"] == 28
    plan = (folder / "plan.json").read_bytes()
    assert all(saved == plan for saved in plan_copies)
    assert hashlib.sha256(plan).hexdigest() == report["plan_sha256"]
    assert json.loads(plan) == report["plan"]
    assert report["plan"]["warmup_sessions"] == 253
    assert (folder / "results.json").stat().st_mode & 0o777 == 0o600
    assert (folder / "plan.json").stat().st_mode & 0o777 == 0o600
    assert folder.stat().st_mode & 0o777 == 0o700
    assert (folder / "cache").stat().st_mode & 0o777 == 0o700
    for ticker in study.ASSETS:
        data = folder / "data" / f"{ticker}.csv"
        assert hashlib.sha256(data.read_bytes()).hexdigest() == report["data_hashes"][ticker]
        assert data.stat().st_mode & 0o777 == 0o600
    assert defaults == DEFAULT_CONFIG
    assert get_config() == before_config


def test_runner_keeps_failed_status_and_frozen_plan(small_market, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(study, "load_ohlcv", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("missing source")))
    with pytest.raises(ValueError, match="missing source"):
        study.run_study()
    folder = next((tmp_path / ".tradingagents/experiments/sectors").iterdir())
    report = json.loads((folder / "results.json").read_bytes())
    assert report["status"] == "failed"
    assert report["error"] == "missing source"
    assert hashlib.sha256((folder / "plan.json").read_bytes()).hexdigest() == report["plan_sha256"]


def test_cli_returns_nonzero_on_failure_without_changing_config(monkeypatch):
    monkeypatch.setattr(study.os, "umask", lambda value: None)
    monkeypatch.setattr("sys.argv", ["sector_study"])
    monkeypatch.setattr(study, "run_study", lambda: (_ for _ in ()).throw(ValueError("bad prices")))
    with pytest.raises(SystemExit) as error:
        study.main()
    assert error.value.code == 1
