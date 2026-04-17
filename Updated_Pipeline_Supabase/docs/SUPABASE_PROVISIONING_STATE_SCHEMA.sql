-- Supabase schema migration for provisioning state persistence.
-- Run this in the Supabase SQL editor before enabling multi-instance provisioning state.

BEGIN;

CREATE TABLE IF NOT EXISTS public.provisioning_devices (
    machine_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'provisioned', 'rejected')),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    token TEXT NOT NULL DEFAULT '',
    provision_secret_hash TEXT NOT NULL DEFAULT '',
    approved_at TIMESTAMPTZ NULL,
    provisioned_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_provisioning_devices_status
    ON public.provisioning_devices (status);

CREATE INDEX IF NOT EXISTS idx_provisioning_devices_requested_at
    ON public.provisioning_devices (requested_at DESC);

CREATE TABLE IF NOT EXISTS public.provisioning_bootstrap_jti (
    jti TEXT PRIMARY KEY,
    used_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_provisioning_bootstrap_jti_used_at
    ON public.provisioning_bootstrap_jti (used_at DESC);

CREATE OR REPLACE FUNCTION public.set_provisioning_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_provisioning_devices_updated_at ON public.provisioning_devices;
CREATE TRIGGER trg_provisioning_devices_updated_at
BEFORE UPDATE ON public.provisioning_devices
FOR EACH ROW
EXECUTE FUNCTION public.set_provisioning_updated_at();

COMMIT;

-- Optional maintenance query (manual or scheduled):
-- DELETE FROM public.provisioning_bootstrap_jti
-- WHERE used_at < NOW() - INTERVAL '7 days';
