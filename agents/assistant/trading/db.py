"""Persistence layer for the Agent Trading Desk (Service B, asyncpg).

Owns all `trading_*` tables and the async helpers the desk service/coordinator
call. Mirrors the schema in `migrations/0026_trading_desk.sql`, bootstrapped
idempotently on first use (the desk routes never call init explicitly, so the
pool self-initialises and verifies the schema lazily).

Conventions:
- Every user-data query is scoped by user_id.  # MUST SCOPE BY USER
- user_id may be NULL (seed-admin / internal callers), so scoping uses
  `IS NOT DISTINCT FROM` and upserts are UPDATE-then-INSERT rather than
  ON CONFLICT (which never matches a NULL key).
- NUMERIC columns are bound as Decimal (asyncpg rejects float for numeric).
- JSONB columns (universe, guardrails, evidence) round-trip as Python
  objects via a connection codec.
"""

import asyncio
import json
import logging
from decimal import Decimal
from typing import Any, Optional

import asyncpg

from assistant.shared.settings import get_settings

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS trading_config (
    user_id         UUID,
    account         TEXT,
    strategy        TEXT,
    mode            TEXT,
    allocation      NUMERIC,
    reserve_floor   NUMERIC,
    universe        JSONB,
    guardrails      JSONB,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id)
);

CREATE TABLE IF NOT EXISTS trading_broker_connection (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL,
    provider         TEXT NOT NULL DEFAULT 'trading212',
    environment      TEXT,
    api_key_enc      TEXT,
    api_secret_enc   TEXT,
    status           TEXT,
    label            TEXT,
    connected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_verified_at TIMESTAMPTZ,
    UNIQUE (user_id, provider)
);
CREATE INDEX IF NOT EXISTS idx_trading_broker_user
    ON trading_broker_connection (user_id);

CREATE TABLE IF NOT EXISTS trading_run (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL,
    account      TEXT,
    strategy     TEXT,
    mode         TEXT,
    allocation   NUMERIC,
    reserve      NUMERIC,
    status       TEXT NOT NULL DEFAULT 'researching',
    market_read  TEXT,
    notional     NUMERIC,
    error        TEXT,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_trading_run_user
    ON trading_run (user_id, started_at DESC);

CREATE TABLE IF NOT EXISTS trading_run_event (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id     UUID NOT NULL,
    user_id    UUID NOT NULL,
    stage      TEXT,
    agent      TEXT,
    type       TEXT,
    message    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trading_run_event_run
    ON trading_run_event (run_id, created_at);
CREATE INDEX IF NOT EXISTS idx_trading_run_event_user
    ON trading_run_event (user_id);

CREATE TABLE IF NOT EXISTS trading_trade (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id             UUID NOT NULL,
    user_id            UUID NOT NULL,
    ticker             TEXT,
    name               TEXT,
    side               TEXT,
    amount             NUMERIC,
    pct_of_allocation  NUMERIC,
    headline           TEXT,
    reasoning          TEXT,
    evidence           JSONB,
    risk_verdict       TEXT,
    risk_note          TEXT,
    kept               BOOLEAN NOT NULL DEFAULT TRUE,
    status             TEXT    NOT NULL DEFAULT 'pending',
    order_type         TEXT,
    limit_price        NUMERIC,
    broker_order_id    TEXT,
    filled_qty         NUMERIC,
    filled_price       NUMERIC,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trading_trade_run
    ON trading_trade (run_id);
CREATE INDEX IF NOT EXISTS idx_trading_trade_user
    ON trading_trade (user_id);

CREATE TABLE IF NOT EXISTS trading_position (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL,
    account     TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    name        TEXT,
    qty         NUMERIC,
    avg_price   NUMERIC,
    asset_class TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, account, ticker)
);
CREATE INDEX IF NOT EXISTS idx_trading_position_user
    ON trading_position (user_id, account);

CREATE TABLE IF NOT EXISTS trading_paper_account (
    user_id          UUID PRIMARY KEY,
    cash             NUMERIC NOT NULL DEFAULT 100000,
    starting_balance NUMERIC NOT NULL DEFAULT 100000,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Autonomy (mirror of migrations/0027_trading_autonomy.sql) ---------------------
CREATE TABLE IF NOT EXISTS trading_position_plan (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL,
    account              TEXT NOT NULL,
    ticker               TEXT NOT NULL,
    qty                  NUMERIC,
    entry_price          NUMERIC,
    stop_price           NUMERIC,
    target_price         NUMERIC,
    thesis               TEXT,
    status               TEXT NOT NULL DEFAULT 'open',
    broker_stop_order_id TEXT,
    opened_run_id        UUID,
    closed_run_id        UUID,
    realized_pl          NUMERIC,
    opened_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at            TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_trading_plan_user_open
    ON trading_position_plan (user_id, account, status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_trading_plan_open
    ON trading_position_plan (user_id, account, ticker) WHERE status = 'open';

ALTER TABLE trading_config ADD COLUMN IF NOT EXISTS autonomous BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE trading_config ADD COLUMN IF NOT EXISTS paused_until TIMESTAMPTZ;
ALTER TABLE trading_config ADD COLUMN IF NOT EXISTS day_baseline_equity NUMERIC;
ALTER TABLE trading_config ADD COLUMN IF NOT EXISTS day_baseline_date DATE;
ALTER TABLE trading_trade ADD COLUMN IF NOT EXISTS stop_pct NUMERIC;
ALTER TABLE trading_trade ADD COLUMN IF NOT EXISTS stop_price NUMERIC;
ALTER TABLE trading_trade ADD COLUMN IF NOT EXISTS exit_qty NUMERIC;
"""

_pool: Optional[asyncpg.Pool] = None
_init_lock = asyncio.Lock()


async def _init_conn(conn: asyncpg.Connection) -> None:
    """Make JSONB columns round-trip as Python objects."""
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def _get_pool() -> asyncpg.Pool:
    """Lazily create the pool and verify the schema (idempotent)."""
    global _pool
    if _pool is not None:
        return _pool
    async with _init_lock:
        if _pool is None:
            database_url = get_settings().database_url
            if not database_url:
                raise RuntimeError("Database not configured (DATABASE_URL missing)")
            pool = await asyncpg.create_pool(
                database_url, init=_init_conn, min_size=1, max_size=5
            )
            async with pool.acquire() as conn:
                await conn.execute(_DDL)
            _pool = pool
            logger.info("Trading desk DB pool initialised and schema verified")
    return _pool


async def init_pool(database_url: str | None = None) -> asyncpg.Pool:
    """Explicit init hook (e.g. for an app lifespan). Self-init also works."""
    return await _get_pool()


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Trading desk DB pool not initialised")
    return _pool


# ── helpers ──────────────────────────────────────────────────────────────────

def _dec(x: Any) -> Optional[Decimal]:
    """Coerce a number to Decimal for NUMERIC binding (asyncpg rejects float)."""
    if x is None:
        return None
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _uid(x: Any) -> Optional[str]:
    return str(x) if x is not None else None


# ── config ───────────────────────────────────────────────────────────────────

async def get_config(user_id) -> Optional[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # MUST SCOPE BY USER
        row = await conn.fetchrow(
            "SELECT user_id, account, strategy, mode, allocation, reserve_floor, "
            "universe, guardrails, autonomous, paused_until, day_baseline_equity, "
            "day_baseline_date, updated_at FROM trading_config "
            "WHERE user_id IS NOT DISTINCT FROM $1::uuid",
            _uid(user_id),
        )
        return dict(row) if row else None


async def upsert_config(user_id, **fields) -> dict:
    pool = await _get_pool()
    args = (
        _uid(user_id),
        fields.get("account"),
        fields.get("strategy"),
        fields.get("mode"),
        _dec(fields.get("allocation")),
        _dec(fields.get("reserve_floor")),
        fields.get("universe"),
        fields.get("guardrails"),
        bool(fields.get("autonomous", False)),
    )
    async with pool.acquire() as conn:
        # MUST SCOPE BY USER — UPDATE-then-INSERT (NULL user_id can't ON CONFLICT).
        # Note: paused_until / day_baseline_* are owned by the cycle (set_config_flags),
        # so this upsert deliberately never touches them.
        updated = await conn.fetchrow(
            "UPDATE trading_config SET account=$2, strategy=$3, mode=$4, "
            "allocation=$5, reserve_floor=$6, universe=$7, guardrails=$8, "
            "autonomous=$9, updated_at=NOW() "
            "WHERE user_id IS NOT DISTINCT FROM $1::uuid RETURNING *",
            *args,
        )
        if updated:
            return dict(updated)
        inserted = await conn.fetchrow(
            "INSERT INTO trading_config (user_id, account, strategy, mode, "
            "allocation, reserve_floor, universe, guardrails, autonomous) "
            "VALUES ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *",
            *args,
        )
        return dict(inserted)


async def set_config_flags(user_id, **fields) -> None:
    """Set cycle-owned config columns (paused_until, day_baseline_equity,
    day_baseline_date, autonomous) without disturbing the user-edited config."""
    allowed = {"paused_until", "day_baseline_equity", "day_baseline_date", "autonomous"}
    numeric = {"day_baseline_equity"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    pool = await _get_pool()
    sets, args = [], []
    for i, (k, v) in enumerate(updates.items(), start=1):
        args.append(_dec(v) if k in numeric else v)
        sets.append(f"{k}=${i}")
    args.append(_uid(user_id))
    async with pool.acquire() as conn:
        # MUST SCOPE BY USER
        await conn.execute(
            f"UPDATE trading_config SET {', '.join(sets)} "
            f"WHERE user_id IS NOT DISTINCT FROM ${len(args)}::uuid",
            *args,
        )


async def list_autonomous_users() -> list:
    """user_ids that opted into autonomous live trading AND have a connected live
    Trading 212 key. The 30-min cycle fans over exactly these (cost + safety gate)."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT c.user_id FROM trading_config c "
            "JOIN trading_broker_connection b "
            "  ON b.user_id IS NOT DISTINCT FROM c.user_id AND b.provider='trading212' "
            "WHERE c.autonomous = TRUE AND c.account = 'live' "
            "  AND b.environment = 'live' AND b.api_key_enc IS NOT NULL"
        )
        return [r["user_id"] for r in rows]


# ── broker connection ────────────────────────────────────────────────────────

async def get_broker(user_id, provider="trading212") -> Optional[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # MUST SCOPE BY USER
        row = await conn.fetchrow(
            "SELECT * FROM trading_broker_connection "
            "WHERE user_id IS NOT DISTINCT FROM $1::uuid AND provider=$2",
            _uid(user_id), provider,
        )
        return dict(row) if row else None


async def upsert_broker(
    user_id, provider, environment, api_key_enc, api_secret_enc, status, label
) -> dict:
    pool = await _get_pool()
    args = (_uid(user_id), provider, environment, api_key_enc, api_secret_enc, status, label)
    async with pool.acquire() as conn:
        updated = await conn.fetchrow(
            "UPDATE trading_broker_connection SET environment=$3, api_key_enc=$4, "
            "api_secret_enc=$5, status=$6, label=$7, connected_at=NOW() "
            "WHERE user_id=$1::uuid AND provider=$2 RETURNING *",
            *args,
        )
        if updated:
            return dict(updated)
        inserted = await conn.fetchrow(
            "INSERT INTO trading_broker_connection (user_id, provider, environment, "
            "api_key_enc, api_secret_enc, status, label) "
            "VALUES ($1::uuid,$2,$3,$4,$5,$6,$7) RETURNING *",
            *args,
        )
        return dict(inserted)


async def set_broker_verified(user_id, provider="trading212") -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE trading_broker_connection SET last_verified_at=NOW(), "
            "status='connected' WHERE user_id=$1::uuid AND provider=$2",
            _uid(user_id), provider,
        )


async def delete_broker(user_id, provider="trading212") -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM trading_broker_connection "
            "WHERE user_id=$1::uuid AND provider=$2",
            _uid(user_id), provider,
        )


# ── runs ─────────────────────────────────────────────────────────────────────

async def create_run(user_id, account, strategy, mode, allocation, reserve) -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO trading_run (user_id, account, strategy, mode, allocation, "
            "reserve, status) VALUES ($1::uuid,$2,$3,$4,$5,$6,'researching') RETURNING *",
            _uid(user_id), account, strategy, mode, _dec(allocation), _dec(reserve),
        )
        return dict(row)


_RUN_FIELDS = {
    "account", "strategy", "mode", "allocation", "reserve", "status",
    "market_read", "notional", "error", "started_at", "finished_at",
}
_RUN_NUMERIC = {"allocation", "reserve", "notional"}


async def update_run(run_id, **fields) -> None:
    updates = {k: v for k, v in fields.items() if k in _RUN_FIELDS}
    if not updates:
        return
    pool = await _get_pool()
    sets, args = [], []
    for i, (k, v) in enumerate(updates.items(), start=1):
        args.append(_dec(v) if k in _RUN_NUMERIC else v)
        sets.append(f"{k}=${i}")
    args.append(str(run_id))
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE trading_run SET {', '.join(sets)} WHERE id=${len(args)}::uuid",
            *args,
        )


async def claim_run_for_execution(run_id, user_id) -> bool:
    """Atomically transition awaiting_approval → executing.

    Returns True only for the caller that won the transition. A concurrent
    second approval (double-click) gets False and must NOT spawn a second
    execute_run — that would place duplicate live orders. The WHERE clause is
    the single source of truth for the gate; never check-then-act in Python.
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # MUST SCOPE BY USER
        row = await conn.fetchrow(
            "UPDATE trading_run SET status='executing' "
            "WHERE id=$1::uuid AND user_id IS NOT DISTINCT FROM $2::uuid "
            "AND status='awaiting_approval' RETURNING id",
            str(run_id), _uid(user_id),
        )
        return row is not None


async def get_run(run_id, user_id) -> Optional[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # MUST SCOPE BY USER
        row = await conn.fetchrow(
            "SELECT * FROM trading_run WHERE id=$1::uuid "
            "AND user_id IS NOT DISTINCT FROM $2::uuid",
            str(run_id), _uid(user_id),
        )
        return dict(row) if row else None


async def latest_run(user_id) -> Optional[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # MUST SCOPE BY USER
        row = await conn.fetchrow(
            "SELECT * FROM trading_run WHERE user_id IS NOT DISTINCT FROM $1::uuid "
            "ORDER BY started_at DESC LIMIT 1",
            _uid(user_id),
        )
        return dict(row) if row else None


# ── events ───────────────────────────────────────────────────────────────────

async def add_event(run_id, user_id, stage, agent, type, message) -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO trading_run_event (run_id, user_id, stage, agent, type, message) "
            "VALUES ($1::uuid,$2::uuid,$3,$4,$5,$6)",
            str(run_id), _uid(user_id), stage, agent, type, message,
        )


async def list_events(run_id, user_id) -> list[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # MUST SCOPE BY USER
        rows = await conn.fetch(
            "SELECT * FROM trading_run_event WHERE run_id=$1::uuid "
            "AND user_id IS NOT DISTINCT FROM $2::uuid ORDER BY created_at ASC",
            str(run_id), _uid(user_id),
        )
        return [dict(r) for r in rows]


# ── trades ───────────────────────────────────────────────────────────────────

async def add_trades(run_id, user_id, trades: list[dict]) -> list[dict]:
    pool = await _get_pool()
    out: list[dict] = []
    async with pool.acquire() as conn:
        for t in trades:
            row = await conn.fetchrow(
                "INSERT INTO trading_trade (run_id, user_id, ticker, name, side, amount, "
                "pct_of_allocation, headline, reasoning, evidence, risk_verdict, risk_note, "
                "kept, status, order_type, limit_price, stop_pct, stop_price, exit_qty) VALUES "
                "($1::uuid,$2::uuid,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19) RETURNING *",
                str(run_id), _uid(user_id),
                t.get("ticker"), t.get("name"), t.get("side"),
                _dec(t.get("amount")), _dec(t.get("pct_of_allocation")),
                t.get("headline"), t.get("reasoning"), t.get("evidence") or [],
                t.get("risk_verdict"), t.get("risk_note"),
                bool(t.get("kept", True)), t.get("status") or "pending",
                t.get("order_type"), _dec(t.get("limit_price")),
                _dec(t.get("stop_pct")), _dec(t.get("stop_price")), _dec(t.get("exit_qty")),
            )
            out.append(dict(row))
    return out


async def list_trades(run_id, user_id) -> list[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # MUST SCOPE BY USER
        rows = await conn.fetch(
            "SELECT * FROM trading_trade WHERE run_id=$1::uuid "
            "AND user_id IS NOT DISTINCT FROM $2::uuid ORDER BY created_at ASC",
            str(run_id), _uid(user_id),
        )
        return [dict(r) for r in rows]


async def set_trade_kept(trade_id, user_id, kept: bool) -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # MUST SCOPE BY USER
        await conn.execute(
            "UPDATE trading_trade SET kept=$3 WHERE id=$1::uuid "
            "AND user_id IS NOT DISTINCT FROM $2::uuid",
            str(trade_id), _uid(user_id), bool(kept),
        )


_TRADE_FIELDS = {"status", "broker_order_id", "filled_qty", "filled_price"}
_TRADE_NUMERIC = {"filled_qty", "filled_price"}


async def update_trade(trade_id, user_id, **fields) -> None:
    updates = {k: v for k, v in fields.items() if k in _TRADE_FIELDS}
    if not updates:
        return
    pool = await _get_pool()
    sets, args = [], []
    for i, (k, v) in enumerate(updates.items(), start=1):
        args.append(_dec(v) if k in _TRADE_NUMERIC else v)
        sets.append(f"{k}=${i}")
    id_pos = len(args) + 1
    user_pos = len(args) + 2
    args.extend([str(trade_id), _uid(user_id)])
    async with pool.acquire() as conn:
        # MUST SCOPE BY USER
        await conn.execute(
            f"UPDATE trading_trade SET {', '.join(sets)} "
            f"WHERE id=${id_pos}::uuid AND user_id IS NOT DISTINCT FROM ${user_pos}::uuid",
            *args,
        )


# ── paper account + positions ────────────────────────────────────────────────

async def get_paper_account(user_id) -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO trading_paper_account (user_id) VALUES ($1::uuid) "
            "ON CONFLICT (user_id) DO NOTHING",
            _uid(user_id),
        )
        row = await conn.fetchrow(
            "SELECT * FROM trading_paper_account WHERE user_id=$1::uuid",
            _uid(user_id),
        )
        return dict(row)


async def adjust_paper_cash(user_id, delta) -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE trading_paper_account SET cash=cash+$2, updated_at=NOW() "
            "WHERE user_id=$1::uuid",
            _uid(user_id), _dec(delta),
        )


async def get_positions(user_id, account) -> list[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # MUST SCOPE BY USER
        rows = await conn.fetch(
            "SELECT * FROM trading_position WHERE user_id IS NOT DISTINCT FROM $1::uuid "
            "AND account=$2 ORDER BY ticker ASC",
            _uid(user_id), account,
        )
        return [dict(r) for r in rows]


async def upsert_position(user_id, account, ticker, name, qty, avg_price, asset_class) -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO trading_position (user_id, account, ticker, name, qty, "
            "avg_price, asset_class) VALUES ($1::uuid,$2,$3,$4,$5,$6,$7) "
            "ON CONFLICT (user_id, account, ticker) DO UPDATE SET "
            "name=EXCLUDED.name, qty=EXCLUDED.qty, avg_price=EXCLUDED.avg_price, "
            "asset_class=EXCLUDED.asset_class, updated_at=NOW()",
            _uid(user_id), account, ticker, name, _dec(qty), _dec(avg_price), asset_class,
        )


# ── position plans (autonomy: the exit-thesis "notes" read back each cycle) ─────

async def list_open_plans(user_id, account) -> list[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # MUST SCOPE BY USER
        rows = await conn.fetch(
            "SELECT * FROM trading_position_plan WHERE user_id IS NOT DISTINCT FROM $1::uuid "
            "AND account=$2 AND status='open' ORDER BY ticker ASC",
            _uid(user_id), account,
        )
        return [dict(r) for r in rows]


async def get_open_plan(user_id, account, ticker) -> Optional[dict]:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # MUST SCOPE BY USER
        row = await conn.fetchrow(
            "SELECT * FROM trading_position_plan WHERE user_id IS NOT DISTINCT FROM $1::uuid "
            "AND account=$2 AND ticker=$3 AND status='open'",
            _uid(user_id), account, ticker,
        )
        return dict(row) if row else None


async def upsert_open_plan(user_id, account, ticker, **fields) -> dict:
    """Create or update the OPEN plan for a (user, account, ticker). Only the
    provided fields are written; unset ones keep their value (COALESCE)."""
    pool = await _get_pool()
    cols = ("qty", "entry_price", "stop_price", "target_price", "thesis",
            "broker_stop_order_id", "opened_run_id")
    numeric = {"qty", "entry_price", "stop_price", "target_price"}
    vals = {}
    for c in cols:
        if c in fields:
            vals[c] = _dec(fields[c]) if c in numeric else fields[c]
    async with pool.acquire() as conn:
        # MUST SCOPE BY USER — UPDATE the open row, else INSERT (partial unique index
        # on status='open' prevents two open rows for the same ticker).
        set_parts = [f"{c}=COALESCE(${i+3}, {c})" for i, c in enumerate(cols)]
        update_args = [_uid(user_id), account, ticker] + [vals.get(c) for c in cols]
        updated = await conn.fetchrow(
            f"UPDATE trading_position_plan SET {', '.join(set_parts)}, updated_at=NOW() "
            "WHERE user_id IS NOT DISTINCT FROM $1::uuid AND account=$2 AND ticker=$3 "
            "AND status='open' RETURNING *",
            *update_args,
        )
        if updated:
            return dict(updated)
        ins_cols = ["user_id", "account", "ticker"] + list(cols)
        placeholders = ["$1::uuid", "$2", "$3"] + [f"${i+4}" for i in range(len(cols))]
        ins_args = [_uid(user_id), account, ticker] + [vals.get(c) for c in cols]
        inserted = await conn.fetchrow(
            f"INSERT INTO trading_position_plan ({', '.join(ins_cols)}) "
            f"VALUES ({', '.join(placeholders)}) RETURNING *",
            *ins_args,
        )
        return dict(inserted)


async def close_plan(user_id, account, ticker, closed_run_id=None, realized_pl=None) -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # MUST SCOPE BY USER
        await conn.execute(
            "UPDATE trading_position_plan SET status='closed', closed_at=NOW(), "
            "closed_run_id=$4::uuid, realized_pl=$5 "
            "WHERE user_id IS NOT DISTINCT FROM $1::uuid AND account=$2 AND ticker=$3 "
            "AND status='open'",
            _uid(user_id), account, ticker,
            str(closed_run_id) if closed_run_id else None, _dec(realized_pl),
        )
