// API Functions
const API = {
    // Fetch all violations with status info
    async getViolations() {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.VIOLATIONS}`);
            if (!response.ok) throw new Error('Failed to fetch violations');
            return await response.json();
        } catch (error) {
            console.error('Error fetching violations:', error);
            return [];
        }
    },

    // Get violation by ID with status info
    async getViolation(reportId) {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/violation/${reportId}`);
            if (!response.ok) throw new Error('Failed to fetch violation');
            return await response.json();
        } catch (error) {
            console.error('Error fetching violation:', error);
            return null;
        }
    },

    // Get report status
    async getReportStatus(reportId) {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/report/${reportId}/status`);
            if (!response.ok) throw new Error('Failed to fetch report status');
            return await response.json();
        } catch (error) {
            console.error('Error fetching report status:', error);
            return { status: 'unknown', message: 'Unable to check status' };
        }
    },

    // Get pending reports
    async getPendingReports() {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/reports/pending`);
            if (!response.ok) throw new Error('Failed to fetch pending reports');
            return await response.json();
        } catch (error) {
            console.error('Error fetching pending reports:', error);
            return [];
        }
    },

    // Get violation statistics with status breakdown
    async getStats() {
        try {
            // Try fetching pre-calculated stats from backend first (includes breakdown & deltas)
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/stats`);
            if (response.ok) {
                const data = await response.json();

                // Ensure recent violations are attached if not present
                if (!data.recentViolations) {
                    const violations = await this.getViolations();
                    data.recentViolations = violations.slice(0, 5);
                }
                return data;
            }
        } catch (e) {
            console.warn('Backend stats endpoint failed, falling back to client-side calc:', e);
        }

        try {
            const violations = await this.getViolations();

            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            const yesterday = new Date(today);
            yesterday.setDate(yesterday.getDate() - 1);
            const weekAgo = new Date(today);
            weekAgo.setDate(weekAgo.getDate() - 7);

            // Client-side fallback (Delta will be 0 as we don't have historical snapshots)
            const stats = {
                total: violations.length,
                today: 0,
                todayDelta: 0,
                thisWeek: 0,
                weekDelta: 0,
                pending: 0,
                completed: 0,
                failed: 0,
                severity: {
                    high: 0,
                    medium: 0,
                    low: 0
                },
                breakdown: {}, // Cannot reliably calc breakdown client-side without deep parsing
                recentViolations: violations.slice(0, 5)
            };

            violations.forEach(v => {
                const vDate = new Date(v.timestamp);

                if (vDate >= today) stats.today++;
                if (vDate >= weekAgo) stats.thisWeek++;

                // Count by status
                const status = v.status || (v.has_report ? 'completed' : 'pending');
                if (status === 'completed') stats.completed++;
                else if (status === 'failed') stats.failed++;
                else stats.pending++;

                // Count by severity
                const severity = (v.severity || 'HIGH').toLowerCase();
                if (severity === 'high' || severity === 'critical') stats.severity.high++;
                else if (severity === 'medium') stats.severity.medium++;
                else stats.severity.low++;
            });

            return stats;
        } catch (error) {
            console.error('Error calculating stats:', error);
            return {
                total: 0,
                today: 0,
                thisWeek: 0,
                pending: 0,
                completed: 0,
                failed: 0,
                severity: { high: 0, medium: 0, low: 0 },
                breakdown: {},
                recentViolations: []
            };
        }
    },

    // Get image URL
    getImageUrl(reportId, filename) {
        return `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.IMAGE(reportId, filename)}`;
    },

    // Get report URL
    getReportUrl(reportId) {
        return `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.REPORT(reportId)}`;
    },

    // Get event logs
    async getLogs(limit = 50, eventType = null) {
        try {
            let url = `${API_CONFIG.BASE_URL}/api/logs?limit=${limit}`;
            if (eventType) url += `&event_type=${eventType}`;
            const response = await fetch(url);
            if (!response.ok) throw new Error('Failed to fetch logs');
            return await response.json();
        } catch (error) {
            console.error('Error fetching logs:', error);
            return [];
        }
    },

    // Get device statistics
    async getDeviceStats(deviceId) {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/device/${deviceId}/stats`);
            if (!response.ok) throw new Error('Failed to fetch device stats');
            return await response.json();
        } catch (error) {
            console.error('Error fetching device stats:', error);
            return {};
        }
    }
};
