"""Keyless forward simulation. Snapshot fills with 5 bps slippage per side, not broker fills."""

from decimal import Decimal

from .alpaca import BrokerError, size_order
from .store import PaperStore, price_cents


class LocalPaper:
    def __init__(self, desk):
        self.desk = desk
        self.store = PaperStore(desk.store.path.with_name("forward.sqlite3"))

    def market(self, ticker, day):
        quote = self.desk.market(ticker)
        if quote["as_of"] != day:
            raise BrokerError("No Yahoo daily bar for this date; the local simulator will wait for a market day.")
        return quote

    def account(self):
        for p in self.store.snapshot()["positions"]:
            quote = self.desk.market(p["ticker"])
            self.store.mark(p["ticker"], quote["price"], quote["as_of"])
        book = self.store.snapshot()
        return {"id": "local-forward", "cash": str(Decimal(book["cash"]) / 100),
                "equity": str(Decimal(book["total_value"]) / 100), "last_equity": None}

    def positions(self):
        return [{"symbol": p["ticker"], "qty": str(p["quantity"]),
                 "avg_entry_price": str(Decimal(p["basis"]) / p["quantity"] / 100),
                 "current_price": str(Decimal(p["price"]) / 100),
                 "market_value": str(Decimal(p["price"] * p["quantity"]) / 100),
                 "unrealized_pl": str(Decimal(p["price"] * p["quantity"] - p["basis"]) / 100)}
                for p in self.store.snapshot()["positions"]]

    @staticmethod
    def rendered(trade):
        return {"symbol": trade["ticker"], "qty": str(trade["quantity"]), "side": trade["side"].lower(),
                "client_order_id": trade["request_id"], "status": "simulated", "filled_qty": str(trade["quantity"]),
                "filled_avg_price": str(Decimal(trade["price"]) / 100), "limit_price": None, "submitted_at": trade["timestamp"]}

    def orders(self, status="all"):
        return [] if status == "open" else [self.rendered(t) for t in self.store.snapshot()["trades"]]

    def order(self, client_id):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM trades WHERE request_id=?", (client_id,)).fetchone()
        return self.rendered(dict(row)) if row else None

    def intent(self, ticker, rating, account, positions, day):
        if rating not in ("Buy", "Overweight", "Underweight", "Sell"):
            return None
        quote = self.market(ticker, day)
        price = Decimal(str(quote["price"])) * (Decimal("1.0005") if rating in ("Buy", "Overweight") else Decimal("0.9995"))
        return size_order(ticker, rating, account, positions, Decimal(price_cents(price)) / 100)

    def submit(self, intent, client_id, day):
        ticker = intent["symbol"].replace(".", "-")
        quote = self.market(ticker, day)
        trade = self.store.trade(ticker, intent["side"].upper(), int(intent["qty"]), intent["limit_price"],
                                 quote["as_of"], client_id, day)
        self.store.mark(ticker, quote["price"], quote["as_of"])
        return self.rendered(trade)
