// Realtime SSE manager for automatic UI synchronization
const RealtimeSync = {
    source: null,
    supabaseClient: null,
    supabaseChannel: null,
    reconnectTimer: null,
    reconnectDelayMs: 2000,
    maxReconnectDelayMs: 15000,
    started: false,
    isConnected: false,
    mode: 'offline',
    reportStatusCache: {},
    lastProgressReportId: null,
    lastProgressStatus: null,
    lastProgressStep: '',
    pendingSnapshotFetch: false,
    lastSnapshotAt: 0,
    supabaseFailureCount: 0,
    supabaseDisabledUntil: 0,

    start() {
        if (this.started) return;
        this.started = true;

        // Listen for network state changes to automatically reconnect and 
        // trigger UI refreshes when switching between cloud/local modes.
        window.addEventListener('online', () => {
            console.log('Browser back online; reconnecting realtime...');
            this.safeReconnect();
            this.fetchRealtimeSnapshot();
        });
        window.addEventListener('offline', () => {
            console.log('Browser offline; switching to local realtime...');
            this.safeReconnect();
            this.fetchRealtimeSnapshot();
        });

        this.connect();
    },

    stop() {
        this.started = false;
        this.mode = 'offline';
        this.setConnectionState(false, 'offline');
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        this.disconnectSupabase();
        if (this.source) {
            this.source.close();
            this.source = null;
        }
    },

    connect() {
        if (!this.started) return;

        this.setConnectionState(false, 'reconnecting');

        if (this.shouldUseSupabaseRealtime()) {
            const connected = this.connectSupabaseRealtime();
            if (connected) {
                return;
            }
        }

        this.connectSSE();
    },

    connectSSE() {
        this.mode = 'sse';
        this.disconnectSupabase();

        try {
            const url = API.getRealtimeStreamUrl();
            this.source = new EventSource(url);

            this.source.addEventListener('open', () => {
                this.reconnectDelayMs = 2000;
                this.setConnectionState(true, 'connected');
                this.updateTransportHint('SSE');
                console.log('Realtime stream connected (SSE)');
            });

            this.source.addEventListener('update', (event) => {
                this.handleUpdateEvent(event);
            });

            this.source.addEventListener('heartbeat', () => {
                // Keep-alive event; no UI action required.
            });

            this.source.onerror = () => {
                this.setConnectionState(false, 'reconnecting');
                this.safeReconnect();
            };
        } catch (error) {
            console.error('Failed to initialize realtime stream:', error);
            this.setConnectionState(false, 'offline');
            this.safeReconnect();
        }
    },

    shouldUseSupabaseRealtime() {
        const cfg = API.getSupabaseRealtimeConfig();
        if (Date.now() < this.supabaseDisabledUntil) {
            return false;
        }
        return !!(window.supabase && cfg.url && cfg.anonKey);
    },

    fallbackToSSE(reason) {
        console.warn(`Supabase realtime unavailable (${reason}). Falling back to SSE.`);
        this.supabaseFailureCount += 1;

        if (this.supabaseFailureCount >= 2) {
            this.supabaseDisabledUntil = Date.now() + (5 * 60 * 1000);
        }

        this.disconnectSupabase();
        this.disconnectSSEOnly();
        this.connectSSE();
    },

    connectSupabaseRealtime() {
        try {
            const cfg = API.getSupabaseRealtimeConfig();
            if (!window.supabase || !cfg.url || !cfg.anonKey) {
                return false;
            }

            this.mode = 'supabase';

            if (!this.supabaseClient) {
                this.supabaseClient = window.supabase.createClient(cfg.url, cfg.anonKey, {
                    realtime: {
                        params: {
                            eventsPerSecond: 4
                        }
                    }
                });
            }

            this.disconnectSSEOnly();
            this.disconnectSupabase();

            this.supabaseChannel = this.supabaseClient
                .channel('ppe-realtime-db')
                .on('postgres_changes', {
                    event: '*',
                    schema: 'public',
                    table: 'detection_events'
                }, () => {
                    this.fetchRealtimeSnapshot();
                })
                .on('postgres_changes', {
                    event: '*',
                    schema: 'public',
                    table: 'violations'
                }, () => {
                    this.fetchRealtimeSnapshot();
                })
                .subscribe((status) => {
                    const normalized = String(status || '').toUpperCase();
                    if (normalized === 'SUBSCRIBED') {
                        this.supabaseFailureCount = 0;
                        this.supabaseDisabledUntil = 0;
                        this.reconnectDelayMs = 2000;
                        this.setConnectionState(true, 'connected');
                        this.updateTransportHint('Supabase WS');
                        return;
                    }

                    if (normalized === 'CHANNEL_ERROR' || normalized === 'TIMED_OUT' || normalized === 'CLOSED') {
                        this.setConnectionState(false, 'reconnecting');
                        this.fallbackToSSE(normalized);
                    }
                });

            return true;
        } catch (error) {
            console.error('Supabase realtime init failed:', error);
            this.disconnectSupabase();
            this.mode = 'offline';
            this.supabaseFailureCount += 1;
            if (this.supabaseFailureCount >= 2) {
                this.supabaseDisabledUntil = Date.now() + (5 * 60 * 1000);
            }
            return false;
        }
    },

    disconnectSSEOnly() {
        if (this.source) {
            this.source.close();
            this.source = null;
        }
    },

    disconnectSupabase() {
        if (this.supabaseChannel && this.supabaseClient) {
            this.supabaseClient.removeChannel(this.supabaseChannel);
        }
        this.supabaseChannel = null;
    },

    async fetchRealtimeSnapshot() {
        const now = Date.now();
        if (this.pendingSnapshotFetch) return;
        if (now - this.lastSnapshotAt < 700) return;

        this.pendingSnapshotFetch = true;
        this.lastSnapshotAt = now;

        try {
            const response = await fetch(API.getRealtimeSnapshotUrl(), {
                method: 'GET',
                cache: 'no-store'
            });
            if (!response.ok) {
                throw new Error('Realtime snapshot request failed');
            }

            const payload = await response.json();
            this.emitPageUpdate(payload);
            this.emitStatusNotifications(payload);
        } catch (error) {
            console.warn('Failed to fetch realtime snapshot:', error);
        } finally {
            this.pendingSnapshotFetch = false;
        }
    },

    updateTransportHint(label) {
        const badge = document.getElementById('realtimeStatusBadge');
        if (!badge) return;
        badge.title = `Realtime sync active (${label})`;
    },

    setConnectionState(connected, mode) {
        this.isConnected = !!connected;
        this.updateBadge(mode || (connected ? 'connected' : 'offline'));
        window.dispatchEvent(new CustomEvent('ppe-realtime:connection', {
            detail: {
                connected: this.isConnected,
                mode: mode || (connected ? 'connected' : 'offline')
            }
        }));
    },

    updateBadge(mode) {
        const badge = document.getElementById('realtimeStatusBadge');
        if (!badge) return;

        const icon = badge.querySelector('i');
        const text = badge.querySelector('span');

        badge.classList.remove('realtime-live', 'realtime-reconnecting', 'realtime-offline', 'realtime-connecting');

        if (mode === 'connected') {
            badge.classList.add('realtime-live');
            if (icon) icon.className = 'fas fa-circle';
            if (text) text.textContent = 'Live';
            badge.title = 'Realtime sync active';
            return;
        }

        if (mode === 'reconnecting') {
            badge.classList.add('realtime-reconnecting');
            if (icon) icon.className = 'fas fa-circle-notch fa-spin';
            if (text) text.textContent = 'Reconnecting';
            badge.title = 'Realtime reconnect in progress';
            return;
        }

        badge.classList.add('realtime-offline');
        if (icon) icon.className = 'fas fa-triangle-exclamation';
        if (text) text.textContent = 'Offline';
        badge.title = 'Realtime unavailable. Polling fallback should be used.';
    },

    safeReconnect() {
        if (!this.started) return;

        this.disconnectSSEOnly();
        this.disconnectSupabase();

        if (this.reconnectTimer) {
            return;
        }

        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.connect();
        }, this.reconnectDelayMs);

        this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 1.7, this.maxReconnectDelayMs);
    },

    handleUpdateEvent(event) {
        try {
            const payload = JSON.parse(event.data || '{}');
            this.emitPageUpdate(payload);
            this.emitStatusNotifications(payload);
            // Trigger ViolationMonitor's "PPE Violation Detected!" toast / voice
            // alert pipeline immediately whenever the SSE/WS stream pushes a new
            // report. Without this, in local routing profile (no Supabase
            // realtime channel) the violation-detected toast and voice alert
            // would lag up to the polling interval (60s). The monitor now
            // forces a fresh violations + pending-reports merge so local
            // filesystem rows notify at the same time the Reports page updates.
            try {
                if (typeof ViolationMonitor !== 'undefined'
                    && ViolationMonitor.isMonitoring
                    && typeof ViolationMonitor.checkForNewViolations === 'function') {
                    ViolationMonitor.checkForNewViolations({ noCache: true, reason: 'realtime-update' });
                }
            } catch (vmErr) {
                console.warn('Realtime -> ViolationMonitor refresh failed:', vmErr);
            }
        } catch (error) {
            console.error('Invalid realtime payload:', error);
        }
    },

    emitPageUpdate(payload) {
        window.dispatchEvent(new CustomEvent('ppe-realtime:update', {
            detail: payload
        }));
    },

    emitStatusNotifications(payload) {
        const reports = Array.isArray(payload.reports) ? payload.reports : [];
        const nowEpochMs = Date.now();

        const progress = (payload && typeof payload === 'object') ? (payload.progress || {}) : {};
        const progressReportId = String(progress.current || '').trim();
        const progressStatus = String(progress.status || '').trim().toLowerCase();
        const progressStep = String(progress.current_step || '').trim();
        const hasProgressReportRow = !!(progressReportId && reports.some((row) => {
            return String((row && row.report_id) || '').trim() === progressReportId;
        }));
        const isActiveProgress = !!(
            progressReportId
            && (progressStatus === 'waiting' || progressStatus === 'processing' || progressStatus === 'generating')
        );

        const isRecentRow = (row) => {
            const raw = row && (row.updated_at || row.timestamp);
            if (!raw) return false;
            const ts = Date.parse(raw);
            if (!Number.isFinite(ts)) return false;
            return (nowEpochMs - ts) <= 120000;
        };

        const shouldTreatRowAsRecent = (row) => {
            const rowId = String((row && row.report_id) || '').trim();
            if (isActiveProgress && rowId && rowId === progressReportId) {
                return true;
            }
            return isRecentRow(row);
        };

        // DB row notifications are now exclusively handled by ViolationMonitor
        // to prevent duplication. RealtimeSync already triggers ViolationMonitor
        // immediately upon receiving a push payload.

        // Fallback path: when DB-backed report rows are unavailable, use pipeline progress.
        // This keeps UX visibility in local/offline runs while generation is still active.
        if (!progressReportId) {
            this.lastProgressReportId = null;
            this.lastProgressStatus = progressStatus || null;
            this.lastProgressStep = progressStep;
            return;
        }

        const changedReport = this.lastProgressReportId !== progressReportId;
        const changedStatus = this.lastProgressStatus !== progressStatus;
        const changedStep = this.lastProgressStep !== progressStep;
        const allowProgressFallback = !hasProgressReportRow;

        if (allowProgressFallback) {
            if ((progressStatus === 'waiting' || progressStatus === 'processing') && (changedReport || changedStatus)) {
                NotificationManager.reportGenerating(progressReportId, {
                    title: progressStatus === 'waiting' ? 'Report Queued' : 'Report Generating'
                });
            } else if (progressStatus === 'completed' && (changedReport || changedStatus)) {
                NotificationManager.reportReady(progressReportId);
            } else if ((progressStatus === 'error' || progressStatus === 'failed') && (changedReport || changedStatus || changedStep)) {
                NotificationManager.error(
                    `Report ${progressReportId} failed: ${progress.error_message || progressStep || 'Unknown error'}`,
                    {
                        title: 'Report Generation Issue',
                        duration: 8000
                    }
                );
            }
        }

        this.lastProgressReportId = progressReportId;
        this.lastProgressStatus = progressStatus;
        this.lastProgressStep = progressStep;
    }
};
