// API Configuration
// BASE_URL auto-detects: same-origin when served by Flask,
// or set window.PPE_API_URL before this script loads for custom backend URL.
// For Vercel deployment, set PPE_API_URL to your backend server's public URL.
const normalizeApiBaseUrl = (value) => {
    const raw = String(value || '').trim();
    if (!raw || raw === window.location.origin) {
        return '';
    }
    return raw.replace(/\/+$/, '');
};

let runtimeApiBaseOverride = null;

const API_CONFIG = {
    get BASE_URL() {
        if (runtimeApiBaseOverride !== null) {
            return runtimeApiBaseOverride;
        }
        if (typeof navigator !== 'undefined' && navigator.onLine === false) {
            return this.LOCAL_BACKEND_URL;
        }
        return normalizeApiBaseUrl(window.PPE_API_URL || (window.__PPE_CONFIG__ && window.__PPE_CONFIG__.API_BASE_URL) || '');
    },
    set BASE_URL(value) {
        if (value === null || value === undefined) {
            runtimeApiBaseOverride = null;
            return;
        }

        const normalized = normalizeApiBaseUrl(value);
        runtimeApiBaseOverride = normalized;

        if (normalized) {
            window.PPE_API_URL = normalized;
            if (window.__PPE_CONFIG__ && typeof window.__PPE_CONFIG__ === 'object') {
                window.__PPE_CONFIG__.API_BASE_URL = normalized;
            }
        }
    },
    LOCAL_BACKEND_URL: 'http://localhost:5000',
    ENDPOINTS: {
        VIOLATIONS: '/api/violations',
        REPORT: (id) => `/report/${id}`,
        IMAGE: (id, filename) => `/image/${id}/${filename}`,
        STATS: '/api/stats',
        LIVE_STREAM: '/api/live/stream',
        LIVE_START: '/api/live/start',
        LIVE_STOP: '/api/live/stop',
        LIVE_STATUS: '/api/live/status',
        LIVE_DEVICES: '/api/live/devices',
        LIVE_EDGE_REALSENSE_STATUS: '/api/live/edge/realsense/status',
        LIVE_DEPTH_STATUS: '/api/live/depth/status',
        LIVE_DEPTH_PREVIEW: '/api/live/depth/preview',
        UPLOAD_INFERENCE: '/api/inference/upload',
        LIVE_FRAME_INFERENCE: '/api/inference/live-frame',
        SYSTEM_INFO: '/api/system/info',
        RELIABILITY_STATS: '/api/reliability/stats',
        PROVIDER_RUNTIME_STATUS: '/api/providers/runtime-status',
        REALTIME_STREAM: '/api/realtime/stream',
        REALTIME_SNAPSHOT: '/api/realtime/snapshot'
    }
};

// Application State
const APP_STATE = {
    currentPage: 'home',
    violations: [],
    liveStreamActive: false,
    stats: {
        total: 0,
        today: 0,
        thisWeek: 0,
        severity: {
            high: 0,
            medium: 0,
            low: 0
        }
    }
};
