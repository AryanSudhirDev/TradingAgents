"""A fixed consistency screen and safe, read-only local presentation."""

import copy

import pytest

from tradingagents.experiment_report import forward_candidates, lab_snapshot, render_lab


def test_screen_requires_both_higher_cost_windows_and_drawdown_controls():
    rows = []
    for window in ("validation", "evaluation"):
        rows += [{"ticker": "XLY", "rule": "buy_hold", "window": window, "slippage_bps": 20,
                  "return_pct": 0, "max_drawdown_pct": -5, "benchmark_rule": "buy_hold", "excess_return_pct": 0},
                 {"ticker": "XLY", "rule": "weekly_reversal", "window": window, "slippage_bps": 20,
                  "return_pct": 1, "max_drawdown_pct": -4, "benchmark_rule": "buy_hold", "excess_return_pct": 1}]
    assert len(forward_candidates(rows)) == 1
    bad = copy.deepcopy(rows)
    bad[-1]["max_drawdown_pct"] = -6
    assert not forward_candidates(bad)
    bad[-1]["slippage_bps"] = 5
    assert not forward_candidates(bad)


def test_empty_lab_is_read_only_and_escapes_saved_metadata(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert not list(tmp_path.iterdir())
    snapshot = lab_snapshot()
    assert not list(tmp_path.iterdir())
    snapshot["sectors"] = {"status": "<script>alert(1)</script>", "case_count": "<unsafe>", "results": []}
    html = render_lab(snapshot)
    assert "<script>" not in html and "<unsafe>" not in html
    assert "&lt;script&gt;" in html and "&lt;unsafe&gt;" in html
    assert '<form action="/experiments" method="get">' in html
    assert "No completed sector results" in html


@pytest.mark.parametrize("options", [{"window": "future"}, {"cost": 0}, {"metric": "<script>"}])
def test_invalid_filters_are_rejected(options):
    with pytest.raises(ValueError, match="available"):
        render_lab({}, **options)


def test_other_horizons_do_not_enter_pooled_native_scores(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    folder = tmp_path / ".tradingagents/experiments/agents/ten-session"
    folder.mkdir(parents=True)
    (folder / "results.json").write_text(json.dumps({"planned_decisions": 50, "holding_sessions": 10}))
    snapshot = lab_snapshot()
    assert not snapshot["agents"]
    assert any("different outcome horizon" in e for e in snapshot["errors"])
