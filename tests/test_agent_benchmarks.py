"""Matched frozen outcomes, input integrity and observation-only native reads."""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from tradingagents.agent_benchmarks import compare_study
from tradingagents.dashboard.operations import private_write
from tradingagents.memory import TradingMemoryLog


@pytest.fixture
def native_study(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    folder = tmp_path / ".tradingagents/experiments/agents/fixed"
    dates = pd.bdate_range(end="2026-10-15", periods=550)
    hashes = {}
    for ticker in ("SPY", "AAPL"):
        frame = pd.DataFrame({"Date": dates, "Close": 100.0 if ticker == "SPY" else [400 - i / 3 for i in range(550)]})
        data = frame.to_csv(index=False).encode()
        private_write(folder / "validation_prices" / f"{ticker}.csv", data)
        hashes[ticker] = hashlib.sha256(data).hexdigest()
    manifest = {"tickers": ["AAPL"], "dates": ["2026-09-21", "2026-10-02"], "holding_sessions": 5,
                "validation_price_hashes": hashes, "status": "running", "variants": []}
    private_write(folder / "results.json", json.dumps(manifest).encode())
    return folder


def add_decision(folder, name, day="2026-09-21", rating="Underweight", holding=5):
    path = folder / "backtest" / name / "trading_memory.md"
    log = TradingMemoryLog({"memory_log_path": str(path)})
    log.store_decision("AAPL", day, f"Rating: {rating}")
    log.update_with_outcome("AAPL", day, -0.99, -0.99, holding, "test", "2026-09-28")


def test_missing_variant_reads_create_no_files_or_directories(native_study):
    add_decision(native_study, "market_only")
    before = {str(p.relative_to(native_study)): p.read_bytes() if p.is_file() else None for p in native_study.rglob("*")}
    result = compare_study(native_study)
    after = {str(p.relative_to(native_study)): p.read_bytes() if p.is_file() else None for p in native_study.rglob("*")}
    assert before == after
    assert result["coverage"]["full"]["saved"] == 0
    assert result["paired_resolved_cells"] == 0
    assert len(result["cells"]) == 2


def test_all_arms_use_identical_pairs_and_common_frozen_outcomes(native_study):
    add_decision(native_study, "market_only")
    add_decision(native_study, "full", rating="Buy")
    result = compare_study(native_study)
    assert result["paired_resolved_cells"] == 1
    assert all(row["cells"] == 1 for row in result["summary"].values())
    assert result["summary"]["market_only"]["direction_hit_rate"] == 1
    assert result["summary"]["full"]["direction_hit_rate"] == 0
    assert result["summary"]["market_only"]["mean_signed_alpha_pct"] < 1  # ignores recorded -99%
    assert result["summary"]["momentum_252"]["holds"] == 1
    assert result["summary"]["momentum_252"]["mean_signed_alpha_pct"] == 0
    assert result["cells"][0]["outcome_date"] == "2026-09-28"


def test_hash_and_horizon_mismatches_are_not_comparable(native_study):
    add_decision(native_study, "market_only", holding=10)
    add_decision(native_study, "full")
    result = compare_study(native_study)
    assert result["paired_resolved_cells"] == 0
    assert result["coverage"]["market_only"]["horizon_mismatch"] == 1
    with (native_study / "validation_prices/AAPL.csv").open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        compare_study(native_study)


def test_duplicate_manifest_cells_are_rejected(native_study):
    path = native_study / "results.json"
    manifest = json.loads(path.read_text())
    manifest["dates"] *= 2
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="unique"):
        compare_study(native_study)
