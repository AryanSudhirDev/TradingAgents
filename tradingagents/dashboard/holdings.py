"""Derive holding ages only from confirmed, journal-owned paper fills."""

import json
from datetime import datetime

from .alpaca import BrokerError, number
from .automation import NEW_YORK

TERMINAL = {"filled", "canceled", "expired", "rejected", "replaced", "simulated"}


def sync_holdings(automation, execution, positions, account):
    """Unknown submissions remain the automation's responsibility; never resubmit here."""
    store = automation.store
    with store.connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS confirmed_paper_fills (
            client_id TEXT PRIMARY KEY, account TEXT NOT NULL, ticker TEXT NOT NULL,
            side TEXT NOT NULL, quantity TEXT NOT NULL, first_day TEXT NOT NULL, status TEXT NOT NULL)""")
        runs = [dict(r) for r in db.execute("SELECT * FROM paper_runs WHERE account=? AND status='submitted' ORDER BY day,updated", (account,))]
        confirmed = {r["client_id"]: dict(r) for r in db.execute("SELECT * FROM confirmed_paper_fills WHERE account=?", (account,))}
    for run in runs:
        old = confirmed.get(run["client_id"])
        if old and old["status"] in TERMINAL:
            continue
        order = execution.order(run["client_id"])
        if not order:
            raise BrokerError("A journal-owned order is missing; review it before resuming.")
        intent = json.loads(run["intent"] or "{}")
        ticker = order.get("symbol", "").replace(".", "-")
        side = order.get("side")
        quantity = number(order.get("filled_qty", 0))
        if (ticker != run["ticker"] or side != intent.get("side") or side not in ("buy", "sell")
                or quantity < 0 or quantity != quantity.to_integral_value()
                or quantity > number(intent.get("qty", 0))):
            raise BrokerError("Confirmed fill does not match the saved whole-share intent.")
        if old and quantity < number(old["quantity"]):
            raise BrokerError("A confirmed fill quantity decreased; reconcile the account.")
        stamp = order.get("filled_at") or order.get("submitted_at")
        first_day = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(NEW_YORK).date().isoformat() if stamp and execution is not automation.simulator else run["day"]
        row = {"client_id": run["client_id"], "account": account, "ticker": ticker, "side": side,
               "quantity": str(quantity), "first_day": old["first_day"] if old else first_day, "status": order["status"]}
        with store.connect() as db:
            db.execute("INSERT OR REPLACE INTO confirmed_paper_fills VALUES (?,?,?,?,?,?,?)", tuple(row.values()))
        confirmed[run["client_id"]] = row
    held = {}
    for row in sorted(confirmed.values(), key=lambda r: (r["first_day"], r["client_id"])):
        item = held.setdefault(row["ticker"], {"quantity": number(0), "first_day": None})
        qty = number(row["quantity"])
        if row["side"] == "buy" and qty:
            if not item["quantity"]:
                item["first_day"] = row["first_day"]
            item["quantity"] += qty
        elif row["side"] == "sell":
            item["quantity"] -= qty
            if item["quantity"] < 0:
                raise BrokerError("Recorded sells exceed owned fills; review the account.")
            if not item["quantity"]:
                item["first_day"] = None
    symbols = automation.settings()["symbols"]
    for ticker in symbols:
        actual = next((number(p["qty"]) for p in positions if p["symbol"].replace(".", "-") == ticker), number(0))
        if actual != held.get(ticker, {}).get("quantity", number(0)):
            raise BrokerError("A managed position differs from journal-owned fills. Review manual trades, splits or missing fills before resuming.")
    return {ticker: {"quantity": str(row["quantity"]), "first_day": row["first_day"]}
            for ticker, row in held.items() if row["quantity"]}


def deadline(first_day, calendar):
    days = sorted({row["date"] for row in calendar if row["date"] >= first_day})
    if not days or days[0] != first_day or len(days) < 5:
        raise BrokerError("Exchange calendar does not cover the holding deadline.")
    return days[4]
