-- =============================================================================
-- LUNA PPE SAFETY MONITOR - SUPABASE DATABASE SCHEMA
-- =============================================================================
-- 
-- This schema provides a comprehensive database structure for the PPE compliance
-- monitoring system with security best practices.
--
-- Features:
-- - Detection events and violation tracking with status
-- - Multi-device support with device management
-- - Audit logging (flood_logs)
-- - Row Level Security (RLS) policies
-- - User access control
-- - API rate limiting tracking
--
-- To set up:
-- 1. Run this SQL in your Supabase SQL Editor
-- 2. Enable RLS on all tables
-- 3. Create storage buckets: violation-images, reports
-- =============================================================================

-- =============================================================================
-- CORE TABLES
-- =============================================================================

-- Detection Events - Main violation event records
CREATE TABLE IF NOT EXISTS public.detection_events (
    report_id VARCHAR(50) PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    device_id VARCHAR(50),
    person_count INTEGER DEFAULT 0,
    violation_count INTEGER DEFAULT 0,
    severity VARCHAR(20) DEFAULT 'HIGH' CHECK (severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')),
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'generating', 'completed', 'failed', 'partial')),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Violations - Detailed violation data with storage keys
CREATE TABLE IF NOT EXISTS public.violations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id VARCHAR(50) NOT NULL REFERENCES public.detection_events(report_id) ON DELETE CASCADE,
    violation_summary TEXT,
    caption TEXT,
    nlp_analysis JSONB,
    detection_data JSONB,
    original_image_key VARCHAR(500),
    annotated_image_key VARCHAR(500),
    report_html_key VARCHAR(500),
    report_pdf_key VARCHAR(500),
    device_id VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(report_id)  -- One violation record per report
);

-- Flood Logs - System event logging for audit trail
CREATE TABLE IF NOT EXISTS public.flood_logs (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    report_id VARCHAR(50),
    device_id VARCHAR(50),
    user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    message TEXT,
    metadata JSONB,
    ip_address INET,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- SECURITY TABLES
-- =============================================================================

-- Devices - Registered monitoring devices
CREATE TABLE IF NOT EXISTS public.devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100),
    location VARCHAR(200),
    status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'maintenance')),
    api_key_hash VARCHAR(64),  -- SHA-256 hash of device API key
    last_seen TIMESTAMPTZ,
    violation_count INTEGER DEFAULT 0,
    config JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- API Keys - For device authentication
CREATE TABLE IF NOT EXISTS public.api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_hash VARCHAR(64) UNIQUE NOT NULL,  -- SHA-256 hash
    name VARCHAR(100) NOT NULL,
    device_id UUID REFERENCES public.devices(id) ON DELETE CASCADE,
    permissions JSONB DEFAULT '["read", "write"]',
    rate_limit INTEGER DEFAULT 100,  -- Requests per minute
    expires_at TIMESTAMPTZ,
    last_used TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL
);

-- Rate Limiting - Track API usage per device/key
CREATE TABLE IF NOT EXISTS public.rate_limits (
    id BIGSERIAL PRIMARY KEY,
    key_hash VARCHAR(64) NOT NULL,
    endpoint VARCHAR(200),
    request_count INTEGER DEFAULT 1,
    window_start TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- User Roles - Role-based access control
CREATE TABLE IF NOT EXISTS public.user_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL CHECK (role IN ('admin', 'supervisor', 'viewer', 'device')),
    permissions JSONB DEFAULT '[]',
    assigned_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(user_id, role)
);

-- Security Events - Track security-related events
CREATE TABLE IF NOT EXISTS public.security_events (
    id BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,  -- login_failed, api_key_created, permission_denied, etc.
    user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    device_id UUID REFERENCES public.devices(id) ON DELETE SET NULL,
    ip_address INET,
    user_agent TEXT,
    details JSONB,
    severity VARCHAR(20) DEFAULT 'INFO' CHECK (severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- INDEXES
-- =============================================================================

-- Detection Events
CREATE INDEX IF NOT EXISTS idx_detection_events_timestamp ON public.detection_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_detection_events_status ON public.detection_events(status);
CREATE INDEX IF NOT EXISTS idx_detection_events_device ON public.detection_events(device_id);
CREATE INDEX IF NOT EXISTS idx_detection_events_severity ON public.detection_events(severity);

-- Violations
CREATE INDEX IF NOT EXISTS idx_violations_report_id ON public.violations(report_id);
CREATE INDEX IF NOT EXISTS idx_violations_device_id ON public.violations(device_id);
CREATE INDEX IF NOT EXISTS idx_violations_created_at ON public.violations(created_at DESC);

-- Flood Logs
CREATE INDEX IF NOT EXISTS idx_flood_logs_event_type ON public.flood_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_flood_logs_report_id ON public.flood_logs(report_id);
CREATE INDEX IF NOT EXISTS idx_flood_logs_device_id ON public.flood_logs(device_id);
CREATE INDEX IF NOT EXISTS idx_flood_logs_created_at ON public.flood_logs(created_at DESC);

-- Devices
CREATE INDEX IF NOT EXISTS idx_devices_device_id ON public.devices(device_id);
CREATE INDEX IF NOT EXISTS idx_devices_status ON public.devices(status);

-- Rate Limits
CREATE INDEX IF NOT EXISTS idx_rate_limits_key_hash ON public.rate_limits(key_hash);
CREATE INDEX IF NOT EXISTS idx_rate_limits_window ON public.rate_limits(window_start);

-- Security Events
CREATE INDEX IF NOT EXISTS idx_security_events_type ON public.security_events(event_type);
CREATE INDEX IF NOT EXISTS idx_security_events_user ON public.security_events(user_id);
CREATE INDEX IF NOT EXISTS idx_security_events_created ON public.security_events(created_at DESC);

-- =============================================================================
-- ROW LEVEL SECURITY (RLS) POLICIES
-- =============================================================================

-- Enable RLS on all tables
ALTER TABLE public.detection_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.violations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.flood_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.security_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rate_limits ENABLE ROW LEVEL SECURITY;

-- Detection Events Policies
CREATE POLICY "detection_events_select_authenticated" ON public.detection_events
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "detection_events_insert_service" ON public.detection_events
    FOR INSERT TO service_role
    WITH CHECK (true);

CREATE POLICY "detection_events_update_service" ON public.detection_events
    FOR UPDATE TO service_role
    USING (true);

-- Violations Policies
CREATE POLICY "violations_select_authenticated" ON public.violations
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "violations_insert_service" ON public.violations
    FOR INSERT TO service_role
    WITH CHECK (true);

CREATE POLICY "violations_update_service" ON public.violations
    FOR UPDATE TO service_role
    USING (true);

-- Flood Logs Policies (read-only for authenticated users)
CREATE POLICY "flood_logs_select_authenticated" ON public.flood_logs
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "flood_logs_insert_service" ON public.flood_logs
    FOR INSERT TO service_role
    WITH CHECK (true);

-- Devices Policies (admin only for management)
CREATE POLICY "devices_select_authenticated" ON public.devices
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "devices_all_admin" ON public.devices
    FOR ALL TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.user_roles
            WHERE user_id = auth.uid() AND role = 'admin'
        )
    );

-- API Keys Policies (admin only)
CREATE POLICY "api_keys_all_admin" ON public.api_keys
    FOR ALL TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.user_roles
            WHERE user_id = auth.uid() AND role = 'admin'
        )
    );

-- User Roles Policies (admin only for management)
CREATE POLICY "user_roles_select_own" ON public.user_roles
    FOR SELECT TO authenticated
    USING (user_id = auth.uid());

CREATE POLICY "user_roles_all_admin" ON public.user_roles
    FOR ALL TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.user_roles
            WHERE user_id = auth.uid() AND role = 'admin'
        )
    );

-- Security Events Policies (admin only)
CREATE POLICY "security_events_select_admin" ON public.security_events
    FOR SELECT TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.user_roles
            WHERE user_id = auth.uid() AND role IN ('admin', 'supervisor')
        )
    );

CREATE POLICY "security_events_insert_service" ON public.security_events
    FOR INSERT TO service_role
    WITH CHECK (true);

-- Rate Limits Policies (service role only)
CREATE POLICY "rate_limits_all_service" ON public.rate_limits
    FOR ALL TO service_role
    USING (true);

-- =============================================================================
-- FUNCTIONS
-- =============================================================================

-- Update timestamp function
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create triggers for updated_at
DROP TRIGGER IF EXISTS update_detection_events_timestamp ON public.detection_events;
CREATE TRIGGER update_detection_events_timestamp
    BEFORE UPDATE ON public.detection_events
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS update_violations_timestamp ON public.violations;
CREATE TRIGGER update_violations_timestamp
    BEFORE UPDATE ON public.violations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS update_devices_timestamp ON public.devices;
CREATE TRIGGER update_devices_timestamp
    BEFORE UPDATE ON public.devices
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Function to check rate limit
CREATE OR REPLACE FUNCTION check_rate_limit(
    p_key_hash VARCHAR(64),
    p_endpoint VARCHAR(200),
    p_limit INTEGER DEFAULT 100,
    p_window_minutes INTEGER DEFAULT 1
)
RETURNS BOOLEAN AS $$
DECLARE
    v_count INTEGER;
    v_window_start TIMESTAMPTZ;
BEGIN
    v_window_start := NOW() - (p_window_minutes || ' minutes')::INTERVAL;
    
    -- Count requests in current window
    SELECT COALESCE(SUM(request_count), 0) INTO v_count
    FROM public.rate_limits
    WHERE key_hash = p_key_hash
      AND (p_endpoint IS NULL OR endpoint = p_endpoint)
      AND window_start >= v_window_start;
    
    -- Return true if under limit
    RETURN v_count < p_limit;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to increment rate limit counter
CREATE OR REPLACE FUNCTION increment_rate_limit(
    p_key_hash VARCHAR(64),
    p_endpoint VARCHAR(200)
)
RETURNS VOID AS $$
BEGIN
    INSERT INTO public.rate_limits (key_hash, endpoint, request_count, window_start)
    VALUES (p_key_hash, p_endpoint, 1, date_trunc('minute', NOW()))
    ON CONFLICT DO NOTHING;
    
    UPDATE public.rate_limits
    SET request_count = request_count + 1
    WHERE key_hash = p_key_hash 
      AND endpoint = p_endpoint 
      AND window_start = date_trunc('minute', NOW());
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to log security event
CREATE OR REPLACE FUNCTION log_security_event(
    p_event_type VARCHAR(50),
    p_user_id UUID,
    p_device_id UUID,
    p_ip_address INET,
    p_details JSONB,
    p_severity VARCHAR(20) DEFAULT 'INFO'
)
RETURNS BIGINT AS $$
DECLARE
    v_event_id BIGINT;
BEGIN
    INSERT INTO public.security_events 
        (event_type, user_id, device_id, ip_address, details, severity)
    VALUES 
        (p_event_type, p_user_id, p_device_id, p_ip_address, p_details, p_severity)
    RETURNING id INTO v_event_id;
    
    RETURN v_event_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get report status with fallback
CREATE OR REPLACE FUNCTION get_report_status(p_report_id VARCHAR(50))
RETURNS TABLE (
    status VARCHAR(20),
    has_report BOOLEAN,
    has_original BOOLEAN,
    has_annotated BOOLEAN,
    error_message TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        de.status,
        (v.report_html_key IS NOT NULL) AS has_report,
        (v.original_image_key IS NOT NULL) AS has_original,
        (v.annotated_image_key IS NOT NULL) AS has_annotated,
        de.error_message
    FROM public.detection_events de
    LEFT JOIN public.violations v ON de.report_id = v.report_id
    WHERE de.report_id = p_report_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get device statistics
CREATE OR REPLACE FUNCTION get_device_stats(p_device_id VARCHAR(50))
RETURNS TABLE (
    total BIGINT,
    completed BIGINT,
    pending BIGINT,
    failed BIGINT,
    critical BIGINT,
    high BIGINT,
    last_detection TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        COUNT(*)::BIGINT as total,
        COUNT(*) FILTER (WHERE de.status = 'completed')::BIGINT as completed,
        COUNT(*) FILTER (WHERE de.status IN ('pending', 'generating'))::BIGINT as pending,
        COUNT(*) FILTER (WHERE de.status = 'failed')::BIGINT as failed,
        COUNT(*) FILTER (WHERE de.severity = 'CRITICAL')::BIGINT as critical,
        COUNT(*) FILTER (WHERE de.severity = 'HIGH')::BIGINT as high,
        MAX(de.timestamp) as last_detection
    FROM public.detection_events de
    WHERE de.device_id = p_device_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================================================
-- STORAGE BUCKET SETUP (Run separately in Supabase Dashboard)
-- =============================================================================

-- Create buckets via Supabase Dashboard:
-- 1. violation-images (private)
-- 2. reports (private)

-- After creating buckets, run these storage policies:
/*
-- Allow authenticated users to read from violation-images
CREATE POLICY "violation_images_select_authenticated"
ON storage.objects FOR SELECT TO authenticated
USING (bucket_id = 'violation-images');

-- Allow service role to insert/update/delete in violation-images
CREATE POLICY "violation_images_all_service"
ON storage.objects FOR ALL TO service_role
USING (bucket_id = 'violation-images');

-- Allow authenticated users to read from reports
CREATE POLICY "reports_select_authenticated"
ON storage.objects FOR SELECT TO authenticated
USING (bucket_id = 'reports');

-- Allow service role to insert/update/delete in reports
CREATE POLICY "reports_all_service"
ON storage.objects FOR ALL TO service_role
USING (bucket_id = 'reports');
*/

-- =============================================================================
-- SAMPLE DATA FOR TESTING (uncomment to use)
-- =============================================================================

-- Insert test admin user role (replace with actual user ID)
-- INSERT INTO public.user_roles (user_id, role, permissions)
-- VALUES ('your-user-uuid', 'admin', '["read", "write", "delete", "manage_users"]');

-- Insert test device
-- INSERT INTO public.devices (device_id, name, location, status)
-- VALUES ('CAM_01', 'Main Entrance Camera', 'Building A - Entry', 'active');

-- =============================================================================
-- CLEANUP (for testing only - DO NOT RUN IN PRODUCTION)
-- =============================================================================

-- DROP TABLE IF EXISTS public.rate_limits CASCADE;
-- DROP TABLE IF EXISTS public.security_events CASCADE;
-- DROP TABLE IF EXISTS public.user_roles CASCADE;
-- DROP TABLE IF EXISTS public.api_keys CASCADE;
-- DROP TABLE IF EXISTS public.devices CASCADE;
-- DROP TABLE IF EXISTS public.flood_logs CASCADE;
-- DROP TABLE IF EXISTS public.violations CASCADE;
-- DROP TABLE IF EXISTS public.detection_events CASCADE;
