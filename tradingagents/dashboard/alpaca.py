"""Paper-only Alpaca REST calls and deterministic sizing; never accepts a live URL."""

import json
import os
import re
from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_UP, Decimal, InvalidOperation

import requests

from .store import stock_symbol

PAPER_URL = "https://paper-api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"


class BrokerError(ValueError):
    pass


def number(value):
    try:
        result = Decimal(str(value))
        if result.is_finite():
            return result
    except (InvalidOperation, ValueError, TypeError):
        pass
    raise BrokerError("Alpaca returned an invalid number; no order was sent.")


class AlpacaPaper:
    def __init__(self, key, secret):
        if any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", v) for v in (key, secret)):
            raise BrokerError("Enter the API key and secret from your Alpaca paper account.")
        self.headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

    @classmethod
    def load(cls, path):
        if not path.exists():
            return None
        try:
            saved = json.loads(path.read_text())
            return cls(saved["key"], saved["secret"])
        except (OSError, ValueError, KeyError, TypeError):
            raise BrokerError("Cannot read paper credentials. Reconnect in the dashboard.") from None

    def save(self, path):
        temporary = path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            os.chmod(temporary, 0o600)
            json.dump({"key": self.headers["APCA-API-KEY-ID"], "secret": self.headers["APCA-API-SECRET-KEY"]}, stream)
        os.replace(temporary, path)

    def request(self, method, path, *, params=None, body=None, data=False, missing=False):
        # Redirects could forward authentication headers to a different host.
        try:
            response = requests.request(method, (DATA_URL if data else PAPER_URL) + path,
                                        headers=self.headers, params=params, json=body,
                                        timeout=20, allow_redirects=False)
            if missing and response.status_code == 404:
                return None
            if not 200 <= response.status_code < 300:
                raise BrokerError(f"Alpaca paper API returned HTTP {response.status_code}. Check the account and retry later.")
            result = response.json()
            if not isinstance(result, (dict, list)):
                raise ValueError
            return result
        except (requests.RequestException, ValueError) as exc:
            if isinstance(exc, BrokerError):
                raise
            raise BrokerError("Alpaca paper API unavailable. An interrupted submission must be reconciled before retrying.") from None

    def account(self):
        account = self.request("GET", "/v2/account")
        if (account.get("status") != "ACTIVE" or account.get("currency") != "USD"
                or account.get("trading_blocked") or account.get("account_blocked")
                or account.get("trade_suspended_by_user") or not account.get("id")):
            raise BrokerError("An active, unblocked USD paper account is required.")
        if number(account["equity"]) <= 0 or number(account["cash"]) < 0:
            raise BrokerError("The paper test requires positive equity and nonnegative cash.")
        return account

    def positions(self):
        positions = self.request("GET", "/v2/positions")
        if not isinstance(positions, list) or any(p.get("asset_class") != "us_equity" or number(p["qty"]) < 0 for p in positions):
            raise BrokerError("Use a paper account holding only long US stocks or ETFs for this test.")
        return positions

    def orders(self, status="all"):
        return self.request("GET", "/v2/orders", params={"status": status, "limit": 100, "direction": "desc"})

    def order(self, client_id):
        return self.request("GET", "/v2/orders:by_client_order_id", params={"client_order_id": client_id}, missing=True)

    def clock(self):
        return self.request("GET", "/v2/clock")

    def quote(self, ticker):
        return self.request("GET", f"/v2/stocks/{stock_symbol(ticker).replace('-', '.')}/quotes/latest", params={"feed": "iex"}, data=True)["quote"]

    def submit(self, intent, client_id):
        return self.request("POST", "/v2/orders", body={**intent, "type": "limit", "time_in_force": "day",
                            "extended_hours": False, "client_order_id": client_id})


def order_intent(ticker, rating, account, positions, quote, now=None):
    """Buy targets 10%, Overweight 5%, Underweight halves, Sell exits, Hold/REVIEW waits."""
    ticker = stock_symbol(ticker)
    if rating not in ("Buy", "Overweight", "Underweight", "Sell"):
        return None
    bid, ask = number(quote["bp"]), number(quote["ap"])
    stamp = datetime.fromisoformat(quote["t"].replace("Z", "+00:00"))
    age = ((now or datetime.now(UTC)) - stamp).total_seconds()
    if not 0 <= age <= 300 or not 0 < bid <= ask or (ask - bid) / ask > Decimal("0.01"):
        raise BrokerError("IEX quote is stale, crossed, or has a spread above 1%; no order was sent.")
    buying = rating in ("Buy", "Overweight")
    limit = ((ask * Decimal("1.005")) if buying else (bid * Decimal("0.995"))).quantize(
        Decimal("0.01"), rounding=ROUND_UP if buying else ROUND_DOWN)
    if limit < Decimal("0.01"):
        raise BrokerError("The stock price is below the supported minimum.")
    return size_order(ticker, rating, account, positions, limit)


def size_order(ticker, rating, account, positions, limit):
    """Shared fixed policy; caller supplies an execution price, never an LLM share count."""
    ticker = stock_symbol(ticker)
    if rating not in ("Buy", "Overweight", "Underweight", "Sell"):
        return None
    position = next((p for p in positions if p["symbol"].replace(".", "-") == ticker), None)
    held = number(position["qty"]) if position else Decimal(0)
    if held < 0 or held != held.to_integral_value():
        raise BrokerError("Automation requires whole, long shares in each managed symbol.")
    limit = number(limit)
    if limit < Decimal("0.01"):
        raise BrokerError("The stock price is below the supported minimum.")
    buying = rating in ("Buy", "Overweight")
    if buying:
        equity, cash = number(account["equity"]), number(account["cash"])
        gross = sum((abs(number(p["market_value"])) for p in positions), Decimal(0))
        target = equity * (Decimal("0.10") if rating == "Buy" else Decimal("0.05"))
        budget = min(target - held * limit, equity * Decimal("0.40") - gross, cash - equity * Decimal("0.10"))
        quantity = max(0, int(budget // limit))
    else:
        quantity = int(held) if rating == "Sell" else int(held) - int(held // 2)
    if not quantity:
        return None
    return {"symbol": ticker.replace("-", "."), "qty": str(quantity), "side": "buy" if buying else "sell", "limit_price": str(limit)}
