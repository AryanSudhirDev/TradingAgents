"""Transactional paper ledger. Money is integer cents; positions are whole shares."""

import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

INITIAL_CASH = 10_000_000


def stock_symbol(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{1,6}(?:-[A-Z])?", value.strip().upper()):
        raise ValueError("Use a US stock or ETF symbol, such as NVDA, SPY, or BRK-B.")
    return value.strip().upper()


def price_cents(value) -> int:
    try:
        price = Decimal(str(value))
        if not price.is_finite() or not 0 < price <= 1_000_000:
            raise ValueError
        cents = int((price * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        if cents <= 0:
            raise ValueError
        return cents
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        raise ValueError("A finite, positive price of at least one cent is required.") from None


class PaperStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK(id=1), cash INTEGER NOT NULL CHECK(cash>=0));
                CREATE TABLE IF NOT EXISTS watchlist (ticker TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS positions (ticker TEXT PRIMARY KEY, quantity INTEGER NOT NULL CHECK(quantity>0), basis INTEGER NOT NULL CHECK(basis>=0));
                CREATE TABLE IF NOT EXISTS quotes (ticker TEXT PRIMARY KEY, price INTEGER NOT NULL CHECK(price>0), as_of TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS trades (
                    request_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, side TEXT NOT NULL,
                    quantity INTEGER NOT NULL, price INTEGER NOT NULL, realized INTEGER NOT NULL,
                    timestamp TEXT NOT NULL, quote_as_of TEXT NOT NULL, analysis_date TEXT
                );
            """)
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM account").fetchone() is None:
                db.execute("INSERT INTO account VALUES (1, ?)", (INITIAL_CASH,))
                db.executemany("INSERT INTO watchlist VALUES (?)", [(t,) for t in ("NVDA", "AAPL", "MSFT", "SPY")])

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def watch(self, ticker, remove=False):
        ticker = stock_symbol(ticker)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if remove:
                db.execute("DELETE FROM watchlist WHERE ticker=?", (ticker,))
            else:
                if db.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] >= 20:
                    raise ValueError("The watchlist is limited to 20 symbols.")
                db.execute("INSERT OR IGNORE INTO watchlist VALUES (?)", (ticker,))

    def mark(self, ticker, price, as_of):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO quotes VALUES (?, ?, ?)", (stock_symbol(ticker), price_cents(price), as_of))

    def trade(self, ticker, side, quantity, price, as_of, request_id, analysis_date=None):
        ticker = stock_symbol(ticker)
        if side not in ("BUY", "SELL") or type(quantity) is not int or not 1 <= quantity <= 1_000_000:
            raise ValueError("Choose BUY or SELL and a positive whole-share quantity.")
        request_id = str(UUID(str(request_id)))
        cents = price_cents(price)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM trades WHERE request_id=?", (request_id,)).fetchone()
            if previous:
                if (previous["ticker"], previous["side"], previous["quantity"]) != (ticker, side, quantity):
                    raise ValueError("This request ID was already used for a different trade.")
                return dict(previous)
            cash = db.execute("SELECT cash FROM account WHERE id=1").fetchone()[0]
            pos = db.execute("SELECT quantity,basis FROM positions WHERE ticker=?", (ticker,)).fetchone()
            held, basis = (pos["quantity"], pos["basis"]) if pos else (0, 0)
            amount, realized = quantity * cents, 0
            if side == "BUY":
                if amount > cash:
                    raise ValueError("Insufficient virtual cash.")
                cash -= amount
                db.execute("INSERT OR REPLACE INTO positions VALUES (?, ?, ?)", (ticker, held + quantity, basis + amount))
            else:
                if quantity > held:
                    raise ValueError("Cannot sell more shares than the paper portfolio holds.")
                removed_basis = (2 * basis * quantity + held) // (2 * held)
                cash += amount
                realized = amount - removed_basis
                if quantity == held:
                    db.execute("DELETE FROM positions WHERE ticker=?", (ticker,))
                else:
                    db.execute("UPDATE positions SET quantity=?,basis=? WHERE ticker=?", (held - quantity, basis - removed_basis, ticker))
            db.execute("UPDATE account SET cash=? WHERE id=1", (cash,))
            db.execute("INSERT OR REPLACE INTO quotes VALUES (?, ?, ?)", (ticker, cents, as_of))
            db.execute("INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                request_id, ticker, side, quantity, cents, realized,
                datetime.now(UTC).isoformat(), as_of, analysis_date,
            ))
            return dict(db.execute("SELECT * FROM trades WHERE request_id=?", (request_id,)).fetchone())

    def snapshot(self):
        with self.connect() as db:
            db.execute("BEGIN")
            cash = db.execute("SELECT cash FROM account WHERE id=1").fetchone()[0]
            watchlist = [r[0] for r in db.execute("SELECT ticker FROM watchlist ORDER BY ticker")]
            positions = [dict(r) for r in db.execute("""
                SELECT p.*, q.price, q.as_of FROM positions p LEFT JOIN quotes q USING(ticker) ORDER BY ticker
            """)]
            trades = [dict(r) for r in db.execute("SELECT * FROM trades ORDER BY rowid DESC LIMIT 100")]
            realized = db.execute("SELECT COALESCE(SUM(realized),0) FROM trades").fetchone()[0]
        total = cash + sum(p["quantity"] * p["price"] for p in positions if p["price"] is not None)
        return {"cash": cash, "initial_cash": INITIAL_CASH, "total_value": total,
                    "realized": realized, "positions": positions, "trades": trades, "watchlist": watchlist}
