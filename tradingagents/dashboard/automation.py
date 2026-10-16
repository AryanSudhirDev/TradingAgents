"""One research-and-paper-order attempt per account, ticker and trading day."""

import copy
import hashlib
import json
import logging
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from tradingagents.agents.rating import run_rating
from tradingagents.portfolio import PortfolioContext

from .alpaca import AlpacaPaper, BrokerError, number, order_intent
from .simulator import LocalPaper
from .store import stock_symbol

NEW_YORK = ZoneInfo("America/New_York")
logger = logging.getLogger(__name__)


def trading_window(clock, *, scheduled=False):
    now = datetime.fromisoformat(clock["timestamp"]).astimezone(NEW_YORK)
    close = datetime.fromisoformat(clock["next_close"]).astimezone(NEW_YORK)
    start = now.replace(hour=10 if scheduled else 9, minute=0 if scheduled else 30, second=0, microsecond=0)
    return now, clock.get("is_open") is True and start <= now < close - timedelta(minutes=30)


class PaperAutomation:
    def __init__(self, desk):
        self.desk, self.store = desk, desk.store
        self.credentials = self.store.path.with_name("alpaca-paper.json")
        self.gate = threading.RLock()
        self.run_lock = threading.Lock()
        self.cancel = threading.Event()
        self.shutdown = threading.Event()
        self.worker = None
        self.started_at = datetime.now(UTC).isoformat()
        self.last_poll = None
        self.scheduler_error = None
        self.message = "Connect an Alpaca paper account to begin."
        self.cached = None
        self.fetched = 0
        self.broker = None
        self.simulator = LocalPaper(desk)
        try:
            self.broker = AlpacaPaper.load(self.credentials)
            if self.broker:
                self.message = "Paper credentials loaded. Enable daily runs or run one cycle."
        except BrokerError as exc:
            self.message = str(exc)
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS automation (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL, symbols TEXT NOT NULL, account TEXT);
                INSERT OR IGNORE INTO automation (id,enabled,symbols,account) VALUES (1, 0, '["AAPL","MSFT","NVDA"]', NULL);
                CREATE TABLE IF NOT EXISTS paper_runs (
                    account TEXT NOT NULL, day TEXT NOT NULL, ticker TEXT NOT NULL,
                    client_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL, rating TEXT,
                    intent TEXT, note TEXT NOT NULL, updated TEXT NOT NULL, report TEXT,
                    PRIMARY KEY(account,day,ticker)
                );
                CREATE TABLE IF NOT EXISTS paper_equity (account TEXT NOT NULL, stamp TEXT NOT NULL, equity INTEGER NOT NULL, benchmark INTEGER, PRIMARY KEY(account,stamp));
            """)
            db.execute("BEGIN IMMEDIATE")
            if "report" not in {r[1] for r in db.execute("PRAGMA table_info(paper_runs)")}:
                db.execute("ALTER TABLE paper_runs ADD COLUMN report TEXT")
            if "mode" not in {r[1] for r in db.execute("PRAGMA table_info(automation)")}:
                db.execute("ALTER TABLE automation ADD COLUMN mode TEXT NOT NULL DEFAULT 'alpaca'")

    def settings(self):
        with self.store.connect() as db:
            row = dict(db.execute("SELECT * FROM automation WHERE id=1").fetchone())
        row["symbols"] = json.loads(row["symbols"])
        return row

    def symbols(self, symbols):
        if not isinstance(symbols, list) or not 1 <= len(symbols) <= 8:
            raise ValueError("Choose one to eight watched symbols for automation.")
        result = list(dict.fromkeys(stock_symbol(t) for t in symbols))
        if not set(result).issubset(self.store.snapshot()["watchlist"]):
            raise ValueError("Add every automated symbol to the watchlist first.")
        return result

    def connect(self, key, secret):
        with self.gate:
            if self.run_lock.locked():
                raise ValueError("Pause and wait for the active cycle before changing credentials.")
            broker = AlpacaPaper(key, secret)
            account = broker.account()
            broker.positions()
            broker.save(self.credentials)
            with self.store.connect() as db:
                db.execute("UPDATE automation SET enabled=0, mode='alpaca', account=? WHERE id=1", (account["id"],))
            self.broker, self.cached, self.fetched = broker, None, 0
            self.message = "Paper account connected. Enable daily runs or run one cycle."

    def control(self, action, symbols=None, mode="alpaca"):
        with self.gate:
            if action == "pause":
                self.cancel.set()
                with self.store.connect() as db:
                    db.execute("UPDATE automation SET enabled=0 WHERE id=1")
                self.message = "Paused. Existing DAY orders remain at Alpaca until filled, canceled, or expired."
                return
            if mode not in ("alpaca", "local"):
                raise ValueError("Choose local simulation or Alpaca paper.")
            if action not in ("enable", "run", "select"):
                raise ValueError("Choose enable, run, select, or pause.")
            if action == "select":
                if self.run_lock.locked():
                    raise ValueError("Pause and finish the current cycle before switching modes.")
                self.cancel.set()
                with self.store.connect() as db:
                    db.execute("UPDATE automation SET enabled=0,mode=? WHERE id=1", (mode,))
                self.cached, self.fetched = None, 0
                self.message = "Local simulation selected. Run a cycle or enable daily runs." if mode == "local" else "Alpaca paper selected. Connect credentials to begin."
                return
            if mode == "alpaca" and not self.broker:
                raise ValueError("Connect your Alpaca paper account first.")
            if self.run_lock.locked() or (self.desk.active and self.desk.active["status"] == "running"):
                raise ValueError("A research cycle is already running.")
            selected = self.symbols(symbols)
            with self.store.connect() as db:
                db.execute("UPDATE automation SET symbols=?, mode=?, enabled=CASE WHEN ? THEN 1 ELSE enabled END WHERE id=1", (json.dumps(selected), mode, action == "enable"))
            self.cancel.clear()
            self.kick(scheduled=action == "enable")

    def kick(self, *, scheduled=True):
        with self.gate:
            if scheduled and not self.settings()["enabled"]:
                return
            if self.desk.active and self.desk.active["status"] == "running":
                return
            if not self.run_lock.acquire(blocking=False):
                return
            self.message = "Checking the selected paper account and execution window…"
            threading.Thread(target=self.cycle, kwargs={"scheduled": scheduled}, daemon=True).start()

    def start(self):
        def worker():
            while not self.shutdown.is_set():
                self.last_poll = datetime.now(UTC).isoformat()
                try:
                    if self.settings()["enabled"]:
                        self.kick()
                    self.scheduler_error = None
                except Exception:
                    self.scheduler_error = "Scheduler check failed; retrying in 30 seconds. Check the server log."
                    logger.exception("Paper scheduler check failed")
                if self.shutdown.wait(30):
                    break
        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def stop(self):
        self.shutdown.set()
        self.cancel.set()

    def health(self):
        alive = bool(self.worker and self.worker.is_alive())
        fresh = bool(self.last_poll and (datetime.now(UTC) - datetime.fromisoformat(self.last_poll)).total_seconds() < 120)
        return {"ok": alive and fresh and not self.scheduler_error, "pid": os.getpid(),
                "started_at": self.started_at, "worker_alive": alive, "last_poll": self.last_poll,
                "error": self.scheduler_error}

    def update(self, account, day, ticker, status, note, *, rating=None, intent=None):
        with self.store.connect() as db:
            db.execute("""UPDATE paper_runs SET status=?, note=?, rating=COALESCE(?,rating),
                        intent=COALESCE(?,intent), updated=? WHERE account=? AND day=? AND ticker=?""",
                       (status, note, rating, json.dumps(intent) if intent else None,
                        datetime.now(UTC).isoformat(), account, day, ticker))

    def window(self, execution, scheduled=False):
        if execution is not self.simulator:
            return trading_window(execution.clock(), scheduled=scheduled)
        now = datetime.now(NEW_YORK)
        return now, now.weekday() < 5 and (not scheduled or (now.hour, now.minute) >= (16, 30))

    def sample(self, execution):
        account = execution.account()
        try:
            benchmark = round(self.desk.market("SPY")["price"] * 100)
        except Exception:
            benchmark = None
        with self.store.connect() as db:
            db.execute("INSERT INTO paper_equity VALUES (?,?,?,?)", (account["id"], datetime.now(UTC).isoformat(), int((number(account["equity"]) * 100).quantize(number(1))), benchmark))

    def performance(self, account):
        with self.store.connect() as db:
            samples = [dict(r) for r in db.execute("SELECT stamp,equity,benchmark FROM paper_equity WHERE account=? ORDER BY stamp", (account,))]
        if not samples:
            return {"samples": []}
        peak = samples[0]["equity"]
        drawdown = 0
        for row in samples:
            peak = max(peak, row["equity"])
            drawdown = min(drawdown, (row["equity"] / peak - 1) * 100)
        first, last = samples[0], samples[-1]
        return {"samples": samples[-500:], "initial_equity": first["equity"], "initial_benchmark": first["benchmark"],
                "started": first["stamp"], "pnl": last["equity"] - first["equity"],
                "return_pct": (last["equity"] / first["equity"] - 1) * 100,
                "spy_return_pct": (last["benchmark"] / first["benchmark"] - 1) * 100 if first["benchmark"] and last["benchmark"] else None,
                "drawdown_pct": drawdown, "count": len(samples)}

    def cycle(self, *, scheduled=True):
        account_id = day = ticker = None
        process_lock = None
        analysis_claimed = False
        sampled = False
        try:
            # Multiple local servers must not size different symbols against the same cash.
            try:
                import fcntl
            except ImportError:
                raise BrokerError("Run the automated paper worker on macOS or Linux.") from None
            process_lock = self.store.path.with_suffix(".worker.lock").open("a")
            try:
                fcntl.flock(process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.message = "Another paper worker is running for this account database."
                return
            if self.cancel.is_set():
                return
            settings = self.settings()
            execution = self.simulator if settings["mode"] == "local" else self.broker
            account = execution.account()
            account_id = account["id"]
            if settings["mode"] == "alpaca" and account_id != settings["account"]:
                raise BrokerError("The account changed. Reconnect before running automation.")
            with self.store.connect() as db:
                uncertain = [dict(r) for r in db.execute("SELECT * FROM paper_runs WHERE account=? AND status IN ('submitting','unknown')", (account_id,))]
            for previous in uncertain:
                existing = execution.order(previous["client_id"])
                if not existing:
                    raise BrokerError("An uncertain submission needs review in Alpaca. No further orders will be sent.")
                self.update(account_id, previous["day"], previous["ticker"], "submitted", "Recovered broker order: " + existing["status"])
            # The process lock proves these claims belong to a worker that has stopped.
            with self.store.connect() as db:
                db.execute("UPDATE paper_runs SET status='error',note=?,updated=? WHERE account=? AND status='researching'",
                           ("Interrupted research. No order was sent; this symbol resumes on the next trading day.",
                            datetime.now(UTC).isoformat(), account_id))
            now, allowed = self.window(execution, scheduled=scheduled)
            if not allowed:
                self.message = "Waiting for 16:30 New York on a market day." if execution is self.simulator else "Waiting for a market session: daily start 10:00 New York; no new orders in the final 30 minutes."
                return
            day = now.date().isoformat()
            for ticker in settings["symbols"]:
                if self.cancel.is_set():
                    return
                if execution is self.simulator:
                    execution.market(ticker, day)
                if execution.orders("open"):
                    self.message = "Waiting for open paper orders to finish. See Alpaca orders below."
                    return
                client_id = "ta-" + hashlib.sha256(f"{account_id}:{day}:{ticker}".encode()).hexdigest()[:40]
                if execution is self.simulator:
                    client_id = str(uuid5(NAMESPACE_URL, client_id))
                with self.store.connect() as db:
                    claimed = db.execute("INSERT OR IGNORE INTO paper_runs (account,day,ticker,client_id,status,note,updated) VALUES (?,?,?,?, 'researching',?,?)",
                                         (account_id, day, ticker, client_id, "Research started", datetime.now(UTC).isoformat())).rowcount
                if not claimed:
                    with self.store.connect() as db:
                        previous = dict(db.execute("SELECT * FROM paper_runs WHERE account=? AND day=? AND ticker=?", (account_id, day, ticker)).fetchone())
                    if previous["status"] == "researching":
                        self.update(account_id, day, ticker, "error", "Interrupted research. No order was sent; this symbol resumes on the next trading day.")
                    continue
                self.desk.claim(ticker)
                analysis_claimed = True
                if not sampled:
                    self.sample(execution)
                    sampled = True
                account = execution.account()
                positions = execution.positions()
                portfolio = PortfolioContext.model_validate({"cash": account["cash"], "currency": "USD", "positions": [
                    {"ticker": p["symbol"].replace(".", "-"), "quantity": p["qty"], "average_price": p["avg_entry_price"]} for p in positions
                ]})
                self.message = f"Researching {ticker} for the {day} paper cycle…"
                final = self.desk.analyze(ticker, portfolio=portfolio, day=day)
                if not final or not final.get("final_trade_decision"):
                    self.update(account_id, day, ticker, "error", "Analysis failed or incomplete; no order was sent.")
                    continue
                rating = run_rating(final)
                report = {key: value for key, value in final.items() if key.endswith("_report") or key in (
                    "final_trade_decision", "final_rating", "investment_plan", "trader_investment_plan",
                    "investment_debate_state", "risk_debate_state", "run_settings",
                )}
                report.update(company_of_interest=ticker, trade_date=day)
                with self.store.connect() as db:
                    db.execute("UPDATE paper_runs SET report=?,rating=? WHERE client_id=?", (json.dumps(report, default=str), rating, client_id))
                with self.gate:
                    if self.cancel.is_set():
                        self.update(account_id, day, ticker, "skipped", "Paused before submission", rating=rating)
                        return
                    current, allowed = self.window(execution)
                    if not allowed or current.date().isoformat() != day:
                        self.update(account_id, day, ticker, "skipped", "Execution window closed during research", rating=rating)
                        continue
                    account, positions = execution.account(), execution.positions()
                    if account["id"] != account_id or execution.orders("open"):
                        raise BrokerError("Account changed or an open order exists; no additional order was sent.")
                    if execution is self.simulator:
                        intent = execution.intent(ticker, rating, account, positions, day)
                    else:
                        quote = execution.quote(ticker) if rating in ("Buy", "Overweight", "Underweight", "Sell") else None
                        intent = order_intent(ticker, rating, account, positions, quote)
                    if not intent:
                        self.update(account_id, day, ticker, "skipped", "No change under the rating and sizing rules", rating=rating)
                        continue
                    self.update(account_id, day, ticker, "submitting", "Intent saved before broker submission", rating=rating, intent=intent)
                    try:
                        order = execution.order(client_id)
                        if not order:
                            order = execution.submit(intent, client_id, day) if execution is self.simulator else execution.submit(intent, client_id)
                    except Exception:
                        self.update(account_id, day, ticker, "unknown", "Submission uncertain. Reconcile using client order ID in Alpaca; no automatic resubmission.")
                        raise BrokerError("Paper submission needs reconciliation; check the order journal and Alpaca.") from None
                    self.update(account_id, day, ticker, "submitted", "Simulated fill" if execution is self.simulator else "Broker order: " + order["status"])
            self.message = f"{day} cycle complete. Each symbol is attempted once per trading day."
        except Exception as exc:
            safe = str(exc) if isinstance(exc, BrokerError) else "Paper cycle failed. No automatic retry of this symbol today."
            self.message = safe
            if account_id and day and ticker:
                with self.store.connect() as db:
                    db.execute("UPDATE paper_runs SET status='error',note=?,updated=? WHERE account=? AND day=? AND ticker=? AND status='researching'", (safe, datetime.now(UTC).isoformat(), account_id, day, ticker))
            with self.desk.lock:
                if analysis_claimed and self.desk.active and self.desk.active["status"] == "running":
                    self.desk.active.update(status="error", error=safe)
        finally:
            if sampled:
                try:
                    self.sample(execution)
                except Exception:
                    self.message += " Performance sample unavailable."
            self.fetched = 0
            if process_lock:
                process_lock.close()
            self.run_lock.release()

    def status(self):
        settings = self.settings()
        local = settings["mode"] == "local"
        account_id = "local-forward" if local else settings["account"]
        result = {"configured": bool(self.broker), "enabled": bool(settings["enabled"]), "symbols": settings["symbols"],
                  "mode": settings["mode"], "busy": self.run_lock.locked(), "message": self.message, "connected": False,
                  "performance": self.performance(account_id), "health": self.health()}
        with self.store.connect() as db:
            result["runs"] = [dict(r) for r in db.execute("SELECT day,ticker,client_id,status,rating,intent,note,updated,report IS NOT NULL AS has_report FROM paper_runs WHERE account=? ORDER BY updated DESC LIMIT 100", (account_id,))]
        if local:
            try:
                return {**result, "connected": True, "account": self.simulator.account(), "positions": self.simulator.positions(),
                        "orders": self.simulator.orders(), "as_of": datetime.now(UTC).isoformat()}
            except Exception:
                return {**result, "error": "Local portfolio marks unavailable; retry later."}
        if not self.broker:
            return result
        if time.monotonic() - self.fetched >= 30:
            try:
                account, positions, orders, clock = self.broker.account(), self.broker.positions(), self.broker.orders(), self.broker.clock()
                if account["id"] != settings["account"]:
                    raise BrokerError("Paper account changed. Reconnect before proceeding.")
                self.cached = {"connected": True, "account": {k: account.get(k) for k in ("equity", "cash", "last_equity")},
                               "positions": [{k: p.get(k) for k in ("symbol", "qty", "avg_entry_price", "current_price", "market_value", "unrealized_pl")} for p in positions],
                               "orders": [{k: o.get(k) for k in ("symbol", "side", "qty", "status", "filled_qty", "filled_avg_price", "limit_price", "client_order_id", "submitted_at")} for o in orders],
                               "market_open": clock.get("is_open"), "next_open": clock.get("next_open"), "as_of": datetime.now(UTC).isoformat()}
            except Exception as exc:
                self.cached = {"connected": False, "error": str(exc) if isinstance(exc, BrokerError) else "Paper account data unavailable."}
            self.fetched = time.monotonic()
        return {**result, **copy.deepcopy(self.cached or {})}
