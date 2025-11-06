// API Functions
const API = {
    // Fetch all violations
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

    // Get violation statistics
    async getStats() {
        try {
            const violations = await this.getViolations();
            
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            const weekAgo = new Date(today);
            weekAgo.setDate(weekAgo.getDate() - 7);

            const stats = {
                total: violations.length,
                today: 0,
                thisWeek: 0,
                severity: {
                    high: 0,
                    medium: 0,
                    low: 0
                },
                recentViolations: violations.slice(0, 5)
            };

            violations.forEach(v => {
                const vDate = new Date(v.timestamp);
                
                if (vDate >= today) stats.today++;
                if (vDate >= weekAgo) stats.thisWeek++;
                
                // For now, all violations are high severity (missing hardhat)
                stats.severity.high++;
            });

            return stats;
        } catch (error) {
            console.error('Error calculating stats:', error);
            return {
                total: 0,
                today: 0,
                thisWeek: 0,
                severity: { high: 0, medium: 0, low: 0 },
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
    }
};
