"""Local dashboard over the current graph, with optional Alpaca paper execution."""

import argparse
import copy
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from cli.stats_handler import StatsCallbackHandler
from tradingagents.agents.rating import run_rating
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.portfolio import PortfolioContext
from tradingagents.report_html import render_report
from tradingagents.reporting import _report_parts

from .automation import PaperAutomation
from .store import PaperStore, stock_symbol

logger = logging.getLogger(__name__)
REPORT_FIELDS = {
    "market_report": "Market", "sentiment_report": "Sentiment", "news_report": "News",
    "fundamentals_report": "Fundamentals", "investment_plan": "Research manager",
    "trader_investment_plan": "Trader", "final_trade_decision": "Portfolio manager",
}


def completed_stages(state):
    completed = [name for field, name in REPORT_FIELDS.items() if state.get(field)]
    for group, fields in (
        ("investment_debate_state", (("bull_history", "Bull"), ("bear_history", "Bear"))),
        ("risk_debate_state", (("aggressive_history", "Aggressive"), ("conservative_history", "Conservative"), ("neutral_history", "Neutral"))),
    ):
        for field, name in fields:
            if (state.get(group) or {}).get(field):
                completed.append(name)
    return completed


class Desk:
    def __init__(self, config, path):
        self.config = copy.deepcopy(config)
        self.store = PaperStore(path)
        self.lock = threading.Lock()
        self.active = None
        self.stats = None
        self.markets = {}
        self.automation = PaperAutomation(self)

    def history(self, ticker):
        ticker = stock_symbol(ticker)
        folder = Path(self.config["results_dir"]) / ticker / "TradingAgentsStrategy_logs"
        result = []
        for path in sorted(folder.glob("full_states_log_*.json"), reverse=True):
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
            if active and active["status"] == "running" and self.stats:
                active["stats"] = self.stats.get_stats()
        latest = {}
        for ticker in portfolio["watchlist"]:
            history = self.history(ticker)
            if history:
                s = history[0]
                latest[ticker] = {"date": s["trade_date"], "rating": run_rating(s),
                                      "plan": s.get("trader_investment_plan", ""), "decision": s["final_trade_decision"],
                                      "completed": completed_stages(s)}
        return {"portfolio": portfolio, "latest": latest, "active": active,
                    "provider": self.config["llm_provider"], "quick_model": self.config["quick_think_llm"],
                    "deep_model": self.config["deep_think_llm"], "fred_configured": bool(os.environ.get("FRED_API_KEY"))}

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
            self.active = {"ticker": ticker, "status": "running", "completed": [], "reports": {}, "stats": {}, "error": None}
            self.stats = None

    def analyze(self, ticker, portfolio=None, day=None):
        stats = StatsCallbackHandler()
        with self.lock:
            self.stats = stats
        graph = None
        try:
            if portfolio is None:
                book = self.store.snapshot()
                portfolio = PortfolioContext.model_validate({"cash": book["cash"] / 100, "currency": "USD", "positions": [
                    {"ticker": p["ticker"], "quantity": p["quantity"], "average_price": p["basis"] / p["quantity"] / 100}
                    for p in book["positions"]
                ]})
            graph = TradingAgentsGraph(config=copy.deepcopy(self.config), callbacks=[stats])
            today = day or date.today().isoformat()
            initial = graph.create_run_state(ticker, today, portfolio=portfolio)
            args = graph.propagator.get_graph_args(callbacks=[stats])
            tid = graph.begin_checkpoint(ticker, today, portfolio=portfolio)
            if tid:
                args["config"].setdefault("configurable", {})["thread_id"] = tid
            final = {}
            for _, chunk in graph.stream_run(graph.checkpoint_input(initial), **args):
                if chunk:
                    final.update(chunk)
                    completed = completed_stages(final)
                    reports = {name: final[field] for field, name in REPORT_FIELDS.items() if final.get(field)}
                    with self.lock:
                        self.active.update(completed=completed, reports=reports, stats=stats.get_stats())
            graph.record_decision(ticker, today, final)
            graph.save_reports(final, ticker)
            graph.clear_checkpoint_on_success(ticker, today, portfolio=portfolio)
            final["run_settings"] = graph.run_settings()
            with self.lock:
                self.active.update(status="done", stats=stats.get_stats())
            return final
        except Exception as exc:
            logger.exception("Dashboard analysis failed for %s", ticker)
            with self.lock:
                self.active.update(status="error", error=f"{type(exc).__name__}: analysis failed. Check the server log and retry.")
        finally:
            if graph is not None:
                graph.end_checkpoint()


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

    app = FastAPI(title="TradingAgents Research Desk", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
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
        return HTMLResponse(render_report(saved["company_of_interest"], saved, saved.get("run_settings"), _report_parts(saved)))

    @app.get("/api/history/{ticker}")
    def history(ticker: str):
        try:
            return [{"date": s["trade_date"], "rating": run_rating(s)} for s in desk.history(ticker)]
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get("/api/report/{ticker}/{day}")
    def report(ticker: str, day: str):
        try:
            for saved in desk.history(ticker):
                if saved["trade_date"] == day:
                    return HTMLResponse(render_report(stock_symbol(ticker), saved, saved.get("run_settings"), _report_parts(saved)))
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
        parser.error('Install the dashboard extra: pip install -e ".[chatgpt,dashboard]"')
    print(f"Research desk: http://127.0.0.1:{args.port} (paper money only)", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
