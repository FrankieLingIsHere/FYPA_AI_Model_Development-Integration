// Violation Monitor - Smart Notification System
// ==============================================
// NOTIFICATION BEHAVIOR:
// - On page load: ONE summary notification for new violations since last visit
// - During session: Specific real-time notifications ONLY for live detections
//   (detected through live monitor or image upload during this session)

const ViolationMonitor = {
    isMonitoring: false,
    checkInterval: null,
    knownViolations: new Map(),      // Map of reportId -> {status, timestamp}
    notifiedEvents: new Set(),        // Track which events we've notified about
    sessionStartTime: null,           // When this session started
    isInitialLoad: true,              // First load flag - shows summary only
    lastVisitTime: null,              // From localStorage
    isChecking: false,
    pendingCheckOptions: null,
    inFlightStatusTimer: null,
    inFlightStatusInProgress: false,
    inFlightStatusIntervalMs: 15000,

    // LocalStorage key for tracking last visit
    STORAGE_KEY: 'casm_last_visit_time',

    start() {
        if (this.isMonitoring) return;

        this.isMonitoring = true;
        this.isInitialLoad = true;
        this.sessionStartTime = new Date();
        this.knownViolations = new Map();
        this.notifiedEvents = new Set();
        this.isChecking = false;
        this.pendingCheckOptions = null;

        // Get last visit time from localStorage
        this.lastVisitTime = this._getLastVisitTime();

        // Initial check - will show summary notification only
        this.checkForNewViolations({ noCache: true, reason: 'initial-load' });

        // Egress guard:
        //  - Default polling cadence raised from 3s -> 15s (5x reduction in API hits).
        //  - When the Realtime websocket is connected, the server already pushes
        //    new violations, so timed polling is purely a fallback and can run far
        //    less aggressively (60s).
        //  - When the tab is hidden (background tab), suspend polling entirely;
        //    the next checkForNewViolations() runs on visibilitychange.
        const POLL_INTERVAL_ACTIVE_MS = 15000;
        const POLL_INTERVAL_REALTIME_MS = 60000;
        const computePollInterval = () => {
            if (typeof document !== 'undefined' && document.hidden) return null;
            const realtimeConnected = typeof RealtimeSync !== 'undefined' && !!RealtimeSync.isConnected;
            return realtimeConnected ? POLL_INTERVAL_REALTIME_MS : POLL_INTERVAL_ACTIVE_MS;
        };
        const armPolling = () => {
            if (this.checkInterval) {
                clearInterval(this.checkInterval);
                this.checkInterval = null;
            }
            const intervalMs = computePollInterval();
            if (!intervalMs) return;
            this.checkInterval = setInterval(() => {
                this.checkForNewViolations({ reason: 'poll' });
            }, intervalMs);
        };
        armPolling();

        this._pollAdjustHandler = () => {
            armPolling();
            if (typeof document === 'undefined' || !document.hidden) {
                this.checkForNewViolations({ reason: 'visibility-or-realtime-connection' });
            }
        };
        window.addEventListener('ppe-realtime:connection', this._pollAdjustHandler);
        if (typeof document !== 'undefined') {
            document.addEventListener('visibilitychange', this._pollAdjustHandler);
        }

        // Save visit time when user leaves
        window.addEventListener('beforeunload', () => this._saveVisitTime());

        console.log('[ViolationMonitor] Started monitoring');
        console.log(`[ViolationMonitor] Last visit: ${this.lastVisitTime ? this.lastVisitTime.toLocaleString() : 'First visit'}`);
        console.log(`[ViolationMonitor] Session start: ${this.sessionStartTime.toLocaleString()}`);
    },

    stop() {
        if (!this.isMonitoring) return;

        this.isMonitoring = false;
        this._saveVisitTime();

        if (this.checkInterval) {
            clearInterval(this.checkInterval);
            this.checkInterval = null;
        }

        if (this._pollAdjustHandler) {
            window.removeEventListener('ppe-realtime:connection', this._pollAdjustHandler);
            if (typeof document !== 'undefined') {
                document.removeEventListener('visibilitychange', this._pollAdjustHandler);
            }
            this._pollAdjustHandler = null;
        }
        if (this.inFlightStatusTimer) {
            clearInterval(this.inFlightStatusTimer);
            this.inFlightStatusTimer = null;
        }

        console.log('[ViolationMonitor] Stopped monitoring');
    },

    hasTrackedInFlightReports() {
        for (const item of this.knownViolations.values()) {
            if (!item || item.watchStatus !== true) continue;
            const status = this.normalizeStatusValue(item && item.status);
            if (status === 'pending' || status === 'generating') {
                return true;
            }
        }
        return false;
    },

    syncInFlightStatusFallback() {
        if (!this.isMonitoring) return;
        if (!this.hasTrackedInFlightReports()) {
            if (this.inFlightStatusTimer) {
                clearInterval(this.inFlightStatusTimer);
                this.inFlightStatusTimer = null;
            }
            return;
        }

        if (this.inFlightStatusTimer) return;
        this.inFlightStatusTimer = setInterval(() => {
            this.pollInFlightReportStatuses();
        }, this.inFlightStatusIntervalMs);
    },

    async pollInFlightReportStatuses() {
        if (this.inFlightStatusInProgress) return;
        if (typeof API === 'undefined' || typeof API.getReportStatus !== 'function') return;
        if (typeof document !== 'undefined' && document.hidden) return;

        const candidates = Array.from(this.knownViolations.entries())
            .filter(([, item]) => {
                if (!item || item.watchStatus !== true) return false;
                const status = this.normalizeStatusValue(item && item.status);
                return status === 'pending' || status === 'generating';
            })
            .slice(0, 3);
        if (!candidates.length) {
            this.syncInFlightStatusFallback();
            return;
        }

        this.inFlightStatusInProgress = true;
        try {
            await Promise.allSettled(candidates.map(async ([reportId, tracked]) => {
                const data = await API.getReportStatus(reportId, {
                    source: { report_id: reportId, source_scope: 'cloud' },
                    noCache: true,
                    timeoutMs: 6000
                });
                if (!data || typeof data !== 'object') return;

                const previousStatus = this.normalizeStatusValue(tracked && tracked.status);
                const nextStatus = this.normalizeStatusValue(data.status, !!data.has_report);
                if (!nextStatus || nextStatus === previousStatus) return;

                const previousTimestamp = tracked && tracked.timestamp instanceof Date
                    ? tracked.timestamp
                    : this.parseEventDate(tracked && tracked.timestamp);
                const violation = {
                    ...data,
                    report_id: reportId,
                    status: nextStatus,
                    has_report: !!data.has_report,
                    timestamp: previousTimestamp || new Date()
                };
                const shouldNotify = this.isLifecycleEventDuringSession(violation)
                    || (previousTimestamp && this.sessionStartTime && previousTimestamp >= this.sessionStartTime);

                this.knownViolations.set(reportId, {
                    status: nextStatus,
                    timestamp: previousTimestamp || new Date(),
                    watchStatus: nextStatus === 'pending' || nextStatus === 'generating'
                });

                if (typeof window !== 'undefined') {
                    window.dispatchEvent(new CustomEvent('ppe-report-status:update', {
                        detail: violation
                    }));
                }

                if (!shouldNotify) return;
                if (nextStatus === 'generating' && previousStatus === 'pending') {
                    this._notifyReportGenerating(violation);
                } else if (nextStatus === 'completed' && data.has_report) {
                    this._notifyReportReady(violation);
                } else if (nextStatus === 'failed' || nextStatus === 'partial' || nextStatus === 'skipped') {
                    this._notifyReportFailed(violation);
                }
            }));
        } finally {
            this.inFlightStatusInProgress = false;
            this.syncInFlightStatusFallback();
        }
    },

    _getLastVisitTime() {
        try {
            const stored = localStorage.getItem(this.STORAGE_KEY);
            return stored ? new Date(stored) : null;
        } catch (e) {
            console.warn('[ViolationMonitor] Could not read localStorage:', e);
            return null;
        }
    },

    _saveVisitTime() {
        try {
            localStorage.setItem(this.STORAGE_KEY, new Date().toISOString());
        } catch (e) {
            console.warn('[ViolationMonitor] Could not save to localStorage:', e);
        }
    },

    _mergeCheckOptions(existing = null, incoming = {}) {
        return {
            noCache: !!((existing && existing.noCache) || (incoming && incoming.noCache)),
            reason: String((incoming && incoming.reason) || (existing && existing.reason) || '').trim()
        };
    },

    async checkForNewViolations(options = {}) {
        const requestedOptions = this._mergeCheckOptions(null, options);
        if (this.isChecking) {
            this.pendingCheckOptions = this._mergeCheckOptions(this.pendingCheckOptions, requestedOptions);
            return;
        }

        this.isChecking = true;
        try {
            let currentOptions = requestedOptions;
            while (currentOptions) {
                await this._runViolationCheck(currentOptions);
                currentOptions = this.pendingCheckOptions;
                this.pendingCheckOptions = null;
            }
        } finally {
            this.isChecking = false;
        }
    },

    applyRealtimePayload(payload = {}) {
        const reports = Array.isArray(payload && payload.reports) ? payload.reports : [];
        if (!reports.length) return;
        this.processViolationRows(reports, { reason: 'realtime-payload' });
    },

    processViolationRows(violations = [], options = {}) {
        const reason = String((options && options.reason) || '').trim();

        for (const violation of violations) {
            const reportId = violation && violation.report_id;
            if (!reportId) continue;

            const status = this.normalizeStatusValue(violation.status, !!violation.has_report);
            const violationTime = this.parseEventDate(violation.updated_at)
                || this.parseEventDate(violation.timestamp)
                || this.getLifecycleEventDate(violation)
                || new Date(0);
            const eventType = String((violation && violation.event_type) || '').trim().toLowerCase();
            const previousData = this.knownViolations.get(reportId);
            const happenedDuringSession = violationTime >= this.sessionStartTime;
            const watchStatus = (status === 'pending' || status === 'generating')
                && (happenedDuringSession || eventType === 'violation_detected' || (previousData && previousData.watchStatus === true));

            if (!previousData) {
                if (happenedDuringSession) {
                    console.log(`[ViolationMonitor] realtime/poll row: ${reportId} ${status} (${reason || 'unknown'})`);
                    if (eventType === 'violation_detected') {
                        this._notifyViolationDetected(violation);
                    }
                    if (status === 'generating') {
                        this._notifyReportGenerating(violation);
                    } else if (status === 'completed') {
                        this._notifyReportReady(violation);
                    } else if (status === 'failed' || status === 'partial' || status === 'skipped') {
                        this._notifyReportFailed(violation);
                    }
                }

                this.knownViolations.set(reportId, {
                    status,
                    timestamp: violationTime,
                    watchStatus
                });
                continue;
            }

            if (previousData.status !== status) {
                console.log(`[ViolationMonitor] Status change: ${reportId} ${previousData.status} -> ${status}`);
                const shouldNotify = previousData.watchStatus === true || happenedDuringSession;
                if (shouldNotify) {
                    if (status === 'generating' && previousData.status === 'pending') {
                        this._notifyReportGenerating(violation);
                    } else if (status === 'completed') {
                        this._notifyReportReady(violation);
                    } else if (status === 'failed' || status === 'partial' || status === 'skipped') {
                        this._notifyReportFailed(violation);
                    }
                } else {
                    console.log(`[ViolationMonitor] Historical status change hydrated without toast: ${reportId}`);
                }

                this.knownViolations.set(reportId, {
                    status,
                    timestamp: previousData.timestamp,
                    watchStatus: previousData.watchStatus === true && (status === 'pending' || status === 'generating')
                });
            }

            const isRealtime = this.knownViolations.get(reportId)?.timestamp > this.sessionStartTime;
            if (isRealtime) {
                this._checkValidationWarnings(violation);
            }
        }

        this.syncInFlightStatusFallback();
    },

    async _runViolationCheck(options = {}) {
        try {
            const violations = await this.fetchMonitorViolations(options);

            if (this.isInitialLoad) {
                // INITIAL LOAD: hydrate baseline state without replaying historical toasts.
                this._handleInitialLoad(violations);
                this.isInitialLoad = false;
                this.syncInFlightStatusFallback();
                return;
            }

            this.processViolationRows(violations, { reason: options && options.reason });
            return;

            // REAL-TIME MODE: Only notify for violations detected AFTER session started
            for (const violation of violations) {
                const reportId = violation.report_id;
                if (!reportId) continue;
                const status = this.normalizeStatusValue(violation.status, !!violation.has_report);
                const violationTime = this.parseEventDate(violation.timestamp) || this.getLifecycleEventDate(violation) || new Date(0);
                const previousData = this.knownViolations.get(reportId);

                // Check if this is a NEW violation (not seen before)
                if (!previousData) {
                    // Only show real-time notifications for violations created after this page session started.
                    const isNewDuringSession = violationTime >= this.sessionStartTime;

                    if (isNewDuringSession) {
                        console.log(`[ViolationMonitor] 🆕 NEW real-time violation detected via polling fallback: ${reportId}`);

                        // We call the notification helpers.
                        // These helpers already contain the de-duplication check:
                        // 'if (this.notifiedEvents.has(key)) return;'
                        // So if live.js already fired the notification, these calls
                        // will do absolutely nothing, preventing duplicates.
                        this._notifyViolationDetected(violation);

                        if (status === 'generating') {
                            this._notifyReportGenerating(violation);
                        } else if (status === 'completed') {
                            this._notifyReportReady(violation);
                        } else if (status === 'failed') {
                            this._notifyReportFailed(violation);
                        }
                    }

                    // Track this violation
                    this.knownViolations.set(reportId, {
                        status,
                        timestamp: violationTime,
                        watchStatus: isNewDuringSession && (status === 'pending' || status === 'generating')
                    });
                }
                // Check for STATUS CHANGES on violations we're tracking
                else if (previousData.status !== status) {
                    console.log(`[ViolationMonitor] Status change: ${reportId} ${previousData.status} -> ${status}`);

                    // Only toast lifecycle changes that actually happened during this page session.
                    // Historical rows can still hydrate status without replaying old notifications.
                    if (this.isLifecycleEventDuringSession(violation)) {
                        if (status === 'generating' && previousData.status === 'pending') {
                            this._notifyReportGenerating(violation);
                        }
                        else if (status === 'completed') {
                            this._notifyReportReady(violation);
                        }
                        else if (status === 'failed') {
                            this._notifyReportFailed(violation);
                        }
                    } else {
                        console.log(`[ViolationMonitor] Historical status change hydrated without toast: ${reportId}`);
                    }

                    // Update tracked status
                    this.knownViolations.set(reportId, {
                        status,
                        timestamp: previousData.timestamp,
                        watchStatus: previousData.watchStatus === true && (status === 'pending' || status === 'generating')
                    });
                }

                // Check for validation warnings (only for real-time violations)
                const isRealtime = this.knownViolations.get(reportId)?.timestamp > this.sessionStartTime;
                if (isRealtime) {
                    this._checkValidationWarnings(violation);
                }
            }

            this.syncInFlightStatusFallback();
        } catch (error) {
            console.error('[ViolationMonitor] Error checking violations:', error);
        }
    },

    async fetchMonitorViolations(options = {}) {
        const noCache = !!(options && options.noCache);
        const requestOptions = noCache
            ? { noCache: true, timeoutMs: 12000 }
            : {};

        const [violationsResult, pendingResult] = await Promise.allSettled([
            API.getViolations(requestOptions),
            API.getPendingReports(requestOptions)
        ]);

        if (violationsResult.status === 'rejected' && pendingResult.status === 'rejected') {
            throw violationsResult.reason || pendingResult.reason;
        }

        if (violationsResult.status === 'rejected') {
            console.warn('[ViolationMonitor] getViolations failed; using pending reports fallback:', violationsResult.reason);
        }
        if (pendingResult.status === 'rejected') {
            console.warn('[ViolationMonitor] getPendingReports failed; using violations only:', pendingResult.reason);
        }

        const violations = violationsResult.status === 'fulfilled' && Array.isArray(violationsResult.value)
            ? violationsResult.value
            : [];
        const pendingReports = pendingResult.status === 'fulfilled' && Array.isArray(pendingResult.value)
            ? pendingResult.value
            : [];

        return this.mergePendingReportsForNotifications(violations, pendingReports);
    },

    mergePendingReportsForNotifications(violations, pendingReports) {
        const byId = new Map();
        const base = Array.isArray(violations) ? violations : [];
        const pending = Array.isArray(pendingReports) ? pendingReports : [];

        base.forEach((item) => {
            const reportId = String((item && item.report_id) || '').trim();
            if (!reportId) return;
            const normalized = { ...item, report_id: reportId };
            normalized.status = this.normalizeStatusValue(normalized.status, !!normalized.has_report);
            byId.set(reportId, normalized);
        });

        pending.forEach((item) => {
            const reportId = String((item && item.report_id) || '').trim();
            if (!reportId) return;

            const pendingStatus = this.normalizeStatusValue(item && item.status, !!(item && item.has_report));
            const existing = byId.get(reportId);
            if (existing) {
                const existingStatus = this.normalizeStatusValue(existing.status, !!existing.has_report);
                const allowRetryTransition = (
                    (pendingStatus === 'pending' || pendingStatus === 'generating')
                    && !existing.has_report
                    && (existingStatus === 'failed' || existingStatus === 'skipped')
                );
                if (
                    (
                        this.getStatusPriority(pendingStatus) > this.getStatusPriority(existingStatus)
                        && !existing.has_report
                    )
                    || allowRetryTransition
                ) {
                    existing.status = pendingStatus;
                }
                existing.timestamp = existing.timestamp || item.timestamp || item.updated_at;
                existing.updated_at = existing.updated_at || item.updated_at;
                existing.device_id = existing.device_id || item.device_id || null;
                existing.severity = existing.severity || item.severity || 'HIGH';
                existing.violation_count = Number(existing.violation_count || item.violation_count || 0);
                existing.missing_ppe = Array.isArray(existing.missing_ppe) && existing.missing_ppe.length
                    ? existing.missing_ppe
                    : (Array.isArray(item.missing_ppe) ? item.missing_ppe : []);
                existing.violation_summary = existing.violation_summary
                    || item.violation_summary
                    || 'Violation queued for report generation';
                existing.has_original = !!existing.has_original || !!item.has_original;
                existing.has_annotated = !!existing.has_annotated || !!item.has_annotated;
                existing.has_report = !!existing.has_report || !!item.has_report;
                return;
            }

            byId.set(reportId, {
                report_id: reportId,
                timestamp: item.timestamp || item.updated_at || new Date().toISOString(),
                updated_at: item.updated_at || item.timestamp || null,
                status: pendingStatus,
                severity: item.severity || 'HIGH',
                device_id: item.device_id || null,
                violation_count: Number(item.violation_count || 0),
                missing_ppe: Array.isArray(item.missing_ppe) ? item.missing_ppe : [],
                violation_summary: item.violation_summary || 'Violation queued for report generation',
                has_original: !!item.has_original,
                has_annotated: !!item.has_annotated,
                has_report: !!item.has_report,
                source_scope: item.source_scope || 'local',
                source_label: item.source_label || 'Local'
            });
        });

        const merged = Array.from(byId.values());
        merged.sort((a, b) => {
            const aTime = Date.parse(a.timestamp || a.updated_at || '') || 0;
            const bTime = Date.parse(b.timestamp || b.updated_at || '') || 0;
            return bTime - aTime;
        });
        return merged;
    },

    normalizeStatusValue(status, hasReport = false) {
        const raw = String(status || '').trim().toLowerCase();
        if (!raw) return hasReport ? 'completed' : 'pending';
        if (raw === 'completed' || raw === 'ready' || raw === 'done' || raw === 'success') return 'completed';
        if (raw === 'partial' || raw === 'degraded') return 'partial';
        if (raw === 'failed' || raw === 'error' || raw === 'errored') return 'failed';
        if (raw === 'skipped' || raw === 'cancelled' || raw === 'canceled') return 'skipped';
        if (hasReport && (
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
        )) {
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
        return hasReport ? 'completed' : raw;
    },

    getStatusPriority(status) {
        const normalized = this.normalizeStatusValue(status);
        if (normalized === 'completed') return 50;
        if (normalized === 'failed' || normalized === 'skipped' || normalized === 'partial') return 40;
        if (normalized === 'generating') return 30;
        if (normalized === 'pending') return 20;
        return 0;
    },

    parseEventDate(value) {
        if (!value) return null;
        const date = new Date(value);
        return Number.isFinite(date.getTime()) ? date : null;
    },

    getLifecycleEventDate(violation) {
        if (!violation || typeof violation !== 'object') return null;
        const candidates = [
            violation.updated_at,
            violation.status_updated_at,
            violation.report_updated_at,
            violation.completed_at,
            violation.generated_at,
            violation.failed_at,
            violation.timestamp
        ];
        for (const candidate of candidates) {
            const parsed = this.parseEventDate(candidate);
            if (parsed) return parsed;
        }
        return null;
    },

    isLifecycleEventDuringSession(violation) {
        const eventDate = this.getLifecycleEventDate(violation);
        if (!eventDate || !this.sessionStartTime) return false;
        return eventDate >= this.sessionStartTime;
    },

    _handleInitialLoad(violations) {
        if (!violations || violations.length === 0) {
            console.log('[ViolationMonitor] No violations in database');
            return;
        }

        for (const v of violations) {
            const reportId = String((v && v.report_id) || '').trim();
            if (!reportId) continue;
            const violationTime = this.parseEventDate(v.timestamp) || this.getLifecycleEventDate(v) || new Date(0);
            const status = this.normalizeStatusValue(v.status, !!v.has_report);

            this.knownViolations.set(reportId, { status, timestamp: violationTime, watchStatus: false });
        }

        console.log(`[ViolationMonitor] Initial load hydrated ${violations.length} violation(s); startup notifications suppressed`);
        const pendingCount = 0;
        const generatingCount = 0;
        const failedCount = 0;

        // Startup processing summaries are disabled so historical rows do not replay notifications.
        const inProgress = pendingCount + generatingCount;
        if (inProgress > 0) {
            setTimeout(() => {
                NotificationManager.show(
                    `${inProgress} report${inProgress > 1 ? 's are' : ' is'} currently being processed`,
                    'warning',
                    6000,
                    {
                        title: '⏳ Reports In Progress'
                    }
                );
            }, 1500);
        }

        // Startup failed-report summaries are disabled for the same reason.
        if (failedCount > 0) {
            setTimeout(() => {
                NotificationManager.show(
                    `${failedCount} report${failedCount > 1 ? 's' : ''} failed to generate`,
                    'error',
                    6000,
                    {
                        title: 'Failed Reports',
                        action: {
                            text: 'View Details',
                            onClick: `Router.navigate('reports')`
                        }
                    }
                );
            }, 3000);
        }
    },

    // Real-time notification: Violation detected (NEW during session)
    _notifyViolationDetected(violation) {
        const notifKey = `detected_${violation.report_id}`;
        if (this.notifiedEvents.has(notifKey)) return;

        this.notifiedEvents.add(notifKey);

        const severity = violation.severity || 'HIGH';
        const timestamp = new Date(violation.timestamp).toLocaleTimeString();
        const reportId = violation.report_id;
        const status = this.normalizeStatusValue(violation.status, !!violation.has_report);
        const violationTime = this.parseEventDate(violation.timestamp) || this.getLifecycleEventDate(violation) || new Date();
        if (reportId) {
            const previous = this.knownViolations.get(reportId);
            if (!previous || this.getStatusPriority(status) >= this.getStatusPriority(previous.status)) {
                this.knownViolations.set(reportId, {
                    status,
                    timestamp: violationTime,
                    watchStatus: status === 'pending' || status === 'generating'
                });
                if (status === 'pending' || status === 'generating') {
                    this.syncInFlightStatusFallback();
                }
            }
        }

        // Derive a human-friendly type string: prefer explicit type, else missing PPE, else try parsing summary
        let derivedType = null;
        if (violation.violation_type && violation.violation_type !== 'PPE Violation') {
            derivedType = violation.violation_type;
        }

        if (!derivedType) {
            if (Array.isArray(violation.missing_ppe) && violation.missing_ppe.length > 0) {
                if (violation.missing_ppe.length === 1) derivedType = `Missing ${violation.missing_ppe[0]}`;
                else if (violation.missing_ppe.length === 2) derivedType = `Missing ${violation.missing_ppe[0]} and ${violation.missing_ppe[1]}`;
                else derivedType = `Missing ${violation.missing_ppe.slice(0, 5).join(', ')}`;
            }
        }

        if (!derivedType && violation.violation_summary) {
            const s = violation.violation_summary;
            const m = s.match(/Missing:?\s*([^\.\n]+)/i) || s.match(/PPE Violation Detected:\s*(.+)/i);
            if (m && m[1]) {
                const parts = m[1].split(',').map(x => x.trim()).filter(Boolean);
                if (parts.length === 1) derivedType = `Missing ${parts[0]}`;
                else if (parts.length === 2) derivedType = `Missing ${parts[0]} and ${parts[1]}`;
                else derivedType = `Missing ${parts.slice(0, 5).join(', ')}`;
            }
        }

        if (!derivedType) derivedType = 'PPE Violation';

        NotificationManager.show(
            `${derivedType} at ${timestamp} - Severity: ${severity}`,
            'violation',
            10000,  // Auto-dismiss after 10 seconds
            {
                title: 'PPE Violation Detected',
                action: {
                    text: 'View Report',
                    onClickFn: () => this.navigateToReport(reportId)
                },
                dedupeKey: reportId ? `violation:${reportId}` : undefined,
                dedupeTtlMs: 12000
            }
        );

        console.log(`[ViolationMonitor] VIOLATION: ${violation.report_id} (${derivedType})`);
        // Trigger audio alert (if available) for immediate real-time detections
        try {
            if (window.AudioAlert && typeof window.AudioAlert.speakViolation === 'function') {
                console.log('[ViolationMonitor] Calling AudioAlert.speakViolation for', violation.report_id);
                AudioAlert.speakViolation(violation);
            } else {
                console.log('[ViolationMonitor] AudioAlert not available to speak violation');
            }
        } catch (e) {
            console.error('[ViolationMonitor] Error calling AudioAlert:', e);
        }
    },

    // Real-time notification: Report generating
    _notifyReportGenerating(violation) {
        const notifKey = `generating_${violation.report_id}`;
        if (this.notifiedEvents.has(notifKey)) return;

        this.notifiedEvents.add(notifKey);
        const reportId = violation.report_id;

        NotificationManager.show(
            `Analyzing violation and generating safety report...`,
            'report',
            10000,
            {
                title: 'Generating Report',
                action: {
                    text: 'View Progress',
                    onClickFn: () => this.navigateToReport(reportId)
                }
            }
        );

        console.log(`[ViolationMonitor] GENERATING: ${violation.report_id}`);
    },

    // Real-time notification: Report ready
    _notifyReportReady(violation) {
        const notifKey = `ready_${violation.report_id}`;
        if (this.notifiedEvents.has(notifKey)) return;

        this.notifiedEvents.add(notifKey);

        NotificationManager.show(
            `Safety report is ready for review`,
            'success',
            10000,
            {
                title: 'Report Complete',
                action: {
                    text: 'Open Report',
                    onClickFn: () => {
                        const url = (typeof API !== 'undefined' && typeof API.getReportUrl === 'function')
                            ? API.getReportUrl(violation.report_id, violation)
                            : `${API_CONFIG.BASE_URL}/report/${violation.report_id}`;
                        window.open(url, '_blank');
                    }
                }
            }
        );

        console.log(`[ViolationMonitor] READY: ${violation.report_id}`);
    },

    // Real-time notification: Report failed
    _notifyReportFailed(violation) {
        const notifKey = `failed_${violation.report_id}`;
        if (this.notifiedEvents.has(notifKey)) return;

        this.notifiedEvents.add(notifKey);
        const reportId = violation.report_id;
        const errorMsg = violation.error_message || 'Unknown error';

        NotificationManager.show(
            `Report generation failed: ${errorMsg.slice(0, 80)}`,
            'error',
            10000,
            {
                title: 'Report Failed',
                action: {
                    text: 'View Details',
                    onClickFn: () => this.navigateToReport(reportId)
                }
            }
        );

        console.log(`[ViolationMonitor] FAILED: ${violation.report_id}`);
    },

    // Check for caption validation warnings (real-time only)
    _checkValidationWarnings(violation) {
        const validation = violation.detection_data?.caption_validation;
        if (!validation || validation.is_valid !== false) return;

        const notifKey = `validation_${violation.report_id}`;
        if (this.notifiedEvents.has(notifKey)) return;

        this.notifiedEvents.add(notifKey);
        const reportId = violation.report_id;

        const contradictions = validation.contradictions || [];
        let message = 'Caption validation issues detected';
        if (contradictions.length > 0) {
            // Clean up the message
            message = contradictions[0]
                .replace('PPE Mismatch: ', '')
                .slice(0, 100);
        }

        NotificationManager.show(
            message,
            'warning',
            8000,
            {
                title: 'PPE Caption Mismatch',
                action: {
                    text: 'View Report',
                    onClickFn: () => this.navigateToReport(reportId)
                }
            }
        );

        console.warn(`[ViolationMonitor] VALIDATION: ${violation.report_id}`);
    },

    // Navigate to reports page and scroll to specific report
    navigateToReport(reportId) {
        console.log(`[ViolationMonitor] Navigating to report: ${reportId}`);

        // Navigate to reports page
        Router.navigate('reports');

        // Wait for page to render, then scroll to specific report
        setTimeout(() => {
            const reportCard = document.getElementById(`report-${reportId}`);
            if (reportCard) {
                reportCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
                // Highlight the card briefly
                reportCard.style.boxShadow = '0 0 20px rgba(231, 76, 60, 0.6)';
                reportCard.style.transition = 'box-shadow 0.3s ease';
                setTimeout(() => {
                    reportCard.style.boxShadow = '';
                }, 2000);
            }
        }, 500);
    },

    // Manual trigger for testing
    testNotifications() {
        console.log('[ViolationMonitor] Testing notifications...');

        NotificationManager.info('Info notification test');
        setTimeout(() => NotificationManager.success('Success notification test'), 1000);
        setTimeout(() => NotificationManager.warning('Warning notification test'), 2000);
        setTimeout(() => NotificationManager.error('Error notification test'), 3000);
        setTimeout(() => {
            NotificationManager.show('Test violation detected', 'violation', 0, {
                title: 'Test Violation'
            });
        }, 4000);
    },

    // Clear last visit time (for testing - shows all as new)
    resetLastVisit() {
        localStorage.removeItem(this.STORAGE_KEY);
        console.log('[ViolationMonitor] Last visit time cleared - refresh to test');
    },

    // Force show summary (for testing)
    showSummary() {
        this.isInitialLoad = true;
        this.lastVisitTime = null;
        this.checkForNewViolations();
    }
};

// Auto-start monitoring when page loads
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        setTimeout(() => ViolationMonitor.start(), 2000);
    });
} else {
    setTimeout(() => ViolationMonitor.start(), 2000);
}

// Save visit time when page unloads
window.addEventListener('beforeunload', () => {
    ViolationMonitor.stop();
});
