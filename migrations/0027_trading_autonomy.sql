-- 0027_trading_autonomy.sql — autonomous self-managing trading desk
-- Mirrored idempotently in agents/assistant/trading/db.py::_DDL (bootstrap on first use).
-- Adds: per-position exit plans (the "notes" the 30-min review loop reads back),
-- autonomy + circuit-breaker config flags, and persisted stop levels on trades.

-- Open positions the desk is actively managing. One row per (user, account, ticker)
-- while open; carries the exit thesis + the resting broker stop so the next cycle
-- can review it, and reconcile (close) it if the stop fired between cycles.
CREATE TABLE IF NOT EXISTS trading_position_plan (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL,
    account              TEXT NOT NULL,
    ticker               TEXT NOT NULL,
    qty                  NUMERIC,
    entry_price          NUMERIC,
    stop_price           NUMERIC,
    target_price         NUMERIC,
    thesis               TEXT,            -- when/why to sell (the studied exit plan)
    status               TEXT NOT NULL DEFAULT 'open',   -- open | closed
    broker_stop_order_id TEXT,            -- resting T212 stop order protecting it
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

-- Autonomy + circuit-breaker state on the existing config row.
ALTER TABLE trading_config ADD COLUMN IF NOT EXISTS autonomous BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE trading_config ADD COLUMN IF NOT EXISTS paused_until TIMESTAMPTZ;
ALTER TABLE trading_config ADD COLUMN IF NOT EXISTS day_baseline_equity NUMERIC;
ALTER TABLE trading_config ADD COLUMN IF NOT EXISTS day_baseline_date DATE;

-- Persist the stop the RiskOfficer attaches (was previously computed then dropped),
-- and the exact share count for cycle-driven exits (full sell / partial trim).
ALTER TABLE trading_trade ADD COLUMN IF NOT EXISTS stop_pct NUMERIC;
ALTER TABLE trading_trade ADD COLUMN IF NOT EXISTS stop_price NUMERIC;
ALTER TABLE trading_trade ADD COLUMN IF NOT EXISTS exit_qty NUMERIC;
