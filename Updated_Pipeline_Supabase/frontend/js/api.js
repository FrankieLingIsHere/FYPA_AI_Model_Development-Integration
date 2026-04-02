// API Functions
const API = {
    canonicalViolationKey(rawKey) {
        if (!rawKey) return null;

        const normalized = rawKey
            .toString()
            .trim()
            .toUpperCase()
            .replace(/\s+/g, ' ')
            .replace(/^NO\s+/, 'NO-');

        const simplified = normalized
            .replace(/^MISSING\s+/, '')
            .replace(/^WITHOUT\s+/, '')
            .replace(/^NO[-\s]+/, '')
            .replace(/[\s_-]+/g, ' ')
            .trim();

        if (/HARD ?HAT|HELMET/.test(simplified)) return 'NO-Hardhat';
        if (/SAFETY ?VEST|HI ?VIS|HIGH ?VIS|VEST/.test(simplified)) return 'NO-Safety Vest';
        if (/GLOVE/.test(simplified)) return 'NO-Gloves';
        if (/MASK|RESPIRATOR/.test(simplified)) return 'NO-Mask';
        if (/GOGGLE|EYE/.test(simplified)) return 'NO-Goggles';
        if (/SAFETY ?SHOE|SAFETY ?BOOT|FOOTWEAR|BOOT/.test(simplified)) return 'NO-Safety Shoes';

        return null;
    },

    extractViolationKeys(violation) {
        const keys = [];

        if (Array.isArray(violation?.ppe_tags) && violation.ppe_tags.length > 0) {
            violation.ppe_tags.forEach((tag) => {
                const key = this.canonicalViolationKey(tag);
                if (key) keys.push(key);
            });
        }

        if (keys.length === 0 && Array.isArray(violation?.missing_ppe) && violation.missing_ppe.length > 0) {
            violation.missing_ppe.forEach((item) => {
                const key = this.canonicalViolationKey(`NO-${item}`);
                if (key) keys.push(key);
            });
        }

        if (keys.length === 0 && violation?.violation_summary) {
            const summary = violation.violation_summary.toString();
            const matches = summary.match(/NO-[A-Za-z ]+/g) || [];
            matches.forEach((m) => {
                const key = this.canonicalViolationKey(m.trim());
                if (key) keys.push(key);
            });

            const missingMatches = summary.match(/Missing\s+[A-Za-z\s-]+/gi) || [];
            missingMatches.forEach((m) => {
                const key = this.canonicalViolationKey(m.trim());
                if (key) keys.push(key);
            });
        }

        return keys;
    },

    computeSafetyCompliance(stats) {
        const severity = stats?.severity || {};
        const high = Number(severity.high || 0);
        const medium = Number(severity.medium || 0);
        const low = Number(severity.low || 0);
        const total = Math.max(1, Number(stats?.total || (high + medium + low) || 0));
        const today = Number(stats?.today || 0);

        // Benchmark-inspired leading indicator proxy:
        // severity-weighted non-compliance burden + short-term frequency pressure.
        const weightedBurden = (high * 1.0) + (medium * 0.6) + (low * 0.3);
        const severityPenalty = (weightedBurden / total) * 45;
        const frequencyPenalty = Math.min(30, today * 2.5);
        const complianceScore = Math.round(Math.max(0, Math.min(100, 100 - severityPenalty - frequencyPenalty)));

        let benchmarkBand = 'critical';
        if (complianceScore >= 95) benchmarkBand = 'best-practice';
        else if (complianceScore >= 85) benchmarkBand = 'acceptable';
        else if (complianceScore >= 70) benchmarkBand = 'watchlist';

        return {
            score: complianceScore,
            benchmarkBand,
            benchmarkNote: 'Benchmark-inspired leading indicator aligned with construction PPE audit practice (95%+ is commonly targeted).'
        };
    },

    buildBreakdown(violations) {
        const breakdown = {
            'NO-Hardhat': 0,
            'NO-Safety Vest': 0,
            'NO-Gloves': 0,
            'NO-Mask': 0,
            'NO-Goggles': 0,
            'NO-Safety Shoes': 0
        };

        violations.forEach((violation) => {
            const keys = this.extractViolationKeys(violation);
            if (keys.length === 0) return;
            keys.forEach((key) => {
                const canonical = this.canonicalViolationKey(key);
                if (canonical && Object.prototype.hasOwnProperty.call(breakdown, canonical)) {
                    breakdown[canonical] += 1;
                }
            });
        });

        return breakdown;
    },

    computeDeltas(violations) {
        const now = new Date();
        const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const startYesterday = new Date(startToday);
        startYesterday.setDate(startYesterday.getDate() - 1);

        const startThisWeek = new Date(startToday);
        startThisWeek.setDate(startThisWeek.getDate() - ((startThisWeek.getDay() + 6) % 7));

        const startLastWeek = new Date(startThisWeek);
        startLastWeek.setDate(startLastWeek.getDate() - 7);

        let todayCount = 0;
        let yesterdayCount = 0;
        let thisWeekCount = 0;
        let lastWeekCount = 0;

        violations.forEach((v) => {
            if (!v?.timestamp) return;
            const ts = new Date(v.timestamp);
            if (Number.isNaN(ts.getTime())) return;

            if (ts >= startToday) todayCount += 1;
            else if (ts >= startYesterday) yesterdayCount += 1;

            if (ts >= startThisWeek) thisWeekCount += 1;
            else if (ts >= startLastWeek) lastWeekCount += 1;
        });

        return {
            todayDelta: todayCount - yesterdayCount,
            weekDelta: thisWeekCount - lastWeekCount
        };
    },

    enrichStatsWithViolations(baseStats, violations) {
        const sortedViolations = [...violations].sort((a, b) => {
            const aTs = new Date(a.timestamp || 0).getTime();
            const bTs = new Date(b.timestamp || 0).getTime();
            return bTs - aTs;
        });

        const deltas = this.computeDeltas(sortedViolations);

        return {
            ...baseStats,
            breakdown: baseStats.breakdown && Object.keys(baseStats.breakdown).length
                ? baseStats.breakdown
                : this.buildBreakdown(sortedViolations),
            todayDelta: baseStats.todayDelta !== undefined ? baseStats.todayDelta : deltas.todayDelta,
            weekDelta: baseStats.weekDelta !== undefined ? baseStats.weekDelta : deltas.weekDelta,
            recentViolations: baseStats.recentViolations && baseStats.recentViolations.length
                ? baseStats.recentViolations
                : sortedViolations.slice(0, 5)
        };
    },

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
                const needsEnrichment =
                    data.todayDelta === undefined ||
                    data.weekDelta === undefined ||
                    !data.breakdown ||
                    !data.recentViolations;

                if (!needsEnrichment) {
                    return data;
                }

                const violations = await this.getViolations();
                return this.enrichStatsWithViolations(data, violations);
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

            return this.enrichStatsWithViolations(stats, violations);
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

    async getDeviceStats(deviceId) {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/device/${deviceId}/stats`);
            if (!response.ok) throw new Error('Failed to fetch device stats');
            return await response.json();
        } catch (error) {
            console.error('Error fetching device stats:', error);
            return {};
        }
    },

    // Reprocess a single report
    async reprocessReport(reportId) {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/report/${reportId}/reprocess`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            if (!response.ok) throw new Error('Failed to trigger reprocess');
            return await response.json();
        } catch (error) {
            console.error('Error reprocessing report:', error);
            return { success: false, error: error.message };
        }
    },

    async generateReportNow(reportId, options = {}) {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/report/${reportId}/generate-now`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    force: !!options.force
                })
            });
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.error || 'Failed to trigger priority generation');
            }
            return await response.json();
        } catch (error) {
            console.error('Error triggering priority generation:', error);
            return { success: false, error: error.message };
        }
    },

    async getProviderRoutingSettings() {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/settings/provider-routing`);
            if (!response.ok) throw new Error('Failed to fetch provider routing settings');
            return await response.json();
        } catch (error) {
            console.error('Error fetching provider routing settings:', error);
            return null;
        }
    },

    async updateProviderRoutingSettings(settings) {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/settings/provider-routing`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });
            if (!response.ok) throw new Error('Failed to update provider routing settings');
            return await response.json();
        } catch (error) {
            console.error('Error updating provider routing settings:', error);
            return { success: false, error: error.message };
        }
    },

    async getDiskSpaceStatus() {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/settings/disk-space-status`);
            if (!response.ok) throw new Error('Failed to fetch disk space status');
            return await response.json();
        } catch (error) {
            console.error('Error fetching disk space status:', error);
            return null;
        }
    },

    async getReliabilityStats(windowSize = 50) {
        try {
            const safeWindow = Number.isFinite(Number(windowSize)) ? Number(windowSize) : 50;
            const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.RELIABILITY_STATS}?window=${safeWindow}`);
            if (!response.ok) throw new Error('Failed to fetch reliability stats');
            return await response.json();
        } catch (error) {
            console.error('Error fetching reliability stats:', error);
            return { success: false, error: error.message };
        }
    },

    async getProviderRuntimeStatus() {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.PROVIDER_RUNTIME_STATUS}`);
            if (!response.ok) throw new Error('Failed to fetch provider runtime status');
            return await response.json();
        } catch (error) {
            console.error('Error fetching provider runtime status:', error);
            return { success: false, error: error.message };
        }
    },

    async getReportRecoveryOptions() {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/reports/recovery/options`);
            if (!response.ok) throw new Error('Failed to fetch recovery options');
            return await response.json();
        } catch (error) {
            console.error('Error fetching report recovery options:', error);
            return { success: false, error: error.message };
        }
    },

    async executeReportRecovery(mode, reportIds = null) {
        try {
            const payload = { mode };
            if (Array.isArray(reportIds) && reportIds.length > 0) {
                payload.report_ids = reportIds;
            }

            const response = await fetch(`${API_CONFIG.BASE_URL}/api/reports/recovery/execute`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.error || 'Failed to execute report recovery');
            }
            return data;
        } catch (error) {
            console.error('Error executing report recovery:', error);
            return { success: false, error: error.message };
        }
    },

    getRealtimeStreamUrl() {
        return `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.REALTIME_STREAM}`;
    },

    getRealtimeSnapshotUrl() {
        return `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.REALTIME_SNAPSHOT}`;
    },

    getSupabaseRealtimeConfig() {
        const runtime = window.__PPE_CONFIG__ || {};
        return {
            url: runtime.SUPABASE_URL || window.PPE_SUPABASE_URL || '',
            anonKey: runtime.SUPABASE_ANON_KEY || window.PPE_SUPABASE_ANON_KEY || ''
        };
    }
};
