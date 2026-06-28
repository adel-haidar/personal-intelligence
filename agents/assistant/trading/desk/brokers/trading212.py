"""Live broker adapter for Trading 212 (per the 2026-06-27 broker research).

Reality the contract encodes:
  - Base URL by env: demo `https://demo.trading212.com/api/v0`,
    live `https://live.trading212.com/api/v0`. Same endpoints, different host.
  - Auth is in flux: primary `Authorization: Basic base64(KEY:SECRET)`, fallback
    `Authorization: <KEY>`. Implemented as a single swappable `_auth_header`.
  - No instrument search → cache `GET /equity/metadata/instruments` and resolve
    'AAPL' → 'AAPL_US_EQ' client-side (match shortName/ticker/name/isin), per env.
  - Orders POST are NOT idempotent → a per-intent asyncio lock + persisting the
    returned id is the caller's job; here we at least serialise same-intent POSTs.
  - Live executes MARKET orders reliably in beta → prefer market on live.
  - Rate limits: read `x-ratelimit-*` headers and back off.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from typing import Optional

import httpx

from assistant.trading.desk.brokers.base import BrokerAdapter, BrokerError

logger = logging.getLogger(__name__)

_DEFAULT_HOSTS = {
    "demo": "https://demo.trading212.com/api/v0",
    "live": "https://live.trading212.com/api/v0",
}

_TIMEOUT = httpx.Timeout(15.0)
# Worst-case wall-clock for a single _request (incl. 429 backoff). Must stay well
# under nginx's 60s gateway timeout so a rate-limited call degrades, never 504s.
_REQUEST_BUDGET = 35.0
_MAX_ATTEMPTS = 3
# Cache instruments per (environment) for the process lifetime; refresh lazily.
_INSTRUMENT_CACHE: dict[str, tuple[float, list[dict]]] = {}
_INSTRUMENT_TTL = 60 * 60 * 6  # 6h
# Serialise non-idempotent POSTs per intent key within this process.
_INTENT_LOCKS: dict[str, asyncio.Lock] = {}


def _base_url(environment: str) -> str:
    """Resolve the API base URL, allowing env-var override per environment."""
    override = os.environ.get(f"TRADING212_{environment.upper()}_BASE_URL")
    if override:
        return override.rstrip("/")
    if environment not in _DEFAULT_HOSTS:
        raise BrokerError(f"Unknown Trading 212 environment: {environment!r}", code="bad_env")
    return _DEFAULT_HOSTS[environment]


def _auth_header(api_key: str, api_secret: Optional[str]) -> str:
    """Build the Authorization header value.

    Primary scheme is HTTP Basic base64(KEY:SECRET) when a secret is present;
    otherwise the raw key (the documented fallback). Swap this single function if
    Trading 212 finalises a different scheme.
    """
    if api_secret:
        raw = f"{api_key}:{api_secret}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")
    return api_key


class Trading212Broker(BrokerAdapter):
    """Live Trading 212 adapter. Credentials are PLAINTEXT here (decrypted by the
    service layer just before constructing this) — never log them."""

    def __init__(self, api_key: str, api_secret: Optional[str], environment: str = "demo"):
        self._api_key = api_key
        self._api_secret = api_secret
        self._environment = environment
        self._base = _base_url(environment)
        self._headers = {
            "Authorization": _auth_header(api_key, api_secret),
            "Content-Type": "application/json",
        }

    # ── low-level request with rate-limit backoff ────────────────────────────
    async def _request(self, method: str, path: str, *, json: dict | None = None) -> dict | list:
        url = f"{self._base}{path}"
        attempts = 0
        # Hard wall-clock budget so a request can NEVER exceed nginx's gateway
        # timeout (60s) — otherwise a rate-limited (429) call would 504 the page.
        deadline = time.monotonic() + _REQUEST_BUDGET
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=self._headers) as client:
            while True:
                attempts += 1
                try:
                    resp = await client.request(method, url, json=json)
                except httpx.HTTPError as exc:
                    raise BrokerError(f"Trading 212 request failed: {exc}", code="network") from exc

                if resp.status_code == 429 and attempts <= _MAX_ATTEMPTS:
                    delay = self._retry_after(resp)
                    # Don't sleep past the budget — give up cleanly instead of 504.
                    if time.monotonic() + delay >= deadline:
                        raise BrokerError(
                            "Trading 212 is rate-limiting; please retry in a moment.",
                            status=503, code="rate_limited",
                        )
                    logger.warning("Trading 212 rate-limited; backing off %.1fs", delay)
                    await asyncio.sleep(delay)
                    continue
                if resp.status_code == 429:
                    raise BrokerError(
                        "Trading 212 is rate-limiting; please retry in a moment.",
                        status=503, code="rate_limited",
                    )

                if resp.status_code == 401 or resp.status_code == 403:
                    # Surface as 401-style auth failure (never 403 to the client).
                    raise BrokerError(
                        "Trading 212 rejected the API key.", status=401, code="auth"
                    )
                if resp.status_code >= 400:
                    raise BrokerError(
                        f"Trading 212 error {resp.status_code}: {resp.text[:300]}",
                        status=502,
                        code="broker_error",
                    )
                if not resp.content:
                    return {}
                try:
                    return resp.json()
                except ValueError:
                    return {}

    @staticmethod
    def _retry_after(resp: httpx.Response) -> float:
        """Compute a backoff delay from rate-limit / retry headers."""
        for h in ("retry-after", "x-ratelimit-reset"):
            v = resp.headers.get(h)
            if v:
                try:
                    val = float(v)
                    # x-ratelimit-reset may be an epoch; normalise to a delay.
                    if val > time.time():
                        return min(val - time.time(), 10.0)
                    return min(val, 10.0)
                except ValueError:
                    pass
        return 2.0

    # ── reads ────────────────────────────────────────────────────────────────
    async def get_cash(self) -> dict:
        data = await self._request("GET", "/equity/account/cash")
        if not isinstance(data, dict):
            raise BrokerError("Unexpected cash response from Trading 212.", code="bad_response")
        return {
            "free": data.get("free"),
            "total": data.get("total"),
            "invested": data.get("invested"),
            "currency": data.get("currency") or "EUR",
            "raw": data,
        }

    async def get_positions(self) -> list[dict]:
        data = await self._request("GET", "/equity/positions")
        rows = data if isinstance(data, list) else data.get("positions", []) if isinstance(data, dict) else []
        out: list[dict] = []
        for p in rows:
            qty = p.get("quantity")
            out.append(
                {
                    "ticker": p.get("ticker"),
                    "name": p.get("ticker"),
                    "qty": float(qty) if qty is not None else None,
                    "avg_price": p.get("averagePrice"),
                    "current_price": p.get("currentPrice"),
                    "value": p.get("ppl"),  # profit/loss; best available without a price multiply
                    "asset_class": "equity",
                }
            )
        return out

    # ── instrument resolution ─────────────────────────────────────────────────
    async def _instruments(self) -> list[dict]:
        cached = _INSTRUMENT_CACHE.get(self._environment)
        if cached and (time.time() - cached[0]) < _INSTRUMENT_TTL:
            return cached[1]
        data = await self._request("GET", "/equity/metadata/instruments")
        instruments = data if isinstance(data, list) else []
        _INSTRUMENT_CACHE[self._environment] = (time.time(), instruments)
        return instruments

    async def resolve_symbol(self, symbol: str) -> str:
        """Map a human ticker to a Trading 212 instrument ticker (e.g. AAPL_US_EQ)."""
        if not symbol:
            raise BrokerError("Empty symbol.", code="bad_symbol")
        # Already a T212 ticker.
        if symbol.endswith("_EQ") or "_" in symbol:
            return symbol
        target = symbol.strip().upper()
        instruments = await self._instruments()
        # Prefer an exact shortName/ticker match, then name/isin contains.
        for field in ("shortName", "ticker"):
            for ins in instruments:
                if str(ins.get(field, "")).upper() == target:
                    return ins["ticker"]
        for ins in instruments:
            if target == str(ins.get("isin", "")).upper():
                return ins["ticker"]
        for ins in instruments:
            if target in str(ins.get("name", "")).upper():
                return ins["ticker"]
        raise BrokerError(
            f"Could not resolve '{symbol}' to a Trading 212 instrument.",
            code="unresolved_symbol",
        )

    # ── orders (non-idempotent POSTs serialised per intent) ───────────────────
    def _lock(self, intent_key: str | None) -> asyncio.Lock:
        key = intent_key or "global"
        lock = _INTENT_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _INTENT_LOCKS[key] = lock
        return lock

    @staticmethod
    def _order_dict(data: dict) -> dict:
        return {
            "id": str(data.get("id")) if data.get("id") is not None else None,
            "status": data.get("status"),
            "ticker": data.get("ticker"),
            "filled_qty": data.get("filledQuantity"),
            "filled_price": data.get("fillPrice") or data.get("filledValue"),
            "raw": data,
        }

    async def place_market_order(
        self, ticker: str, quantity: float, *, intent_key: str | None = None
    ) -> dict:
        body = {"ticker": ticker, "quantity": quantity, "extendedHours": False}
        async with self._lock(intent_key):
            data = await self._request("POST", "/equity/orders/market", json=body)
        return self._order_dict(data if isinstance(data, dict) else {})

    async def place_limit_order(
        self,
        ticker: str,
        quantity: float,
        limit_price: float,
        *,
        intent_key: str | None = None,
    ) -> dict:
        body = {
            "ticker": ticker,
            "quantity": quantity,
            "limitPrice": limit_price,
            "timeValidity": "DAY",
        }
        async with self._lock(intent_key):
            data = await self._request("POST", "/equity/orders/limit", json=body)
        return self._order_dict(data if isinstance(data, dict) else {})

    async def place_stop_order(
        self, ticker: str, quantity: float, stop_price: float, *, intent_key: str | None = None
    ) -> dict:
        """Place a resting protective STOP order. quantity<0 = sell-stop (fires when
        price falls to stop_price). GTC so it keeps protecting the position between
        the desk's review cycles. Whole shares only, like every other T212 order."""
        body = {
            "ticker": ticker,
            "quantity": quantity,
            "stopPrice": round(float(stop_price), 2),
            "timeValidity": "GTC",
        }
        async with self._lock(intent_key):
            data = await self._request("POST", "/equity/orders/stop", json=body)
        return self._order_dict(data if isinstance(data, dict) else {})

    async def get_order(self, order_id: str) -> dict:
        data = await self._request("GET", f"/equity/orders/{order_id}")
        return self._order_dict(data if isinstance(data, dict) else {})

    async def cancel_order(self, order_id: str) -> dict:
        await self._request("DELETE", f"/equity/orders/{order_id}")
        return {"id": order_id, "status": "CANCELLED"}
