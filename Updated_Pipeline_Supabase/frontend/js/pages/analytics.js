// Analytics Page Component
const AnalyticsPage = {
    _realtimeHandler: null,
    _connectionHandler: null,
    _timezoneChangeHandler: null,
    _realtimeRefreshTimer: null,
    _fallbackInterval: null,
    _assistantIntentHandler: null,
    assistantFilterState: null,
    _overviewMode: 'risk',

    render() {
        return `
            <div class="page analytics-dashboard">
                <section class="page-command-bar analytics-command-bar">
                    <div>
                        <span class="ops-kicker"><i class="fas fa-chart-simple"></i> Safety intelligence</span>
                        <h1>Analytics</h1>
                        <p>Trends, severity mix, and timing patterns for PPE compliance decisions.</p>
                    </div>
                    <div class="command-bar-pills" aria-label="Analytics focus areas">
                        <span><i class="fas fa-triangle-exclamation"></i> Risk</span>
                        <span><i class="fas fa-clock"></i> Timing</span>
                        <span><i class="fas fa-route"></i> Trend</span>
                    </div>
                </section>

                <div id="analyticsAssistantFilterBanner" class="card mb-4" style="display: none;">
                    <div class="card-content" style="display:flex;align-items:center;justify-content:space-between;gap:0.85rem;flex-wrap:wrap;">
                        <div style="display:flex;flex-direction:column;gap:0.25rem;">
                            <span style="font-size:0.72rem;font-weight:800;letter-spacing:0.08em;text-transform:uppercase;color:#b45309;">Assistant filter active</span>
                            <strong id="analyticsAssistantFilterSummary" style="color:#0f172a;">Filtered analytics view</strong>
                            <span id="analyticsAssistantFilterHint" style="font-size:0.82rem;color:#64748b;">Mira opened this analytics slice from chat.</span>
                        </div>
                        <button id="analyticsClearAssistantFilterBtn" class="btn btn-secondary" type="button">
                            <i class="fas fa-rotate-left"></i> Clear filter
                        </button>
                    </div>
                </div>

                <div class="card mb-4">
                    <div class="card-header">
                        <span><i class="fas fa-chart-line"></i> Safety Analytics Dashboard</span>
                    </div>
                    <div class="card-content">
                        <div id="analytics-overview-control" class="analytics-overview-control">
                            <div class="spinner"></div>
                        </div>
                        <div id="analytics-stats" class="analytics-stats-grid mb-4">
                            <div class="spinner"></div>
                        </div>
                        <div id="analytics-insights" class="analytics-insights-grid">
                            <div class="spinner"></div>
                        </div>
                    </div>
                </div>

                <!-- Violation Trends -->
                <div class="card mb-4">
                    <div class="card-header">
                        <span><i class="fas fa-chart-bar"></i> Violation Trends</span>
                    </div>
                    <div class="card-content">
                        <div class="analytics-chart-shell">
                            <canvas id="trendChart"></canvas>
                        </div>
                    </div>
                </div>

                <div class="grid grid-2">
                    <!-- Violation Types Breakdown -->
                    <div class="card">
                        <div class="card-header">
                            <span><i class="fas fa-pie-chart"></i> Violation Types</span>
                        </div>
                        <div class="card-content" id="analytics-violation-types">
                            <div class="spinner"></div>
                        </div>
                    </div>

                    <!-- Time Distribution -->
                    <div class="card">
                        <div class="card-header">
                            <span><i class="fas fa-clock"></i> Time Distribution</span>
                        </div>
                        <div class="card-content" id="analytics-time-distribution">
                            <div class="spinner"></div>
                        </div>
                    </div>
                </div>

                <!-- Safety Score -->
                <div class="card mt-4">
                    <div class="card-header">
                        <span><i class="fas fa-trophy"></i> Safety Compliance Score</span>
                    </div>
                    <div class="card-content">
                        <div class="analytics-score-shell">
                            <div id="safety-score" class="analytics-score-value">
                                --
                            </div>
                            <p class="analytics-score-caption">
                                Overall Safety Compliance
                            </p>
                            <div class="analytics-score-meter">
                                <div id="safety-bar" class="analytics-score-meter-fill"></div>
                            </div>
                            <p class="analytics-score-subnote">
                                Based on violation frequency and severity
                            </p>
                            <p id="analytics-safety-benchmark-note" class="analytics-score-benchmark"></p>
                        </div>
                    </div>
                </div>
            </div>
        `;
    },

    async mount() {
        const cachedRendered = await this.renderCachedDataIfAvailable();
        if (typeof API !== 'undefined' && typeof API.warmDashboardCaches === 'function') {
            API.warmDashboardCaches({ reason: 'analytics-mount', timeoutMs: 10000, minIntervalMs: 90000 });
        }
        await this.refreshData({ skipInitialCache: cachedRendered });

        this._realtimeHandler = () => {
            if (this._realtimeRefreshTimer) return;
            this._realtimeRefreshTimer = setTimeout(async () => {
                this._realtimeRefreshTimer = null;
                await this.refreshData();
            }, 1200);
        };
        window.addEventListener('ppe-realtime:update', this._realtimeHandler);

        this._connectionHandler = () => this.syncFallbackPolling();
        window.addEventListener('ppe-realtime:connection', this._connectionHandler);

        this._timezoneChangeHandler = () => this.refreshData();
        window.addEventListener('ppe-timezone:changed', this._timezoneChangeHandler);
        this._assistantIntentHandler = (event) => this.applyAssistantIntent((event && event.detail) || {});
        window.addEventListener('casm-analytics:intent', this._assistantIntentHandler);
        this.bindAssistantBanner();
        if (window.__CASM_ANALYTICS_ASSISTANT_INTENT) {
            this.applyAssistantIntent(window.__CASM_ANALYTICS_ASSISTANT_INTENT);
            delete window.__CASM_ANALYTICS_ASSISTANT_INTENT;
        } else {
            this.renderAssistantBanner();
        }
        this.syncFallbackPolling();
    },

    unmount() {
        if (this._realtimeHandler) {
            window.removeEventListener('ppe-realtime:update', this._realtimeHandler);
            this._realtimeHandler = null;
        }
        if (this._realtimeRefreshTimer) {
            clearTimeout(this._realtimeRefreshTimer);
            this._realtimeRefreshTimer = null;
        }
        if (this._connectionHandler) {
            window.removeEventListener('ppe-realtime:connection', this._connectionHandler);
            this._connectionHandler = null;
        }
        if (this._timezoneChangeHandler) {
            window.removeEventListener('ppe-timezone:changed', this._timezoneChangeHandler);
            this._timezoneChangeHandler = null;
        }
        if (this._assistantIntentHandler) {
            window.removeEventListener('casm-analytics:intent', this._assistantIntentHandler);
            this._assistantIntentHandler = null;
        }
        if (this._fallbackInterval) {
            clearInterval(this._fallbackInterval);
            this._fallbackInterval = null;
        }
        if (window.analyticsChart) {
            window.analyticsChart.destroy();
            window.analyticsChart = null;
        }
        if (window.violationPieChart) {
            window.violationPieChart.destroy();
            window.violationPieChart = null;
        }
        if (window.timePieChart) {
            window.timePieChart.destroy();
            window.timePieChart = null;
        }
    },

    async renderCachedDataIfAvailable() {
        if (typeof API === 'undefined' || typeof API.readJsonCache !== 'function') return false;
        try {
            const [cachedStats, cachedViolations] = await Promise.all([
                API.readJsonCache('stats:summary'),
                API.readJsonCache('violations:limit:1000')
            ]);
            const violations = cachedViolations && Array.isArray(cachedViolations.data)
                ? cachedViolations.data
                : [];
            const stats = cachedStats && cachedStats.data && typeof cachedStats.data === 'object'
                ? cachedStats.data
                : (violations.length ? this.buildStatsFromViolations(violations) : null);
            if (!stats) return false;
            this.renderAnalyticsDataset(stats, violations);
            return true;
        } catch (error) {
            return false;
        }
    },

    bindAssistantBanner() {
        const clearBtn = document.getElementById('analyticsClearAssistantFilterBtn');
        if (clearBtn) {
            clearBtn.onclick = () => {
                this.assistantFilterState = null;
                this.renderAssistantBanner();
                this.refreshData();
            };
        }
    },

    applyAssistantIntent(detail = {}) {
        const filters = this.sanitizeAssistantFilters(detail && typeof detail.filters === 'object' ? detail.filters : {});
        if (!this.hasActiveAssistantFilters(filters)) {
            this.assistantFilterState = null;
            this.renderAssistantBanner();
            this.refreshData();
            return;
        }
        this.assistantFilterState = {
            filters,
            summary: String(detail.summary || 'Filtered analytics view').trim() || 'Filtered analytics view'
        };
        this.renderAssistantBanner();
        this.refreshData();
    },

    renderAssistantBanner() {
        const banner = document.getElementById('analyticsAssistantFilterBanner');
        const summary = document.getElementById('analyticsAssistantFilterSummary');
        const hint = document.getElementById('analyticsAssistantFilterHint');
        if (!banner || !summary || !hint) return;
        if (!this.assistantFilterState) {
            banner.style.display = 'none';
            return;
        }
        banner.style.display = 'block';
        summary.textContent = this.assistantFilterState.summary || 'Filtered analytics view';
        hint.textContent = 'Mira opened this analytics slice from chat. Clear filter to return to the full dashboard.';
    },

    sanitizeAssistantFilters(filters = {}) {
        const cleaned = {};
        const source = String(filters.source || '').trim().toLowerCase().replace(/-/g, '_');
        if (['cloud', 'local', 'synced_local'].includes(source)) {
            cleaned.source = source;
        }

        const severity = String(filters.severity || '').trim().toLowerCase();
        if (['high', 'medium', 'low'].includes(severity)) {
            cleaned.severity = severity;
        }

        const dateRange = String(filters.dateRange || '').trim().toLowerCase();
        if (['today', 'yesterday', 'week', 'month'].includes(dateRange)) {
            cleaned.dateRange = dateRange;
        }

        const dateExact = this.normalizeAssistantDateKey(filters.dateExact);
        const dateFrom = this.normalizeAssistantDateKey(filters.dateFrom);
        const dateTo = this.normalizeAssistantDateKey(filters.dateTo);
        if (dateExact) {
            cleaned.dateExact = dateExact;
            delete cleaned.dateRange;
        } else {
            if (dateFrom) {
                cleaned.dateFrom = dateFrom;
                delete cleaned.dateRange;
            }
            if (dateTo) {
                cleaned.dateTo = dateTo;
                delete cleaned.dateRange;
            }
        }

        const validPpe = new Set([
            'NO-Hardhat',
            'NO-Safety Vest',
            'NO-Gloves',
            'NO-Mask',
            'NO-Goggles',
            'NO-Safety Shoes'
        ]);
        const ppeTypes = Array.isArray(filters.ppeTypes) ? filters.ppeTypes : [];
        const normalizedPpe = Array.from(new Set(
            ppeTypes
                .map((label) => this.normalizePpeFilterLabel(label))
                .filter((label) => validPpe.has(label))
        ));
        if (normalizedPpe.length) {
            cleaned.ppeTypes = normalizedPpe;
        }

        return cleaned;
    },

    hasActiveAssistantFilters(filters = {}) {
        return !!(
            filters
            && typeof filters === 'object'
            && (
                filters.source
                || filters.severity
                || filters.dateRange
                || filters.dateExact
                || filters.dateFrom
                || filters.dateTo
                || (Array.isArray(filters.ppeTypes) && filters.ppeTypes.length > 0)
            )
        );
    },

    normalizeAssistantDateKey(value) {
        const raw = String(value || '').trim();
        const match = raw.match(/^(20\d{2})-(0[1-9]|1[0-2])-([0-2]\d|3[01])$/);
        if (!match) return '';
        const [, year, month, day] = match;
        const parsed = new Date(Number(year), Number(month) - 1, Number(day));
        if (
            parsed.getFullYear() !== Number(year)
            || parsed.getMonth() !== Number(month) - 1
            || parsed.getDate() !== Number(day)
        ) {
            return '';
        }
        return `${year}-${month}-${day}`;
    },

    getAssistantRowDateKey(row) {
        const rowDate = new Date(row?.timestamp || 0);
        if (Number.isNaN(rowDate.getTime())) return '';
        return `${rowDate.getFullYear()}-${String(rowDate.getMonth() + 1).padStart(2, '0')}-${String(rowDate.getDate()).padStart(2, '0')}`;
    },

    normalizePpeFilterLabel(label) {
        const normalized = String(label || '')
            .toLowerCase()
            .replace(/[^a-z0-9\s-]/g, ' ')
            .replace(/-/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
        if (/\b(no )?(hardhat|hard hat|helmet|helmets)\b/.test(normalized)) return 'NO-Hardhat';
        if (/\b(no )?(safety )?vests?\b/.test(normalized)) return 'NO-Safety Vest';
        if (/\b(no )?gloves?\b/.test(normalized)) return 'NO-Gloves';
        if (/\b(no )?(mask|masks|respirator|respirators)\b/.test(normalized)) return 'NO-Mask';
        if (/\b(no )?(goggles?|eye protection|eyewear)\b/.test(normalized)) return 'NO-Goggles';
        if (/\b(no )?(safety )?(shoe|shoes|boot|boots)\b/.test(normalized)) return 'NO-Safety Shoes';
        return String(label || '').trim();
    },

    syncFallbackPolling() {
        const connected = typeof RealtimeSync !== 'undefined' && RealtimeSync.isConnected;
        if (connected) {
            if (this._fallbackInterval) {
                clearInterval(this._fallbackInterval);
                this._fallbackInterval = null;
            }
            return;
        }

        if (!this._fallbackInterval) {
            this._fallbackInterval = setInterval(() => this.refreshData(), 12000);
        }
    },

    normalizeStats(stats = {}, violations = []) {
        const list = Array.isArray(violations) ? violations : [];
        const severity = stats.severity && typeof stats.severity === 'object'
            ? stats.severity
            : {};
        const derivedFromList = this.buildStatsFromViolations(list);
        const severityFromStats = {
            high: Number(severity.high) || 0,
            medium: Number(severity.medium) || 0,
            low: Number(severity.low) || 0
        };
        const severityHasData = (severityFromStats.high + severityFromStats.medium + severityFromStats.low) > 0;
        const breakdownFromStats = stats.breakdown && typeof stats.breakdown === 'object'
            ? stats.breakdown
            : {};
        const breakdownHasData = Object.values(breakdownFromStats).some((value) => Number(value) > 0);
        const completedFromList = list.filter((v) => {
            const status = String((v && (v.status || (v.has_report ? 'completed' : ''))) || '').toLowerCase();
            return status === 'completed' || status === 'ready';
        }).length;
        const pendingFromList = list.filter((v) => {
            const status = String((v && (v.status || (v.has_report ? 'completed' : 'pending'))) || '').toLowerCase();
            return status === 'pending' || status === 'queued' || status === 'processing' || status === 'generating';
        }).length;

        const reportsGenerated = Number(stats.reportsGenerated)
            || Number(stats.reports_generated)
            || Number(stats.totalReports)
            || Number(stats.reportsTotal)
            || Number(stats.completed)
            || completedFromList
            || 0;

        return {
            ...stats,
            total: Number(stats.total) || list.length || 0,
            today: Number(stats.today) || derivedFromList.today || 0,
            pending: Number(stats.pending) || pendingFromList || derivedFromList.pending || 0,
            completed: Number(stats.completed) || reportsGenerated || 0,
            reportsGenerated,
            severity: severityHasData ? severityFromStats : derivedFromList.severity,
            breakdown: breakdownHasData ? breakdownFromStats : derivedFromList.breakdown
        };
    },

    normalizeSourceScope(record) {
        const explicit = String(record?.source_scope || record?.report_scope || record?.scope || '').trim().toLowerCase();
        if (explicit === 'synced-local') return 'synced_local';
        if (explicit) return explicit;

        const label = String(record?.source_label || '').trim().toLowerCase();
        if (label === 'local synced') return 'synced_local';
        if (label === 'local') return 'local';
        if (label === 'shared') return 'shared';
        if (label === 'cloud') return 'cloud';
        return 'unknown';
    },

    buildStatsFromViolations(violations = []) {
        const list = Array.isArray(violations) ? violations : [];
        const severity = { high: 0, medium: 0, low: 0 };
        const breakdown = {};
        const todayFloor = new Date();
        todayFloor.setHours(0, 0, 0, 0);
        let today = 0;
        let reportsGenerated = 0;
        let pending = 0;

        list.forEach((item) => {
            const severityKey = String(item?.severity || '').trim().toLowerCase();
            if (Object.prototype.hasOwnProperty.call(severity, severityKey)) {
                severity[severityKey] += 1;
            }

            const breakdownSource = item?.breakdown && typeof item.breakdown === 'object'
                ? item.breakdown
                : null;
            if (breakdownSource) {
                Object.entries(breakdownSource).forEach(([key, value]) => {
                    breakdown[key] = (Number(breakdown[key]) || 0) + (Number(value) || 0);
                });
            } else if (Array.isArray(item?.missing_ppe)) {
                item.missing_ppe.forEach((label) => {
                    if (!label) return;
                    breakdown[label] = (Number(breakdown[label]) || 0) + 1;
                });
            }

            const status = String(item?.status || (item?.has_report ? 'completed' : 'pending')).trim().toLowerCase();
            if (status === 'completed' || status === 'ready') {
                reportsGenerated += 1;
            }
            if (status === 'pending' || status === 'queued' || status === 'processing' || status === 'generating') {
                pending += 1;
            }

            const timestamp = new Date(item?.timestamp || 0);
            if (!Number.isNaN(timestamp.getTime()) && timestamp >= todayFloor) {
                today += 1;
            }
        });

        return {
            total: list.length,
            today,
            pending,
            reportsGenerated,
            completed: reportsGenerated,
            severity,
            breakdown
        };
    },

    matchesAssistantFilters(row, filters = {}) {
        const safeFilters = this.sanitizeAssistantFilters(filters);
        if (!this.hasActiveAssistantFilters(safeFilters)) return true;
        if (safeFilters.source) {
            const scope = this.normalizeSourceScope(row);
            if (scope !== String(safeFilters.source || '').trim().toLowerCase()) return false;
        }

        if (safeFilters.severity) {
            const severity = String(row?.severity || '').trim().toLowerCase();
            if (severity !== String(safeFilters.severity || '').trim().toLowerCase()) return false;
        }

        if (safeFilters.dateRange) {
            const rowDate = new Date(row?.timestamp || 0);
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            if (safeFilters.dateRange === 'today' && rowDate < today) return false;
            if (safeFilters.dateRange === 'yesterday') {
                const yesterday = new Date(today);
                yesterday.setDate(yesterday.getDate() - 1);
                if (rowDate < yesterday || rowDate >= today) return false;
            }
            if (safeFilters.dateRange === 'week') {
                const weekAgo = new Date(today);
                weekAgo.setDate(weekAgo.getDate() - 7);
                if (rowDate < weekAgo) return false;
            }
            if (safeFilters.dateRange === 'month') {
                const monthAgo = new Date(today);
                monthAgo.setMonth(monthAgo.getMonth() - 1);
                if (rowDate < monthAgo) return false;
            }
        }

        if (safeFilters.dateExact || safeFilters.dateFrom || safeFilters.dateTo) {
            const rowDateKey = this.getAssistantRowDateKey(row);
            if (!rowDateKey) return false;
            if (safeFilters.dateExact && rowDateKey !== safeFilters.dateExact) return false;
            if (safeFilters.dateFrom && rowDateKey < safeFilters.dateFrom) return false;
            if (safeFilters.dateTo && rowDateKey > safeFilters.dateTo) return false;
        }

        if (Array.isArray(safeFilters.ppeTypes) && safeFilters.ppeTypes.length) {
            const missing = Array.isArray(row?.missing_ppe) ? row.missing_ppe : [];
            const breakdownLabels = row?.breakdown && typeof row.breakdown === 'object'
                ? Object.entries(row.breakdown)
                    .filter(([, value]) => Number(value) > 0)
                    .map(([label]) => label)
                : [];
            const normalizedLabels = new Set([...missing, ...breakdownLabels].map((label) => this.normalizePpeFilterLabel(label)));
            if (!safeFilters.ppeTypes.every((label) => normalizedLabels.has(this.normalizePpeFilterLabel(label)))) return false;
        }

        return true;
    },

    filterViolations(violations = [], filters = {}) {
        const list = Array.isArray(violations) ? violations : [];
        const safeFilters = this.sanitizeAssistantFilters(filters);
        if (!this.hasActiveAssistantFilters(safeFilters)) return list;
        return list.filter((row) => this.matchesAssistantFilters(row, safeFilters));
    },

    buildDerivedMetrics(stats = {}, violations = []) {
        const list = Array.isArray(violations) ? violations : [];
        const total = Math.max(0, Number(stats.total) || list.length || 0);
        const reportsReady = Math.max(0, Number(stats.reportsGenerated) || 0);
        const pending = Math.max(0, Number(stats.pending) || 0);
        const high = Math.max(0, Number(stats.severity?.high) || 0);
        const readyRate = total > 0 ? Math.round((reportsReady / total) * 100) : 0;
        const highShare = total > 0 ? Math.round((high / total) * 100) : 0;

        const sevenDaysAgo = Date.now() - (7 * 24 * 60 * 60 * 1000);
        const recentWeekCount = list.filter((item) => {
            const ts = Date.parse(item?.timestamp || '');
            return Number.isFinite(ts) && ts >= sevenDaysAgo;
        }).length;
        const dailyAverage = recentWeekCount > 0 ? (recentWeekCount / 7) : 0;

        const sourceMix = {
            local: 0,
            synced_local: 0,
            cloud: 0,
            shared: 0,
            unknown: 0
        };
        const timeDistribution = {
            'Morning (6AM-12PM)': 0,
            'Afternoon (12PM-6PM)': 0,
            'Evening (6PM-12AM)': 0,
            'Night (12AM-6AM)': 0
        };

        list.forEach((item) => {
            const scope = this.normalizeSourceScope(item);
            if (Object.prototype.hasOwnProperty.call(sourceMix, scope)) {
                sourceMix[scope] += 1;
            } else {
                sourceMix.unknown += 1;
            }

            const date = new Date(item?.timestamp || 0);
            const hour = date.getHours();
            if (!Number.isNaN(hour)) {
                if (hour >= 6 && hour < 12) timeDistribution['Morning (6AM-12PM)'] += 1;
                else if (hour >= 12 && hour < 18) timeDistribution['Afternoon (12PM-6PM)'] += 1;
                else if (hour >= 18 && hour < 24) timeDistribution['Evening (6PM-12AM)'] += 1;
                else timeDistribution['Night (12AM-6AM)'] += 1;
            }
        });

        const sourceEntries = Object.entries(sourceMix).sort((a, b) => Number(b[1]) - Number(a[1]));
        const dominantSourceEntry = sourceEntries.find((entry) => Number(entry[1]) > 0) || ['unknown', 0];
        const localOriginCount = sourceMix.local + sourceMix.synced_local;
        const cloudOriginCount = sourceMix.cloud + sourceMix.shared;

        const peakWindowEntry = Object.entries(timeDistribution).sort((a, b) => Number(b[1]) - Number(a[1]))[0] || ['No data', 0];
        const topTypeEntry = Object.entries(stats.breakdown || {}).sort((a, b) => Number(b[1]) - Number(a[1]))[0] || null;

        const lastViolation = list
            .map((item) => new Date(item?.timestamp || 0))
            .filter((date) => !Number.isNaN(date.getTime()))
            .sort((a, b) => b.getTime() - a.getTime())[0];

        const lastViolationDisplay = lastViolation
            ? (typeof TimezoneManager !== 'undefined' && typeof TimezoneManager.formatDateTime === 'function'
                ? TimezoneManager.formatDateTime(lastViolation.toISOString())
                : lastViolation.toLocaleString())
            : 'No data';

        return {
            total,
            reportsReady,
            pending,
            readyRate,
            highShare,
            dailyAverage,
            recentWeekCount,
            localOriginCount,
            cloudOriginCount,
            peakWindow: peakWindowEntry[0],
            peakWindowCount: Number(peakWindowEntry[1]) || 0,
            topType: topTypeEntry ? `${topTypeEntry[0]} (${topTypeEntry[1]})` : 'No violations yet',
            dominantSource: dominantSourceEntry[0],
            dominantSourceCount: Number(dominantSourceEntry[1]) || 0,
            sourceMix,
            timeDistribution,
            lastViolationDisplay
        };
    },

    renderOverviewControl(stats = {}, derivedMetrics = {}, violations = []) {
        const container = document.getElementById('analytics-overview-control');
        if (!container) return;

        const mode = ['risk', 'source', 'queue', 'timing'].includes(this._overviewMode) ? this._overviewMode : 'risk';
        const severity = stats.severity && typeof stats.severity === 'object' ? stats.severity : {};
        const high = Math.max(0, Number(severity.high) || 0);
        const medium = Math.max(0, Number(severity.medium) || 0);
        const low = Math.max(0, Number(severity.low) || 0);
        const severityTotal = Math.max(1, high + medium + low);
        const sourceMix = derivedMetrics.sourceMix || {};
        const timeDistribution = derivedMetrics.timeDistribution || {};
        const timeEntries = Object.entries(timeDistribution);
        const timeRows = timeEntries.map(([label, value]) => {
            const normalizedLabel = String(label || '').trim();
            const match = normalizedLabel.match(/^([^()]+)\s*\(([^)]+)\)$/);
            return {
                label: match ? match[1].trim() : normalizedLabel,
                range: match ? match[2].trim() : '',
                value: Number(value) || 0
            };
        });
        const timeMax = Math.max(1, ...timeEntries.map(([, value]) => Number(value) || 0));
        const sourceActualTotal = Math.max(0,
            Number(sourceMix.local || 0)
            + Number(sourceMix.synced_local || 0)
            + Number(sourceMix.cloud || 0)
            + Number(sourceMix.shared || 0)
            + Number(sourceMix.unknown || 0)
        );
        const sourceTotal = Math.max(1, sourceActualTotal);
        const rowCount = Array.isArray(violations) ? violations.length : 0;
        const riskTone = derivedMetrics.highShare >= 40 ? 'danger' : derivedMetrics.highShare >= 18 ? 'warning' : 'stable';
        const readyTone = derivedMetrics.readyRate >= 80 ? 'stable' : derivedMetrics.readyRate >= 50 ? 'warning' : 'danger';
        const safePercent = (value, total) => Math.max(0, Math.min(100, (Number(value) || 0) / Math.max(1, Number(total) || 1) * 100));
        const displayPercent = (value, total) => `${Math.round(safePercent(value, total))}%`;
        const modeModels = {
            risk: {
                kicker: 'Risk Focus',
                title: `${derivedMetrics.highShare || 0}%`,
                label: 'high-severity share',
                tone: riskTone,
                insight: high > 0
                    ? `${high} high-severity detections are in this analytics slice. Prioritize complete PPE report review.`
                    : 'No high-severity detections in this analytics slice.',
                primaryAction: 'Review reports',
                primaryRoute: 'reports'
            },
            source: {
                kicker: 'Source Mix',
                title: String(derivedMetrics.dominantSource || 'unknown').replace(/_/g, ' '),
                label: `${derivedMetrics.dominantSourceCount || 0} rows leading`,
                tone: 'source',
                insight: `Local-origin rows: ${derivedMetrics.localOriginCount || 0}. Cloud-origin rows: ${derivedMetrics.cloudOriginCount || 0}.`,
                primaryAction: 'Open reports',
                primaryRoute: 'reports'
            },
            queue: {
                kicker: 'Report Flow',
                title: `${derivedMetrics.readyRate || 0}%`,
                label: 'ready rate',
                tone: readyTone,
                insight: `${stats.reportsGenerated || 0} reports are ready and ${derivedMetrics.pending || 0} are queued or generating.`,
                primaryAction: 'Open reports',
                primaryRoute: 'reports'
            },
            timing: {
                kicker: 'Timing Pattern',
                title: derivedMetrics.peakWindow || 'No data',
                label: `${derivedMetrics.peakWindowCount || 0} rows at peak`,
                tone: 'timing',
                insight: `${derivedMetrics.recentWeekCount || 0} detections appeared in the last 7 days, averaging ${(derivedMetrics.dailyAverage || 0).toFixed(1)} per day.`,
                primaryAction: 'Open live monitor',
                primaryRoute: 'live'
            }
        };
        const model = modeModels[mode] || modeModels.risk;
        const sourceSegments = [
            { label: 'Local', value: Number(sourceMix.local || 0), className: 'local' },
            { label: 'Local Synced', value: Number(sourceMix.synced_local || 0), className: 'synced' },
            { label: 'Cloud', value: Number(sourceMix.cloud || 0), className: 'cloud' },
            { label: 'Shared', value: Number(sourceMix.shared || 0), className: 'shared' },
            { label: 'Unknown', value: Number(sourceMix.unknown || 0), className: 'unknown' }
        ];
        const totalTimeRows = timeRows.reduce((sum, item) => sum + item.value, 0);

        container.innerHTML = `
            <div class="analytics-overview-hero tone-${model.tone}">
                <div class="analytics-overview-main">
                    <div class="analytics-overview-tabs" role="tablist" aria-label="Analytics overview focus">
                        ${[
                            { key: 'risk', icon: 'fa-triangle-exclamation', label: 'Risk' },
                            { key: 'source', icon: 'fa-diagram-project', label: 'Source' },
                            { key: 'queue', icon: 'fa-file-circle-check', label: 'Queue' },
                            { key: 'timing', icon: 'fa-clock', label: 'Timing' }
                        ].map((tab) => `
                            <button class="analytics-overview-tab ${mode === tab.key ? 'active' : ''}" type="button" role="tab" aria-selected="${mode === tab.key ? 'true' : 'false'}" data-analytics-overview-mode="${tab.key}">
                                <i class="fas ${tab.icon}" aria-hidden="true"></i>
                                <span>${tab.label}</span>
                            </button>
                        `).join('')}
                    </div>

                    <div class="analytics-overview-readout">
                        <span>${model.kicker}</span>
                        <strong>${model.title}</strong>
                        <em>${model.label}</em>
                        <p>${model.insight}</p>
                    </div>

                    <div class="analytics-overview-actions">
                        <button class="btn btn-primary" type="button" data-analytics-route="${model.primaryRoute}">
                            ${model.primaryAction}
                        </button>
                        <button class="btn btn-secondary" type="button" data-analytics-export="analytics">
                            <i class="fas fa-file-csv"></i> Export CSV
                        </button>
                    </div>
                </div>

                <div class="analytics-overview-visual">
                    <div class="analytics-overview-ring" style="--score:${Math.max(0, Math.min(100, Number(derivedMetrics.readyRate || 0)))};">
                        <span>${derivedMetrics.readyRate || 0}%</span>
                        <small>Ready</small>
                    </div>

                    <div class="analytics-severity-mix" aria-label="Severity mix">
                        <div class="analytics-panel-title">
                            <span>Severity mix</span>
                            <strong>${high + medium + low} rows</strong>
                        </div>
                        <div class="analytics-severity-strip">
                            <span class="severity-high" style="width:${safePercent(high, severityTotal)}%"></span>
                            <span class="severity-medium" style="width:${safePercent(medium, severityTotal)}%"></span>
                            <span class="severity-low" style="width:${safePercent(low, severityTotal)}%"></span>
                        </div>
                        <div class="analytics-overview-legend">
                            <span><i class="legend-dot high"></i>${high} high</span>
                            <span><i class="legend-dot medium"></i>${medium} medium</span>
                            <span><i class="legend-dot low"></i>${low} low</span>
                        </div>
                    </div>

                    <div class="analytics-source-breakdown" aria-label="Source mix">
                        <div class="analytics-panel-title">
                            <span>Source mix</span>
                            <strong>${sourceActualTotal} rows</strong>
                        </div>
                        <div class="analytics-source-rows">
                        ${sourceSegments.map((item) => `
                            <div class="analytics-source-row">
                                <span class="analytics-source-label"><i class="analytics-source-swatch ${item.className}" aria-hidden="true"></i>${item.label}</span>
                                <span class="analytics-source-meter" aria-hidden="true"><i class="${item.className}" style="width:${Math.max(item.value > 0 ? 7 : 0, safePercent(item.value, sourceTotal))}%"></i></span>
                                <strong class="analytics-source-value">${item.value} <em>${displayPercent(item.value, sourceTotal)}</em></strong>
                            </div>
                        `).join('')}
                        </div>
                    </div>

                    <div class="analytics-time-bars" aria-label="Time distribution">
                        <div class="analytics-panel-title">
                            <span>Time distribution</span>
                            <strong>${totalTimeRows} rows</strong>
                        </div>
                        <div class="analytics-time-bar-grid">
                        ${timeRows.map((item) => `
                            <div class="analytics-time-bar">
                                <span style="height:${Math.max(12, Math.round((item.value / timeMax) * 58))}px"></span>
                                <strong>${item.value}</strong>
                                <em>${item.label}</em>
                                <small>${item.range}</small>
                            </div>
                        `).join('')}
                        </div>
                    </div>

                    <div class="analytics-overview-mini-grid">
                        <span><strong>${rowCount}</strong><em>Rows</em></span>
                        <span><strong>${derivedMetrics.recentWeekCount || 0}</strong><em>7 days</em></span>
                        <span><strong>${derivedMetrics.pending || 0}</strong><em>Pending</em></span>
                    </div>
                </div>
            </div>
        `;

        container.querySelectorAll('[data-analytics-overview-mode]').forEach((button) => {
            button.addEventListener('click', () => {
                this._overviewMode = String(button.dataset.analyticsOverviewMode || 'risk');
                this.renderOverviewControl(stats, derivedMetrics, violations);
            });
        });

        container.querySelectorAll('[data-analytics-route]').forEach((button) => {
            button.addEventListener('click', () => {
                const route = button.dataset.analyticsRoute || 'reports';
                if (typeof Router !== 'undefined' && Router && typeof Router.navigate === 'function') {
                    Router.navigate(route);
                }
            });
        });

        const exportBtn = container.querySelector('[data-analytics-export]');
        if (exportBtn) {
            exportBtn.addEventListener('click', async () => {
                if (window.CASMAssistant && typeof window.CASMAssistant.exportAnalyticsCsv === 'function') {
                    await window.CASMAssistant.exportAnalyticsCsv();
                }
            });
        }
    },

    renderAnalyticsDataset(stats, violations) {
        const filteredViolations = this.assistantFilterState
            ? this.filterViolations(violations, this.assistantFilterState.filters || {})
            : (Array.isArray(violations) ? violations : []);
        const baseStats = this.assistantFilterState
            ? this.buildStatsFromViolations(filteredViolations)
            : stats;
        const normalizedStats = this.normalizeStats(baseStats, filteredViolations);
        const derivedMetrics = this.buildDerivedMetrics(normalizedStats, filteredViolations);

        this.renderAssistantBanner();
        this.renderOverviewControl(normalizedStats, derivedMetrics, filteredViolations);
        this.renderStats(normalizedStats, derivedMetrics);
        this.renderInsights(derivedMetrics);
        this.renderTrendsChart(filteredViolations);
        this.renderViolationTypes(normalizedStats);
        this.renderTimeDistribution(filteredViolations);
        this.calculateSafetyScore(normalizedStats);
    },

    async refreshData(options = {}) {
        try {
            if (!options.skipInitialCache) {
                await this.renderCachedDataIfAvailable();
            }
            const [stats, violations] = await Promise.all([
                API.getStats(),
                API.getViolations()
            ]);
            this.renderAnalyticsDataset(stats, violations);
        } catch (e) {
            console.error('Error loading analytics:', e);
            const statsEl = document.getElementById('analytics-stats');
            if (statsEl) {
                statsEl.innerHTML = '<div class="alert alert-danger">Failed to load analytics data.</div>';
            }
        }
    },

    renderStats(stats, derivedMetrics) {
        const container = document.getElementById('analytics-stats');
        if (!container) return;
        const cards = [
            {
                kicker: 'Volume',
                value: stats.total,
                label: 'Total Violations',
                note: `${stats.today || 0} logged today`,
                tone: 'is-neutral'
            },
            {
                kicker: 'Output',
                value: stats.reportsGenerated,
                label: 'Reports Ready',
                note: `${derivedMetrics.pending} still queued or generating`,
                tone: 'is-good'
            },
            {
                kicker: 'Flow',
                value: `${derivedMetrics.readyRate}%`,
                label: 'Ready Rate',
                note: 'Share of report rows already openable',
                tone: derivedMetrics.readyRate >= 80 ? 'is-good' : 'is-warning'
            },
            {
                kicker: 'Risk',
                value: `${derivedMetrics.highShare}%`,
                label: 'High Severity Share',
                note: `${stats.severity.high} high-severity detections`,
                tone: derivedMetrics.highShare >= 40 ? 'is-danger' : 'is-warning'
            },
            {
                kicker: 'Local',
                value: derivedMetrics.localOriginCount,
                label: 'Local-Origin Runs',
                note: `${derivedMetrics.sourceMix.synced_local} synced back to cloud`,
                tone: 'is-neutral'
            },
            {
                kicker: 'Cloud',
                value: derivedMetrics.cloudOriginCount,
                label: 'Cloud-Origin Runs',
                note: `${derivedMetrics.sourceMix.shared} shared records included`,
                tone: 'is-neutral'
            },
            {
                kicker: 'Cadence',
                value: derivedMetrics.dailyAverage.toFixed(1),
                label: '7-Day Daily Avg',
                note: `${derivedMetrics.recentWeekCount} violations over the last week`,
                tone: 'is-neutral'
            },
            {
                kicker: 'Queue',
                value: stats.pending || 0,
                label: 'Pending Reports',
                note: 'Queued, pending, or generating right now',
                tone: (stats.pending || 0) > 0 ? 'is-warning' : 'is-good'
            }
        ];

        container.innerHTML = cards.map((card) => `
            <article class="analytics-metric-card ${card.tone}">
                <span class="metric-kicker">${card.kicker}</span>
                <h3>${card.value}</h3>
                <p>${card.label}</p>
                <span class="metric-note">${card.note}</span>
            </article>
        `).join('');
    },

    renderInsights(derivedMetrics) {
        const container = document.getElementById('analytics-insights');
        if (!container) return;

        container.innerHTML = `
            <div class="analytics-insight-card">
                <div class="label">Top Violation Type</div>
                <div class="value">${derivedMetrics.topType}</div>
            </div>
            <div class="analytics-insight-card">
                <div class="label">Peak Monitoring Window</div>
                <div class="value">${derivedMetrics.peakWindow} (${derivedMetrics.peakWindowCount})</div>
            </div>
            <div class="analytics-insight-card">
                <div class="label">Last Violation Seen</div>
                <div class="value">${derivedMetrics.lastViolationDisplay}</div>
            </div>
            <div class="analytics-insight-card">
                <div class="label">Dominant Source Mix</div>
                <div class="value">${String(derivedMetrics.dominantSource || 'unknown').replace(/_/g, ' ')} (${derivedMetrics.dominantSourceCount})</div>
            </div>
        `;
    },

    renderTrendsChart(violations) {
        const canvas = document.getElementById('trendChart');
        if (!canvas) return;

        if (typeof Chart === 'undefined') {
            canvas.parentElement.innerHTML = '<div class="alert alert-warning">Trend chart is unavailable because Chart.js failed to load.</div>';
            return;
        }

        const ctx = canvas.getContext('2d');

        // Destroy existing chart if any
        if (window.analyticsChart) {
            window.analyticsChart.destroy();
        }

        // Build 7-day trend from violations
        const today = new Date();
        const dayBuckets = new Map();
        for (let i = 6; i >= 0; i -= 1) {
            const d = new Date(today);
            d.setHours(0, 0, 0, 0);
            d.setDate(d.getDate() - i);
            const key = d.toISOString().slice(0, 10);
            dayBuckets.set(key, 0);
        }

        (violations || []).forEach((v) => {
            if (!v?.timestamp) return;
            const ts = new Date(v.timestamp);
            if (Number.isNaN(ts.getTime())) return;
            ts.setHours(0, 0, 0, 0);
            const key = ts.toISOString().slice(0, 10);
            if (dayBuckets.has(key)) {
                dayBuckets.set(key, dayBuckets.get(key) + 1);
            }
        });

        const isoDates = Array.from(dayBuckets.keys());
        const labels = isoDates.map((isoDate) => {
            const date = new Date(`${isoDate}T00:00:00`);
            return `${date.getDate()}/${date.getMonth() + 1}`;
        });
        const counts = Array.from(dayBuckets.values());

        window.analyticsChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Daily Violations',
                    data: counts,
                    borderColor: '#3498db',
                    backgroundColor: 'rgba(52, 152, 219, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 4,
                    pointHoverRadius: 7,
                    pointHitRadius: 18
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        enabled: true,
                        mode: 'nearest',
                        intersect: false,
                        callbacks: {
                            title(context) {
                                if (!context || context.length === 0) return '';
                                const idx = context[0].dataIndex;
                                const isoDate = isoDates[idx];
                                if (!isoDate) return '';
                                const date = new Date(`${isoDate}T00:00:00`);
                                return date.toLocaleDateString(undefined, {
                                    year: 'numeric',
                                    month: 'short',
                                    day: 'numeric'
                                });
                            },
                            label(context) {
                                const value = Number(context.raw || 0);
                                return `Violations: ${value}`;
                            }
                        }
                    }
                },
                interaction: {
                    mode: 'nearest',
                    intersect: false
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            precision: 0
                        }
                    }
                }
            }
        });
    },

    renderViolationTypes(stats) {
        const container = document.getElementById('analytics-violation-types');
        if (!container) return;
        const breakdown = stats.breakdown || {};
        const types = [
            { name: 'Missing Hardhat', count: breakdown['NO-Hardhat'] || 0, color: 'var(--error-color)' },
            { name: 'Missing Safety Vest', count: breakdown['NO-Safety Vest'] || 0, color: 'var(--warning-color)' },
            { name: 'Missing Gloves', count: breakdown['NO-Gloves'] || 0, color: 'var(--info-color)' },
            { name: 'Missing Mask', count: breakdown['NO-Mask'] || 0, color: '#9b59b6' },
            { name: 'Missing Goggles', count: breakdown['NO-Goggles'] || 0, color: '#e67e22' },
            { name: 'Missing Safety Shoes', count: breakdown['NO-Safety Shoes'] || 0, color: '#16a085' }
        ];

        const total = types.reduce((sum, type) => sum + type.count, 0);

        container.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.6rem;">
                <div style="font-weight:600;">Breakdown</div>
                <div style="display:flex;gap:0.5rem">
                    <button id="violationToggleBtn" class="btn btn-secondary" type="button">Show Pie</button>
                </div>
            </div>

            <div id="analytics-violation-types-original">
                <div style="display: flex; flex-direction: column; gap: 1rem;">
                    ${types.map(type => `
                        <div>
                            <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                                <span style="font-weight: 500;">${type.name}</span>
                                <span style="font-weight: 600; color: ${type.color};">${type.count}</span>
                            </div>
                            <div style="height: 8px; background: var(--background-color); border-radius: 4px; overflow: hidden;">
                                <div style="height: 100%; background: ${type.color}; width: ${total > 0 ? (type.count / total * 100) : 0}%; transition: width 0.5s ease;"></div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>

            <div id="analytics-violation-types-pie" style="display:none;text-align:center;">
                <canvas id="violationTypesPie" style="max-height:220px;"></canvas>
            </div>
        `;

        const toggleBtn = document.getElementById('violationToggleBtn');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                const orig = document.getElementById('analytics-violation-types-original');
                const pie = document.getElementById('analytics-violation-types-pie');
                const showingPie = pie && pie.style.display !== 'none';
                if (showingPie) {
                    if (pie) pie.style.display = 'none';
                    if (orig) orig.style.display = 'block';
                    toggleBtn.textContent = 'Show Pie';
                    if (window.violationPieChart) { window.violationPieChart.destroy(); window.violationPieChart = null; }
                } else {
                    if (orig) orig.style.display = 'none';
                    if (pie) pie.style.display = 'block';
                    toggleBtn.textContent = 'Show Bars';
                    this.initViolationPieChart(types);
                }
            });
        }
    },

    initViolationPieChart(types) {
        const canvas = document.getElementById('violationTypesPie');
        if (!canvas || typeof Chart === 'undefined') return;
        const ctx = canvas.getContext('2d');
        if (window.violationPieChart) { window.violationPieChart.destroy(); window.violationPieChart = null; }
        window.violationPieChart = new Chart(ctx, {
            type: 'pie',
            data: {
                labels: types.map(t => t.name),
                datasets: [{
                    data: types.map(t => t.count),
                    backgroundColor: types.map(t => t.color)
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'right' } }
            }
        });
    },

    renderTimeDistribution(violations) {
        const container = document.getElementById('analytics-time-distribution');
        if (!container) return;

        // Calculate time distribution
        const distribution = {
            'Morning (6AM-12PM)': 0,
            'Afternoon (12PM-6PM)': 0,
            'Evening (6PM-12AM)': 0,
            'Night (12AM-6AM)': 0
        };

        (violations || []).forEach(v => {
            if (!v?.timestamp) return;
            const hour = new Date(v.timestamp).getHours();
            if (Number.isNaN(hour)) return;
            if (hour >= 6 && hour < 12) distribution['Morning (6AM-12PM)']++;
            else if (hour >= 12 && hour < 18) distribution['Afternoon (12PM-6PM)']++;
            else if (hour >= 18 && hour < 24) distribution['Evening (6PM-12AM)']++;
            else distribution['Night (12AM-6AM)']++;
        });

        const maxCount = Math.max(...Object.values(distribution), 1);

        // Prepare ordered distribution for chart
        const entries = Object.entries(distribution);

        container.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.6rem;">
                <div style="font-weight:600;">Time Distribution</div>
                <div style="display:flex;gap:0.5rem">
                    <button id="timeToggleBtn" class="btn btn-secondary" type="button">Show Pie</button>
                </div>
            </div>

            <div id="analytics-time-distribution-original">
                <div style="display: flex; flex-direction: column; gap: 1rem;">
                    ${entries.map(([period, count]) => `
                        <div>
                            <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                                <span style="font-weight: 500;">${period}</span>
                                <span style="font-weight: 600;">${count}</span>
                            </div>
                            <div style="height: 8px; background: var(--background-color); border-radius: 4px; overflow: hidden;">
                                <div style="height: 100%; background: var(--secondary-color); width: ${(count / maxCount * 100)}%; transition: width 0.5s ease;"></div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>

            <div id="analytics-time-distribution-pie" style="display:none;text-align:center;">
                <canvas id="timeDistributionPie" style="max-height:220px;"></canvas>
            </div>
        `;

        const toggleBtn = document.getElementById('timeToggleBtn');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                const orig = document.getElementById('analytics-time-distribution-original');
                const pie = document.getElementById('analytics-time-distribution-pie');
                const showingPie = pie && pie.style.display !== 'none';
                if (showingPie) {
                    if (pie) pie.style.display = 'none';
                    if (orig) orig.style.display = 'block';
                    toggleBtn.textContent = 'Show Pie';
                    if (window.timePieChart) { window.timePieChart.destroy(); window.timePieChart = null; }
                } else {
                    if (orig) orig.style.display = 'none';
                    if (pie) pie.style.display = 'block';
                    toggleBtn.textContent = 'Show Bars';
                    this.initTimePieChart(entries);
                }
            });
        }
    },

    initTimePieChart(entries) {
        const canvas = document.getElementById('timeDistributionPie');
        if (!canvas || typeof Chart === 'undefined') return;
        const ctx = canvas.getContext('2d');
        if (window.timePieChart) { window.timePieChart.destroy(); window.timePieChart = null; }
        window.timePieChart = new Chart(ctx, {
            type: 'pie',
            data: {
                labels: entries.map(e => e[0]),
                datasets: [{ data: entries.map(e => e[1]), backgroundColor: ['#3498db','#f1c40f','#9b59b6','#95a5a6'] }]
            },
            options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right' } } }
        });
    },

    calculateSafetyScore(stats) {
        const safety = API.computeSafetyCompliance(stats || {});
        const score = safety.score;

        const scoreElement = document.getElementById('safety-score');
        const barElement = document.getElementById('safety-bar');
        const benchmarkEl = document.getElementById('analytics-safety-benchmark-note');

        if (!scoreElement || !barElement) return;

        scoreElement.textContent = `${score}%`;
        barElement.style.width = `${score}%`;
        if (benchmarkEl) {
            benchmarkEl.textContent = safety.benchmarkNote;
        }

        // Change color based on score
        if (score >= 80) {
            scoreElement.style.color = 'var(--success-color)';
            barElement.style.background = 'linear-gradient(90deg, var(--success-color), #27ae60)';
        } else if (score >= 60) {
            scoreElement.style.color = 'var(--warning-color)';
            barElement.style.background = 'linear-gradient(90deg, var(--warning-color), #e67e22)';
        } else {
            scoreElement.style.color = 'var(--error-color)';
            barElement.style.background = 'linear-gradient(90deg, var(--error-color), #c0392b)';
        }
    }
};
