// Reports Page Component
const ReportsPage = {
    violations: [],
    providerRuntimeInterval: null,
    realtimeHandler: null,
    realtimeConnectionHandler: null,
    dashboardWarmupHandler: null,
    runtimeTransitionHandler: null,
    localSyncHandler: null,
    reportStatusHandler: null,
    timezoneChangeHandler: null,
    realtimeRefreshTimer: null,
    pendingFocusRequest: null,
    pendingFocusRetryTimer: null,
    filters: {
        search: '',
        severity: 'all',
        dateRange: 'all',
        source: 'all'
    },
    refreshInterval: null,
    autoRefreshTick: 0,
    inFlightStatusPollRunning: false,
    prefetchState: {
        completed: new Set(),
        inFlight: new Set()
    },
    visualStatusTimers: new Map(),
    cacheWarmTimer: null,
    hasLoadedOnce: false,
    modalRuntime: {
        reportId: null,
        pollTimer: null,
        cooldownTimer: null,
        retryCount: 0,
        quotaPromptedForReport: null,
        lastPollStatus: null,
        cooldownUntil: 0,
        pollStartedAt: 0,
        maxRetries: 5,
        cooldownSeconds: 8,
        pollIntervalMs: 2500,
        maxWaitMs: 420000,
        expectedDurationSec: 180,
        minGeneratingDisplayMs: 1800,
        sawGeneratingStage: false
    },

    render() {
        return `
            <div class="page reports-page">
                <section class="page-command-bar reports-command-bar">
                    <div>
                        <span class="ops-kicker"><i class="fas fa-clipboard-list"></i> Incident records</span>
                        <h1>Violation Reports</h1>
                        <p>Search, filter, generate, and open PPE compliance reports from cloud or local mode.</p>
                    </div>
                    <button class="btn btn-primary" onclick="ReportsPage.refreshReports()">
                        <i class="fas fa-sync"></i> Refresh
                    </button>
                </section>

                <div class="card mb-4">
                    <div class="card-header">
                        <div style="display: flex; align-items: center; gap: 0.65rem; flex-wrap: wrap;">
                            <span><i class="fas fa-file-alt"></i> Violation Reports</span>
                            <span id="reportsProviderBadge" class="reports-provider-badge">Provider: loading...</span>
                        </div>
                        <button class="btn btn-primary reports-header-refresh" onclick="ReportsPage.refreshReports()" style="padding: 0.5rem 1rem;">
                            <i class="fas fa-sync"></i> Refresh
                        </button>
                        <button class="btn btn-secondary reports-header-export" onclick="ReportsPage.exportFilteredCsv()" style="padding: 0.5rem 1rem; margin-left: 0.5rem;" title="Export currently filtered reports as CSV">
                            <i class="fas fa-file-csv"></i> Export CSV
                        </button>
                    </div>
                    <div class="card-content">
                        <!-- Filters -->
                        <div class="grid grid-4 mb-3 report-filter-grid">
                            <input
                                type="text"
                                id="search-reports"
                                placeholder="Search reports..."
                                style="padding: 0.75rem; border: 1px solid var(--border-color); border-radius: var(--radius-md);"
                                onkeyup="ReportsPage.handleSearch(event)"
                            >
                            <select
                                id="filter-severity"
                                style="padding: 0.75rem; border: 1px solid var(--border-color); border-radius: var(--radius-md);"
                                onchange="ReportsPage.handleFilter()"
                            >
                                <option value="all">All Severities</option>
                                <option value="high">High Severity</option>
                                <option value="medium">Medium Severity</option>
                                <option value="low">Low Severity</option>
                            </select>
                            <select
                                id="filter-date"
                                style="padding: 0.75rem; border: 1px solid var(--border-color); border-radius: var(--radius-md);"
                                onchange="ReportsPage.handleFilter()"
                            >
                                <option value="all">All Time</option>
                                <option value="today">Today</option>
                                <option value="week">This Week</option>
                                <option value="month">This Month</option>
                            </select>
                            <select
                                id="filter-source"
                                style="padding: 0.75rem; border: 1px solid var(--border-color); border-radius: var(--radius-md);"
                                onchange="ReportsPage.handleFilter()"
                            >
                                <option value="all">All Sources</option>
                                <option value="cloud">Cloud</option>
                                <option value="local">Local</option>
                                <option value="synced_local">Local Synced</option>
                                <option value="shared">Shared</option>
                            </select>
                        </div>

                        <!-- Reports List -->
                        <div id="reports-list">
                            ${this.renderReportsListMarkup()}
                        </div>
                    </div>
                </div>
            </div>
        `;
    },

    async mount() {
        if (this.timezoneChangeHandler) {
            window.removeEventListener('ppe-timezone:changed', this.timezoneChangeHandler);
        }
        this.timezoneChangeHandler = () => this.renderReports();
        window.addEventListener('ppe-timezone:changed', this.timezoneChangeHandler);

        await this.loadReports({ noCache: false });
        if (typeof API !== 'undefined' && typeof API.warmDashboardCaches === 'function') {
            API.warmDashboardCaches({ reason: 'reports-mount', timeoutMs: 10000, minIntervalMs: 90000 });
        }
        await this.updateProviderRuntimeBadge();
        this.providerRuntimeInterval = setInterval(() => this.updateProviderRuntimeBadge(), 15000);
        this.syncFallbackPolling();

        this.realtimeHandler = (event) => {
            if (this.realtimeRefreshTimer) return;
            this.realtimeRefreshTimer = setTimeout(async () => {
                this.realtimeRefreshTimer = null;
                this.applyRealtimePayload((event && event.detail) || {});
            }, 700);
        };
        window.addEventListener('ppe-realtime:update', this.realtimeHandler);

        this.realtimeConnectionHandler = () => this.syncFallbackPolling();
        window.addEventListener('ppe-realtime:connection', this.realtimeConnectionHandler);

        this.dashboardWarmupHandler = (event) => {
            const detail = (event && event.detail) || {};
            if (detail.violations || detail.pending) {
                this.loadReports({ noCache: false }).catch(() => {});
            }
        };
        window.addEventListener('ppe-dashboard:warmup', this.dashboardWarmupHandler);

        this.runtimeTransitionHandler = () => {
            this.loadReports({ noCache: false }).catch(() => {});
        };
        window.addEventListener('ppe-runtime:cloud-transition-cleared', this.runtimeTransitionHandler);

        this.localSyncHandler = (event) => this.applyLocalSyncUpdate((event && event.detail) || {});
        window.addEventListener('ppe-local-report-sync:update', this.localSyncHandler);

        this.reportQueueHandler = (event) => this.applyReportQueueUpdate((event && event.detail) || {});
        window.addEventListener('ppe-report-queue:update', this.reportQueueHandler);

        this.reportStatusHandler = (event) => this.applyReportStatusUpdate((event && event.detail) || {});
        window.addEventListener('ppe-report-status:update', this.reportStatusHandler);
    },

    unmount() {
        this.stopAutoRefresh();
        this.stopModalPolling();
        this.stopModalCooldown();
        this.pendingFocusRequest = null;
        if (this.pendingFocusRetryTimer) {
            clearTimeout(this.pendingFocusRetryTimer);
            this.pendingFocusRetryTimer = null;
        }
        if (this.cacheWarmTimer) {
            clearTimeout(this.cacheWarmTimer);
            this.cacheWarmTimer = null;
        }
        if (this.visualStatusTimers && typeof this.visualStatusTimers.forEach === 'function') {
            this.visualStatusTimers.forEach((timer) => clearTimeout(timer));
            this.visualStatusTimers.clear();
        }
        if (this.providerRuntimeInterval) {
            clearInterval(this.providerRuntimeInterval);
            this.providerRuntimeInterval = null;
        }
        if (this.realtimeHandler) {
            window.removeEventListener('ppe-realtime:update', this.realtimeHandler);
            this.realtimeHandler = null;
        }
        if (this.realtimeRefreshTimer) {
            clearTimeout(this.realtimeRefreshTimer);
            this.realtimeRefreshTimer = null;
        }
        if (this.realtimeConnectionHandler) {
            window.removeEventListener('ppe-realtime:connection', this.realtimeConnectionHandler);
            this.realtimeConnectionHandler = null;
        }
        if (this.dashboardWarmupHandler) {
            window.removeEventListener('ppe-dashboard:warmup', this.dashboardWarmupHandler);
            this.dashboardWarmupHandler = null;
        }
        if (this.runtimeTransitionHandler) {
            window.removeEventListener('ppe-runtime:cloud-transition-cleared', this.runtimeTransitionHandler);
            this.runtimeTransitionHandler = null;
        }
        if (this.localSyncHandler) {
            window.removeEventListener('ppe-local-report-sync:update', this.localSyncHandler);
            this.localSyncHandler = null;
        }
        if (this.reportQueueHandler) {
            window.removeEventListener('ppe-report-queue:update', this.reportQueueHandler);
            this.reportQueueHandler = null;
        }
        if (this.reportStatusHandler) {
            window.removeEventListener('ppe-report-status:update', this.reportStatusHandler);
            this.reportStatusHandler = null;
        }
        if (this.timezoneChangeHandler) {
            window.removeEventListener('ppe-timezone:changed', this.timezoneChangeHandler);
            this.timezoneChangeHandler = null;
        }
    },

    syncFallbackPolling() {
        // Keep a low-frequency reconciliation poll even when realtime is connected.
        // This heals rare drift where notifications update but list state lags.
        this.startAutoRefresh();
    },

    startAutoRefresh() {
        if (this.refreshInterval) return;

        // Egress guard:
        //  - Reconcile only when there are pending/generating reports (real work).
        //  - In-flight reports use tiny per-report status reads so a missed
        //    realtime push cannot leave the card stuck behind stale list cache.
        //  - Periodic reconcile only runs when Realtime is NOT connected, every
        //    ~120s, to heal rare drift on pure-polling clients.
        this.refreshInterval = setInterval(async () => {
            this.autoRefreshTick += 1;
            const hasPending = this.violations.some((v) => {
                const status = this.normalizeStatus(v);
                return status === 'pending' || status === 'queued' || status === 'processing' || status === 'generating';
            });
            const realtimeConnected = typeof RealtimeSync !== 'undefined' && !!RealtimeSync.isConnected;
            const periodicReconcile = !realtimeConnected && (this.autoRefreshTick % 12) === 0;
            const monitorWatchingInFlight = typeof ViolationMonitor !== 'undefined'
                && ViolationMonitor.isMonitoring
                && typeof ViolationMonitor.hasTrackedInFlightReports === 'function'
                && ViolationMonitor.hasTrackedInFlightReports();
            if (hasPending) {
                if (!monitorWatchingInFlight && (this.autoRefreshTick % 2) === 0) {
                    await this.pollInFlightReportStatuses();
                }
            } else if (periodicReconcile) {
                await this.loadReports({ noCache: false });
            }
        }, 10000);
    },

    stopAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
        this.autoRefreshTick = 0;
    },

    async loadReports(options = {}) {
        const noCache = !!options.noCache;
        const targetedReportId = String(options.targetedReportId || '').trim();
        const previousById = new Map(
            this.violations
                .map((item) => [String((item && item.report_id) || '').trim(), item])
                .filter(([reportId]) => !!reportId)
        );

        const [violations, pendingReports] = await Promise.all([
            API.getViolations({ noCache }),
            API.getPendingReports({ noCache })
        ]);

        this.violations = this.mergePendingReports(violations, pendingReports)
            .map((item) => this.reconcileReportRuntimeContinuity(
                item,
                previousById.get(String((item && item.report_id) || '').trim())
            ));
        this.hasLoadedOnce = true;
        if (targetedReportId) {
            await this.hydrateFocusedReport(targetedReportId, { noCache: true });
        }
        this.renderReports();
        this.scheduleReportPrefetch({ reason: noCache ? 'fresh-load' : 'cached-load' });
        this.applyPendingFocusRequest();
    },

    applyRealtimePayload(payload = {}) {
        const reports = Array.isArray(payload && payload.reports) ? payload.reports : [];
        if (reports.length) {
            this.applyReportQueueUpdate({ reports, realtime: true });
        }

        const progress = payload && typeof payload === 'object' ? (payload.progress || {}) : {};
        const reportId = String((progress && progress.current) || '').trim();
        const progressStatus = this.normalizeStatusValue(progress && progress.status, false);
        if (!reportId || !progressStatus || progressStatus === 'idle' || progressStatus === 'unknown') {
            return;
        }

        const hasReport = progressStatus === 'completed';
        this.applyReportStatusUpdate({
            report_id: reportId,
            status: progressStatus,
            has_report: hasReport,
            active_step: progress.current_step || '',
            active_status: progress.status || '',
            updated_at: progress.updated_at || new Date().toISOString(),
            source_scope: 'cloud',
            source_label: 'Cloud',
        });
    },

    async pollInFlightReportStatuses() {
        if (this.inFlightStatusPollRunning) return false;
        if (typeof API === 'undefined' || typeof API.getReportStatus !== 'function') return false;

        const candidates = this.violations
            .filter((violation) => {
                const status = this.normalizeStatus(violation);
                return status === 'pending' || status === 'queued' || status === 'processing' || status === 'generating';
            })
            .slice(0, 3);
        if (!candidates.length) return false;

        this.inFlightStatusPollRunning = true;
        let changed = false;
        try {
            await Promise.allSettled(candidates.map(async (violation) => {
                const reportId = String((violation && violation.report_id) || '').trim();
                if (!reportId) return;

                const data = await API.getReportStatus(reportId, {
                    source: violation,
                    noCache: true,
                    timeoutMs: 6000
                });
                if (!data || typeof data !== 'object') return;

                const currentStatus = this.normalizeStatus(violation);
                const wasReady = this.isReportReady(violation);
                const nextHasReport = this.hasReadableReportEvidence(data) || this.hasReadableReportEvidence(violation);
                const nextStatus = this.normalizeStatusValue(data.status, nextHasReport);
                const statusChanged = nextStatus && nextStatus !== currentStatus;
                const reportReadyChanged = nextHasReport !== this.hasReadableReportEvidence(violation);
                if (!statusChanged && !reportReadyChanged) return;

                const updated = this.upsertReportRuntimeState(reportId, {
                    ...data,
                    status: nextStatus || currentStatus,
                    has_report: nextHasReport,
                    source_scope: data.source_scope || violation.source_scope || '',
                    source_label: data.source_label || violation.source_label || ''
                }, violation);
                changed = true;

                if (updated && this.isReportReady(updated)) {
                    this.prefetchReport(reportId, updated).catch(() => {});
                    if (!wasReady) {
                        this.notifyReportReady(reportId, updated);
                    }
                }
            }));
        } finally {
            this.inFlightStatusPollRunning = false;
        }
        return changed;
    },

    applyReportStatusUpdate(detail = {}) {
        const reportId = String((detail && detail.report_id) || '').trim();
        if (!reportId) return;

        const existing = this.violations.find((v) => String((v && v.report_id) || '').trim() === reportId) || null;
        const wasReady = existing ? this.isReportReady(existing) : false;
        const hasReport = this.hasReadableReportEvidence(detail) || this.hasReadableReportEvidence(existing);
        const status = this.normalizeStatusValue(detail.status || (existing && existing.status), hasReport);
        const sourceScope = this.inferSourceScope(detail) || (existing && existing.source_scope) || 'cloud';
        const updated = this.upsertReportRuntimeState(reportId, {
            ...detail,
            status,
            has_report: hasReport,
            source_scope: sourceScope,
            source_label: String(detail.source_label || '').trim() || this.sourceLabelForScope(sourceScope)
        }, existing || detail);

        if (updated && this.isReportReady(updated)) {
            this.prefetchReport(reportId, updated).catch(() => {});
            if (!wasReady) {
                this.notifyReportReady(reportId, updated);
            }
        }
    },

    applyReportQueueUpdate(detail = {}) {
        const rows = [];
        if (detail && detail.report && typeof detail.report === 'object') {
            rows.push(detail.report);
        }
        if (detail && Array.isArray(detail.reports)) {
            detail.reports.forEach((report) => {
                if (report && typeof report === 'object') rows.push(report);
            });
        }
        if (!rows.length && detail && detail.report_id) {
            rows.push(detail);
        }

        const seen = new Set();
        rows.forEach((row) => {
            const reportId = String((row && row.report_id) || '').trim();
            if (!reportId || seen.has(reportId)) return;
            seen.add(reportId);
            const sourceScope = this.inferSourceScope(row) || 'cloud';
            const rowHasReport = this.hasReadableReportEvidence(row);
            this.upsertReportRuntimeState(reportId, {
                ...row,
                status: this.normalizeStatusValue(row.status || 'pending', rowHasReport),
                has_report: rowHasReport,
                source_scope: sourceScope,
                source_label: String(row.source_label || '').trim() || this.sourceLabelForScope(sourceScope)
            }, row);
        });

        if (!seen.size && detail && detail.success) {
            setTimeout(() => this.loadReports({ noCache: false }), 700);
        }
    },

    applyLocalSyncUpdate(detail = {}) {
        const queuedReportIds = Array.from(new Set(
            (Array.isArray(detail.queued_report_ids) ? detail.queued_report_ids : [])
                .map((id) => String(id || '').trim())
                .filter(Boolean)
        ));
        if (queuedReportIds.length) {
            const queuedSet = new Set(queuedReportIds);
            let queuedChanged = false;
            this.violations = this.violations.map((violation) => {
                const reportId = String((violation && violation.report_id) || '').trim();
                if (!queuedSet.has(reportId)) return violation;
                const sourceScope = this.inferSourceScope(violation);
                if (sourceScope === 'cloud' || sourceScope === 'synced_local' || !this.hasLocalOriginEvidence(violation)) {
                    return violation;
                }
                queuedChanged = true;
                return {
                    ...violation,
                    source_scope: 'local',
                    source_label: 'Local',
                    sync_source: detail.sync_source || violation.sync_source || 'sync_local_cache',
                    source: detail.source || violation.source || 'sync_local_cache',
                    sync_state: detail.sync_state || violation.sync_state || 'cloud_sync_queued',
                    updated_at: new Date().toISOString()
                };
            });
            if (queuedChanged) {
                this.renderReports();
            }
        }

        const reportIds = Array.from(new Set([
            ...(Array.isArray(detail.synced_report_ids) ? detail.synced_report_ids : []),
            ...(Array.isArray(detail.completed_report_ids) ? detail.completed_report_ids : []),
            ...(detail.completed === true && detail.report_id ? [detail.report_id] : [])
        ].map((id) => String(id || '').trim()).filter(Boolean)));

        if (!reportIds.length) {
            if (detail && detail.success) {
                setTimeout(() => this.loadReports({ noCache: false }), 1200);
            }
            return;
        }

        const idSet = new Set(reportIds);
        const detailSyncState = String(detail.sync_state || '').trim();
        const completedSyncState = detailSyncState && !/queued|pending|retry/i.test(detailSyncState)
            ? detailSyncState
            : 'cloud_completed';
        let changed = false;
        let changedCount = 0;
        const changedReportIds = [];
        this.violations = this.violations.map((violation) => {
            const reportId = String((violation && violation.report_id) || '').trim();
            if (!idSet.has(reportId)) return violation;
            const sourceScope = this.inferSourceScope(violation);
            const cloudAnchored = sourceScope === 'cloud'
                || this.sourceLabelMatchesScope(violation && violation.source_label, 'cloud');
            if (cloudAnchored || !this.hasLocalOriginEvidence(violation)) {
                return violation;
            }
            changed = true;
            changedCount += 1;
            changedReportIds.push(reportId);
            return {
                ...violation,
                status: this.normalizeStatusValue(violation.status, true),
                has_report: true,
                has_cloud_report_artifact: true,
                has_cloud_artifacts: true,
                source_scope: 'synced_local',
                source_label: 'Local Synced',
                origin: 'local_synced',
                sync_source: detail.sync_source || violation.sync_source || 'sync_local_cache',
                source: detail.source || violation.source || 'sync_local_cache',
                sync_state: completedSyncState,
                display_status: '',
                display_status_until: 0,
                updated_at: new Date().toISOString()
            };
        });

        const toastReportIds = changedReportIds.length
            ? changedReportIds
            : reportIds.filter((reportId) => {
                const violation = this.violations.find((item) => String((item && item.report_id) || '').trim() === reportId);
                return violation
                    && this.inferSourceScope(violation) === 'synced_local'
                    && this.hasSyncedLocalEvidence(violation);
            });

        if (changed) {
            this.renderReports();
        }
        if (toastReportIds.length) {
            this.notify(`${toastReportIds.length} local report${toastReportIds.length === 1 ? '' : 's'} synced to cloud storage.`, 'success', {
                dedupeKey: `local-sync-${toastReportIds.join('-')}`,
                dedupeTtlMs: 12000
            });
        }

        changedReportIds.slice(0, 8).forEach((reportId, index) => {
            const warmCache = async (attempt = 1) => {
                if (typeof API !== 'undefined' && typeof API.cacheReportHtml === 'function') {
                    const cached = await API.cacheReportHtml(reportId, {
                        source_scope: 'synced_local',
                        origin: 'local_synced',
                        sync_source: 'sync_local_cache'
                    });
                    if (!cached && attempt < 3) {
                        setTimeout(() => warmCache(attempt + 1), 2500 * attempt);
                    }
                }
            };
            setTimeout(() => warmCache(1), 1000 + (index * 600));
        });

        setTimeout(() => this.loadReports({ noCache: false }), 1800);
    },

    hasReportInList(reportId) {
        const rid = String(reportId || '').trim();
        if (!rid) return false;
        return this.violations.some((v) => String((v && v.report_id) || '').trim() === rid);
    },

    isLikelyRuntimeReportId(reportId) {
        return /^[0-9]{8}_[0-9]{6}$/.test(String(reportId || '').trim());
    },

    async hydrateFocusedReport(reportId, options = {}) {
        const rid = String(reportId || '').trim();
        if (!rid || this.hasReportInList(rid)) return;
        if (!this.isLikelyRuntimeReportId(rid)) return;

        try {
            const statusData = await API.getReportStatus(rid, {
                noCache: !!options.noCache,
                timeoutMs: 12000
            });
            if (!statusData || typeof statusData !== 'object') {
                return;
            }

            const statusDataHasReport = this.hasReadableReportEvidence(statusData);
            const normalizedStatus = this.normalizeStatusValue(
                statusData.status,
                statusDataHasReport
            );
            if (normalizedStatus === 'unknown' && !statusDataHasReport) {
                return;
            }

            const sourceScope = this.normalizeSourceScope(statusData.source_scope)
                || this.inferSourceScope(statusData)
                || 'cloud';
            const hydrated = {
                report_id: rid,
                timestamp: statusData.updated_at || statusData.timestamp || new Date().toISOString(),
                status: normalizedStatus,
                severity: statusData.severity || 'HIGH',
                device_id: statusData.device_id || null,
                violation_count: Number(statusData.violation_count || 0),
                missing_ppe: Array.isArray(statusData.missing_ppe) ? statusData.missing_ppe : [],
                violation_summary: statusData.violation_summary || 'Violation queued for report generation',
                has_original: !!statusData.has_original,
                has_annotated: !!statusData.has_annotated,
                has_report: statusDataHasReport,
                has_cloud_report_artifact: !!statusData.has_cloud_report_artifact,
                has_cloud_artifacts: !!statusData.has_cloud_artifacts,
                has_local_report: !!statusData.has_local_report,
                source_scope: sourceScope,
                source_label: String(statusData.source_label || '').trim() || this.sourceLabelForScope(sourceScope)
            };

            const existingIndex = this.violations.findIndex((v) => String(v.report_id) === rid);
            if (existingIndex >= 0) {
                this.violations[existingIndex] = {
                    ...this.violations[existingIndex],
                    ...hydrated,
                    has_original: !!this.violations[existingIndex].has_original || hydrated.has_original,
                    has_annotated: !!this.violations[existingIndex].has_annotated || hydrated.has_annotated,
                    has_report: !!this.violations[existingIndex].has_report || hydrated.has_report
                };
            } else {
                this.violations.unshift(hydrated);
            }

            this.violations.sort((a, b) => {
                const aTime = Date.parse(a.timestamp || '') || 0;
                const bTime = Date.parse(b.timestamp || '') || 0;
                return bTime - aTime;
            });

            if (this.isReportReady(hydrated)) {
                void this.prefetchReport(rid, hydrated);
            }
        } catch (error) {
            console.debug('Focused report hydration failed:', error);
        }
    },

    schedulePendingFocusHydration(delayMs = 550) {
        if (this.pendingFocusRetryTimer) return;
        this.pendingFocusRetryTimer = setTimeout(async () => {
            this.pendingFocusRetryTimer = null;
            await this.executePendingFocusHydration();
        }, Math.max(100, Number(delayMs) || 550));
    },

    async executePendingFocusHydration() {
        const req = this.pendingFocusRequest;
        if (!req || !req.reportId) return;
        if (!this.isLikelyRuntimeReportId(req.reportId)) {
            this.pendingFocusRequest = null;
            return;
        }

        const attempts = Number(req.attempts || 0);
        if (attempts >= 4) {
            const rid = String(req.reportId || '').trim();
            this.pendingFocusRequest = null;
            this.notify(`Report ${rid} is still syncing. Refresh shortly if it does not appear.`, 'warning');
            return;
        }

        req.attempts = attempts + 1;
        await this.loadReports({ noCache: true, targetedReportId: req.reportId });

        if (this.pendingFocusRequest && this.pendingFocusRequest.reportId === req.reportId) {
            this.schedulePendingFocusHydration(900 + (req.attempts * 350));
        }
    },

    isPendingLikeStatus(status) {
        const normalized = this.normalizeStatusValue(status);
        return normalized === 'pending' || normalized === 'generating';
    },

    hasReadableReportEvidence(record = {}) {
        if (!record || typeof record !== 'object') return false;
        return !!(
            record.has_report
            || record.has_local_report
            || record.has_report_html
            || record.has_report_html_key
            || record.has_cloud_report_artifact
            || record.has_cloud_report
            || record.report_html_key
            || record.report_pdf_key
            || record.cloud_report_url
            || record.report_url
            || record.local_report_url
        );
    },

    isDowngradeRuntimeStatus(status) {
        const normalized = this.normalizeStatusValue(status, false);
        return normalized === 'pending' || normalized === 'generating';
    },

    reconcileReportRuntimeContinuity(record = {}, previous = {}) {
        if (!record || typeof record !== 'object' || !previous || typeof previous !== 'object') {
            return record;
        }

        const previousReady = this.isReportReady(previous) || this.hasReadableReportEvidence(previous);
        if (!previousReady) return record;

        const nextStatus = this.normalizeStatus(record);
        if (nextStatus === 'failed' || nextStatus === 'skipped') {
            return record;
        }

        const reconciled = {
            ...previous,
            ...record,
            has_report: true,
            status: nextStatus === 'partial' ? 'partial' : 'completed',
            display_status: '',
            display_status_until: 0,
            report_html_key: record.report_html_key || previous.report_html_key,
            report_pdf_key: record.report_pdf_key || previous.report_pdf_key,
            cloud_report_url: record.cloud_report_url || previous.cloud_report_url,
            report_url: record.report_url || previous.report_url,
            local_report_url: record.local_report_url || previous.local_report_url,
            has_cloud_report_artifact: !!(record.has_cloud_report_artifact || previous.has_cloud_report_artifact),
            has_cloud_artifacts: !!(record.has_cloud_artifacts || previous.has_cloud_artifacts),
            has_local_report: !!(record.has_local_report || previous.has_local_report),
            has_original: !!(record.has_original || previous.has_original || record.original_image_key || previous.original_image_key),
            has_annotated: !!(record.has_annotated || previous.has_annotated || record.annotated_image_key || previous.annotated_image_key),
            original_image_key: record.original_image_key || previous.original_image_key,
            annotated_image_key: record.annotated_image_key || previous.annotated_image_key,
            local_image_url: record.local_image_url || previous.local_image_url
        };

        if (!record.sync_state && previous.sync_state) {
            reconciled.sync_state = previous.sync_state;
        }

        return reconciled;
    },

    encodeInlineReportPayload(violation) {
        return JSON.stringify(violation || {})
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '\\u003c')
            .replace(/>/g, '\\u003e');
    },

    upsertReportRuntimeState(reportId, patch = {}, sourceHint = null) {
        const rid = String(reportId || '').trim();
        if (!rid) return null;

        const existingIndex = this.violations.findIndex((v) => String((v && v.report_id) || '').trim() === rid);
        const existing = existingIndex >= 0 ? this.violations[existingIndex] : {};
        const sourceRecord = sourceHint && typeof sourceHint === 'object' ? sourceHint : {};
        const nowIso = new Date().toISOString();
        const sourceScopeCandidate = this.normalizeSourceScope(patch.source_scope)
            || this.inferSourceScope(sourceRecord)
            || this.inferSourceScope(existing)
            || 'cloud';
        const sourceScope = this.resolveStableRuntimeSourceScope(
            existing,
            sourceRecord,
            patch,
            sourceScopeCandidate
        );
        const patchLabel = sourceScope === sourceScopeCandidate
            ? String(patch.source_label || '').trim()
            : '';
        const inheritedLabel = [
            existing.source_label,
            sourceRecord.source_label
        ].map((label) => String(label || '').trim())
            .find((label) => this.sourceLabelMatchesScope(label, sourceScope)) || '';
        const incomingStatusSequence = this.normalizeStatusSequence(
            patch.status_sequence || sourceRecord.status_sequence || existing.status_sequence || []
        );
        const existingHasReadableReport = this.hasReadableReportEvidence(existing);
        const sourceHasReadableReport = this.hasReadableReportEvidence(sourceRecord);
        const patchHasReadableReport = this.hasReadableReportEvidence(patch);
        const anyReadableReport = existingHasReadableReport || sourceHasReadableReport || patchHasReadableReport;
        const patchHasReport = Object.prototype.hasOwnProperty.call(patch, 'has_report')
            ? (!!patch.has_report || patchHasReadableReport)
            : anyReadableReport;
        let nextStatus = this.normalizeStatusValue(
            patch.status || existing.status || sourceRecord.status || 'pending',
            patchHasReport
        );
        let nextHasReport = patchHasReport;
        const explicitTerminalFailure = nextStatus === 'failed' || nextStatus === 'skipped';
        if (
            existingHasReadableReport
            && !explicitTerminalFailure
            && !patch.force_status_downgrade
            && (this.isDowngradeRuntimeStatus(nextStatus) || nextStatus === 'completed' || nextStatus === 'unknown')
        ) {
            nextStatus = 'completed';
            nextHasReport = true;
        }
        const existingStatus = this.normalizeStatus(existing);
        const nowMs = Date.now();
        const hadExistingRecord = existingIndex >= 0;
        const statusSequence = this.normalizeStatusSequence([
            ...incomingStatusSequence,
            ...(hadExistingRecord ? [existingStatus] : []),
            nextStatus
        ]);
        let displayStatus = existing.display_status;
        let displayStatusUntil = Number(existing.display_status_until || 0);
        const sawInFlightBeforeCompleted = statusSequence.includes('generating')
            || (
                hadExistingRecord
                && (existingStatus === 'pending' || existingStatus === 'generating')
                && nextStatus === 'completed'
            );
        const fastCompletedAfterGenerating = !!(
            nextStatus === 'completed'
            && !existingHasReadableReport
            && sawInFlightBeforeCompleted
            && existingStatus !== 'generating'
            && (!displayStatusUntil || displayStatusUntil < nowMs)
        );
        if (existingHasReadableReport && !explicitTerminalFailure) {
            displayStatus = '';
            displayStatusUntil = 0;
        }
        if (fastCompletedAfterGenerating) {
            displayStatus = 'generating';
            displayStatusUntil = nowMs + Math.max(300, Number(this.modalRuntime.minGeneratingDisplayMs || 650));
            if (this.visualStatusTimers.has(rid)) {
                clearTimeout(this.visualStatusTimers.get(rid));
            }
            this.visualStatusTimers.set(rid, setTimeout(() => {
                this.visualStatusTimers.delete(rid);
                const index = this.violations.findIndex((v) => String((v && v.report_id) || '').trim() === rid);
                if (index >= 0) {
                    this.violations[index] = {
                        ...this.violations[index],
                        display_status: '',
                        display_status_until: 0
                    };
                    this.renderReports();
                }
            }, Math.max(300, Number(this.modalRuntime.minGeneratingDisplayMs || 650))));
        }
        const next = {
            ...sourceRecord,
            ...existing,
            ...patch,
            report_id: rid,
            timestamp: patch.timestamp || existing.timestamp || sourceRecord.timestamp || nowIso,
            status: nextStatus,
            status_sequence: statusSequence,
            has_report: nextHasReport,
            has_original: !!(
                patch.has_original
                || existing.has_original
                || sourceRecord.has_original
                || patch.original_image_key
                || existing.original_image_key
                || sourceRecord.original_image_key
                || patch.local_image_url
                || existing.local_image_url
                || sourceRecord.local_image_url
            ),
            has_annotated: !!(
                patch.has_annotated
                || existing.has_annotated
                || sourceRecord.has_annotated
                || patch.annotated_image_key
                || existing.annotated_image_key
                || sourceRecord.annotated_image_key
            ),
            has_local_report: !!(patch.has_local_report || existing.has_local_report || sourceRecord.has_local_report),
            has_cloud_report_artifact: !!(
                patch.has_cloud_report_artifact
                || existing.has_cloud_report_artifact
                || sourceRecord.has_cloud_report_artifact
                || patch.report_html_key
                || patch.report_pdf_key
                || existing.report_html_key
                || existing.report_pdf_key
                || sourceRecord.report_html_key
                || sourceRecord.report_pdf_key
            ),
            has_cloud_artifacts: !!(
                patch.has_cloud_artifacts
                || existing.has_cloud_artifacts
                || sourceRecord.has_cloud_artifacts
                || patch.report_html_key
                || existing.report_html_key
                || sourceRecord.report_html_key
            ),
            report_html_key: patch.report_html_key || existing.report_html_key || sourceRecord.report_html_key,
            report_pdf_key: patch.report_pdf_key || existing.report_pdf_key || sourceRecord.report_pdf_key,
            original_image_key: patch.original_image_key || existing.original_image_key || sourceRecord.original_image_key,
            annotated_image_key: patch.annotated_image_key || existing.annotated_image_key || sourceRecord.annotated_image_key,
            cloud_report_url: patch.cloud_report_url || existing.cloud_report_url || sourceRecord.cloud_report_url,
            report_url: patch.report_url || existing.report_url || sourceRecord.report_url,
            local_report_url: patch.local_report_url || existing.local_report_url || sourceRecord.local_report_url,
            display_status: displayStatus,
            display_status_until: displayStatusUntil,
            source_scope: sourceScope,
            source_label: patchLabel
                || inheritedLabel
                || this.sourceLabelForScope(sourceScope),
            updated_at: patch.updated_at || nowIso
        };

        if (sourceScope === 'cloud') {
            const deviceKey = String(next.device_id || '').trim().toLowerCase();
            if (deviceKey === 'local_cache' || deviceKey === 'offline_local_cache' || deviceKey.startsWith('local_') || deviceKey.startsWith('offline_')) {
                next.device_id = null;
            }
            next.origin = '';
            next.sync_source = '';
            next.source = '';
        }

        if (existingIndex >= 0) {
            this.violations.splice(existingIndex, 1, next);
        } else {
            this.violations.unshift(next);
        }

        const listEl = document.getElementById('reports-list');
        if (listEl) {
            this.renderReports();
        }
        return next;
    },

    mergePendingReports(violations, pendingReports) {
        const base = Array.isArray(violations) ? violations : [];
        const pending = Array.isArray(pendingReports) ? pendingReports : [];
        const byId = new Map();

        base.forEach((item) => {
            const reportId = String((item && item.report_id) || '').trim();
            if (!reportId) return;
            const normalized = { ...item, report_id: reportId };
            normalized.status = this.normalizeStatus(normalized);
            const inferredScope = this.inferSourceScope(normalized);
            const normalizedLabel = String(normalized.source_label || '').trim();
            normalized.source_scope = inferredScope;
            normalized.source_label = this.sourceLabelMatchesScope(normalizedLabel, inferredScope)
                ? normalizedLabel
                : this.sourceLabelForScope(inferredScope);
            byId.set(reportId, normalized);
        });

        pending.forEach((item) => {
            const reportId = String((item && item.report_id) || '').trim();
            if (!reportId) return;

            const itemHasReport = this.hasReadableReportEvidence(item);
            const pendingStatus = this.normalizeStatusValue(
                item && item.status,
                itemHasReport
            );
            const pendingScope = this.inferSourceScope(item);
            const rawPendingLabel = String((item && item.source_label) || '').trim();
            const pendingLabel = this.sourceLabelMatchesScope(rawPendingLabel, pendingScope)
                ? rawPendingLabel
                : this.sourceLabelForScope(pendingScope);
            const existing = byId.get(reportId);

            if (existing) {
                const existingScope = this.inferSourceScope(existing);
                const existingStatus = this.normalizeStatus(existing);
                const existingHasReport = this.hasReadableReportEvidence(existing);
                const pendingPriority = this.getStatusPriority(pendingStatus);
                const existingPriority = this.getStatusPriority(existingStatus);
                const allowRetryTransition = this.isPendingLikeStatus(pendingStatus)
                    && !existingHasReport
                    && (existingStatus === 'failed' || existingStatus === 'skipped');

                if ((pendingPriority > existingPriority && !existingHasReport) || allowRetryTransition) {
                    existing.status = pendingStatus;
                }
                if (!existing.timestamp && item.timestamp) {
                    existing.timestamp = item.timestamp;
                }
                if (!existing.device_id && item.device_id) {
                    const pendingDevice = String(item.device_id || '').trim().toLowerCase();
                    const isLocalCacheSeed = pendingScope === 'local' && (pendingDevice === 'local_cache' || pendingDevice === 'offline_local_cache');
                    if (!(existingScope === 'cloud' && isLocalCacheSeed)) {
                        existing.device_id = item.device_id;
                    }
                }
                if (!existing.severity && item.severity) {
                    existing.severity = item.severity;
                }
                existing.has_original = !!existing.has_original || !!item.has_original;
                existing.has_annotated = !!existing.has_annotated || !!item.has_annotated;
                existing.has_report = existingHasReport || itemHasReport;
                existing.has_cloud_report_artifact = !!existing.has_cloud_report_artifact || !!item.has_cloud_report_artifact || !!item.report_html_key || !!item.report_pdf_key;
                existing.has_cloud_artifacts = !!existing.has_cloud_artifacts || !!item.has_cloud_artifacts;
                existing.report_html_key = existing.report_html_key || item.report_html_key;
                existing.report_pdf_key = existing.report_pdf_key || item.report_pdf_key;
                if (item.sync_state || item.syncState || item.cloud_sync_state || item.cloudSyncState) {
                    const nextSyncState = item.sync_state || item.syncState || item.cloud_sync_state || item.cloudSyncState;
                    const queuedSyncState = /queued|pending|retry/i.test(String(nextSyncState || ''));
                    if (!(existingScope === 'synced_local' && queuedSyncState)) {
                        existing.sync_state = nextSyncState;
                    }
                }
                if (item.sync_source || item.source) {
                    existing.sync_source = item.sync_source || existing.sync_source || '';
                    existing.source = item.source || existing.source || '';
                }

                let mergedScope = existingScope || pendingScope || 'cloud';
                if (existingScope === 'synced_local' && pendingScope === 'cloud') {
                    mergedScope = this.hasSyncedLocalEvidence(existing) ? 'synced_local' : 'cloud';
                } else if (existingScope === 'local' && pendingScope === 'cloud' && this.hasLocalScopeEvidence(existing)) {
                    mergedScope = 'local';
                } else if (existingScope === 'shared' && pendingScope === 'cloud') {
                    mergedScope = 'shared';
                } else if (pendingScope === 'synced_local') {
                    mergedScope = 'synced_local';
                } else if (pendingScope === 'shared' && mergedScope !== 'synced_local') {
                    mergedScope = 'shared';
                } else if (pendingScope === 'cloud') {
                    mergedScope = 'cloud';
                } else if (!existingScope && pendingScope) {
                    mergedScope = pendingScope;
                }

                existing.source_scope = mergedScope;
                if (mergedScope === 'synced_local') {
                    existing.source_label = 'Local Synced';
                } else if (mergedScope === pendingScope && pendingLabel) {
                    existing.source_label = pendingLabel;
                } else if (this.sourceLabelMatchesScope(existing.source_label, mergedScope)) {
                    existing.source_label = String(existing.source_label || '').trim();
                } else {
                    existing.source_label = this.sourceLabelForScope(mergedScope);
                }
                return;
            }

            byId.set(reportId, {
                report_id: reportId,
                timestamp: item.timestamp || new Date().toISOString(),
                status: pendingStatus,
                severity: item.severity || 'HIGH',
                device_id: item.device_id || null,
                violation_count: Number(item.violation_count || 0),
                missing_ppe: Array.isArray(item.missing_ppe) ? item.missing_ppe : [],
                violation_summary: item.violation_summary || 'Violation queued for report generation',
                has_original: !!item.has_original,
                has_annotated: !!item.has_annotated,
                has_report: itemHasReport,
                has_cloud_report_artifact: !!item.has_cloud_report_artifact || !!item.report_html_key || !!item.report_pdf_key,
                has_cloud_artifacts: !!item.has_cloud_artifacts,
                report_html_key: item.report_html_key,
                report_pdf_key: item.report_pdf_key,
                source_scope: pendingScope,
                source_label: pendingLabel,
                sync_state: item.sync_state || item.syncState || item.cloud_sync_state || item.cloudSyncState || '',
                sync_source: item.sync_source || '',
                source: item.source || ''
            });
        });

        const merged = Array.from(byId.values());
        merged.sort((a, b) => {
            const aTime = Date.parse(a.timestamp || '') || 0;
            const bTime = Date.parse(b.timestamp || '') || 0;
            return bTime - aTime;
        });

        return merged;
    },

    scheduleReportPrefetch(options = {}) {
        if (typeof navigator !== 'undefined' && navigator.onLine === false) return;
        if (this.cacheWarmTimer) {
            clearTimeout(this.cacheWarmTimer);
            this.cacheWarmTimer = null;
        }

        const seen = new Set();
        const ready = this.violations
            .filter((v) => this.isReportReady(v))
            .filter((v) => {
                const reportId = String((v && v.report_id) || '').trim();
                if (!reportId || seen.has(reportId)) return false;
                seen.add(reportId);
                const scope = this.inferSourceScope(v);
                return scope === 'cloud' || scope === 'synced_local' || scope === 'shared';
            })
            .slice(0, Math.max(8, Math.min(Number(options.limit || 60), 120)));

        let index = 0;
        const pump = () => {
            const batch = ready.slice(index, index + 4);
            batch.forEach((v, batchIndex) => {
                const reportId = String(v.report_id || '').trim();
                if (!reportId) return;
                setTimeout(() => {
                    this.prefetchReport(reportId, v);
                }, 120 * batchIndex);
            });
            index += batch.length;
            if (index < ready.length) {
                this.cacheWarmTimer = setTimeout(pump, 1500);
            } else {
                this.cacheWarmTimer = null;
            }
        };

        if (ready.length) {
            this.cacheWarmTimer = setTimeout(pump, 250);
        }
    },

    async prefetchReport(reportId, sourceHint = null) {
        const rid = String(reportId || '').trim();
        if (!rid) return;
        if (this.prefetchState.completed.has(rid)) return;
        if (this.prefetchState.inFlight.has(rid)) return;

        this.prefetchState.inFlight.add(rid);
        try {
            const result = await API.prefetchReport(rid, { source: sourceHint });
            if (result && result.success) {
                this.prefetchState.completed.add(rid);
            }
        } catch (error) {
            // Non-blocking optimization path.
        } finally {
            this.prefetchState.inFlight.delete(rid);
        }
    },

    async refreshReports() {
        const list = document.getElementById('reports-list');
        list.innerHTML = '<div class="spinner"></div>';
        await this.loadReports({ noCache: true });
        await this.updateProviderRuntimeBadge();
    },

    setProviderBadgeText(text, state = 'info') {
        const badge = document.getElementById('reportsProviderBadge');
        if (!badge) return;

        badge.textContent = text;
        badge.classList.remove('state-info', 'state-ok', 'state-warn', 'state-error');
        if (state === 'ok') badge.classList.add('state-ok');
        else if (state === 'warn') badge.classList.add('state-warn');
        else if (state === 'error') badge.classList.add('state-error');
        else badge.classList.add('state-info');
    },

    async updateProviderRuntimeBadge() {
        try {
            const data = await API.getProviderRuntimeStatus();
            if (!data || data.success === false) {
                throw new Error((data && data.error) || 'runtime unavailable');
            }

            const runtime = data.runtime || {};
            const nlp = runtime.nlp || {};
            const capacity = data.capacity || {};

            const rawProvider = (nlp.last_provider || '').trim();
            const provider = rawProvider || 'awaiting-first-success';
            const model = nlp.last_model || '-';
            const estimate = capacity.estimate_reports_remaining;
            const estimateText = estimate == null ? 'unknown' : String(estimate);

            let state = 'info';
            if (capacity.status === 'depleted') state = 'error';
            else if (capacity.status === 'limited') state = 'warn';
            else if (capacity.status === 'sustainable') state = 'ok';

            const providerLabel = rawProvider
                ? provider
                : 'awaiting first successful generation';
            this.setProviderBadgeText(`Provider: ${providerLabel} (${model}) | Remaining: ${estimateText}`, state);
        } catch (error) {
            this.setProviderBadgeText('Provider: unavailable', 'error');
        }
    },

    handleSearch(event) {
        this.filters.search = event.target.value.toLowerCase();
        this.renderReports();
    },

    handleFilter() {
        this.filters.severity = document.getElementById('filter-severity').value;
        this.filters.dateRange = document.getElementById('filter-date').value;
        this.filters.source = document.getElementById('filter-source').value;
        this.renderReports();
    },

    getFilteredViolations() {
        let filtered = [...this.violations];

        // Search filter
        if (this.filters.search) {
            filtered = filtered.filter(v =>
                String(v.report_id || '').toLowerCase().includes(this.filters.search) ||
                String(v.timestamp || '').toLowerCase().includes(this.filters.search) ||
                String(v.device_id || '').toLowerCase().includes(this.filters.search)
            );
        }

        // Severity filter
        if (this.filters.severity !== 'all') {
            filtered = filtered.filter(v => {
                const severity = (v.severity || 'HIGH').toLowerCase();
                return severity === this.filters.severity;
            });
        }

        // Date range filter
        if (this.filters.dateRange !== 'all') {
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());

            filtered = filtered.filter(v => {
                const vDate = new Date(v.timestamp);

                switch(this.filters.dateRange) {
                    case 'today':
                        return vDate >= today;
                    case 'week':
                        const weekAgo = new Date(today);
                        weekAgo.setDate(weekAgo.getDate() - 7);
                        return vDate >= weekAgo;
                    case 'month':
                        const monthAgo = new Date(today);
                        monthAgo.setMonth(monthAgo.getMonth() - 1);
                        return vDate >= monthAgo;
                    default:
                        return true;
                }
            });
        }

        // Source filter
        if (this.filters.source !== 'all') {
            filtered = filtered.filter((v) => this.inferSourceScope(v) === this.filters.source);
        }

        return filtered;
    },

    exportFilteredCsv() {
        try {
            const rows = this.getFilteredViolations();
            if (!rows.length) {
                if (typeof notifyApp === 'function') {
                    notifyApp('No reports match the current filters.', 'warning');
                } else {
                    alert('No reports match the current filters.');
                }
                return;
            }

            const escapeCell = (v) => {
                if (v === null || v === undefined) return '';
                let s = String(v);
                // Strip line breaks for CSV row safety
                s = s.replace(/\r?\n/g, ' ');
                if (/[",]/.test(s)) {
                    s = '"' + s.replace(/"/g, '""') + '"';
                }
                return s;
            };

            const headers = [
                'report_id', 'timestamp', 'status', 'severity',
                'device_id', 'violation_count', 'missing_ppe',
                'source_scope', 'source_label', 'violation_summary'
            ];

            const lines = [headers.join(',')];
            rows.forEach((r) => {
                const missing = Array.isArray(r.missing_ppe) ? r.missing_ppe.join('; ') : '';
                lines.push([
                    r.report_id, r.timestamp, r.status, r.severity,
                    r.device_id, r.violation_count, missing,
                    r.source_scope, r.source_label, r.violation_summary
                ].map(escapeCell).join(','));
            });

            // Prepend BOM so Excel detects UTF-8
            const csv = '\uFEFF' + lines.join('\r\n');
            const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const ts = new Date().toISOString().replace(/[:.]/g, '-');
            const a = document.createElement('a');
            a.href = url;
            a.download = `casm-reports-${ts}.csv`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            setTimeout(() => URL.revokeObjectURL(url), 1000);

            if (typeof notifyApp === 'function') {
                notifyApp(`Exported ${rows.length} report${rows.length === 1 ? '' : 's'} to CSV.`, 'success');
            }
        } catch (err) {
            console.error('CSV export failed:', err);
            if (typeof notifyApp === 'function') {
                notifyApp('CSV export failed. See console for details.', 'error');
            }
        }
    },

    normalizeStatusValue(status, hasReport = false) {
        const raw = String(status || '').trim().toLowerCase();
        if (!raw) {
            return hasReport ? 'completed' : 'pending';
        }

        if (raw === 'completed' || raw === 'ready' || raw === 'done' || raw === 'success') {
            return 'completed';
        }
        if (raw === 'partial' || raw === 'degraded') {
            return 'partial';
        }
        if (raw === 'failed' || raw === 'error' || raw === 'errored') {
            return 'failed';
        }
        if (raw === 'skipped' || raw === 'cancelled' || raw === 'canceled') {
            return 'skipped';
        }

        // Keep UI card state aligned with actual report availability.
        if (
            hasReport && (
                raw === 'generating'
                || raw === 'processing'
                || raw === 'in_progress'
                || raw === 'in-progress'
                || raw === 'running'
                || raw === 'pending'
                || raw === 'queued'
                || raw === 'queue'
                || raw === 'waiting'
                || raw === 'enqueued'
            )
        ) {
            return 'completed';
        }

        if (
            raw === 'generating'
            || raw === 'processing'
            || raw === 'in_progress'
            || raw === 'in-progress'
            || raw === 'running'
        ) {
            return 'generating';
        }
        if (
            raw === 'pending'
            || raw === 'queued'
            || raw === 'queue'
            || raw === 'waiting'
            || raw === 'enqueued'
        ) {
            return 'pending';
        }

        if (hasReport) {
            return 'completed';
        }
        return raw;
    },

    normalizeStatusSequence(sequence) {
        const values = Array.isArray(sequence) ? sequence : [sequence];
        const normalized = [];
        values.forEach((value) => {
            const status = this.normalizeStatusValue(value, false);
            if (!status || status === 'unknown') return;
            if (!normalized.length || normalized[normalized.length - 1] !== status) {
                normalized.push(status);
            }
        });
        return normalized.slice(-6);
    },

    getStatusPriority(status) {
        const normalized = this.normalizeStatusValue(status);
        if (normalized === 'completed') return 50;
        if (normalized === 'failed' || normalized === 'skipped' || normalized === 'partial') return 40;
        if (normalized === 'generating') return 30;
        if (normalized === 'pending') return 20;
        if (normalized === 'unknown') return 10;
        return 0;
    },

    normalizeStatus(violation) {
        const hasReport = this.hasReadableReportEvidence(violation);
        const raw = violation && Object.prototype.hasOwnProperty.call(violation, 'status')
            ? violation.status
            : '';
        return this.normalizeStatusValue(raw, hasReport);
    },

    getDisplayStatus(violation) {
        const displayStatus = this.normalizeStatusValue(violation && violation.display_status, false);
        const displayUntil = Number(violation && violation.display_status_until);
        if (
            displayStatus
            && displayStatus !== 'unknown'
            && Number.isFinite(displayUntil)
            && displayUntil > Date.now()
        ) {
            return displayStatus;
        }
        return this.normalizeStatus(violation);
    },

    normalizeSourceScope(scope) {
        const normalized = String(scope || '').trim().toLowerCase();
        if (normalized === 'local' || normalized === 'cloud' || normalized === 'shared' || normalized === 'synced_local') {
            return normalized;
        }
        return '';
    },

    inferSourceScope(violation) {
        const explicit = this.normalizeSourceScope(violation && violation.source_scope);
        if (explicit === 'synced_local') {
            if (this.hasSyncedLocalEvidence(violation)) {
                return 'synced_local';
            }
            return this.hasStrictLocalArtifactOrigin(violation) ? 'local' : 'cloud';
        }
        if (explicit === 'local' && this.hasCloudArtifactEvidence(violation) && !this.hasDurableLocalOriginEvidence(violation)) {
            return 'cloud';
        }
        if (explicit) return explicit;

        const sourceMarker = this.getSourceMarker(violation);
        if (
            sourceMarker === 'sync_local_cache'
            || sourceMarker === 'local_cache_sync'
            || sourceMarker === 'offline_local_cache_sync'
        ) {
            if (this.hasSyncedLocalEvidence(violation)) return 'synced_local';
            return this.hasStrictLocalArtifactOrigin(violation) ? 'local' : 'cloud';
        }
        if (sourceMarker === 'local_synced') {
            if (this.hasSyncedLocalEvidence(violation)) return 'synced_local';
            return this.hasStrictLocalArtifactOrigin(violation) ? 'local' : 'cloud';
        }
        if (sourceMarker === 'browser_local_draft_handoff') {
            if (this.hasSyncedLocalEvidence(violation)) return 'synced_local';
            return this.hasStrictLocalArtifactOrigin(violation) ? 'local' : 'cloud';
        }

        const deviceId = this.getDeviceKey(violation);
        if (deviceId === 'local_cache_sync' || deviceId === 'sync_local_cache') {
            if (this.hasSyncedLocalEvidence(violation)) return 'synced_local';
            return this.hasStrictLocalArtifactOrigin(violation) ? 'local' : 'cloud';
        }

        return this.hasLocalOriginEvidence(violation) ? 'local' : 'cloud';
    },

    sourceLabelForScope(scope) {
        if (scope === 'local') return 'Local';
        if (scope === 'synced_local') return 'Local Synced';
        if (scope === 'shared') return 'Shared';
        return 'Cloud';
    },

    sourceLabelMatchesScope(label, scope) {
        const normalized = String(label || '').trim().toLowerCase();
        if (!normalized) return false;
        if (scope === 'local') return normalized === 'local';
        if (scope === 'synced_local') return normalized.includes('local synced');
        if (scope === 'shared') return normalized.includes('shared');
        return normalized.includes('cloud');
    },

    getSourceMarker(record = {}) {
        return String(
            (record && (record.origin || record.sync_source || record.source || record.source_reason)) || ''
        ).trim().toLowerCase();
    },

    getSourceMarkers(record = {}) {
        return [
            record && record.origin,
            record && record.sync_source,
            record && record.source,
            record && record.source_reason
        ].map((value) => String(value || '').trim().toLowerCase()).filter(Boolean);
    },

    getDeviceKey(record = {}) {
        return String((record && record.device_id) || '').trim().toLowerCase();
    },

    hasLocalArtifactOriginDevice(deviceId = '') {
        const normalized = String(deviceId || '').trim().toLowerCase();
        return (
            normalized === 'local_cache'
            || normalized === 'offline_local_cache'
            || normalized === 'browser_local_draft'
            || normalized === 'local_cache_sync'
            || normalized === 'sync_local_cache'
            || normalized.startsWith('local_')
            || normalized.startsWith('offline_')
            || normalized.startsWith('browser_local')
        );
    },

    hasStrictLocalArtifactOrigin(record = {}) {
        if (!record || typeof record !== 'object') return false;
        const reportId = String((record && (record.report_id || record.id)) || '').trim().toLowerCase();
        if (/^(local|offline|browser_local|local-cache|offline-cache)[_-]/.test(reportId)) return true;
        return this.hasLocalArtifactOriginDevice(this.getDeviceKey(record));
    },

    getSyncState(record = {}) {
        return String(
            (record && (record.sync_state || record.syncState || record.cloud_sync_state || record.cloudSyncState)) || ''
        ).trim().toLowerCase();
    },

    hasCloudArtifactEvidence(record = {}) {
        return !!(
            record
            && (
                record.has_cloud_artifacts
                || record.original_image_key
                || record.annotated_image_key
                || record.report_html_key
                || record.cloud_report_url
                || record.cloud_image_url
            )
        );
    },

    hasCloudReportArtifactEvidence(record = {}) {
        return !!(
            record
            && (
                record.has_cloud_report_artifact
                || record.has_cloud_report
                || record.report_html_key
                || record.report_pdf_key
                || record.cloud_report_url
            )
        );
    },

    hasLocalOriginMarkerEvidence(record = {}) {
        const sourceMarker = this.getSourceMarker(record);
        const handoffOnlyMarker = sourceMarker === 'browser_local_draft_handoff'
            || sourceMarker === 'sync_local_cache_partial';
        if (handoffOnlyMarker) {
            return this.hasStrictLocalArtifactOrigin(record);
        }
        if (
            sourceMarker === 'local'
            || sourceMarker === 'local_pipeline'
            || sourceMarker === 'local_pending_recovery'
            || sourceMarker === 'offline_local'
            || sourceMarker === 'offline_local_cache'
            || sourceMarker === 'browser_local_draft'
            || sourceMarker === 'sync_local_cache'
            || sourceMarker === 'local_cache'
            || sourceMarker === 'local_cache_sync'
            || sourceMarker === 'offline_local_cache_sync'
            || sourceMarker === 'local_synced'
            || sourceMarker.startsWith('local_')
            || sourceMarker.startsWith('offline_')
            || (sourceMarker.startsWith('browser_local') && sourceMarker !== 'browser_local_draft_handoff')
        ) {
            return true;
        }

        const deviceId = this.getDeviceKey(record);
        if (
            deviceId === 'local_cache'
            || deviceId === 'offline_local_cache'
            || deviceId === 'local_cache_sync'
            || deviceId === 'sync_local_cache'
            || deviceId === 'browser_local_draft'
            || deviceId.startsWith('local_')
            || deviceId.startsWith('offline_')
            || deviceId.startsWith('browser_local')
        ) {
            return true;
        }

        const reportId = String((record && (record.report_id || record.id)) || '').trim().toLowerCase();
        return /^(local|offline|browser_local|local-cache|offline-cache)[_-]/.test(reportId);
    },

    hasDurableLocalOriginEvidence(record = {}) {
        if (!record || typeof record !== 'object') return false;
        if (this.hasStrictLocalArtifactOrigin(record)) return true;
        if (this.hasLocalOriginMarkerEvidence(record)) return true;
        return !!(
            record.local_report_url
            || record.original_blob
            || record.annotated_blob
            || record.report_blob
            || record.report_html_blob
            || record.cached_report_html
        );
    },

    hasLocalOriginEvidence(record = {}) {
        const explicit = this.normalizeSourceScope(record && record.source_scope);
        if (explicit === 'local') {
            return !this.hasCloudArtifactEvidence(record) || this.hasDurableLocalOriginEvidence(record);
        }
        return this.hasLocalOriginMarkerEvidence(record);
    },

    hasLocalScopeEvidence(record = {}) {
        const explicit = this.normalizeSourceScope(record && record.source_scope);
        if (explicit === 'local') {
            return !this.hasCloudArtifactEvidence(record) || this.hasDurableLocalOriginEvidence(record);
        }
        return this.hasLocalOriginMarkerEvidence(record) && !this.hasSyncedLocalEvidence(record);
    },

    hasSyncedLocalEvidence(record = {}) {
        const explicit = this.normalizeSourceScope(record && record.source_scope);
        const sourceMarkers = this.getSourceMarkers(record);
        const hasMarker = (marker) => sourceMarkers.includes(marker);
        const sourceMarker = sourceMarkers[0] || '';
        const deviceId = this.getDeviceKey(record);
        const syncState = this.getSyncState(record);
        const syncMarker = (
            hasMarker('sync_local_cache')
            || hasMarker('local_cache_sync')
            || hasMarker('offline_local_cache_sync')
            || deviceId === 'local_cache_sync'
            || deviceId === 'sync_local_cache'
        );
        if (syncMarker) {
            return this.hasCloudReportArtifactEvidence(record);
        }

        const strictLocalOrigin = this.hasStrictLocalArtifactOrigin(record);
        if (hasMarker('local_synced')) {
            return strictLocalOrigin && this.hasCloudReportArtifactEvidence(record);
        }
        if (hasMarker('browser_local_draft_handoff')) {
            return strictLocalOrigin && this.hasCloudReportArtifactEvidence(record);
        }

        const syncStateConfirmed = (
            syncState === 'synced'
            || syncState === 'cloud_completed'
            || syncState === 'completed_synced'
            || syncState.startsWith('cloud_sync_')
            || syncState.startsWith('sync_')
        );
        if (syncStateConfirmed && strictLocalOrigin && this.hasCloudReportArtifactEvidence(record)) {
            return true;
        }

        return false;
    },

    resolveStableRuntimeSourceScope(existing = {}, sourceRecord = {}, patch = {}, candidateScope = '') {
        const normalizedCandidate = this.normalizeSourceScope(candidateScope) || 'cloud';
        const existingExplicit = this.normalizeSourceScope(existing && existing.source_scope);
        const sourceExplicit = this.normalizeSourceScope(sourceRecord && sourceRecord.source_scope);
        const anchoredScope = existingExplicit || sourceExplicit;
        const forceCloudRuntime = !!(
            patch
            && (
                patch.routed_via_cloud_fallback
                || patch.force_cloud_runtime
                || patch.source_reason === 'manual_cloud_reprocess_fallback'
            )
        );

        if (forceCloudRuntime && normalizedCandidate === 'cloud') {
            return 'cloud';
        }

        if (anchoredScope === 'shared' && normalizedCandidate === 'cloud') {
            return 'shared';
        }

        if (
            normalizedCandidate === 'synced_local'
            && !(
                this.hasSyncedLocalEvidence(existing)
                || this.hasSyncedLocalEvidence(sourceRecord)
                || this.hasSyncedLocalEvidence(patch)
            )
        ) {
            const mergedForUnsyncedLocal = { ...sourceRecord, ...existing, ...patch };
            return this.hasLocalOriginMarkerEvidence(mergedForUnsyncedLocal) ? 'local' : 'cloud';
        }

        if (
            normalizedCandidate === 'cloud'
            && anchoredScope === 'local'
            && (this.hasLocalScopeEvidence(existing) || this.hasLocalScopeEvidence(sourceRecord))
            && !this.hasSyncedLocalEvidence(patch)
        ) {
            return 'local';
        }

        if (
            normalizedCandidate === 'cloud'
            && anchoredScope === 'synced_local'
            && (
                this.hasSyncedLocalEvidence(existing)
                || this.hasSyncedLocalEvidence(sourceRecord)
                || this.hasSyncedLocalEvidence(patch)
            )
        ) {
            return 'synced_local';
        }

        if (normalizedCandidate !== 'local') {
            return normalizedCandidate;
        }

        if (
            anchoredScope === 'synced_local'
            && (
                this.hasSyncedLocalEvidence(existing)
                || this.hasSyncedLocalEvidence(sourceRecord)
                || this.hasSyncedLocalEvidence(patch)
            )
        ) {
            return 'synced_local';
        }
        if (anchoredScope === 'shared') {
            return 'shared';
        }

        const existingLabel = String((existing && existing.source_label) || '').trim().toLowerCase();
        const sourceLabel = String((sourceRecord && sourceRecord.source_label) || '').trim().toLowerCase();
        const cloudAnchored = anchoredScope === 'cloud'
            || existingLabel.includes('cloud')
            || sourceLabel.includes('cloud')
            || this.hasCloudArtifactEvidence(existing)
            || this.hasCloudArtifactEvidence(sourceRecord);
        if (!cloudAnchored) {
            return normalizedCandidate;
        }

        const mergedForMarker = { ...sourceRecord, ...existing, ...patch };
        const localOrigin = this.hasDurableLocalOriginEvidence(mergedForMarker);
        if (localOrigin) {
            return normalizedCandidate;
        }

        if (cloudAnchored) {
            return 'cloud';
        }

        const status = this.normalizeStatusValue(
            patch.status || existing.status || sourceRecord.status,
            !!(Object.prototype.hasOwnProperty.call(patch, 'has_report') ? patch.has_report : (existing.has_report || sourceRecord.has_report))
        );
        if (status === 'pending' || status === 'queued' || status === 'generating' || status === 'processing') {
            return 'cloud';
        }

        return normalizedCandidate;
    },

    notify(message, type = 'info', options = {}) {
        if (typeof NotificationManager !== 'undefined') {
            if (type === 'success') return NotificationManager.success(message, options);
            if (type === 'warning') return NotificationManager.warning(message, options);
            if (type === 'error') return NotificationManager.error(message, options);
            return NotificationManager.info(message, options);
        }
        if (type === 'error') {
            alert(message);
        } else {
            console.log(`[${type.toUpperCase()}] ${message}`);
        }
    },

    notifyReportReady(reportId, sourceHint = null) {
        const rid = String(reportId || '').trim();
        if (!rid) return;
        if (typeof NotificationManager !== 'undefined' && typeof NotificationManager.reportReady === 'function') {
            NotificationManager.reportReady(rid, {
                action: {
                    text: 'Open Report',
                    onClickFn: () => this.openReport(rid, sourceHint)
                }
            });
        } else {
            this.notify(`Report ${rid} is ready for review.`, 'success', {
                dedupeKey: `report-ready:${rid}`,
                dedupeTtlMs: 60000
            });
        }
    },

    async openReport(reportId, sourceHint = null) {
        const rid = String(reportId || '').trim();
        if (!rid) return;
        const resolvedSourceHint = sourceHint || this.violations.find((v) => String(v.report_id) === rid) || null;
        const offline = typeof navigator !== 'undefined' && navigator.onLine === false;
        const sourceScope = typeof API !== 'undefined' && typeof API.inferReportSourceScope === 'function'
            ? API.inferReportSourceScope(resolvedSourceHint)
            : this.inferSourceScope(resolvedSourceHint);

        const requiresCloudBase = sourceScope === 'cloud' || sourceScope === 'shared' || sourceScope === 'synced_local';
        if (
            offline
            && requiresCloudBase
            && typeof API !== 'undefined'
            && typeof API.getOfflineCachedReportUrl === 'function'
        ) {
            const cachedUrl = await API.getOfflineCachedReportUrl(rid, resolvedSourceHint);
            if (cachedUrl) {
                window.open(cachedUrl, '_blank');
                this.notify(`Opening cached report ${rid}`, 'info');
                return;
            }
        }

        if (typeof API !== 'undefined' && API.isCloudReportUnavailableOffline(resolvedSourceHint)) {
            const cachedUrl = typeof API.getOfflineCachedReportUrl === 'function'
                ? await API.getOfflineCachedReportUrl(rid, resolvedSourceHint)
                : null;
            if (cachedUrl) {
                window.open(cachedUrl, '_blank');
                this.notify(`Opening cached report ${rid}`, 'info');
                return;
            }
            this.notify('Cloud report details are unavailable offline or without a cloud connection.', 'warning', {
                dedupeKey: `cloud-report-offline-${rid}`,
                dedupeTtlMs: 10000
            });
            return;
        }

        const readyForCachedOpen = resolvedSourceHint && this.isReportReady(resolvedSourceHint);
        if (
            !offline
            && readyForCachedOpen
            && typeof API !== 'undefined'
            && typeof API.getCachedReportUrl === 'function'
        ) {
            const cachedUrl = await API.getCachedReportUrl(rid, resolvedSourceHint);
            if (cachedUrl) {
                window.open(cachedUrl, '_blank');
                this.notify(`Opening cached report ${rid}`, 'info');
                if (typeof this.prefetchReport === 'function') {
                    this.prefetchReport(rid, resolvedSourceHint).catch(() => {});
                }
                return;
            }
        }

        try {
            await Promise.race([
                this.prefetchReport(rid, resolvedSourceHint),
                new Promise((resolve) => setTimeout(resolve, 250))
            ]);
        } catch (error) {
            // Fall through to open even if prefetch fails or times out.
        }

        const url = typeof API.getReportNavigationUrl === 'function'
            ? API.getReportNavigationUrl(reportId, resolvedSourceHint)
            : API.getReportUrl(reportId, resolvedSourceHint);
        window.open(url, '_blank');
        this.notify(`Opening report ${reportId}`, 'info');
    },

    focusReport(reportId, { openModal = false } = {}) {
        if (!reportId) {
            Router.navigate('reports');
            return;
        }

        const attemptFocus = () => {
            const card = document.getElementById(`report-${reportId}`);
            if (!card) return false;

            card.scrollIntoView({ behavior: 'smooth', block: 'center' });
            card.style.outline = '2px solid var(--accent-color)';
            card.style.outlineOffset = '2px';
            setTimeout(() => {
                card.style.outline = '';
                card.style.outlineOffset = '';
            }, 1800);

            if (openModal) {
                const violation = this.violations.find((v) => String(v.report_id) === String(reportId));
                if (violation) this.showGeneratingModal(violation);
            }

            return true;
        };

        const currentRoute = (typeof Router !== 'undefined' && typeof Router.normalizePath === 'function')
            ? Router.normalizePath(window.location.hash)
            : String(window.location.hash || '').replace(/^#\/?/, '') || 'home';

        if (currentRoute !== 'reports') {
            this.pendingFocusRequest = {
                reportId: String(reportId),
                openModal: !!openModal,
                attempts: 0
            };
            Router.navigate('reports');
            return;
        }

        if (!attemptFocus()) {
            this.pendingFocusRequest = {
                reportId: String(reportId),
                openModal: !!openModal,
                attempts: 0
            };
            this.schedulePendingFocusHydration(400);
        }
    },

    applyPendingFocusRequest() {
        const req = this.pendingFocusRequest;
        if (!req || !req.reportId) return;

        const card = document.getElementById(`report-${req.reportId}`);
        if (!card) {
            this.schedulePendingFocusHydration();
            return;
        }

        this.pendingFocusRequest = null;
        this.focusReport(req.reportId, { openModal: !!req.openModal });
    },

    renderReports() {
        const list = document.getElementById('reports-list');
        if (!list) return;
        list.innerHTML = this.renderReportsListMarkup();
    },

    renderReportsListMarkup() {
        const filtered = this.getFilteredViolations();
        if (!this.hasLoadedOnce && filtered.length === 0) {
            return '<div class="spinner"></div>';
        }
        if (filtered.length === 0) {
            return `
                <div class="alert alert-info">
                    <i class="fas fa-info-circle"></i>
                    <span>No reports found. Try adjusting your filters or run the live demo to generate violations.</span>
                </div>
            `;
        }

        // Show ALL reports including in-progress ones (Pipeline_CASM behavior)
        return `
            <div class="grid">
                ${filtered.map(v => this.renderReportCard(v)).join('')}
            </div>
        `;
    },

    // Check if report is ready to view
    isReportReady(violation) {
        const status = this.normalizeStatus(violation);
        return this.hasReadableReportEvidence(violation) &&
               (status === 'completed' || status === 'partial' || status === 'unknown');
    },

    // Get status display info
    getStatusInfo(violation) {
        const status = this.getDisplayStatus(violation);
        const ready = this.isReportReady(violation);

        switch(status) {
            case 'completed':
                if (ready) {
                    return { icon: 'fa-check-circle', color: 'success', text: 'Ready' };
                }
                return { icon: 'fa-spinner fa-spin', color: 'warning', text: 'Finalizing...' };
            case 'generating':
                return { icon: 'fa-spinner fa-spin', color: 'warning', text: 'Generating...' };
            case 'processing':
                return { icon: 'fa-spinner fa-spin', color: 'warning', text: 'Generating...' };
            case 'pending':
                return { icon: 'fa-clock', color: 'warning', text: 'Queued' };
            case 'queued':
                return { icon: 'fa-clock', color: 'warning', text: 'Queued' };
            case 'failed':
                return { icon: 'fa-exclamation-triangle', color: 'danger', text: 'Failed' };
            case 'skipped':
                return { icon: 'fa-ban', color: 'danger', text: 'Skipped' };
            case 'partial':
                return { icon: 'fa-exclamation-circle', color: 'warning', text: 'Partial' };
            default:
                return this.hasReadableReportEvidence(violation)
                    ? { icon: 'fa-check-circle', color: 'success', text: 'Ready' }
                    : { icon: 'fa-spinner fa-spin', color: 'warning', text: 'Processing' };
        }
    },

    getSourceInfo(violation) {
        const scope = this.inferSourceScope(violation);
        const labelFromApi = String((violation && violation.source_label) || '').trim();

        if (scope === 'local') {
            return {
                scope,
                label: labelFromApi || this.sourceLabelForScope(scope),
                color: 'warning',
                icon: 'fa-laptop'
            };
        }

        if (scope === 'synced_local') {
            return {
                scope,
                label: labelFromApi || this.sourceLabelForScope(scope),
                color: 'success',
                icon: 'fa-cloud-upload-alt'
            };
        }

        if (scope === 'shared') {
            return {
                scope,
                label: labelFromApi || this.sourceLabelForScope(scope),
                color: 'success',
                icon: 'fa-link'
            };
        }

        return {
            scope: 'cloud',
            label: labelFromApi || this.sourceLabelForScope('cloud'),
            color: 'info',
            icon: 'fa-cloud'
        };
    },

    getSyncInfo(violation, sourceScope = '') {
        const syncState = this.getSyncState(violation);

        const scope = this.normalizeSourceScope(sourceScope) || this.inferSourceScope(violation);
        const localRelated = scope === 'local'
            || scope === 'synced_local'
            || this.hasLocalOriginMarkerEvidence(violation);
        if (!localRelated) return null;

        if (scope === 'synced_local') {
            return {
                color: 'success',
                icon: 'fa-check-circle',
                label: 'Synced',
                title: 'Local report HTML is confirmed in cloud storage.'
            };
        }

        if (!syncState) return null;

        if (
            syncState === 'cloud_completed'
            || syncState === 'completed_synced'
            || syncState === 'synced'
        ) {
            return {
                color: 'success',
                icon: 'fa-check-circle',
                label: 'Synced',
                title: 'Local report HTML is confirmed in cloud storage.'
            };
        }

        if (
            syncState.includes('queued')
            || syncState.includes('pending')
            || syncState.includes('retry')
        ) {
            return {
                color: 'warning',
                icon: 'fa-cloud-upload-alt',
                label: 'Sync queued',
                title: 'Cloud sync is queued; this changes to Local Synced after report HTML is confirmed in cloud storage.'
            };
        }

        if (syncState.includes('syncing') || syncState.includes('in_progress')) {
            return {
                color: 'warning',
                icon: 'fa-sync-alt fa-spin',
                label: 'Syncing',
                title: 'Cloud sync is in progress.'
            };
        }

        return null;
    },

    // Handle report click with fallback for generating reports
    handleReportClick(violation) {
        if (this.isReportReady(violation)) {
            this.openReport(violation.report_id, violation);
        } else {
            this.showGeneratingModal(violation);
        }
    },

    // Show modal for reports still generating
    async showGeneratingModal(violation) {
        const statusInfo = this.getStatusInfo(violation);
        const ready = this.isReportReady(violation);
        const processAction = this.getProcessAction(violation);

        // Fetch detailed status from API if failed
        let detailedError = violation.error_message;
        if (this.normalizeStatus(violation) === 'failed') {
            try {
                const data = await API.getReportStatus(violation.report_id, { source: violation });
                detailedError = (data && data.error_message) || detailedError;
            } catch (e) {
                console.error('Failed to fetch detailed error:', e);
            }
        }

        // Create modal overlay
        const inlineViolation = this.encodeInlineReportPayload(violation);
        const modal = document.createElement('div');
        modal.id = 'report-status-modal';
        modal.style.cssText = `
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.5); display: flex; align-items: center;
            justify-content: center; z-index: 1000; padding: 0.75rem;
            overflow-y: auto;
        `;

        const errorDetails = this.normalizeStatus(violation) === 'failed' && detailedError ? `
            <div style="margin-top: 1rem; padding: 1rem; background: #fee; border-left: 3px solid #e74c3c; border-radius: 4px; text-align: left; max-height: 200px; overflow-y: auto;">
                <strong style="color: #c0392b; display: block; margin-bottom: 0.5rem;">Error Details:</strong>
                <pre style="margin: 0; font-size: 0.85rem; color: #7f8c8d; white-space: pre-wrap; word-wrap: break-word;">${detailedError}</pre>
            </div>
        ` : '';

        modal.innerHTML = `
            <div style="background: white; padding: 1.15rem; border-radius: 12px; max-width: 600px; width: min(96vw, 600px); text-align: center; max-height: 88vh; overflow-y: auto;">
                <style>
                    .report-stage-list { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; margin: 0.8rem 0 1rem 0; padding: 0; list-style: none; }
                    .report-stage-item { padding: 6px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; background: #e5e7eb; color: #4b5563; }
                    .report-stage-item.active { background: #f59e0b; color: #111827; }
                    .report-stage-item.done { background: #10b981; color: #ecfeff; }
                    .report-modal-actions { display: flex; gap: 0.65rem; justify-content: center; margin-top: 1rem; flex-wrap: wrap; }
                    .report-modal-actions .btn { flex: 1 1 180px; justify-content: center; }
                    @media (max-width: 560px), (max-height: 430px) and (orientation: landscape) {
                        #report-status-modal h2 { font-size: 1.1rem; }
                        .report-stage-item { font-size: 11px; padding: 5px 8px; }
                        .report-modal-actions { gap: 0.5rem; }
                        .report-modal-actions .btn { flex-basis: 100%; }
                    }
                </style>
                <div style="font-size: 4rem; color: var(--${statusInfo.color}-color); margin-bottom: 1rem;">
                    <i class="fas ${statusInfo.icon}"></i>
                </div>
                <h2 style="color: var(--text-color); margin-bottom: 0.5rem;">
                    Report ${statusInfo.text}
                </h2>
                <p id="report-modal-status" style="color: #7f8c8d; margin-bottom: 0.8rem;">
                    ${this.getStatusMessage(violation)}
                </p>
                <ul class="report-stage-list">
                    <li id="report-stage-ready" class="report-stage-item">Ready</li>
                    <li id="report-stage-queued" class="report-stage-item">Queued</li>
                    <li id="report-stage-generating" class="report-stage-item">Generating</li>
                    <li id="report-stage-completed" class="report-stage-item">Completed</li>
                </ul>
                <div id="report-modal-cooldown" style="display:none; margin-bottom: 0.5rem; font-size: 0.88rem; color: #b45309;"></div>
                <div id="report-modal-retries" style="margin-bottom: 0.8rem; font-size: 0.88rem; color: #374151;"></div>
                <div id="report-modal-eta" style="margin-bottom: 0.8rem; font-size: 0.88rem; color: #6b7280;"></div>
                <div id="report-modal-provider-warning" style="display:none; margin-bottom: 0.8rem; padding: 0.65rem 0.8rem; border: 1px solid #f59e0b; background: #fffbeb; color: #92400e; border-radius: 8px; font-size: 0.88rem; text-align: left;"></div>
                ${errorDetails}
                <div class="report-modal-actions">
                    <button onclick="ReportsPage.closeModal()" class="btn" style="background: #95a5a6;">
                        <i class="fas fa-times"></i> Close
                    </button>
                    <button id="report-modal-process-btn" onclick="ReportsPage.generateNow('${violation.report_id}', { force: ${processAction.force}, source: ${inlineViolation} })" class="btn btn-success">
                        <i class="fas ${processAction.icon}"></i> ${processAction.label}
                    </button>
                    ${!ready ? `
                        <button onclick="ReportsPage.checkAndRefresh('${violation.report_id}')" class="btn btn-primary">
                            <i class="fas fa-sync"></i> Check Status
                        </button>
                    ` : ''}
                    ${ready ? `
                        <button onclick="ReportsPage.openReport('${violation.report_id}', ${inlineViolation}); ReportsPage.closeModal();" class="btn btn-primary">
                            <i class="fas fa-file-alt"></i> Open Report
                        </button>
                    ` : this.normalizeStatus(violation) === 'failed' ? `
                        <button onclick="ReportsPage.viewPartialReport('${violation.report_id}')" class="btn btn-warning">
                            <i class="fas fa-eye"></i> View Available Data
                        </button>
                    ` : ''}
                </div>
            </div>
        `;

        modal.onclick = (e) => {
            if (e.target === modal) this.closeModal();
        };

        document.body.appendChild(modal);

        this.ensureModalRuntime(violation.report_id);
        this.updateModalRetryText();
        if (this.isQuotaOrRateLimitError(detailedError)) {
            this.setProviderWarning('Provider quota/rate limit detected. Report generation may be delayed. Please retry after quota reset or switch provider.');
        } else {
            this.setProviderWarning('');
        }
        const normalizedStatus = this.normalizeStatus(violation);
        if (ready) {
            this.setModalStage('completed');
        } else if (normalizedStatus === 'generating' || normalizedStatus === 'processing') {
            this.setModalStage('generating');
        } else if (normalizedStatus === 'pending' || normalizedStatus === 'queued') {
            this.setModalStage('queued');
        } else {
            this.setModalStage('ready');
        }
    },

    getStatusMessage(violation) {
        const status = this.normalizeStatus(violation);
        const ready = this.isReportReady(violation);

        if (ready) {
            return 'Report is ready. Click Open Report to view it.';
        }

        if (status === 'completed' && !this.hasReadableReportEvidence(violation)) {
            return 'Status says completed, but report file is not ready yet. Click Process Now to force generation.';
        }

        switch(status) {
            case 'generating':
                if (violation && violation.active_step) {
                    const elapsed = this.formatDuration(violation.active_elapsed_seconds);
                    const stageElapsed = this.formatDuration(violation.active_stage_elapsed_seconds);
                    const timingText = elapsed
                        ? ` Elapsed ${elapsed}${stageElapsed ? `; current step ${stageElapsed}` : ''}.`
                        : '';
                    return `${violation.active_step}.${timingText}`;
                }
                return 'The AI is analyzing the violation and generating a detailed report. Provider timing can vary by image caption and report-analysis latency.';
            case 'processing':
                if (violation && violation.active_step) {
                    const elapsed = this.formatDuration(violation.active_elapsed_seconds);
                    return `${violation.active_step}.${elapsed ? ` Elapsed ${elapsed}.` : ''}`;
                }
                return 'The report job is actively processing and generation is in progress.';
            case 'pending':
                if (violation && violation.active_report_id && String(violation.active_report_id) !== String(violation.report_id || '')) {
                    const elapsed = this.formatDuration(violation.active_elapsed_seconds);
                    return `Queued for generation. The worker is currently processing ${violation.active_report_id}${elapsed ? ` (${elapsed} elapsed)` : ''}.`;
                }
                if (violation && violation.queue_position) {
                    return `Queued for generation at position ${violation.queue_position}.`;
                }
                return 'This report is queued for processing. It will be generated shortly.';
            case 'queued':
                if (violation && violation.active_report_id && String(violation.active_report_id) !== String(violation.report_id || '')) {
                    const elapsed = this.formatDuration(violation.active_elapsed_seconds);
                    return `Queued for generation. The worker is currently processing ${violation.active_report_id}${elapsed ? ` (${elapsed} elapsed)` : ''}.`;
                }
                if (violation && violation.queue_position) {
                    return `Queued for generation at position ${violation.queue_position}.`;
                }
                return 'This report is queued for processing. It will be generated shortly.';
            case 'failed':
                return `Report generation failed. ${violation.error_message || 'Please try again or contact support.'}`;
            case 'skipped':
                return `Report was skipped. ${violation.error_message || 'The scene may not match a valid work environment.'}`;
            default:
                return 'The report is being processed. Please wait a moment.';
        }
    },

    ensureModalRuntime(reportId) {
        if (this.modalRuntime.reportId !== reportId) {
            this.stopModalPolling();
            this.stopModalCooldown();
            this.modalRuntime.reportId = reportId;
            this.modalRuntime.retryCount = 0;
            this.modalRuntime.quotaPromptedForReport = null;
            this.modalRuntime.lastPollStatus = null;
            this.modalRuntime.cooldownUntil = 0;
            this.modalRuntime.pollStartedAt = 0;
            this.modalRuntime.sawGeneratingStage = false;
        }
        return this.modalRuntime;
    },

    formatDuration(seconds) {
        const value = Number(seconds || 0);
        if (!Number.isFinite(value) || value <= 0) return '';
        const total = Math.floor(value);
        if (total < 60) return `${total}s`;
        const mins = Math.floor(total / 60);
        const secs = total % 60;
        return secs ? `${mins}m ${secs}s` : `${mins}m`;
    },

    updateModalEtaText() {
        const etaEl = document.getElementById('report-modal-eta');
        if (!etaEl) return;

        if (!this.modalRuntime.pollStartedAt) {
            etaEl.textContent = '';
            return;
        }

        const elapsedSec = Math.max(0, Math.floor((Date.now() - this.modalRuntime.pollStartedAt) / 1000));
        etaEl.textContent = `Elapsed: ${this.formatDuration(elapsedSec) || '0s'} | Current provider/runtime speed may vary by caption and report analysis.`;
    },

    setModalStatusText(message) {
        const el = document.getElementById('report-modal-status');
        if (el) el.textContent = message;
    },

    setModalStage(stage) {
        const order = ['ready', 'queued', 'generating', 'completed'];
        const stageIndex = order.indexOf(stage);
        order.forEach((name, index) => {
            const el = document.getElementById(`report-stage-${name}`);
            if (!el) return;
            el.classList.remove('active', 'done');
            if (stageIndex >= 0 && index < stageIndex) el.classList.add('done');
            if (name === stage) el.classList.add('active');
            if (stage === 'completed' && name === 'completed') {
                el.classList.remove('active');
                el.classList.add('done');
            }
        });
    },

    updateModalRetryText() {
        const el = document.getElementById('report-modal-retries');
        if (!el) return;
        el.textContent = `Retries used: ${this.modalRuntime.retryCount} / ${this.modalRuntime.maxRetries}`;
    },

    setModalProcessButtonEnabled(enabled) {
        const btn = document.getElementById('report-modal-process-btn');
        if (btn) btn.disabled = !enabled;
    },

    isQuotaOrRateLimitError(message) {
        const text = String(message || '').toLowerCase();
        if (!text) return false;
        return (
            text.includes('resource_exhausted') ||
            text.includes('quota') ||
            text.includes('rate limit') ||
            text.includes('429') ||
            text.includes('exceeded your current quota')
        );
    },

    setProviderWarning(message) {
        const el = document.getElementById('report-modal-provider-warning');
        if (!el) return;
        if (!message) {
            el.style.display = 'none';
            el.textContent = '';
            return;
        }
        el.style.display = 'block';
        el.textContent = message;
    },

    async promptQuotaRecovery(reportId, sourceError = '') {
        const runtime = this.ensureModalRuntime(reportId);
        if (runtime.quotaPromptedForReport === reportId) {
            return;
        }
        runtime.quotaPromptedForReport = reportId;

        const options = await API.getReportRecoveryOptions();
        if (!options || options.success === false) {
            this.setModalStatusText('Quota recovery options unavailable. You can retry manually.');
            return;
        }

        const local = options.local || {};
        const counts = options.counts || {};
        let localReady = !!local.local_mode_possible;
        const pullHint = local.pull_command || 'ollama pull llama3';
        const startHint = local.start_command || 'ollama serve';
        const installUrl = local.install_url || 'https://ollama.com/download';
        const installCommands = Array.isArray(local.install_commands) && local.install_commands.length
            ? local.install_commands.join('\n- ')
            : 'winget install Ollama.Ollama';

        let chooseLocal = false;
        if (localReady) {
            const recoveryChoice = window.confirm(
                `Provider quota is exhausted. Pending candidates: ${counts.total_candidates || 0}.\n\nRecommended: use FAILOVER pipeline now for highest chance of completion.\n\nOK = Use failover pipeline now\nCancel = Try Local mode first`
            );
            chooseLocal = !recoveryChoice;
        } else {
            const tryAutoSetup = window.confirm(
                `Provider quota is exhausted and Local mode is not ready yet.\n\nTry automatic setup now?\nThis will attempt to:\n1) start Ollama if installed\n2) pull required model\n3) switch provider routing to local-first\n\nOK = Try automatic setup\nCancel = Skip and use failover`
            );

            if (tryAutoSetup) {
                this.setModalStatusText('Preparing LOCAL mode (auto-start + model setup)...');
                const prep = await API.prepareLocalMode({
                    autoPull: true,
                    setLocalFirst: true,
                    waitSeconds: 10,
                    pullTimeoutSeconds: 900
                });

                if (prep && prep.success === true) {
                    localReady = true;
                    chooseLocal = true;
                } else {
                    const prepErr = String((prep && prep.error) || (prep && prep.message) || 'Local mode bootstrap failed');
                    const after = (prep && prep.after) || {};
                    const missingInstall = after.ollama_installed === false || local.ollama_installed === false;
                    const installHelp = missingInstall
                        ? `\n\nOllama appears not installed on this machine.\nInstall from: ${installUrl}\n\nOr run:\n- ${installCommands}\n\nThen reopen app and retry automatic setup.`
                        : '';

                    const continueFailoverAfterPrepFail = window.confirm(
                        `Automatic local setup failed: ${prepErr}${installHelp}\n\nRun failover pipeline for pending reports now?`
                    );

                    if (!continueFailoverAfterPrepFail) {
                        this.setModalStatusText('Recovery paused. You can retry automatic local setup from the report modal.');
                        return;
                    }
                }
            }
        }

        if (chooseLocal) {
            this.setModalStatusText('Preparing LOCAL mode (starting Ollama / pulling model if needed)...');
            const prep = await API.prepareLocalMode({
                autoPull: true,
                setLocalFirst: true,
                waitSeconds: 8,
                pullTimeoutSeconds: 600
            });

            if (!prep || prep.success !== true) {
                const prepErr = String((prep && prep.error) || (prep && prep.message) || 'Local mode bootstrap failed');
                const continueFailoverAfterPrepFail = window.confirm(
                    `Automatic local-mode setup failed: ${prepErr}\n\nRun failover pipeline for pending reports now?`
                );
                if (!continueFailoverAfterPrepFail) {
                    this.setModalStatusText('Recovery paused. You can retry local setup from the report modal.');
                    return;
                }
            }

            this.setModalStatusText('Applying LOCAL mode and re-queuing pending/quota-failed reports...');
            const res = await API.executeReportRecovery('local');
            if (res && res.success) {
                this.notify(`Local recovery started: ${res.enqueued}/${res.total_candidates} queued`, 'success');
                this.setProviderWarning('Local mode recovery approved. Monitoring queue progress...');
                await this.refreshReports();
                this.startModalPolling(reportId, { autoOpen: true });
                return;
            }

            const err = String((res && res.error) || sourceError || 'Local recovery failed');
            const continueFailover = window.confirm(
                `Local mode could not be started: ${err}\n\nRun failover pipeline for pending reports now?`
            );
            if (!continueFailover) {
                this.setModalStatusText('Recovery paused. You can retry after preparing local mode.');
                return;
            }
        } else if (!localReady) {
            const proceedFailoverNoLocal = window.confirm(
                `Provider quota is exhausted and Local mode is not ready on this backend.\n\nTo prepare local mode later:\n1) ${startHint}\n2) ${pullHint}\n\nIf Ollama is not installed:\n- Download: ${installUrl}\n- Command: ${installCommands}\n\nProceed with failover pipeline now?`
            );
            if (!proceedFailoverNoLocal) {
                this.setModalStatusText('Recovery paused. Prepare local mode and retry when ready.');
                return;
            }
        }

        const approveFailover = window.confirm(
            'Proceed with failover pipeline for pending/quota-failed reports?\n\nThis keeps generation running after your approval.'
        );
        if (!approveFailover) {
            this.setModalStatusText('Failover not approved. Report remains pending/manual retry.');
            return;
        }

        this.setModalStatusText('Applying FAILOVER mode and re-queuing pending/quota-failed reports...');
        const failoverRes = await API.executeReportRecovery('failover');
        if (failoverRes && failoverRes.success) {
            this.notify(`Failover recovery started: ${failoverRes.enqueued}/${failoverRes.total_candidates} queued`, 'success');
            this.setProviderWarning('Failover recovery approved. Monitoring queue progress...');
            await this.refreshReports();
            this.startModalPolling(reportId, { autoOpen: true });
            return;
        }

        const failoverError = String((failoverRes && failoverRes.error) || 'Failover recovery failed');
        this.setModalStatusText(failoverError);
        this.notify(failoverError, 'error');
    },

    stopModalPolling() {
        if (this.modalRuntime.pollTimer) {
            clearInterval(this.modalRuntime.pollTimer);
            this.modalRuntime.pollTimer = null;
        }
        this.modalRuntime.pollStartedAt = 0;
        this.updateModalEtaText();
    },

    stopModalCooldown() {
        if (this.modalRuntime.cooldownTimer) {
            clearInterval(this.modalRuntime.cooldownTimer);
            this.modalRuntime.cooldownTimer = null;
        }
        const cooldownEl = document.getElementById('report-modal-cooldown');
        if (cooldownEl) cooldownEl.style.display = 'none';
    },

    startModalCooldown(seconds) {
        this.stopModalCooldown();
        let remaining = seconds;
        this.modalRuntime.cooldownUntil = Date.now() + (seconds * 1000);
        this.notify(`Queue busy. Retry available in ${remaining}s.`, 'warning');

        const cooldownEl = document.getElementById('report-modal-cooldown');
        if (cooldownEl) {
            cooldownEl.style.display = 'block';
            cooldownEl.textContent = `Queue busy. Retry available in ${remaining}s...`;
        }

        this.setModalProcessButtonEnabled(false);
        this.modalRuntime.cooldownTimer = setInterval(() => {
            remaining -= 1;
            if (remaining <= 0) {
                this.stopModalCooldown();
                this.setModalProcessButtonEnabled(this.modalRuntime.retryCount < this.modalRuntime.maxRetries);
                return;
            }
            if (cooldownEl) {
                cooldownEl.textContent = `Queue busy. Retry available in ${remaining}s...`;
            }
        }, 1000);
    },

    async pollReportProgress(reportId, { autoOpen = false } = {}) {
        const sourceHint = this.violations.find((v) => String(v.report_id) === String(reportId)) || null;
        const data = await API.getReportStatus(reportId, { source: sourceHint, noCache: true, timeoutMs: 6000 });
        const dataHasReport = this.hasReadableReportEvidence(data) || this.hasReadableReportEvidence(sourceHint);
        const status = this.normalizeStatusValue(data && data.status, dataHasReport);
        const providerError = data && data.error_message ? String(data.error_message) : '';
        const alertMessage = data && data.alert_message ? String(data.alert_message) : '';
        const runtime = this.ensureModalRuntime(reportId);
        const latestSourceHint = this.upsertReportRuntimeState(reportId, {
            ...(data && typeof data === 'object' ? data : {}),
            status,
            has_report: dataHasReport,
            source_scope: (data && data.source_scope) || (sourceHint && sourceHint.source_scope) || ''
        }, sourceHint) || sourceHint;

        if (runtime.lastPollStatus !== status) {
            if (status === 'pending' || status === 'queued') {
                this.notify(`Report ${reportId} is queued for generation.`, 'info');
            } else if (status === 'generating' || status === 'processing') {
                if (typeof NotificationManager !== 'undefined' && typeof NotificationManager.reportGenerating === 'function') {
                    NotificationManager.reportGenerating(reportId, {
                        title: 'Generating Report',
                        action: {
                            text: 'View Progress',
                            onClickFn: () => this.focusReport(reportId, { openModal: true })
                        }
                    });
                }
            } else if (status === 'completed' && dataHasReport) {
                if (typeof NotificationManager !== 'undefined' && typeof NotificationManager.reportReady === 'function') {
                    NotificationManager.reportReady(reportId, {
                        action: {
                            text: 'Open Report',
                            onClickFn: () => this.openReport(reportId, latestSourceHint)
                        }
                    });
                }
            } else if (status === 'failed' || status === 'partial' || status === 'skipped') {
                this.notify(`Report ${reportId} status changed to ${status}. Retry is available.`, 'warning');
            }
            runtime.lastPollStatus = status;
        }

        if (this.isQuotaOrRateLimitError(providerError)) {
            this.setProviderWarning('Provider quota/rate limit detected. Generation is waiting on provider availability.');
            if (status === 'failed') {
                await this.promptQuotaRecovery(reportId, providerError);
            }
        } else {
            this.setProviderWarning('');
        }

        if (status === 'pending' || status === 'queued') {
            this.setModalStage('queued');
            this.setModalStatusText((data && data.message) || 'Report is queued for generation...');
            return false;
        }

        if (status === 'generating' || status === 'processing') {
            runtime.sawGeneratingStage = true;
            this.setModalStage('generating');
            this.setModalStatusText((data && data.message) || 'AI is generating your report...');
            if (alertMessage) {
                this.setProviderWarning(alertMessage);
            }
            return false;
        }

        if (status === 'completed' && dataHasReport) {
            if (
                !runtime.sawGeneratingStage
                && runtime.lastPollStatus
                && runtime.lastPollStatus !== 'generating'
                && Number(this.modalRuntime.minGeneratingDisplayMs || 0) > 0
            ) {
                runtime.sawGeneratingStage = true;
                this.setModalStage('generating');
                this.setModalStatusText('AI finished generating your report. Finalizing view...');
                await new Promise((resolve) => setTimeout(
                    resolve,
                    Math.max(300, Number(this.modalRuntime.minGeneratingDisplayMs || 650))
                ));
            }
            this.setModalStage('completed');
            this.setModalStatusText('Report completed. Opening now...');
            await this.loadReports({ noCache: true, targetedReportId: reportId });
            if (autoOpen) {
                const refreshedSourceHint = this.violations.find((v) => String(v.report_id) === String(reportId)) || latestSourceHint;
                this.openReport(reportId, refreshedSourceHint);
                this.closeModal();
            }
            return true;
        }

        if (status === 'failed' || status === 'partial' || status === 'skipped') {
            this.setModalStatusText(`Generation status: ${status}. You can retry.`);
            this.setModalProcessButtonEnabled(this.modalRuntime.retryCount < this.modalRuntime.maxRetries);
            return true;
        }

        return false;
    },

    startModalPolling(reportId, opts = {}) {
        this.stopModalPolling();
        const startedAt = Date.now();
        this.modalRuntime.pollStartedAt = startedAt;
        this.updateModalEtaText();
        this.modalRuntime.pollTimer = setInterval(async () => {
            this.updateModalEtaText();
            const done = await this.pollReportProgress(reportId, opts);
            if (done) {
                this.stopModalPolling();
                return;
            }
            if (Date.now() - startedAt > this.modalRuntime.maxWaitMs) {
                this.stopModalPolling();
                this.setModalStatusText('Still processing. You can check status again or retry in a moment.');
                this.setModalProcessButtonEnabled(this.modalRuntime.retryCount < this.modalRuntime.maxRetries);
            }
        }, this.modalRuntime.pollIntervalMs);
    },

    closeModal() {
        this.stopModalPolling();
        this.stopModalCooldown();
        const modal = document.getElementById('report-status-modal');
        if (modal) modal.remove();
    },

    async checkAndRefresh(reportId) {
        this.closeModal();
        await this.refreshReports();

        // Find the updated violation
        const violation = this.violations.find(v => v.report_id === reportId);
        if (violation && this.isReportReady(violation)) {
            this.openReport(reportId);
        } else if (violation) {
            this.showGeneratingModal(violation);
        }
    },

    viewPartialReport(reportId) {
        this.closeModal();
        // Navigate to violation detail page with available images
        window.location.hash = `#/violation/${reportId}`;
    },

    getProcessAction(violation) {
        const status = this.normalizeStatus(violation);
        const isReprocess = status === 'completed'
            || status === 'failed'
            || status === 'skipped'
            || status === 'partial'
            // Stuck queued/pending reports also need force=true so the backend
            // re-enqueues them instead of returning an early 'already_queued'.
            || status === 'pending'
            || status === 'queued';

        return {
            force: isReprocess,
            label: isReprocess ? 'Reprocess Now' : 'Process Now',
            icon: isReprocess ? 'fa-rotate-right' : 'fa-bolt'
        };
    },

    async generateNow(reportId, options = {}) {
        const runtime = this.ensureModalRuntime(reportId);
        const now = Date.now();

        if (runtime.retryCount >= runtime.maxRetries) {
            this.setModalStatusText('Maximum retries reached. Please wait before trying again.');
            this.setModalProcessButtonEnabled(false);
            this.notify('Maximum retries reached for this report.', 'warning');
            return;
        }

        if (runtime.cooldownUntil && now < runtime.cooldownUntil) {
            const waitSeconds = Math.max(1, Math.ceil((runtime.cooldownUntil - now) / 1000));
            this.setModalStatusText(`Queue is busy. Retry available in ${waitSeconds}s.`);
            this.setModalProcessButtonEnabled(false);
            this.notify(`Queue is still busy. Retry in ${waitSeconds}s.`, 'warning');
            return;
        }

        this.setModalProcessButtonEnabled(false);
        this.setModalStage('queued');
        this.setModalStatusText('Submitting request to queue...');

        try {
            const sourceHint = options.source || options.violation || this.violations.find((v) => String(v.report_id) === String(reportId)) || null;
            const sourceScope = this.inferSourceScope(sourceHint);
            this.upsertReportRuntimeState(reportId, {
                status: 'pending',
                has_report: false,
                source_scope: sourceScope
            }, sourceHint);
            const result = await API.generateReportNow(reportId, {
                force: !!options.force,
                source: sourceHint
            });
            if (!result || !result.success) {
                runtime.retryCount += 1;
                this.updateModalRetryText();

                const errorText = String(result?.error || 'Failed to prioritize report generation');
                const rejectedReason = String(result?.rejected_reason || '').trim().toLowerCase();
                const httpStatus = Number(result?.http_status || 0);
                const queueSize = Number(result?.queue_size || 0);
                const queueBusy = rejectedReason === 'queue_full'
                    || rejectedReason === 'rate_limited'
                    || (/queue|busy|rate|limit|full|capacity|409|429/i.test(errorText) && httpStatus !== 503);
                if (this.isQuotaOrRateLimitError(errorText)) {
                    this.setProviderWarning('Provider quota/rate limit detected. Awaiting your recovery choice.');
                    await this.promptQuotaRecovery(reportId, errorText);
                }

                if (httpStatus === 503 || result?.worker_running === false) {
                    this.setModalStatusText('Queue worker is not running. Please restart local backend and retry.');
                    this.setModalProcessButtonEnabled(runtime.retryCount < runtime.maxRetries);
                    this.notify('Queue worker is not running. Restart backend and retry.', 'error');
                    return;
                }

                if (queueBusy) {
                    const busyMessage = (rejectedReason === 'rate_limited' && queueSize <= 0)
                        ? 'Queue appears idle but this request was rate-limited. Please retry in a moment.'
                        : `Queue busy: ${errorText}`;
                    this.setModalStatusText(busyMessage);
                    this.notify(`Queue busy for report ${reportId}. Monitoring in progress.`, 'warning');
                    this.startModalCooldown(runtime.cooldownSeconds);
                    return;
                }

                this.setModalStatusText(errorText);
                this.upsertReportRuntimeState(reportId, {
                    status: 'failed',
                    has_report: false,
                    error_message: errorText,
                    source_scope: sourceScope
                }, sourceHint);
                this.setModalProcessButtonEnabled(runtime.retryCount < runtime.maxRetries);
                this.notify(errorText, 'error');
                return;
            }

            // Surface the actual backend outcome so users aren't told "started"
            // when the request was actually a no-op (already queued / already
            // completed). Otherwise the UI looks broken when a stuck report
            // returns success without anything happening.
            let successMessage;
            let successLevel = 'success';
            if (result.already_completed) {
                successMessage = 'Report is already completed.';
                successLevel = 'info';
            } else if (result.already_queued) {
                successMessage = 'Report is already queued or generating; awaiting the worker.';
                successLevel = 'info';
            } else {
                successMessage = options.force ? 'Reprocess started successfully' : 'Report generation started successfully';
            }
            this.notify(successMessage, successLevel);
            this.stopModalCooldown();
            this.setModalStage('queued');
            this.setModalStatusText('Regeneration queued. Monitoring progress...');
            this.upsertReportRuntimeState(reportId, {
                status: result.already_completed ? 'completed' : (result.status || 'pending'),
                has_report: !!(result.already_completed || result.has_report),
                source_scope: result.source_scope || sourceScope,
                source_label: result.source_label || '',
                source_reason: result.routed_via_cloud_fallback ? 'manual_cloud_reprocess_fallback' : '',
                routed_via_cloud_fallback: !!result.routed_via_cloud_fallback
            }, sourceHint);
            if (typeof NotificationManager !== 'undefined' && typeof NotificationManager.reportGenerating === 'function') {
                NotificationManager.reportGenerating(reportId, {
                    title: options.force ? 'Reprocessing Started' : 'Generation Started',
                    action: {
                        text: 'View Progress',
                        onClickFn: () => this.focusReport(reportId, { openModal: true })
                    }
                });
            }
            await this.refreshReports();
            this.startModalPolling(reportId, { autoOpen: true });
        } catch (error) {
            console.error('Process/reprocess request failed:', error);
            runtime.retryCount += 1;
            this.updateModalRetryText();
            this.setModalStatusText('Failed to prioritize report generation');
            const sourceHint = options.source || options.violation || this.violations.find((v) => String(v.report_id) === String(reportId)) || null;
            this.upsertReportRuntimeState(reportId, {
                status: 'failed',
                has_report: false,
                error_message: 'Failed to prioritize report generation',
                source_scope: this.inferSourceScope(sourceHint)
            }, sourceHint);
            this.setModalProcessButtonEnabled(runtime.retryCount < runtime.maxRetries);
            this.notify('Failed to prioritize report generation', 'error');
        }
    },

    renderReportCard(violation) {
        const timestamp = violation && violation.timestamp ? violation.timestamp : null;
        const reportTime = timestamp
            ? ((typeof TimezoneManager !== 'undefined' && typeof TimezoneManager.formatDateTime === 'function')
                ? TimezoneManager.formatDateTime(timestamp)
                : new Date(timestamp).toLocaleString())
            : 'Unknown time';
        const originalImageUrl = API.getImageUrl(violation.report_id, 'original.jpg', violation);
        const annotatedImageUrl = API.getImageUrl(violation.report_id, 'annotated.jpg', violation);
        const imageUrl = violation.local_image_url || (violation.has_annotated ? annotatedImageUrl : originalImageUrl);
        const fallbackImageUrl = (!violation.local_image_url && violation.has_annotated && violation.has_original)
            ? originalImageUrl
            : '';
        const hasPreviewImage = Boolean(violation.local_image_url || violation.has_annotated || violation.has_original);
        const statusInfo = this.getStatusInfo(violation);
        const sourceInfo = this.getSourceInfo(violation);
        const sourceScope = this.inferSourceScope(violation);
        const syncInfo = this.getSyncInfo(violation, sourceScope);
        const inlineViolation = this.encodeInlineReportPayload(violation);
        const deviceId = String((violation && violation.device_id) || '').trim();
        const deviceKey = deviceId.toLowerCase();
        const shouldShowDevice = Boolean(deviceId) && !(
            sourceScope === 'cloud'
            && (deviceKey === 'local_cache' || deviceKey === 'offline_local_cache')
        );
        const isReady = this.isReportReady(violation);
        const processAction = this.getProcessAction(violation);
        const missingPpeLabels = (typeof API !== 'undefined' && typeof API.extractMissingPpeLabels === 'function')
            ? API.extractMissingPpeLabels(violation)
            : (Array.isArray(violation.missing_ppe) ? violation.missing_ppe : []);
        const displayViolationCount = Number(violation.violation_count || missingPpeLabels.length || 0);
        const severityClass = (violation.severity === 'HIGH' || violation.severity === 'CRITICAL') ? 'danger' :
                             (violation.severity === 'MEDIUM' ? 'warning' : 'info');

                return `
            <div class="report_card ${sourceScope === 'local' ? 'report-card-local' : ''}" id="report-${violation.report_id}"
                 style="cursor: pointer; ${!isReady ? 'opacity: 0.9;' : ''}"
                 onclick="ReportsPage.handleReportClick(${inlineViolation})">
                <div style="height: 200px; overflow: hidden; background: #000; position: relative;">
                    ${hasPreviewImage ?
                        `<img src="${imageUrl}" alt="Violation" loading="lazy" decoding="async"
                               data-fallback-src="${fallbackImageUrl}"
                               onerror="if(this.dataset.fallbackSrc){this.src=this.dataset.fallbackSrc; this.dataset.fallbackSrc=''; return;} if(this.dataset.fallbackDone==='1') return; this.dataset.fallbackDone='1'; this.style.display='none'; const fallback=this.parentElement&&this.parentElement.querySelector('[data-image-fallback]'); if(fallback){fallback.style.display='flex';}"
                               style="width: 100%; height: 100%; object-fit: cover;">
                         <div data-image-fallback style="display: none; align-items: center; justify-content: center; height: 100%;">
                            <i class="fas fa-image" style="font-size: 3rem; color: #fff; opacity: 0.3;"></i>
                         </div>` :
                        `<div data-image-fallback style="display: flex; align-items: center; justify-content: center; height: 100%;">
                            <i class="fas fa-image" style="font-size: 3rem; color: #fff; opacity: 0.3;"></i>
                         </div>`
                    }
                    ${!isReady ? `
                        <div style="position: absolute; top: 0; left: 0; right: 0; bottom: 0;
                                    background: rgba(0,0,0,0.4); display: flex; align-items: center;
                                    justify-content: center;">
                            <div style="color: white; text-align: center;">
                                <i class="fas ${statusInfo.icon}" style="font-size: 2rem;"></i>
                                <p style="margin: 0.5rem 0 0 0;">${statusInfo.text}</p>
                            </div>
                        </div>
                    ` : ''}
                    <div class="report-source-indicator" style="position: absolute; top: 0.5rem; left: 0.5rem; z-index: 10;">
                        <span class="badge badge-${sourceInfo.color}" style="box-shadow: 0 2px 4px rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.2);">
                            <i class="fas ${sourceInfo.icon}"></i> ${sourceInfo.label}
                        </span>
                    </div>
                </div>
                <div class="card-content">
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 1rem;">
                        <div style="flex: 1;">
                            <h3 style="color: var(--primary-color); margin-bottom: 0.5rem; font-size: 1.1rem;">
                                Report #${violation.report_id}
                            </h3>
                            <p style="color: #7f8c8d; font-size: 0.9rem; margin: 0;">
                                <i class="fas fa-clock"></i> ${reportTime}
                            </p>
                        </div>
                        <span class="badge badge-${severityClass}">
                            ${violation.severity || 'High'}
                        </span>
                    </div>

                    <div style="display: flex; gap: 0.4rem; flex-wrap: wrap; margin-bottom: 1rem;">
                        <span class="badge badge-${statusInfo.color}">
                            <i class="fas ${statusInfo.icon}"></i> ${statusInfo.text}
                        </span>
                        ${syncInfo ? `<span class="badge badge-${syncInfo.color}" title="${syncInfo.title}">
                            <i class="fas ${syncInfo.icon}"></i> ${syncInfo.label}
                        </span>` : ''}
                        ${violation.has_original ? '<span class="badge badge-success"><i class="fas fa-image"></i> Original</span>' : ''}
                        ${violation.has_annotated ? '<span class="badge badge-success"><i class="fas fa-draw-polygon"></i> Annotated</span>' : ''}
                    </div>

                    <div style="padding-top: 1rem; border-top: 1px solid var(--border-color);">
                        <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.9rem;">
                            <button class="btn btn-primary" style="padding: 0.45rem 0.75rem; font-size: 0.85rem;"
                                onclick="event.stopPropagation(); ReportsPage.generateNow('${violation.report_id}', { force: ${processAction.force}, source: ${inlineViolation} });">
                                <i class="fas ${processAction.icon}"></i> ${processAction.label}
                            </button>
                            ${isReady ? `
                                <button class="btn btn-secondary" style="padding: 0.45rem 0.75rem; font-size: 0.85rem;"
                                    onclick="event.stopPropagation(); ReportsPage.openReport('${violation.report_id}', ${inlineViolation});">
                                    <i class="fas fa-file-alt"></i> Open Report
                                </button>
                            ` : ''}
                        </div>

                        <p style="margin: 0; color: var(--text-color); font-size: 0.9rem;">
                            <i class="fas fa-exclamation-triangle" style="color: var(--error-color);"></i>
                            <strong>${displayViolationCount} Violation${displayViolationCount !== 1 ? 's' : ''}</strong>
                        </p>
                        ${missingPpeLabels.length > 0 ? `
                            <div style="margin-top: 0.75rem; display: flex; gap: 0.5rem; flex-wrap: wrap;">
                                ${missingPpeLabels.map(ppe => `
                                    <span class="badge badge-danger" style="font-size: 0.75rem;">
                                        <i class="fas fa-times-circle"></i> No ${ppe}
                                    </span>
                                `).join('')}
                            </div>
                        ` : `
                            <p style="margin: 0.5rem 0 0 0; color: #7f8c8d; font-size: 0.85rem;">
                                ${violation.violation_summary || 'PPE Violation'}
                            </p>
                        `}
                        ${shouldShowDevice ? `
                            <p style="margin: 0.5rem 0 0 0; color: #95a5a6; font-size: 0.8rem;">
                                <i class="fas fa-desktop"></i> Device: ${deviceId}
                            </p>
                        ` : ''}
                    </div>
                </div>
            </div>
        `;
    }
};
