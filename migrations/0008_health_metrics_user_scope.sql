-- 0008_health_metrics_user_scope.sql
-- Make health_metrics uniqueness per-user so the health module can be multi-tenant
-- (each user's wearable data is scoped by user_id, mirroring the finance per-user
-- pattern). The old UNIQUE(recorded_at, metric_type, source) would let one user's
-- reading collide with another's at the same timestamp. Additive + constraint swap;
-- existing rows (all owned by the seed admin via migration 0005's default) stay valid.
-- The agents health module also applies this idempotently in db.py::_DDL at startup.

ALTER TABLE health_metrics ADD COLUMN IF NOT EXISTS user_id UUID;

-- Drop the old global unique constraint (auto-named by the inline UNIQUE in 001).
ALTER TABLE health_metrics DROP CONSTRAINT IF EXISTS health_metrics_recorded_at_metric_type_source_key;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_health_user_metric') THEN
        ALTER TABLE health_metrics
            ADD CONSTRAINT uq_health_user_metric UNIQUE (user_id, recorded_at, metric_type, source);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_hm_user_type_time
    ON health_metrics (user_id, metric_type, recorded_at DESC);
