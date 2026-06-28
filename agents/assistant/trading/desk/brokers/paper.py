"""Internal paper-trading broker — fully simulated, no external calls.

Implements the same `BrokerAdapter` interface as the live broker, but fills orders
instantly at the latest snapshot price and tracks positions + cash in our own
tables (`trading_position`, `trading_paper_account`) via db.py. This is the desk's
"plan mode for trading": anyone can try it without a broker key.

Price source: a `price_lookup(ticker) -> float | None` callable supplied by the
coordinator (built from the run's market snapshot). When the snapshot has no price
for a ticker, the order is rejected with a BrokerError rather than guessing.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from assistant.trading import db
from assistant.trading.desk.brokers.base import BrokerAdapter, BrokerError

logger = logging.getLogger(__name__)

# A price lookup may be sync or async; we normalise both.
PriceLookup = Callable[[str], object]

PAPER_ACCOUNT = "paper"


class PaperBroker(BrokerAdapter):
    """Simulated broker backed by our own DB tables."""

    def __init__(
        self,
        user_id,
        price_lookup: Optional[PriceLookup] = None,
        currency: str = "EUR",
    ):
        self._user_id = user_id
        self._price_lookup = price_lookup
        self._currency = currency

    async def _price(self, ticker: str) -> float | None:
        if self._price_lookup is None:
            return None
        result = self._price_lookup(ticker)
        if isinstance(result, Awaitable):
            result = await result
        return float(result) if result is not None else None

    async def get_cash(self) -> dict:
        acct = await db.get_paper_account(self._user_id)
        cash = float(acct["cash"])
        return {
            "free": cash,
            "total": cash,
            "currency": self._currency,
            "starting_balance": float(acct.get("starting_balance", cash)),
        }

    async def get_positions(self) -> list[dict]:
        rows = await db.get_positions(self._user_id, PAPER_ACCOUNT)
        out: list[dict] = []
        for r in rows:
            ticker = r["ticker"]
            price = await self._price(ticker)
            qty = float(r["qty"])
            avg = float(r["avg_price"])
            out.append(
                {
                    "ticker": ticker,
                    "name": r.get("name") or ticker,
                    "qty": qty,
                    "avg_price": avg,
                    "current_price": price,
                    "value": round(qty * price, 2) if price is not None else None,
                    "asset_class": r.get("asset_class") or "equity",
                }
            )
        return out

    async def resolve_symbol(self, symbol: str) -> str:
        # Paper broker trades the symbol as-is.
        return symbol

    async def _fill(
        self, ticker: str, quantity: float, price: float, name: str | None
    ) -> dict:
        """Apply a fill: move cash, update the position, return an order dict."""
        cost = quantity * price  # >0 buy (cash out), <0 sell (cash in)

        if quantity > 0:
            acct = await db.get_paper_account(self._user_id)
            if float(acct["cash"]) < cost:
                raise BrokerError(
                    f"Insufficient paper cash for {ticker}: need {cost:.2f}, "
                    f"have {float(acct['cash']):.2f}",
                    code="insufficient_funds",
                )

        # Recompute the position. Buys raise avg cost; sells reduce qty, keeping avg.
        existing = {
            r["ticker"]: r for r in await db.get_positions(self._user_id, PAPER_ACCOUNT)
        }
        prev = existing.get(ticker)
        prev_qty = float(prev["qty"]) if prev else 0.0
        prev_avg = float(prev["avg_price"]) if prev else 0.0
        new_qty = prev_qty + quantity

        if new_qty < -1e-9:
            raise BrokerError(
                f"Cannot sell {abs(quantity)} of {ticker}: only {prev_qty} held",
                code="insufficient_position",
            )

        if quantity > 0:
            new_avg = ((prev_qty * prev_avg) + cost) / new_qty if new_qty else price
        else:
            new_avg = prev_avg if new_qty > 1e-9 else 0.0

        await db.upsert_position(
            self._user_id,
            PAPER_ACCOUNT,
            ticker,
            prev["name"] if prev else (name or ticker),
            round(new_qty, 8),
            round(new_avg, 6),
            (prev.get("asset_class") if prev else None) or "equity",
        )
        # Cash moves opposite to position change.
        await db.adjust_paper_cash(self._user_id, round(-cost, 2))

        return {
            "id": f"paper-{uuid.uuid4().hex[:16]}",
            "status": "FILLED",
            "ticker": ticker,
            "filled_qty": abs(quantity),
            "filled_price": round(price, 6),
            "side": "buy" if quantity > 0 else "sell",
            "filled_at": datetime.now(timezone.utc).isoformat(),
        }

    async def place_market_order(
        self, ticker: str, quantity: float, *, intent_key: str | None = None
    ) -> dict:
        price = await self._price(ticker)
        if price is None:
            raise BrokerError(
                f"No snapshot price available for {ticker}; cannot simulate fill.",
                code="no_price",
            )
        return await self._fill(ticker, quantity, price, name=None)

    async def place_limit_order(
        self,
        ticker: str,
        quantity: float,
        limit_price: float,
        *,
        intent_key: str | None = None,
    ) -> dict:
        # In the sim, fill at the better of snapshot price vs limit (marketable),
        # else fill at the limit price (assume it would eventually fill).
        snap = await self._price(ticker)
        fill_price = limit_price if snap is None else (
            min(snap, limit_price) if quantity > 0 else max(snap, limit_price)
        )
        return await self._fill(ticker, quantity, fill_price, name=None)

    async def place_stop_order(
        self, ticker: str, quantity: float, stop_price: float, *, intent_key: str | None = None
    ) -> dict:
        # Paper has no real resting order book; record a synthetic stop id. The
        # review cycle enforces the stop synthetically (price <= stop_price → sell).
        return {
            "id": f"paper-stop-{uuid.uuid4().hex[:16]}",
            "status": "new",
            "ticker": ticker,
            "stop_price": round(float(stop_price), 6),
        }

    async def get_order(self, order_id: str) -> dict:
        # Paper orders fill instantly; nothing to poll.
        return {"id": order_id, "status": "FILLED"}

    async def cancel_order(self, order_id: str) -> dict:
        return {"id": order_id, "status": "FILLED", "note": "paper orders fill instantly"}
