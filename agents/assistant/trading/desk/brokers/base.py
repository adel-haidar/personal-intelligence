"""Broker adapter interface for the Agent Trading Desk.

Two implementations exist:
  - `paper.PaperBroker`   — internal simulation (our own positions + cash tables).
  - `trading212.Trading212Broker` — live execution via the user's Trading 212 key.

The coordinator/execution layer talks to either through this single async interface
and only ever handles plain dicts, so the rest of the desk is broker-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BrokerError(RuntimeError):
    """A typed broker failure (auth, rate-limit, bad symbol, order rejected, …).

    Carries an optional `status` (HTTP-ish) and a machine `code` so callers can map
    it to a friendly response without scraping the message. Never wraps a secret.
    """

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


class BrokerAdapter(ABC):
    """Common async surface implemented by paper and live brokers.

    All methods return plain JSON-serialisable dicts (or strings) and raise
    `BrokerError` on failure.
    """

    @abstractmethod
    async def get_cash(self) -> dict:
        """Return account cash, e.g. {"free": 1234.5, "total": 1234.5, "currency": "EUR"}."""

    @abstractmethod
    async def get_positions(self) -> list[dict]:
        """Return open positions: [{ticker, name, qty, avg_price, current_price?, value?}]."""

    @abstractmethod
    async def resolve_symbol(self, symbol: str) -> str:
        """Map a human ticker (e.g. 'AAPL') to the broker's order ticker (e.g. 'AAPL_US_EQ').

        For the paper broker this is the identity function.
        """

    @abstractmethod
    async def place_market_order(
        self, ticker: str, quantity: float, *, intent_key: str | None = None
    ) -> dict:
        """Place a market order. quantity>0 buys, <0 sells. Returns an order dict
        with at least {"id", "status"} and, when known, filled qty/price."""

    @abstractmethod
    async def place_limit_order(
        self,
        ticker: str,
        quantity: float,
        limit_price: float,
        *,
        intent_key: str | None = None,
    ) -> dict:
        """Place a DAY limit order. Returns the same shape as place_market_order."""

    @abstractmethod
    async def place_stop_order(
        self, ticker: str, quantity: float, stop_price: float, *, intent_key: str | None = None
    ) -> dict:
        """Place a resting STOP order (protective). quantity<0 is a sell-stop that
        fires when the price falls to stop_price. Returns an order dict with at least
        {"id", "status"}. Used to protect a live position between review cycles."""

    @abstractmethod
    async def get_order(self, order_id: str) -> dict:
        """Fetch an order's current state (status, filled qty/price)."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> dict:
        """Cancel an open order. Returns the (best-effort) order state."""
