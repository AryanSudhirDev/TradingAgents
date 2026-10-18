"""Pinned local CPU forecasts and a fixed, long-only five-session paper policy."""

import hashlib
import json
import math
import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv

MODEL = "mistralai/Timestral-28M"
REVISION = "180698bbf5a50dda3516aa6419798437fb03a430"
VERSION = "timestral-paper-v1"
HORIZON = 5
CONTEXT = 512
MIN_CONTEXT = 128
POLICY = {"entry_buffer_pct": 1.0, "maximum_q10_loss_pct": 3.0, "target_equity_pct": 5.0,
          "maximum_holding_sessions": 5, "shorts": False, "leverage": False}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def decide(forecast, reference, held=False):
    """Quantiles are model estimates, not calibrated confidence or stop-loss promises."""
    if not math.isfinite(reference) or reference <= 0:
        raise ValueError("A positive decision reference price is required.")
    terminal = forecast["rows"][-1]
    median_return = (terminal["median"] / reference - 1) * 100
    downside = (terminal["q10"] / reference - 1) * 100
    if held:
        rating = "Sell" if median_return <= 0 else "Hold"
        reason = "Median forecast does not exceed the reference price." if rating == "Sell" else "Keep the existing position until its deadline or an earlier exit signal; no top-ups."
    elif median_return > POLICY["entry_buffer_pct"] and downside >= -POLICY["maximum_q10_loss_pct"]:
        rating, reason = "Overweight", "Median clears the fixed 1% entry buffer and the estimated q10 loss is within 3%. Target 5% of equity."
    else:
        rating, reason = "Hold", "Entry requirements are not met; keep cash."
    return {"rating": rating, "reason": reason, "reference_price": reference,
            "median_return_pct": median_return, "q10_return_pct": downside}


class TimestralEngine:
    def __init__(self, config):
        self.config = config
        self.lock = threading.Lock()
        self.model = None

    @staticmethod
    def metadata():
        return {"engine": "timestral", "version": VERSION, "model": MODEL, "revision": REVISION,
                "device": "cpu", "threads": 8, "horizon_sessions": HORIZON,
                "context_sessions": CONTEXT, "policy": POLICY,
                "warning": "Uncalibrated forecast intervals; experimental paper strategy. No profitability claim."}

    def load(self, download=False):
        if self.model is None:
            try:
                import torch
                from timestral import TimestralForecaster
            except ImportError:
                raise ValueError('Install the timestral extra and download the pinned model before forecasting.') from None
            torch.set_num_threads(8)
            self.model = TimestralForecaster.from_pretrained(MODEL, revision=REVISION, device="cpu",
                                                           local_files_only=not download)
        return self.model

    def forecast(self, ticker, day, calendar):
        # The decision uses only sessions strictly before its requested day, even after today's close.
        when = date.fromisoformat(day)
        past = sorted({row["date"] for row in calendar if row["date"] < day})[-CONTEXT:]
        if len(past) < MIN_CONTEXT:
            raise ValueError("At least 128 exchange sessions of history are required.")
        future = sorted({row["date"] for row in calendar if row["date"] > past[-1]})[:HORIZON]
        if len(future) != HORIZON or date.fromisoformat(past[-1]) >= when:
            raise ValueError("The exchange calendar does not cover the five-session forecast.")
        with run_config(self.config):
            frame = load_ohlcv(ticker, (when - timedelta(days=1)).isoformat(), fill_gaps=False)
        dates = pd.to_datetime(frame["Date"]).dt.strftime("%Y-%m-%d")
        if dates.duplicated().any():
            raise ValueError("Duplicate historical sessions; forecast refused.")
        closes = pd.Series(pd.to_numeric(frame["Close"], errors="coerce").to_numpy(), index=dates)
        values = closes.reindex(past).to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError("Missing, stale or invalid completed-session prices; forecast refused.")
        return self.forecast_history(ticker, past, values, future)

    def forecast_history(self, ticker, past, values, future):
        """Shared production/replay boundary: historical target values and future labels only."""
        values = np.asarray(values, dtype=float)
        if (values.ndim != 1 or not MIN_CONTEXT <= len(past) <= CONTEXT or len(values) != len(past)
                or past != sorted(set(past)) or future != sorted(set(future)) or len(future) != HORIZON
                or past[-1] >= future[0] or not np.isfinite(values).all() or (values <= 0).any()):
            raise ValueError("Forecast context must be complete, ordered, finite and strictly before its horizon.")
        inputs = {"ticker": ticker, "dates": past, "closes": values.tolist(), "forecast_dates": future,
                  "model": MODEL, "revision": REVISION, "transform": "log-adjusted-close", "version": VERSION}
        identity = digest(inputs)
        path = Path(self.config["results_dir"]) / ticker / "Timestral_inputs" / (identity + ".json")
        with self.lock:
            if path.exists():
                cached = json.loads(path.read_bytes())
                if cached["input_sha256"] != identity or digest(cached["inputs"]) != identity or digest(cached["forecast"]) != cached["forecast_sha256"]:
                    raise ValueError("Saved Timestral input or forecast hash changed.")
                return {**cached["forecast"], "cache_hit": True}
            model = self.load()
            started = time.perf_counter()
            prediction = model.forecast(np.log(values).astype(np.float32), prediction_length=HORIZON)
            elapsed = (time.perf_counter() - started) * 1000
            quantiles = np.exp(np.asarray(prediction.quantiles, dtype=float).reshape(HORIZON, -1))
            levels = np.asarray(prediction.quantile_levels, dtype=float)
            if (quantiles.shape != (HORIZON, 21) or levels.shape != (21,)
                    or not np.isfinite(quantiles).all() or (quantiles <= 0).any()
                    or (np.diff(quantiles, axis=1) < -1e-8).any()
                    or not np.all(np.diff(levels) > 0)):
                raise ValueError("Timestral returned invalid forecast quantiles.")
            indices = [int(np.flatnonzero(np.isclose(levels, q))[0]) for q in (0.1, 0.5, 0.9)]
            rows = [{"date": d, "q10": float(q[indices[0]]), "median": float(q[indices[1]]),
                     "q90": float(q[indices[2]]), "quantiles": q.tolist()}
                    for d, q in zip(future, quantiles, strict=True)]
            result = {"input_sha256": identity, "created_at": datetime.now(UTC).isoformat(),
                      "last_session": past[-1], "last_close": float(values[-1]), "context_sessions": len(past),
                      "rows": rows, "quantile_levels": levels.tolist(), "inference_ms": elapsed, "cache_hit": False,
                      "source": "Yahoo adjusted daily closes, complete exchange sessions only", **self.metadata()}
            from tradingagents.dashboard.operations import private_write
            private_write(path, json.dumps({"inputs": inputs, "input_sha256": identity, "forecast": result,
                                           "forecast_sha256": digest(result)}, allow_nan=False).encode())
            return result


if __name__ == "__main__":
    # Explicit setup only; the dashboard never silently downloads model code or weights.
    from tradingagents.default_config import DEFAULT_CONFIG
    TimestralEngine(DEFAULT_CONFIG).load(download=True)
    print("Pinned Timestral-28M CPU weights are cached.")
