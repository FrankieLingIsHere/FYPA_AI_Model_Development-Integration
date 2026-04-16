// Settings Page Component
const SettingsPage = {
    _provisioningHandler: null,
    _runCheckupHandler: null,
    _refreshStatusHandler: null,
    _openLiveHandler: null,
    _busy: false,

    render() {
        return `
            <div class="page">
                <div class="card mb-3">
                    <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; flex-wrap: wrap;">
                        <span><i class="fas fa-gear"></i> Settings</span>
                        <button id="settingsOpenLiveMonitorBtn" class="btn btn-secondary" type="button">
                            <i class="fas fa-video"></i> Open Live Monitor
                        </button>
                    </div>
                    <div class="card-content">
                        <p style="margin: 0; color: var(--text-secondary);">
                            Local Mode Checkup now runs from this sidebar Settings page.
                        </p>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header" style="display: flex; justify-content: space-between; align-items: center; gap: 0.75rem; flex-wrap: wrap;">
                        <span><i class="fas fa-plug-circle-check"></i> Local Mode Checkup</span>
                        <span id="settingsProvisionBadge" class="badge badge-info">Checking...</span>
                    </div>
                    <div class="card-content">
                        <p id="settingsProvisionMessage" style="margin: 0; color: var(--text-color);">
                            Loading latest local mode provisioning status...
                        </p>
                        <p id="settingsProvisionMachine" style="margin: 0.45rem 0 0 0; color: var(--text-secondary); font-size: 0.9rem;"></p>

                        <div style="margin-top: 1rem; padding: 0.85rem; border-radius: 8px; background: var(--background-color); border: 1px solid var(--border-color);">
                            <label for="settingsAutoSetupToggle" style="display: flex; align-items: center; gap: 0.6rem; cursor: pointer;">
                                <input id="settingsAutoSetupToggle" type="checkbox" />
                                <span>Allow automatic local setup when network disconnects</span>
                            </label>
                        </div>

                        <div style="display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 1rem;">
                            <button id="settingsRunLocalCheckupBtn" class="btn btn-primary" type="button">
                                <i class="fas fa-wifi"></i> Run Local Mode Checkup
                            </button>
                            <button id="settingsRefreshProvisionBtn" class="btn btn-secondary" type="button">
                                <i class="fas fa-sync-alt"></i> Refresh Status
                            </button>
                        </div>

                        <p id="settingsCheckupStatus" style="margin: 0.8rem 0 0 0; color: var(--text-secondary);">
                            Checkup has not started in this session.
                        </p>
                    </div>
                </div>
            </div>
        `;
    },

    mount() {
        const runBtn = document.getElementById('settingsRunLocalCheckupBtn');
        if (runBtn) {
            this._runCheckupHandler = () => {
                this.runLocalModeCheckup();
            };
            runBtn.addEventListener('click', this._runCheckupHandler);
        }

        const refreshBtn = document.getElementById('settingsRefreshProvisionBtn');
        if (refreshBtn) {
            this._refreshStatusHandler = () => {
                if (window.PPEProvisioningStatus && typeof window.PPEProvisioningStatus.refresh === 'function') {
                    window.PPEProvisioningStatus.refresh({
                        source: 'settings-manual-refresh',
                        force: true
                    });
                }
            };
            refreshBtn.addEventListener('click', this._refreshStatusHandler);
        }

        const openLiveBtn = document.getElementById('settingsOpenLiveMonitorBtn');
        if (openLiveBtn) {
            this._openLiveHandler = () => Router.navigate('live');
            openLiveBtn.addEventListener('click', this._openLiveHandler);
        }

        this._provisioningHandler = (event) => {
            this.renderProvisioningStatus((event && event.detail) || null);
        };
        window.addEventListener('ppe-provisioning:status', this._provisioningHandler);

        const policy = window.PPELocalModePolicy && typeof window.PPELocalModePolicy.get === 'function'
            ? window.PPELocalModePolicy.get()
            : { autoSetupAllowed: false };
        const autoSetupToggle = document.getElementById('settingsAutoSetupToggle');
        if (autoSetupToggle) {
            autoSetupToggle.checked = !!policy.autoSetupAllowed;
        }

        if (window.PPEProvisioningStatus && typeof window.PPEProvisioningStatus.get === 'function') {
            this.renderProvisioningStatus(window.PPEProvisioningStatus.get());
        } else {
            this.renderProvisioningStatus(null);
        }

        if (window.PPEProvisioningStatus && typeof window.PPEProvisioningStatus.refresh === 'function') {
            window.PPEProvisioningStatus.refresh({
                source: 'settings-mount',
                force: true,
                notify: false
            });
        }

        if (APP_STATE.currentPage === 'settings-checkup') {
            setTimeout(() => this.runLocalModeCheckup(), 0);
        }
    },

    unmount() {
        const runBtn = document.getElementById('settingsRunLocalCheckupBtn');
        if (runBtn && this._runCheckupHandler) {
            runBtn.removeEventListener('click', this._runCheckupHandler);
        }
        this._runCheckupHandler = null;

        const refreshBtn = document.getElementById('settingsRefreshProvisionBtn');
        if (refreshBtn && this._refreshStatusHandler) {
            refreshBtn.removeEventListener('click', this._refreshStatusHandler);
        }
        this._refreshStatusHandler = null;

        const openLiveBtn = document.getElementById('settingsOpenLiveMonitorBtn');
        if (openLiveBtn && this._openLiveHandler) {
            openLiveBtn.removeEventListener('click', this._openLiveHandler);
        }
        this._openLiveHandler = null;

        if (this._provisioningHandler) {
            window.removeEventListener('ppe-provisioning:status', this._provisioningHandler);
            this._provisioningHandler = null;
        }

        this._busy = false;
    },

    notify(message, type = 'info') {
        if (typeof NotificationManager !== 'undefined') {
            if (type === 'success') return NotificationManager.success(message);
            if (type === 'warning') return NotificationManager.warning(message);
            if (type === 'error') return NotificationManager.error(message);
            return NotificationManager.info(message);
        }
        console.log(`[Settings:${type}] ${message}`);
    },

    setCheckupStatus(message, type = 'info') {
        const statusEl = document.getElementById('settingsCheckupStatus');
        if (!statusEl) return;

        statusEl.textContent = message;
        if (type === 'success') {
            statusEl.style.color = 'var(--success-color)';
        } else if (type === 'warning') {
            statusEl.style.color = 'var(--warning-color)';
        } else if (type === 'error') {
            statusEl.style.color = 'var(--error-color)';
        } else {
            statusEl.style.color = 'var(--text-secondary)';
        }
    },

    renderProvisioningStatus(statusPayload) {
        const badgeEl = document.getElementById('settingsProvisionBadge');
        const messageEl = document.getElementById('settingsProvisionMessage');
        const machineEl = document.getElementById('settingsProvisionMachine');

        if (!badgeEl || !messageEl || !machineEl) {
            return;
        }

        const status = String((statusPayload && statusPayload.status) || 'idle').toLowerCase();
        const machineId = String((statusPayload && (statusPayload.machineId || statusPayload.machine_id)) || '').trim();
        const adminPortalUrl = String((statusPayload && (statusPayload.adminPortalUrl || statusPayload.admin_portal_url)) || '').trim();

        badgeEl.className = 'badge badge-info';
        machineEl.textContent = '';

        if (status === 'provisioned' || status === 'credentials_present') {
            badgeEl.className = 'badge badge-success';
            badgeEl.textContent = 'Provisioned';
            messageEl.textContent = 'Approved and active. Cloud credentials are already configured on this backend.';
        } else if (status === 'pending_approval' || status === 'pending') {
            badgeEl.className = 'badge badge-warning';
            badgeEl.textContent = 'Pending Approval';
            messageEl.textContent = 'Approval request is pending. Status refresh is automatic.';
        } else if (status === 'rejected') {
            badgeEl.className = 'badge badge-danger';
            badgeEl.textContent = 'Rejected';
            messageEl.textContent = 'Approval request was rejected. Run Local Mode Checkup again to submit a new request.';
        } else if (status === 'error') {
            badgeEl.className = 'badge badge-warning';
            badgeEl.textContent = 'Status Error';
            messageEl.textContent = 'Unable to refresh provisioning status right now. Retrying in background.';
        } else {
            badgeEl.className = 'badge badge-info';
            badgeEl.textContent = 'Not Requested';
            messageEl.textContent = 'No approval request yet. Run Local Mode Checkup to begin local provisioning.';
        }

        if (machineId) {
            machineEl.textContent = `Machine ID: ${machineId}`;
            if (adminPortalUrl) {
                machineEl.textContent += ` | Admin portal: ${adminPortalUrl}`;
            }
            return;
        }

        if (adminPortalUrl) {
            machineEl.textContent = `Admin portal: ${adminPortalUrl}`;
        }
    },

    async runLocalModeCheckup() {
        if (this._busy) {
            return;
        }

        const runBtn = document.getElementById('settingsRunLocalCheckupBtn');
        const autoSetupToggle = document.getElementById('settingsAutoSetupToggle');

        this._busy = true;
        if (runBtn) {
            runBtn.disabled = true;
            runBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking...';
        }

        this.setCheckupStatus('Running local mode checkup...', 'info');

        try {
            const diagnostics = await API.getReportRecoveryOptions();
            if (!diagnostics || diagnostics.success === false) {
                throw new Error((diagnostics && diagnostics.error) || 'Failed to fetch local mode diagnostics');
            }

            const local = diagnostics.local || {};
            let localReady = !!local.local_mode_possible;
            const ollamaReady = !!(local.ollama_installed || local.ollama_running || local.model_available);

            if (!ollamaReady) {
                this.setCheckupStatus('Ollama is not detected yet. Install/start Ollama then rerun checkup.', 'warning');
                this.notify('Ollama is not detected on this host. Local setup may not complete.', 'warning');
            }

            if (!localReady) {
                this.setCheckupStatus('Preparing local mode packages and models...', 'info');
                const prepResult = await API.prepareLocalMode({
                    autoPull: true,
                    setLocalFirst: true,
                    waitSeconds: 8,
                    pullTimeoutSeconds: 900
                });

                localReady = !!(prepResult && prepResult.success && prepResult.after && prepResult.after.local_mode_possible);

                if (!localReady && prepResult && prepResult.error) {
                    this.setCheckupStatus(prepResult.error, 'warning');
                }
            }

            const allowAutoSetup = autoSetupToggle ? !!autoSetupToggle.checked : false;
            if (window.PPELocalModePolicy && typeof window.PPELocalModePolicy.set === 'function') {
                window.PPELocalModePolicy.set({
                    checkupCompleted: true,
                    autoSetupAllowed: allowAutoSetup
                });
            }

            let provisionResult = null;
            if (window.PPEProvisioningStatus && typeof window.PPEProvisioningStatus.refresh === 'function') {
                provisionResult = await window.PPEProvisioningStatus.refresh({
                    source: 'settings-checkup-auto',
                    force: true,
                    useAutoEndpoint: true,
                    payload: {}
                });
            } else {
                provisionResult = await API.autoProvisionLocalModeCredentials();
            }

            const provisionStatus = String((provisionResult && provisionResult.status) || '').toLowerCase();

            if (provisionStatus === 'provisioned' || provisionStatus === 'credentials_present') {
                this.setCheckupStatus('Checkup completed. Provisioning approved and cloud sync is active.', 'success');
                this.notify('Local mode checkup completed and provisioning is active.', 'success');
            } else if (provisionStatus === 'pending_approval' || provisionStatus === 'pending') {
                this.setCheckupStatus('Checkup completed. Approval request is pending admin review.', 'warning');
                this.notify('Approval request submitted. Status will update automatically.', 'warning');
            } else if (provisionStatus === 'rejected') {
                this.setCheckupStatus('Approval request was rejected. Contact admin and rerun checkup.', 'error');
                this.notify('Provision request rejected by admin.', 'error');
            } else if (localReady) {
                this.setCheckupStatus('Checkup completed for local readiness. Provisioning request may still be required.', 'success');
                this.notify('Local mode checkup completed.', 'success');
            } else {
                this.setCheckupStatus('Checkup finished but local mode is still not fully ready.', 'warning');
            }

            if (window.PPEProvisioningStatus && typeof window.PPEProvisioningStatus.refresh === 'function') {
                window.PPEProvisioningStatus.refresh({
                    source: 'settings-checkup-followup',
                    force: true,
                    notify: false
                });
            }

            if (APP_STATE.currentPage === 'settings-checkup') {
                Router.navigate('settings');
            }
        } catch (error) {
            console.error('Local mode checkup failed:', error);
            this.setCheckupStatus(error.message || 'Local mode checkup failed.', 'error');
            this.notify(error.message || 'Local mode checkup failed.', 'error');
        } finally {
            this._busy = false;
            if (runBtn) {
                runBtn.disabled = false;
                runBtn.innerHTML = '<i class="fas fa-wifi"></i> Run Local Mode Checkup';
            }
        }
    }
};
