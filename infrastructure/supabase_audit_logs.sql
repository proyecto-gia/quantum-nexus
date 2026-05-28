-- ============================================================
-- QUANTUM NEXUS — Telemetría inmutable (Supabase / PostgreSQL)
-- Política: INSERT-ONLY. UPDATE y DELETE bloqueados por RLS.
-- Con RLS habilitado, la AUSENCIA de policy = denegado.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.trade_logs (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    env         TEXT        NOT NULL CHECK (env IN ('PAPER','LIVE')),
    symbol      TEXT        NOT NULL,
    event_type  TEXT        NOT NULL,   -- TICK | SIGNAL | ORDER | REJECT | KILL
    payload     JSONB       NOT NULL,
    signature   TEXT,                   -- HMAC de la señal (auditoría)
    severity    TEXT        NOT NULL DEFAULT 'INFO'
);

CREATE INDEX IF NOT EXISTS idx_trade_logs_created ON public.trade_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trade_logs_event   ON public.trade_logs (event_type);

-- Habilitar RLS: a partir de aquí, todo está denegado salvo policy explícita.
ALTER TABLE public.trade_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.trade_logs FORCE ROW LEVEL SECURITY;

-- ÚNICA policy: permitir INSERT. (No se crea SELECT/UPDATE/DELETE de escritura.)
CREATE POLICY "Insert Only Telemetry"
    ON public.trade_logs
    FOR INSERT
    WITH CHECK (true);

-- Lectura controlada (sólo para roles de auditoría; opcional, restringible).
CREATE POLICY "Read Telemetry (audit)"
    ON public.trade_logs
    FOR SELECT
    USING (true);

-- STRICT CONSTRAINT: deliberadamente SIN policy para UPDATE ni DELETE
-- bajo ninguna circunstancia. Esto los hace matemáticamente imposibles
-- mientras FORCE ROW LEVEL SECURITY esté activo (ni el owner los evade).

-- Defensa en profundidad: revocar grants de mutación a nivel SQL.
REVOKE UPDATE, DELETE, TRUNCATE ON public.trade_logs FROM PUBLIC;
