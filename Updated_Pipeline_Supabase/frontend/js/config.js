// API Configuration
const API_CONFIG = {
    BASE_URL: 'http://localhost:5000',
    ENDPOINTS: {
        VIOLATIONS: '/api/violations',
        REPORT: (id) => `/report/${id}`,
        IMAGE: (id, filename) => `/image/${id}/${filename}`,
        STATS: '/api/stats',
        LIVE_STREAM: '/api/live/stream',
        LIVE_START: '/api/live/start',
        LIVE_STOP: '/api/live/stop',
        LIVE_STATUS: '/api/live/status',
        UPLOAD_INFERENCE: '/api/inference/upload',
        SYSTEM_INFO: '/api/system/info'
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
