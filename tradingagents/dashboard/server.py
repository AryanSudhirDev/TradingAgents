"""TradingAgents interface over a local Timestral engine and paper execution."""

import argparse
import copy
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from tradingagents.agents.rating import run_rating
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.portfolio import PortfolioContext
from tradingagents.report_html import render_report
from tradingagents.reporting import _report_parts
from tradingagents.timestral_engine import TimestralEngine, decide

from .automation import NEW_YORK, PaperAutomation
from .store import PaperStore, stock_symbol

logger = logging.getLogger(__name__)

def report_parts(state):
    if state.get("run_settings", {}).get("engine") == "timestral":
        return [(title, key, [(title, key + ".md", state[key])]) for title, key in
                (("Forecast", "market_report"), ("Decision policy", "trader_investment_plan"), ("Risk and execution", "final_trade_decision")) if state.get(key)]
    return _report_parts(state)



class Desk:
    def __init__(self, config, path):
        self.config = copy.deepcopy(config)
        self.store = PaperStore(path)
        self.lock = threading.Lock()
        self.active = None
        self.markets = {}
        self.engine = TimestralEngine(self.config)
        self._calendar = None
        self.automation = PaperAutomation(self)

    def history(self, ticker):
        ticker = stock_symbol(ticker)
        result = []
        root = Path(self.config["results_dir"]) / ticker
        paths = [*root.glob("Timestral_logs/full_states_log_*.json"), *root.glob("TradingAgentsStrategy_logs/full_states_log_*.json")]
        for path in sorted(paths, key=lambda p: (p.name, "Timestral_logs" in str(p)), reverse=True):
            try:
                state = json.loads(path.read_text())
                if (isinstance(state, dict) and state.get("company_of_interest") == ticker
                        and isinstance(state.get("trade_date"), str)
                        and isinstance(state.get("final_trade_decision"), str) and state["final_trade_decision"]):
                    result.append(state)
            except (OSError, ValueError, TypeError):
                logger.warning("Cannot read saved state %s", path.name)
        return result

    def market(self, ticker):
        ticker = stock_symbol(ticker)
        with self.lock:
            cached = self.markets.get(ticker)
            if cached and time.monotonic() - cached["fetched"] < 60:
                return copy.deepcopy(cached)
        with run_config(self.config):
            frame = load_ohlcv(ticker, date.today().isoformat(), fill_gaps=False).dropna(subset=["Close"]).tail(60)
        if frame.empty:
            raise ValueError("No usable Yahoo price data.")
        rows = [{"date": str(row["Date"])[:10], "close": float(row["Close"])} for _, row in frame.iterrows()]
        result = {"ticker": ticker, "price": rows[-1]["close"], "as_of": rows[-1]["date"], "rows": rows, "fetched": time.monotonic()}
        self.store.mark(ticker, result["price"], result["as_of"])
        with self.lock:
            self.markets[ticker] = result
        return copy.deepcopy(result)

    def state(self):
        portfolio = self.store.snapshot()
        with self.lock:
            active = copy.deepcopy(self.active)
        latest = {}
        for ticker in portfolio["watchlist"]:
            history = self.history(ticker)
            if history:
                s = next((s for s in history if s.get("run_settings", {}).get("engine") == "timestral"), None)
                if s is None:
                    continue
                latest[ticker] = {"date": s["trade_date"], "rating": run_rating(s),
                                      "plan": s.get("trader_investment_plan", ""), "decision": s["final_trade_decision"],
                                      "forecast": s.get("forecast"), "completed": ["Data", "Timestral", "Policy"]}
        return {"portfolio": portfolio, "latest": latest, "active": active,
                    "provider": "local CPU", "quick_model": self.engine.metadata()["model"],
                    "deep_model": None, "engine": self.engine.metadata(), "fred_configured": False}

    def calendar(self, day):
        with self.lock:
            if self._calendar and self._calendar[0] == day:
                return self._calendar[1]
        when = date.fromisoformat(day)
        start, end = (when - timedelta(days=1100)).isoformat(), (when + timedelta(days=30)).isoformat()
        if self.automation.broker:
            rows = self.automation.broker.calendar(start, end)
        else:
            import exchange_calendars
            calendar = exchange_calendars.get_calendar("XNYS", start=start, end=end)
            rows = [{"date": str(d.date())} for d in calendar.sessions_in_range(start, end)]
        if not isinstance(rows, list) or not rows or any("date" not in row for row in rows):
            raise ValueError("Exchange calendar unavailable.")
        with self.lock:
            self._calendar = (day, rows)
        return rows

    def start(self, ticker):
        with self.automation.gate:
            if self.automation.run_lock.locked():
                raise ValueError("An automated paper cycle is running. Wait for it to finish.")
            self.claim(ticker)
            threading.Thread(target=self.analyze, args=(stock_symbol(ticker),), daemon=True).start()

    def claim(self, ticker):
        ticker = stock_symbol(ticker)
        if ticker not in self.store.snapshot()["watchlist"]:
            raise ValueError("Add this ticker to the watchlist first.")
        with self.lock:
            if self.active and self.active["status"] == "running":
                raise ValueError("An analysis is already running. Wait for it to finish.")
            self.active = {"ticker": ticker, "status": "running", "completed": [], "reports": {}, "stats": {"llm_calls": 0, "model_calls": 0}, "error": None}

    def analyze(self, ticker, portfolio=None, day=None, exit_reason=None):
        try:
            if portfolio is None:
                book = self.store.snapshot()
                portfolio = PortfolioContext.model_validate({"cash": book["cash"] / 100, "currency": "USD", "positions": [
                    {"ticker": p["ticker"], "quantity": p["quantity"], "average_price": p["basis"] / p["quantity"] / 100}
                    for p in book["positions"]
                ]})
            today = day or datetime.now(NEW_YORK).date().isoformat()
            with self.lock:
                self.active.update(completed=["Data"], stats={"llm_calls": 0, "model_calls": 0})
            forecast = None if exit_reason else self.engine.forecast(ticker, today, self.calendar(today))
            held = any(p.ticker == ticker and p.quantity > 0 for p in portfolio.positions)
            policy = {"rating": "Sell", "reason": exit_reason} if exit_reason else decide(forecast, forecast["last_close"], held)
            text = "Deadline exit; the model is bypassed." if exit_reason else "\n".join([
                f"Completed history ends {forecast['last_session']}; {forecast['context_sessions']} sessions. Log adjusted closes.",
                "| Session | Estimated q10 | Median | Estimated q90 |", "| --- | ---: | ---: | ---: |",
                *[f"| {r['date']} | {r['q10']:.2f} | {r['median']:.2f} | {r['q90']:.2f} |" for r in forecast["rows"]]])
            final = {"company_of_interest": ticker, "trade_date": today, "forecast": forecast,
                     "final_rating": policy["rating"], "market_report": text,
                     "trader_investment_plan": policy["reason"], "run_settings": self.engine.metadata(),
                     "final_trade_decision": f"Rating: {policy['rating']}\n{policy['reason']}\nPaper only. Five-session deadline; fresh execution quotes and risk limits still apply. Forecast bands are uncalibrated, not stop-loss guarantees."}
            from .operations import private_write
            folder = Path(self.config["results_dir"]) / ticker / "Timestral_logs"
            private_write(folder / f"full_states_log_{today}.json", json.dumps(final, allow_nan=False).encode())
            private_write(folder / f"report_{today}.html", render_report(ticker, final, final["run_settings"], report_parts(final)).encode())
            with self.lock:
                self.active.update(status="done", completed=["Data", "Timestral", "Policy"], reports={"Forecast": text},
                                   stats={"llm_calls": 0, "model_calls": int(bool(forecast and not forecast["cache_hit"])),
                                          "inference_ms": forecast["inference_ms"] if forecast else 0})
            return final
        except Exception as exc:
            logger.exception("Dashboard analysis failed for %s", ticker)
            with self.lock:
                self.active.update(status="error", error=f"{type(exc).__name__}: analysis failed. Check the server log and retry.")


def create_app(config=None, db_path=None):
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    @asynccontextmanager
    async def lifespan(app):
        app.state.desk.automation.start()
        yield
        app.state.desk.automation.stop()

    app = FastAPI(title="Timestral Paper Desk", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    desk = Desk(config or DEFAULT_CONFIG, db_path or Path.home() / ".tradingagents/dashboard/paper.sqlite3")
    app.state.desk = desk

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        if request.method not in ("GET", "HEAD"):
            if request.headers.get("origin") != f"http://{request.headers.get('host')}":
                return JSONResponse({"detail": "Open the dashboard on localhost to make changes."}, status_code=403)
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return JSONResponse({"detail": "JSON is required."}, status_code=415)
            if len(await request.body()) > 8192:
                return JSONResponse({"detail": "Request too large."}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.get("/")
    def index():
        return FileResponse(Path(__file__).parent / "static/index.html")

    @app.get("/app.js")
    def script():
        return FileResponse(Path(__file__).parent / "static/app.js", media_type="text/javascript")

    @app.get("/experiments")
    def experiments(window: str = "evaluation", cost: int = 20, metric: str = "excess"):
        from tradingagents.experiment_report import lab_snapshot, render_lab
        try:
            return HTMLResponse(render_lab(lab_snapshot(), window, cost, metric))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get("/api/experiments")
    def experiment_data():
        from tradingagents.experiment_report import lab_snapshot
        return lab_snapshot()

    @app.get("/api/timestral/backtest")
    def timestral_backtest():
        path = Path.home() / ".tradingagents/experiments/timestral/20261018-fixed-replay/results.json"
        if not path.exists():
            return {"ready": False}
        saved = json.loads(path.read_bytes())
        fields = ("arm", "sessions", "return_pct", "drawdown_pct", "fills", "average_exposure_pct")
        return {"ready": True, "completed_at": saved["completed_at"], "plan": saved["plan"],
                "limits": saved["limits"], "arms": [{k: arm[k] for k in fields} for arm in saved["arms"]]}

    @app.get("/api/timestral/markets")
    def timestral_markets():
        path = Path.home() / ".tradingagents/experiments/timestral/cross-market-20261018/results.json"
        if not path.exists():
            return {"ready": False}
        saved = json.loads(path.read_bytes())
        return {"ready": True, "completed_at": saved["completed_at"], "aggregates": saved["aggregates"],
                "requested_series": len(saved["plan"]["panel"]), "failed_series": len(saved["failed"]), "limits": saved["limits"]}

    @app.get("/api/state")
    def state():
        return desk.state()

    @app.get("/api/health")
    def health():
        result = desk.automation.health()
        return JSONResponse(result, status_code=200 if result["ok"] else 503)

    @app.get("/api/market/{ticker}")
    def market(ticker: str):
        try:
            return desk.market(ticker)
        except Exception:
            raise HTTPException(503, "Price data unavailable; retry later.") from None

    @app.get("/api/paper/status")
    def paper_status():
        return desk.automation.status()

    @app.post("/api/paper/connect")
    async def paper_connect(request: Request):
        try:
            body = await request.json()
            await run_in_threadpool(desk.automation.connect, body.get("key"), body.get("secret"))
            return {"ok": True}
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception:
            raise HTTPException(503, "Cannot connect the paper account; check credentials and try again.") from None

    @app.post("/api/paper/control")
    async def paper_control(request: Request):
        try:
            body = await request.json()
            await run_in_threadpool(desk.automation.control, body.get("action"), body.get("symbols"), body.get("mode", "alpaca"))
            return {"ok": True}
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get("/api/paper/report/{client_id}")
    def paper_report(client_id: str):
        with desk.store.connect() as db:
            row = db.execute("SELECT report FROM paper_runs WHERE client_id=?", (client_id,)).fetchone()
        if not row or not row[0]:
            raise HTTPException(404, "Paper research snapshot not found.")
        saved = json.loads(row[0])
        return HTMLResponse(render_report(saved["company_of_interest"], saved, saved.get("run_settings"), report_parts(saved)))

    @app.get("/api/history/{ticker}")
    def history(ticker: str):
        try:
            return [{"date": s["trade_date"], "rating": run_rating(s), "engine": s.get("run_settings", {}).get("engine", "archived agents")} for s in desk.history(ticker)]
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get("/api/report/{ticker}/{day}")
    def report(ticker: str, day: str, engine: str | None = None):
        try:
            for saved in desk.history(ticker):
                if saved["trade_date"] == day and (engine is None or saved.get("run_settings", {}).get("engine", "archived agents") == engine):
                    return HTMLResponse(render_report(stock_symbol(ticker), saved, saved.get("run_settings"), report_parts(saved)))
        except ValueError:
            pass
        raise HTTPException(404, "Report not found.")

    @app.post("/api/watch")
    async def watch(request: Request):
        try:
            body = await request.json()
            if type(body.get("remove", False)) is not bool:
                raise ValueError("remove must be a boolean.")
            settings = desk.automation.settings()
            if (body.get("remove") and stock_symbol(body.get("ticker")) in settings["symbols"]
                    and (settings["enabled"] or desk.automation.run_lock.locked())):
                raise ValueError("Pause automation and finish the current cycle before removing a managed symbol.")
            desk.store.watch(body.get("ticker"), body.get("remove", False))
            return {"ok": True}
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post("/api/analyze")
    async def analyze(request: Request):
        try:
            desk.start((await request.json()).get("ticker"))
            return {"ok": True}
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post("/api/trade")
    async def trade(request: Request):
        try:
            body = await request.json()
            ticker = stock_symbol(body.get("ticker"))
            if body.get("side") not in ("BUY", "SELL") or type(body.get("quantity")) is not int or not 1 <= body["quantity"] <= 1_000_000:
                raise ValueError("Choose BUY or SELL and a positive whole-share quantity.")
            quote = await run_in_threadpool(desk.market, ticker)
            history = desk.history(ticker)
            filled = desk.store.trade(ticker, body["side"], body["quantity"], quote["price"], quote["as_of"],
                                       body.get("request_id"), history[0]["trade_date"] if history else None)
            return {"trade": filled}
        except (ValueError, TypeError, AttributeError) as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception:
            logger.exception("Paper trade price could not be fetched")
            raise HTTPException(503, "No usable price; no paper trade was submitted.") from None

    return app


def main():
    parser = argparse.ArgumentParser(description="Local stock research and paper-trading dashboard")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        import uvicorn
        app = create_app()
    except ImportError:
        parser.error('Install the dashboard extra: pip install -e ".[dashboard,timestral]"')
    print(f"Research desk: http://127.0.0.1:{args.port} (paper money only)", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
