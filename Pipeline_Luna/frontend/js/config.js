// API Configuration
const API_CONFIG = {
    BASE_URL: 'http://localhost:5001',
    ENDPOINTS: {
        VIOLATIONS: '/api/violations',
        REPORT: (id) => `/report/${id}`,
        IMAGE: (id, filename) => `/image/${id}/${filename}`,
        STATS: '/api/stats'
    }
};

// Application State
const APP_STATE = {
    currentPage: 'home',
    violations: [],
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
