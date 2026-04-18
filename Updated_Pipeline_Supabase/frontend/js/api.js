// API Functions
const API = {
    imagePrefetchState: {
        completed: new Set(),
        inFlight: new Set(),
        lastBatchAt: 0
    },

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

    getCacheStorageKey(scope) {
        return `ppe-cache-v1:${scope}`;
    },

    writeJsonCache(scope, payload) {
        try {
            const envelope = {
                ts: Date.now(),
                data: payload
            };
            localStorage.setItem(this.getCacheStorageKey(scope), JSON.stringify(envelope));
        } catch (error) {
            // Best-effort cache only.
        }
    },

    readJsonCache(scope) {
        try {
            const raw = localStorage.getItem(this.getCacheStorageKey(scope));
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            if (!parsed || typeof parsed !== 'object') return null;
            return parsed;
        } catch (error) {
            return null;
        }
    },

    async fetchJsonWithCache(url, {
        cacheScope,
        timeoutMs = 8000,
        preferFresh = true
    } = {}) {
        const scope = cacheScope || url;
        const cached = this.readJsonCache(scope);

        if (!navigator.onLine && cached) {
            return cached.data;
        }

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

        try {
            const response = await fetch(url, {
                signal: controller.signal,
                cache: preferFresh ? 'no-store' : 'default'
            });
            if (!response.ok) throw new Error(`Request failed: ${response.status}`);
            const data = await response.json();
            this.writeJsonCache(scope, data);
            return data;
        } catch (error) {
            if (cached) {
                console.warn(`Using cached response for ${scope}:`, error.message || error);
                return cached.data;
            }
            throw error;
        } finally {
            clearTimeout(timeoutId);
        }
    },

    prefetchViolationImages(violations = []) {
        if (!Array.isArray(violations) || violations.length === 0) return;
        if (navigator.onLine === false) return;

        const now = Date.now();
        const state = this.imagePrefetchState || { completed: new Set(), inFlight: new Set(), lastBatchAt: 0 };

        // Prevent repeated broad prefetch storms across pages and refresh loops.
        if (now - Number(state.lastBatchAt || 0) < 12000) {
            return;
        }
        state.lastBatchAt = now;

        const candidates = [];
        violations.slice(0, 12).forEach((violation) => {
            if (!violation || !violation.report_id) return;
            if (violation.has_original) {
                candidates.push({
                    key: `${violation.report_id}:original.jpg`,
                    url: this.getImageUrl(violation.report_id, 'original.jpg')
                });
            }
            if (violation.has_annotated) {
                candidates.push({
                    key: `${violation.report_id}:annotated.jpg`,
                    url: this.getImageUrl(violation.report_id, 'annotated.jpg')
                });
            }
        });

        const selected = candidates
            .filter((item) => !state.completed.has(item.key) && !state.inFlight.has(item.key))
            .slice(0, 6);

        selected.forEach((item, index) => {
            state.inFlight.add(item.key);
            setTimeout(() => {
                fetch(item.url, { cache: 'force-cache' })
                    .then((response) => {
                        if (response && response.ok) {
                            state.completed.add(item.key);
                        }
                    })
                    .catch(() => {
                        // Ignore prefetch failures; this is an optimization path.
                    })
                    .finally(() => {
                        state.inFlight.delete(item.key);
                    });
            }, index * 90);
        });
    },

    // Fetch all violations with status info
    async getViolations(options = {}) {
        try {
            const requestedLimit = Number(options.limit);
            const safeLimit = Number.isFinite(requestedLimit)
                ? Math.max(1, Math.min(Math.floor(requestedLimit), 5000))
                : 1000;
            const url = `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.VIOLATIONS}?limit=${safeLimit}`;
            const data = await this.fetchJsonWithCache(url, {
                cacheScope: `violations:limit:${safeLimit}`,
                timeoutMs: 10000
            });
            const list = Array.isArray(data) ? data : [];
            this.prefetchViolationImages(list);
            return list;
        } catch (error) {
            console.error('Error fetching violations:', error);
            return [];
        }
    },

    // Get violation by ID with status info
    async getViolation(reportId) {
        try {
            const url = `${API_CONFIG.BASE_URL}/api/violation/${reportId}`;
            return await this.fetchJsonWithCache(url, {
                cacheScope: `violation:${reportId}`
            });
        } catch (error) {
            console.error('Error fetching violation:', error);
            return null;
        }
    },

    // Get report status
    async getReportStatus(reportId) {
        try {
            const url = `${API_CONFIG.BASE_URL}/api/report/${reportId}/status`;
            return await this.fetchJsonWithCache(url, {
                cacheScope: `report-status:${reportId}`,
                timeoutMs: 7000
            });
        } catch (error) {
            console.error('Error fetching report status:', error);
            return { status: 'unknown', message: 'Unable to check status' };
        }
    },

    // Get pending reports
    async getPendingReports() {
        try {
            const url = `${API_CONFIG.BASE_URL}/api/reports/pending`;
            const data = await this.fetchJsonWithCache(url, {
                cacheScope: 'reports:pending'
            });
            return Array.isArray(data) ? data : [];
        } catch (error) {
            console.error('Error fetching pending reports:', error);
            return [];
        }
    },

    // Get violation statistics with status breakdown
    async getStats() {
        try {
            // Try fetching pre-calculated stats from backend first (includes breakdown & deltas)
            const data = await this.fetchJsonWithCache(`${API_CONFIG.BASE_URL}/api/stats`, {
                cacheScope: 'stats:summary',
                timeoutMs: 9000
            });
            if (data && typeof data === 'object') {
                const needsEnrichment =
                    data.todayDelta === undefined ||
                    data.weekDelta === undefined ||
                    !data.breakdown ||
                    !data.recentViolations;

                if (!needsEnrichment) {
                    return data;
                }

                const targetLimit = Math.max(Number(data.total || 0), 1000);
                const violations = await this.getViolations({ limit: targetLimit });
                return this.enrichStatsWithViolations(data, violations);
            }
        } catch (e) {
            console.warn('Backend stats endpoint failed, falling back to client-side calc:', e);
        }

        try {
            const violations = await this.getViolations({ limit: 1000 });

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

    async prefetchReport(reportId) {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/report/${reportId}/prefetch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                cache: 'no-store'
            });
            if (!response.ok) {
                return { success: false, error: `Prefetch failed: ${response.status}` };
            }
            const data = await response.json().catch(() => ({}));
            return data && typeof data === 'object' ? data : { success: false, error: 'Invalid prefetch response' };
        } catch (error) {
            return { success: false, error: String(error && error.message ? error.message : error) };
        }
    },

    // Get event logs
    async getLogs(limit = 50, eventType = null) {
        try {
            let url = `${API_CONFIG.BASE_URL}/api/logs?limit=${limit}`;
            if (eventType) url += `&event_type=${eventType}`;
            const data = await this.fetchJsonWithCache(url, {
                cacheScope: `logs:${limit}:${eventType || 'all'}`,
                timeoutMs: 9000
            });
            return Array.isArray(data) ? data : [];
        } catch (error) {
            console.error('Error fetching logs:', error);
            return [];
        }
    },

    async getDeviceStats(deviceId) {
        try {
            const url = `${API_CONFIG.BASE_URL}/api/device/${deviceId}/stats`;
            const data = await this.fetchJsonWithCache(url, {
                cacheScope: `device-stats:${deviceId}`,
                timeoutMs: 9000
            });
            return data && typeof data === 'object' ? data : {};
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
            const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.PROVIDER_RUNTIME_STATUS}`, {
                cache: 'no-store'
            });
            if (!response.ok) throw new Error('Failed to fetch provider runtime status');
            return await response.json();
        } catch (error) {
            console.error('Error fetching provider runtime status:', error);
            return { success: false, error: error.message };
        }
    },

    async getReportRecoveryOptions(options = {}) {
        try {
            const machineId = String(
                (options && (options.machineId || options.machine_id)) || ''
            ).trim();
            const query = new URLSearchParams();
            if (machineId) {
                query.set('machine_id', machineId);
            }

            const querySuffix = query.toString();
            const endpoint = `${API_CONFIG.BASE_URL}/api/reports/recovery/options${querySuffix ? `?${querySuffix}` : ''}`;

            const response = await fetch(endpoint, {
                cache: 'no-store'
            });
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

    async prepareLocalMode(options = {}) {
        try {
            const payload = {
                auto_pull: options.autoPull !== false,
                set_local_first: options.setLocalFirst !== false,
                wait_seconds: Number(options.waitSeconds || 8),
                pull_timeout_seconds: Number(options.pullTimeoutSeconds || 600)
            };

            const response = await fetch(`${API_CONFIG.BASE_URL}/api/local-mode/prepare`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                return {
                    success: false,
                    ...data,
                    error: data.error || data.message || 'Failed to prepare local mode'
                };
            }
            return data;
        } catch (error) {
            console.error('Error preparing local mode:', error);
            return { success: false, error: error.message };
        }
    },

    async autoProvisionLocalModeCredentials(options = {}) {
        try {
            const payload = {};
            if (options.cloudUrl) {
                payload.cloud_url = String(options.cloudUrl).trim();
            }

            const response = await fetch(`${API_CONFIG.BASE_URL}/api/local-mode/provisioning/auto`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                return {
                    success: false,
                    ...data,
                    error: data.error || data.message || `Auto-provisioning failed (${response.status})`
                };
            }

            return data;
        } catch (error) {
            console.error('Error auto-provisioning local mode credentials:', error);
            return { success: false, error: error.message };
        }
    },

    async requestCloudProvisioningApproval(options = {}) {
        try {
            const machineId = String(
                (options && (options.machineId || options.machine_id)) || ''
            ).trim();
            if (!machineId) {
                return {
                    success: false,
                    error: 'machine_id is required to request provisioning approval'
                };
            }

            const response = await fetch(`${API_CONFIG.BASE_URL}/api/provision/request`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ machine_id: machineId })
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                return {
                    success: false,
                    ...data,
                    machine_id: String(data.machine_id || machineId).trim(),
                    error: data.error || data.message || `Provision request failed (${response.status})`
                };
            }

            return {
                success: true,
                ...data,
                machine_id: String(data.machine_id || machineId).trim()
            };
        } catch (error) {
            console.error('Error requesting cloud provisioning approval:', error);
            return { success: false, error: error.message };
        }
    },

    async getCloudProvisioningStatus(options = {}) {
        try {
            const machineId = String(
                (options && (options.machineId || options.machine_id)) || ''
            ).trim();
            const provisionSecret = String(
                (options && (options.provisionSecret || options.provision_secret)) || ''
            ).trim();

            if (!machineId) {
                return {
                    success: false,
                    error: 'machine_id is required to fetch cloud provisioning status'
                };
            }

            if (!provisionSecret) {
                return {
                    success: false,
                    machine_id: machineId,
                    error: 'provision_secret is required to fetch cloud provisioning status'
                };
            }

            const query = new URLSearchParams();
            query.set('machine_id', machineId);

            const response = await fetch(`${API_CONFIG.BASE_URL}/api/provision/status?${query.toString()}`, {
                cache: 'no-store',
                headers: {
                    'X-Provision-Secret': provisionSecret
                }
            });

            const data = await response.json().catch(() => ({}));
            const status = String((data && data.status) || '').trim().toLowerCase();

            if (response.status === 403 && status === 'rejected') {
                return {
                    success: true,
                    ...data,
                    status: 'rejected',
                    machine_id: String(data.machine_id || machineId).trim()
                };
            }

            if (!response.ok) {
                return {
                    success: false,
                    ...data,
                    status,
                    machine_id: String(data.machine_id || machineId).trim(),
                    error: data.error || data.message || `Provision status failed (${response.status})`
                };
            }

            return {
                success: true,
                ...data,
                status,
                machine_id: String(data.machine_id || machineId).trim()
            };
        } catch (error) {
            console.error('Error fetching cloud provisioning status:', error);
            return { success: false, error: error.message };
        }
    },

    async getLocalModeProvisioningStatus(options = {}) {
        try {
            const machineId = String(
                (options && (options.machineId || options.machine_id)) || ''
            ).trim();
            const query = new URLSearchParams();
            if (machineId) {
                query.set('machine_id', machineId);
            }

            const querySuffix = query.toString();
            const endpoint = `${API_CONFIG.BASE_URL}/api/local-mode/provisioning/status${querySuffix ? `?${querySuffix}` : ''}`;

            const response = await fetch(endpoint, {
                cache: 'no-store'
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                return {
                    success: false,
                    ...data,
                    error: data.error || data.message || 'Failed to fetch local provisioning status'
                };
            }
            return data;
        } catch (error) {
            console.error('Error fetching local provisioning status:', error);
            return { success: false, error: error.message };
        }
    },

    async switchPipelineMode(mode) {
        const normalized = String(mode || '').trim().toLowerCase();
        if (normalized !== 'local' && normalized !== 'cloud') {
            return { success: false, error: 'Mode must be either local or cloud' };
        }
        return this.updateProviderRoutingSettings({
            routing_profile: normalized
        });
    },

    async syncLocalCacheToSupabase(options = {}) {
        try {
            const limit = Number(options.limit || 120);
            const reason = String(options.reason || '').trim() || 'manual_api';
            const dryRun = !!options.dryRun;
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/reports/sync-local-cache`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    limit,
                    reason,
                    dry_run: dryRun
                })
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                return {
                    success: false,
                    ...data,
                    error: data.error || 'Failed to sync local cache to Supabase'
                };
            }
            return data;
        } catch (error) {
            console.error('Error syncing local cache to Supabase:', error);
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
