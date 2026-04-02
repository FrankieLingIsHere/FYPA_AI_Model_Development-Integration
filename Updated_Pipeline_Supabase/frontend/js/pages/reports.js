// Reports Page Component
const ReportsPage = {
    violations: [],
    providerRuntimeInterval: null,
    realtimeHandler: null,
    realtimeConnectionHandler: null,
    realtimeRefreshTimer: null,
    filters: {
        search: '',
        severity: 'all',
        dateRange: 'all'
    },
    refreshInterval: null,
    modalRuntime: {
        reportId: null,
        pollTimer: null,
        cooldownTimer: null,
        retryCount: 0,
        quotaPromptedForReport: null,
        cooldownUntil: 0,
        pollStartedAt: 0,
        maxRetries: 5,
        cooldownSeconds: 8,
        pollIntervalMs: 2500,
        maxWaitMs: 240000,
        expectedDurationSec: 60
    },

    render() {
        return `
            <div class="page">
                <div class="card mb-4">
                    <div class="card-header">
                        <div style="display: flex; align-items: center; gap: 0.65rem; flex-wrap: wrap;">
                            <span><i class="fas fa-file-alt"></i> Violation Reports</span>
                            <span id="reportsProviderBadge" class="reports-provider-badge">Provider: loading...</span>
                        </div>
                        <button class="btn btn-primary" onclick="ReportsPage.refreshReports()" style="padding: 0.5rem 1rem;">
                            <i class="fas fa-sync"></i> Refresh
                        </button>
                    </div>
                    <div class="card-content">
                        <!-- Filters -->
                        <div class="grid grid-3 mb-3">
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
                        </div>

                        <!-- Reports List -->
                        <div id="reports-list">
                            <div class="spinner"></div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    },

    async mount() {
        await this.loadReports();
        await this.updateProviderRuntimeBadge();
        this.providerRuntimeInterval = setInterval(() => this.updateProviderRuntimeBadge(), 15000);
        this.syncFallbackPolling();

        this.realtimeHandler = () => {
            if (this.realtimeRefreshTimer) return;
            this.realtimeRefreshTimer = setTimeout(async () => {
                this.realtimeRefreshTimer = null;
                await this.loadReports();
            }, 700);
        };
        window.addEventListener('ppe-realtime:update', this.realtimeHandler);

        this.realtimeConnectionHandler = () => this.syncFallbackPolling();
        window.addEventListener('ppe-realtime:connection', this.realtimeConnectionHandler);
    },

    unmount() {
        this.stopAutoRefresh();
        this.stopModalPolling();
        this.stopModalCooldown();
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
    },

    syncFallbackPolling() {
        const connected = typeof RealtimeSync !== 'undefined' && RealtimeSync.isConnected;
        if (connected) {
            this.stopAutoRefresh();
        } else {
            this.startAutoRefresh();
        }
    },

    startAutoRefresh() {
        // Check for pending reports every 10 seconds
        this.refreshInterval = setInterval(async () => {
            const hasPending = this.violations.some(v => 
                v.status === 'pending' || v.status === 'generating' || !v.has_report
            );
            if (hasPending) {
                await this.loadReports();
            }
        }, 10000);
    },

    stopAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    },

    async loadReports() {
        this.violations = await API.getViolations();
        this.renderReports();
    },

    async refreshReports() {
        const list = document.getElementById('reports-list');
        list.innerHTML = '<div class="spinner"></div>';
        await this.loadReports();
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
        this.renderReports();
    },

    getFilteredViolations() {
        let filtered = [...this.violations];

        // Search filter
        if (this.filters.search) {
            filtered = filtered.filter(v => 
                v.report_id.toLowerCase().includes(this.filters.search) ||
                v.timestamp.toLowerCase().includes(this.filters.search) ||
                (v.device_id && v.device_id.toLowerCase().includes(this.filters.search))
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

        return filtered;
    },

    normalizeStatus(violation) {
        const raw = (violation && violation.status ? String(violation.status) : '').trim().toLowerCase();
        if (raw) return raw;
        return violation && violation.has_report ? 'completed' : 'pending';
    },

    notify(message, type = 'info') {
        if (typeof NotificationManager !== 'undefined') {
            if (type === 'success') return NotificationManager.success(message);
            if (type === 'warning') return NotificationManager.warning(message);
            if (type === 'error') return NotificationManager.error(message);
            return NotificationManager.info(message);
        }
        if (type === 'error') {
            alert(message);
        } else {
            console.log(`[${type.toUpperCase()}] ${message}`);
        }
    },

    openReport(reportId) {
        const url = API.getReportUrl(reportId);
        window.open(url, '_blank');
        this.notify(`Opening report ${reportId}`, 'info');
    },

    renderReports() {
        const list = document.getElementById('reports-list');
        const filtered = this.getFilteredViolations();

        if (filtered.length === 0) {
            list.innerHTML = `
                <div class="alert alert-info">
                    <i class="fas fa-info-circle"></i>
                    <span>No reports found. Try adjusting your filters or run the live demo to generate violations.</span>
                </div>
            `;
            return;
        }

        // Show ALL reports including in-progress ones (Pipeline_Luna behavior)
        list.innerHTML = `
            <div class="grid">
                ${filtered.map(v => this.renderReportCard(v)).join('')}
            </div>
        `;
    },

    // Check if report is ready to view
    isReportReady(violation) {
        const status = this.normalizeStatus(violation);
        return violation.has_report && 
               (status === 'completed' || status === 'partial' || status === 'unknown');
    },

    // Get status display info
    getStatusInfo(violation) {
        const status = this.normalizeStatus(violation);
        const ready = this.isReportReady(violation);
        
        switch(status) {
            case 'completed':
                if (ready) {
                    return { icon: 'fa-check-circle', color: 'success', text: 'Ready' };
                }
                return { icon: 'fa-spinner fa-spin', color: 'warning', text: 'Finalizing...' };
            case 'generating':
                return { icon: 'fa-spinner fa-spin', color: 'warning', text: 'Generating...' };
            case 'pending':
                return { icon: 'fa-clock', color: 'warning', text: 'Queued' };
            case 'failed':
                return { icon: 'fa-exclamation-triangle', color: 'danger', text: 'Failed' };
            case 'partial':
                return { icon: 'fa-exclamation-circle', color: 'warning', text: 'Partial' };
            default:
                return violation.has_report 
                    ? { icon: 'fa-check-circle', color: 'success', text: 'Ready' }
                    : { icon: 'fa-spinner fa-spin', color: 'warning', text: 'Processing' };
        }
    },

    // Handle report click with fallback for generating reports
    handleReportClick(violation) {
        if (this.isReportReady(violation)) {
            this.openReport(violation.report_id);
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
                const response = await fetch(`${API_CONFIG.BASE_URL}/api/report/${violation.report_id}/status`);
                if (response.ok) {
                    const data = await response.json();
                    detailedError = data.error_message || detailedError;
                }
            } catch (e) {
                console.error('Failed to fetch detailed error:', e);
            }
        }
        
        // Create modal overlay
        const modal = document.createElement('div');
        modal.id = 'report-status-modal';
        modal.style.cssText = `
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.5); display: flex; align-items: center;
            justify-content: center; z-index: 1000; padding: 0.75rem;
            overflow-y: auto;
        `;
        
        const errorDetails = violation.status === 'failed' && detailedError ? `
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
                    <button id="report-modal-process-btn" onclick="ReportsPage.generateNow('${violation.report_id}', { force: ${processAction.force} })" class="btn btn-success">
                        <i class="fas ${processAction.icon}"></i> ${processAction.label}
                    </button>
                    ${!ready ? `
                        <button onclick="ReportsPage.checkAndRefresh('${violation.report_id}')" class="btn btn-primary">
                            <i class="fas fa-sync"></i> Check Status
                        </button>
                    ` : ''}
                    ${ready ? `
                        <button onclick="ReportsPage.openReport('${violation.report_id}'); ReportsPage.closeModal();" class="btn btn-primary">
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

        if (status === 'completed' && !violation.has_report) {
            return 'Status says completed, but report file is not ready yet. Click Process Now to force generation.';
        }
        
        switch(status) {
            case 'generating':
                return 'The AI is analyzing the violation and generating a detailed report. This usually takes 30-60 seconds.';
            case 'pending':
                return 'This report is queued for processing. It will be generated shortly.';
            case 'failed':
                return `Report generation failed. ${violation.error_message || 'Please try again or contact support.'}`;
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
            this.modalRuntime.cooldownUntil = 0;
            this.modalRuntime.pollStartedAt = 0;
        }
        return this.modalRuntime;
    },

    updateModalEtaText() {
        const etaEl = document.getElementById('report-modal-eta');
        if (!etaEl) return;

        if (!this.modalRuntime.pollStartedAt) {
            etaEl.textContent = '';
            return;
        }

        const elapsedSec = Math.max(0, Math.floor((Date.now() - this.modalRuntime.pollStartedAt) / 1000));
        const remainingSec = Math.max(0, this.modalRuntime.expectedDurationSec - elapsedSec);
        etaEl.textContent = `Elapsed: ${elapsedSec}s | Est. remaining: ~${remainingSec}s`;
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
        const localReady = !!local.local_mode_possible;
        const pullHint = local.pull_command || 'ollama pull llama3';
        const startHint = local.start_command || 'ollama serve';

        let chooseLocal = false;
        if (localReady) {
            const recoveryChoice = window.confirm(
                `Provider quota is exhausted. Pending candidates: ${counts.total_candidates || 0}.\n\nRecommended: use FAILOVER pipeline now for highest chance of completion.\n\nOK = Use failover pipeline now\nCancel = Try Local mode first`
            );
            chooseLocal = !recoveryChoice;
        }

        if (chooseLocal) {
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
                `Provider quota is exhausted and Local mode is not ready on this backend.\n\nTo prepare local mode later (optional):\n1) ${startHint}\n2) ${pullHint}\n\nProceed with failover pipeline now?`
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
        const data = await API.getReportStatus(reportId);
        const status = String((data && data.status) || '').toLowerCase();
        const providerError = data && data.error_message ? String(data.error_message) : '';

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
            this.setModalStatusText('Report is queued for generation...');
            return false;
        }

        if (status === 'generating' || status === 'processing') {
            this.setModalStage('generating');
            this.setModalStatusText('AI is generating your report...');
            return false;
        }

        if (status === 'completed' && data.has_report) {
            this.setModalStage('completed');
            this.setModalStatusText('Report completed. Opening now...');
            if (autoOpen) {
                this.openReport(reportId);
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
        const ready = this.isReportReady(violation);
        const isCompleted = status === 'completed' && ready;

        return {
            force: isCompleted,
            label: isCompleted ? 'Reprocess Now' : 'Process Now',
            icon: isCompleted ? 'fa-rotate-right' : 'fa-bolt'
        };
    },

    async generateNow(reportId, options = {}) {
        const runtime = this.ensureModalRuntime(reportId);
        const now = Date.now();

        if (runtime.retryCount >= runtime.maxRetries) {
            this.setModalStatusText('Maximum retries reached. Please wait before trying again.');
            this.setModalProcessButtonEnabled(false);
            return;
        }

        if (runtime.cooldownUntil && now < runtime.cooldownUntil) {
            const waitSeconds = Math.max(1, Math.ceil((runtime.cooldownUntil - now) / 1000));
            this.setModalStatusText(`Queue is busy. Retry available in ${waitSeconds}s.`);
            this.setModalProcessButtonEnabled(false);
            return;
        }

        this.setModalProcessButtonEnabled(false);
        this.setModalStage('queued');
        this.setModalStatusText('Submitting request to queue...');

        try {
            const result = await API.generateReportNow(reportId, {
                force: !!options.force
            });
            if (!result || !result.success) {
                runtime.retryCount += 1;
                this.updateModalRetryText();

                const errorText = String(result?.error || 'Failed to prioritize report generation');
                const queueBusy = /queue|busy|rate|limit|full|capacity|409|429|503/i.test(errorText);
                if (this.isQuotaOrRateLimitError(errorText)) {
                    this.setProviderWarning('Provider quota/rate limit detected. Awaiting your recovery choice.');
                    await this.promptQuotaRecovery(reportId, errorText);
                }
                if (queueBusy) {
                    this.setModalStatusText(`Queue busy: ${errorText}`);
                    this.startModalCooldown(runtime.cooldownSeconds);
                    return;
                }

                this.setModalStatusText(errorText);
                this.setModalProcessButtonEnabled(runtime.retryCount < runtime.maxRetries);
                return;
            }

            this.notify(options.force ? 'Reprocess started successfully' : 'Report generation started successfully', 'success');
            this.stopModalCooldown();
            this.setModalStage('queued');
            this.setModalStatusText('Regeneration queued. Monitoring progress...');
            await this.refreshReports();
            this.startModalPolling(reportId, { autoOpen: true });
        } catch (error) {
            console.error('Process/reprocess request failed:', error);
            runtime.retryCount += 1;
            this.updateModalRetryText();
            this.setModalStatusText('Failed to prioritize report generation');
            this.setModalProcessButtonEnabled(runtime.retryCount < runtime.maxRetries);
            this.notify('Failed to prioritize report generation', 'error');
        }
    },

    renderReportCard(violation) {
        const date = new Date(violation.timestamp);
        const imageUrl = API.getImageUrl(violation.report_id, 'annotated.jpg');
        const statusInfo = this.getStatusInfo(violation);
        const isReady = this.isReportReady(violation);
        const processAction = this.getProcessAction(violation);
        const severityClass = (violation.severity === 'HIGH' || violation.severity === 'CRITICAL') ? 'danger' : 
                             (violation.severity === 'MEDIUM' ? 'warning' : 'info');
        
        return `
            <div class="card" id="report-${violation.report_id}" 
                 style="cursor: pointer; ${!isReady ? 'opacity: 0.9;' : ''}" 
                 onclick="ReportsPage.handleReportClick(${JSON.stringify(violation).replace(/"/g, '&quot;')})">
                <div style="height: 200px; overflow: hidden; background: #000; position: relative;">
                    ${violation.has_annotated ? 
                        `<img src="${imageUrl}" alt="Violation" style="width: 100%; height: 100%; object-fit: cover;">` :
                        `<div style="display: flex; align-items: center; justify-content: center; height: 100%;">
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
                </div>
                <div class="card-content">
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 1rem;">
                        <div style="flex: 1;">
                            <h3 style="color: var(--primary-color); margin-bottom: 0.5rem; font-size: 1.1rem;">
                                Report #${violation.report_id}
                            </h3>
                            <p style="color: #7f8c8d; font-size: 0.9rem; margin: 0;">
                                <i class="fas fa-clock"></i> ${date.toLocaleString()}
                            </p>
                        </div>
                        <span class="badge badge-${severityClass}">
                            ${violation.severity || 'High'}
                        </span>
                    </div>
                    
                    <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem;">
                        ${violation.has_original ? '<span class="badge badge-success"><i class="fas fa-image"></i> Original</span>' : ''}
                        ${violation.has_annotated ? '<span class="badge badge-success"><i class="fas fa-draw-polygon"></i> Annotated</span>' : ''}
                        <span class="badge badge-${statusInfo.color}">
                            <i class="fas ${statusInfo.icon}"></i> ${statusInfo.text}
                        </span>
                    </div>
                    
                    <div style="padding-top: 1rem; border-top: 1px solid var(--border-color);">
                        <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.9rem;">
                            <button class="btn btn-primary" style="padding: 0.45rem 0.75rem; font-size: 0.85rem;"
                                onclick="event.stopPropagation(); ReportsPage.generateNow('${violation.report_id}', { force: ${processAction.force} });">
                                <i class="fas ${processAction.icon}"></i> ${processAction.label}
                            </button>
                            ${isReady ? `
                                <button class="btn btn-secondary" style="padding: 0.45rem 0.75rem; font-size: 0.85rem;"
                                    onclick="event.stopPropagation(); ReportsPage.openReport('${violation.report_id}');">
                                    <i class="fas fa-file-alt"></i> Open Report
                                </button>
                            ` : ''}
                        </div>

                        <p style="margin: 0; color: var(--text-color); font-size: 0.9rem;">
                            <i class="fas fa-exclamation-triangle" style="color: var(--error-color);"></i>
                            <strong>${violation.violation_count || 0} Violation${violation.violation_count !== 1 ? 's' : ''}</strong>
                        </p>
                        ${violation.missing_ppe && violation.missing_ppe.length > 0 ? `
                            <div style="margin-top: 0.75rem; display: flex; gap: 0.5rem; flex-wrap: wrap;">
                                ${violation.missing_ppe.map(ppe => `
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
                        ${violation.device_id ? `
                            <p style="margin: 0.5rem 0 0 0; color: #95a5a6; font-size: 0.8rem;">
                                <i class="fas fa-desktop"></i> Device: ${violation.device_id}
                            </p>
                        ` : ''}
                    </div>
                </div>
            </div>
        `;
    }
};
