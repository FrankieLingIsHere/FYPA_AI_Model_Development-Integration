// Global Settings Modal (page-agnostic popup)
const GlobalSettingsModal = {
    initialized: false,
    isOpen: false,
    closeHandler: null,
    keydownHandler: null,
    localProvisionPollInterval: null,
    localProvisionState: {
        status: 'idle',
        machineId: '',
        adminPortalUrl: ''
    },

    RECOMMENDED_SETTINGS: {
        environment_validation_enabled: true,
        cooldown_seconds: 3,
        provider_routing: {
            routing_profile: 'local',
            model_api_enabled: false,
            gemini_enabled: false,
            nlp_provider_order: 'ollama',
            vision_provider_order: 'ollama',
            embedding_provider_order: 'ollama',
            nlp_model: 'gemma4',
            vision_model: 'gemma4',
            embedding_model: 'nomic-embed-text',
            gemini_model: 'gemini-2.5-flash'
        }
    },

    LOCAL_ONLY_PROVIDER_SETTINGS: {
        routing_profile: 'local',
        model_api_enabled: false,
        gemini_enabled: false,
        nlp_provider_order: 'ollama',
        vision_provider_order: 'ollama',
        embedding_provider_order: 'ollama',
        nlp_model: 'gemma4',
        vision_model: 'gemma4',
        embedding_model: 'nomic-embed-text',
        gemini_model: 'gemini-2.5-flash'
    },

    API_MODE_SETTINGS: {
        routing_profile: 'cloud',
        model_api_enabled: false,
        gemini_enabled: true,
        nlp_provider_order: 'gemini',
        vision_provider_order: 'gemini',
        embedding_provider_order: 'model_api',
        nlp_model: 'gemini-2.5-flash',
        vision_model: 'gemini-2.5-flash',
        embedding_model: 'nomic-ai/nomic-embed-text-v1.5',
        gemini_model: 'gemini-2.5-flash'
    },

    ensureStyles() {
        if (document.getElementById('globalSettingsModalStyles')) return;

        const style = document.createElement('style');
        style.id = 'globalSettingsModalStyles';
        style.textContent = `
            .global-settings-modal {
                position: fixed;
                inset: 0;
                background: rgba(15, 23, 42, 0.58);
                z-index: 1300;
                display: none;
                align-items: center;
                justify-content: center;
                padding: 1rem;
            }

            .global-settings-modal.open {
                display: flex;
            }

            .global-settings-window {
                width: min(1100px, 96vw);
                max-height: 92vh;
                overflow: hidden;
                background: var(--card-bg, #ffffff);
                border: 1px solid var(--border-color, #dce3ec);
                border-radius: 14px;
                box-shadow: 0 18px 50px rgba(15, 23, 42, 0.22);
                display: flex;
                flex-direction: column;
            }

            .global-settings-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 0.75rem;
                padding: 1rem 1.2rem;
                border-bottom: 1px solid var(--border-color, #dce3ec);
            }

            .global-settings-content {
                overflow: auto;
                padding: 1rem 1.2rem 1.2rem 1.2rem;
            }

            .global-settings-tabs {
                display: flex;
                gap: 0.5rem;
                margin-bottom: 1rem;
                flex-wrap: wrap;
            }

            .global-settings-tab {
                border: 1px solid var(--border-color, #dce3ec);
                background: #fff;
                color: var(--text-color, #1f2937);
                padding: 0.45rem 0.8rem;
                border-radius: 999px;
                cursor: pointer;
                font-weight: 600;
            }

            .global-settings-tab.active {
                border-color: var(--primary-color, #2f5fad);
                background: rgba(47, 95, 173, 0.1);
                color: var(--primary-color, #2f5fad);
            }

            .global-settings-section {
                display: none;
            }

            .global-settings-section.active {
                display: block;
            }

            .global-settings-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.9rem;
            }

            .global-settings-card {
                padding: 0.9rem;
                border-radius: 10px;
                border: 1px solid var(--border-color, #dce3ec);
                background: #fff;
            }

            .global-settings-card h4 {
                margin: 0 0 0.45rem 0;
            }

            .global-settings-status {
                margin-top: 0.6rem;
                font-size: 0.88rem;
                color: var(--text-secondary, #6b7280);
            }

            .global-provider-input {
                width: 100%;
                margin-top: 0.35rem;
                border: 1px solid var(--border-color, #dce3ec);
                border-radius: 8px;
                padding: 0.45rem 0.55rem;
                background: #fff;
                color: var(--text-color, #1f2937);
            }

            @media (max-width: 920px) {
                .global-settings-grid {
                    grid-template-columns: 1fr;
                }
            }

            @media (max-width: 768px) {
                .global-settings-window {
                    width: 100vw;
                    max-height: 100vh;
                    height: 100vh;
                    border-radius: 0;
                }

                .global-settings-header {
                    align-items: flex-start;
                    flex-direction: column;
                }
            }
        `;

        document.head.appendChild(style);
    },

    ensureDom() {
        if (document.getElementById('globalSettingsModal')) return;

        const modal = document.createElement('div');
        modal.id = 'globalSettingsModal';
        modal.className = 'global-settings-modal';
        modal.setAttribute('aria-hidden', 'true');
        modal.innerHTML = `
            <div id="globalSettingsWindow" class="global-settings-window" role="dialog" aria-modal="true" aria-labelledby="globalSettingsTitle">
                <div class="global-settings-header">
                    <h3 id="globalSettingsTitle" style="margin: 0;"><i class="fas fa-cogs"></i> Settings</h3>
                    <div style="display: flex; gap: 0.55rem; flex-wrap: wrap;">
                        <button id="globalSettingsRecommendedBtn" class="btn btn-primary" type="button">
                            <i class="fas fa-magic"></i> Use Recommended Settings
                        </button>
                        <button id="globalSettingsCloseBtn" class="btn btn-danger" type="button">
                            <i class="fas fa-times"></i> Close
                        </button>
                    </div>
                </div>

                <div class="global-settings-content">
                    <div class="global-settings-tabs">
                        <button type="button" class="global-settings-tab active" data-global-settings-tab="Dsettings">Detection Settings</button>
                        <button type="button" class="global-settings-tab" data-global-settings-tab="Psettings">Processing Settings</button>
                    </div>

                    <section id="global-settings-tab-Dsettings" class="global-settings-section active">
                        <h3 style="margin-top: 0;">Detection Settings</h3>
                        <div class="global-settings-grid">
                            <div class="global-settings-card">
                                <h4>Active PPE Classes</h4>
                                <p style="margin: 0; color: var(--text-secondary);">Hardhat, Safety Vest, Mask, Gloves, Safety Shoes, Goggles, and NO-* violation classes.</p>
                            </div>
                            <div class="global-settings-card">
                                <h4>Violation Rules</h4>
                                <ul style="margin: 0 0 0 1.1rem; color: var(--text-secondary); line-height: 1.7;">
                                    <li>NO-Hardhat triggers immediate violation report flow.</li>
                                    <li>Detection confidence threshold remains optimized for safety recall.</li>
                                    <li>Frames are processed with live pipeline quality controls.</li>
                                </ul>
                            </div>
                        </div>
                    </section>

                    <section id="global-settings-tab-Psettings" class="global-settings-section">
                        <h3 style="margin-top: 0;">Processing Settings</h3>

                        <div class="global-settings-grid">
                            <div class="global-settings-card">
                                <h4><i class="fas fa-building" style="color: var(--primary-color);"></i> Environment Validation</h4>
                                <label class="toggle-switch" style="display: inline-block; margin-top: 0.2rem;">
                                    <input type="checkbox" id="globalEnvValidationToggle">
                                    <span class="toggle-slider"></span>
                                </label>
                                <div id="globalEnvValidationStatus" class="global-settings-status"></div>
                            </div>

                            <div class="global-settings-card">
                                <h4><i class="fas fa-clock" style="color: var(--warning-color);"></i> Capture Cooldown</h4>
                                <div style="display: flex; align-items: center; gap: 0.7rem; margin-top: 0.4rem;">
                                    <input type="range" id="globalCooldownSlider" min="1" max="30" value="3" style="flex: 1;">
                                    <span id="globalCooldownValue" style="font-weight: 700; min-width: 54px; text-align: center;">3s</span>
                                </div>
                                <button id="globalApplyCooldownBtn" class="btn btn-primary" type="button" style="margin-top: 0.75rem; width: 100%;">
                                    <i class="fas fa-save"></i> Apply Cooldown
                                </button>
                            </div>
                        </div>

                        <div class="global-settings-card" style="margin-top: 0.9rem;">
                            <h4><i class="fas fa-route" style="color: var(--primary-color);"></i> Provider Routing</h4>
                            <div class="global-settings-grid" style="margin-top: 0.45rem;">
                                <div>
                                    <label style="font-weight: 600;">NLP Routing Mode</label>
                                    <select id="globalNlpProviderOrderSelect" class="global-provider-input">
                                        <option value="ollama">Local only (Ollama)</option>
                                        <option value="gemini">Cloud only (Gemini)</option>
                                    </select>
                                </div>
                                <div>
                                    <label style="font-weight: 600;">Vision Routing Mode</label>
                                    <select id="globalVisionProviderOrderSelect" class="global-provider-input">
                                        <option value="ollama">Local only (Ollama)</option>
                                        <option value="gemini">Cloud only (Gemini)</option>
                                    </select>
                                </div>
                                <div>
                                    <label style="font-weight: 600;">Embedding Routing Mode</label>
                                    <select id="globalEmbeddingProviderOrderSelect" class="global-provider-input">
                                        <option value="ollama">Local only (Ollama)</option>
                                        <option value="model_api">Cloud API embeddings</option>
                                    </select>
                                </div>
                                <div>
                                    <label style="font-weight: 600;">NLP Model</label>
                                    <select id="globalNlpModelSelect" class="global-provider-input">
                                        <option value="gemma4">Gemma 4 (local)</option>
                                        <option value="gemini-2.5-flash">gemini-2.5-flash</option>
                                    </select>
                                </div>
                                <div>
                                    <label style="font-weight: 600;">Vision Model</label>
                                    <select id="globalVisionModelSelect" class="global-provider-input">
                                        <option value="gemma4">Gemma 4 (local)</option>
                                        <option value="gemini-2.5-flash">gemini-2.5-flash</option>
                                    </select>
                                </div>
                                <div>
                                    <label style="font-weight: 600;">Gemini Model</label>
                                    <select id="globalGeminiModelSelect" class="global-provider-input">
                                        <option value="gemini-2.5-flash">gemini-2.5-flash</option>
                                        <option value="gemini-2.5-pro">gemini-2.5-pro</option>
                                    </select>
                                </div>
                            </div>
                            <div style="display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 0.85rem;">
                                <button id="globalApplyProviderRoutingBtn" class="btn btn-primary" type="button">
                                    <i class="fas fa-save"></i> Apply Local Profile
                                </button>
                                <button id="globalApplyApiModeBtn" class="btn btn-secondary" type="button">
                                    <i class="fas fa-cloud"></i> Switch to API Mode
                                </button>
                                <button id="globalReloadProviderRoutingBtn" class="btn btn-secondary" type="button">
                                    <i class="fas fa-sync-alt"></i> Reload
                                </button>
                            </div>
                            <div id="globalProviderRoutingStatus" class="global-settings-status"></div>
                        </div>

                        <div class="global-settings-card" style="margin-top: 0.9rem;">
                            <h4><i class="fas fa-wifi" style="color: var(--primary-color);"></i> Local Mode Checkup</h4>
                            <div style="display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 0.35rem;">
                                <button id="globalRunLocalModeCheckupBtn" class="btn btn-secondary" type="button">
                                    <i class="fas fa-wifi"></i> Run Local Mode Checkup
                                </button>
                                <button id="globalRedownloadInstallerBtn" class="btn btn-secondary" type="button" style="display: inline-flex;">
                                    <i class="fas fa-download"></i> Re-download Installer BAT
                                </button>
                            </div>
                            <div id="globalLocalModeCheckupStatus" class="global-settings-status" style="margin-top: 0.65rem;">
                                Local mode checkup not completed yet. Offline auto-setup remains disabled.
                            </div>
                        </div>
                    </section>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
    },

    getEl(id) {
        return document.getElementById(id);
    },

    showNotification(message, type = 'info') {
        if (typeof NotificationManager !== 'undefined') {
            if (type === 'success') return NotificationManager.success(message);
            if (type === 'warning') return NotificationManager.warning(message);
            if (type === 'error') return NotificationManager.error(message);
            return NotificationManager.info(message);
        }
        console.log(`[GlobalSettings:${type}] ${message}`);
    },

    setProviderStatus(message, type = 'info') {
        const statusEl = this.getEl('globalProviderRoutingStatus');
        if (!statusEl) return;

        statusEl.textContent = String(message || '').trim();
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

    setSelectValueOrInject(selectEl, value, customPrefix) {
        if (!selectEl) return;
        const normalizedValue = String(value || '').trim();
        if (!normalizedValue) return;
        const existing = Array.from(selectEl.options || []).find((opt) => opt.value === normalizedValue);
        if (existing) {
            selectEl.value = normalizedValue;
            return;
        }

        const option = document.createElement('option');
        option.value = normalizedValue;
        option.textContent = `${customPrefix}: ${normalizedValue}`;
        selectEl.appendChild(option);
        selectEl.value = normalizedValue;
    },

    lockBodyScroll() {
        const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
        if (scrollbarWidth > 0) {
            document.body.style.paddingRight = `${scrollbarWidth}px`;
        }
        document.body.classList.add('settings-modal-open');
    },

    unlockBodyScroll() {
        document.body.classList.remove('settings-modal-open');
        document.body.style.paddingRight = '';
    },

    normalizeLocalProvisionStatus(statusRaw) {
        const normalized = String(statusRaw || '').toLowerCase().trim();
        if (normalized === 'pending' || normalized === 'pending_approval') return 'pending_approval';
        if (normalized === 'credentials_present') return 'credentials_present';
        if (normalized === 'provisioned') return 'provisioned';
        if (normalized === 'rejected') return 'rejected';
        if (normalized === 'error') return 'error';
        return normalized || 'idle';
    },

    syncLocalProvisionStateFromPayload(payload) {
        const source = payload && typeof payload === 'object' ? payload : {};
        this.localProvisionState = {
            status: this.normalizeLocalProvisionStatus(source.status || this.localProvisionState.status),
            machineId: String(source.machineId || source.machine_id || this.localProvisionState.machineId || '').trim(),
            adminPortalUrl: String(source.adminPortalUrl || source.admin_portal_url || this.localProvisionState.adminPortalUrl || '').trim()
        };

        this.updateLocalModeCheckupStatus();
        this.updateInstallerRedownloadButton();
    },

    canIssueInstallerRedownload(statusRaw, machineIdRaw) {
        const status = this.normalizeLocalProvisionStatus(statusRaw);
        const machineId = String(machineIdRaw || '').trim();
        if (!machineId) return false;
        return status === 'approved' || status === 'provisioned' || status === 'credentials_present';
    },

    updateInstallerRedownloadButton() {
        const btn = this.getEl('globalRedownloadInstallerBtn');
        if (!btn) return;

        const status = this.normalizeLocalProvisionStatus(this.localProvisionState.status);
        const machineId = String(this.localProvisionState.machineId || '').trim();
        const canRedownload = this.canIssueInstallerRedownload(status, machineId);

        btn.style.display = 'inline-flex';
        btn.disabled = !canRedownload;

        if (!machineId) {
            btn.title = 'Run Local Mode Checkup first to register this device and obtain machine ID.';
            return;
        }

        if (canRedownload) {
            btn.title = 'Re-issue a fresh one-time installer BAT for this approved machine.';
            return;
        }

        if (status === 'pending_approval') {
            btn.title = 'Installer re-issue becomes available after admin approval.';
            return;
        }

        if (status === 'rejected') {
            btn.title = 'Provision request was rejected. Rerun Local Mode Checkup after admin review.';
            return;
        }

        btn.title = 'Installer re-issue is available after device approval.';
    },

    updateLocalModeCheckupStatus() {
        const statusEl = this.getEl('globalLocalModeCheckupStatus');
        if (!statusEl) return;

        const status = String(this.localProvisionState.status || '').toLowerCase();
        const machineId = String(this.localProvisionState.machineId || '').trim();
        const adminPortalUrl = String(this.localProvisionState.adminPortalUrl || '').trim();

        if (status === 'pending_approval') {
            const machineText = machineId ? ` for machine ${machineId}` : '';
            const portalText = adminPortalUrl ? ` Admin portal: ${adminPortalUrl}` : '';
            statusEl.textContent = `Provision request submitted${machineText}. Waiting for admin approval.${portalText}`;
            statusEl.style.color = 'var(--warning-color)';
            return;
        }

        if (status === 'provisioned') {
            statusEl.textContent = 'Local mode is approved and provisioned. Cloud credentials are active on this backend.';
            statusEl.style.color = 'var(--success-color)';
            return;
        }

        if (status === 'approved') {
            statusEl.textContent = 'Device is approved. You can re-issue a fresh installer BAT below.';
            statusEl.style.color = 'var(--success-color)';
            return;
        }

        if (status === 'credentials_present') {
            statusEl.textContent = 'Cloud credentials exist on this backend, but this device is not marked provisioned yet.';
            statusEl.style.color = 'var(--warning-color)';
            return;
        }

        if (status === 'rejected') {
            statusEl.textContent = 'Provision request was rejected by administrator. Contact admin and rerun Local Mode Checkup.';
            statusEl.style.color = 'var(--error-color)';
            return;
        }

        const policyApi = window.PPELocalModePolicy;
        const policy = policyApi && typeof policyApi.get === 'function'
            ? policyApi.get()
            : { checkupCompleted: false, autoSetupAllowed: false };

        if (!policy.checkupCompleted) {
            statusEl.textContent = 'Local mode checkup not completed yet. Offline auto-setup remains disabled.';
            statusEl.style.color = 'var(--text-secondary)';
            return;
        }

        if (policy.autoSetupAllowed) {
            statusEl.textContent = 'Local mode checkup completed. Offline auto-setup is enabled.';
            statusEl.style.color = 'var(--success-color)';
            return;
        }

        statusEl.textContent = 'Local checkup preference saved. Offline auto-setup is disabled by preference.';
        statusEl.style.color = 'var(--warning-color)';
    },

    updateEnvValidationStatus(enabled) {
        const statusEl = this.getEl('globalEnvValidationStatus');
        if (!statusEl) return;

        if (enabled) {
            statusEl.innerHTML = '<i class="fas fa-check-circle" style="color: var(--success-color);"></i> Environment filtering is enabled.';
            statusEl.style.color = 'var(--success-color)';
            return;
        }

        statusEl.innerHTML = '<i class="fas fa-exclamation-triangle" style="color: var(--warning-color);"></i> All environments are processed (testing mode).';
        statusEl.style.color = 'var(--warning-color)';
    },

    async setEnvironmentValidation(enabled) {
        const response = await fetch(`${API_CONFIG.BASE_URL}/api/settings/environment-validation`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: !!enabled })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to update environment validation');
        }
        return data;
    },

    async setCooldown(seconds) {
        const response = await fetch(`${API_CONFIG.BASE_URL}/api/settings/cooldown`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cooldown_seconds: Number(seconds) })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to update cooldown');
        }
        return data;
    },

    async loadCurrentSettings() {
        try {
            const [envResponse, cooldownResponse] = await Promise.all([
                fetch(`${API_CONFIG.BASE_URL}/api/settings/environment-validation`),
                fetch(`${API_CONFIG.BASE_URL}/api/settings/cooldown`)
            ]);

            const envData = await envResponse.json().catch(() => ({}));
            const cooldownData = await cooldownResponse.json().catch(() => ({}));

            const envToggle = this.getEl('globalEnvValidationToggle');
            const cooldownSlider = this.getEl('globalCooldownSlider');
            const cooldownValue = this.getEl('globalCooldownValue');

            if (envToggle && envData && typeof envData.enabled === 'boolean') {
                envToggle.checked = !!envData.enabled;
                this.updateEnvValidationStatus(envToggle.checked);
            }

            const resolvedCooldown = Number(cooldownData.cooldown_seconds || 3);
            if (cooldownSlider) {
                cooldownSlider.value = String(resolvedCooldown);
            }
            if (cooldownValue) {
                cooldownValue.textContent = `${resolvedCooldown}s`;
            }
        } catch (error) {
            console.error('GlobalSettingsModal: failed loading current settings', error);
            this.setProviderStatus('Failed to load current settings', 'warning');
        }
    },

    async loadProviderRoutingSettings() {
        try {
            this.setProviderStatus('Loading provider settings...');
            const settings = await API.getProviderRoutingSettings();
            if (!settings) {
                this.setProviderStatus('Unable to load provider routing settings', 'warning');
                return;
            }

            const nlpProviderOrderSelect = this.getEl('globalNlpProviderOrderSelect');
            const visionProviderOrderSelect = this.getEl('globalVisionProviderOrderSelect');
            const embeddingProviderOrderSelect = this.getEl('globalEmbeddingProviderOrderSelect');
            const nlpModelSelect = this.getEl('globalNlpModelSelect');
            const visionModelSelect = this.getEl('globalVisionModelSelect');
            const geminiModelSelect = this.getEl('globalGeminiModelSelect');

            this.setSelectValueOrInject(nlpProviderOrderSelect, (settings.nlp_provider_order || []).join(','), 'Current order');
            this.setSelectValueOrInject(visionProviderOrderSelect, (settings.vision_provider_order || []).join(','), 'Current order');
            this.setSelectValueOrInject(embeddingProviderOrderSelect, (settings.embedding_provider_order || []).join(','), 'Current order');
            this.setSelectValueOrInject(nlpModelSelect, settings.nlp_model || '', 'Current model');
            this.setSelectValueOrInject(visionModelSelect, settings.vision_model || '', 'Current model');
            this.setSelectValueOrInject(geminiModelSelect, settings.gemini_model || '', 'Current model');

            const profile = String(settings.routing_profile || '').trim().toLowerCase() === 'cloud' ? 'cloud' : 'local';
            this.setProviderStatus(`Provider settings loaded (${profile} profile)`, 'info');
        } catch (error) {
            console.error('GlobalSettingsModal: failed loading provider routing', error);
            this.setProviderStatus('Failed to load provider settings', 'error');
        }
    },

    async applyProviderRoutingLocalProfile() {
        const applyBtn = this.getEl('globalApplyProviderRoutingBtn');
        if (!applyBtn) return;

        try {
            applyBtn.disabled = true;
            applyBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Applying...';

            const result = await API.updateProviderRoutingSettings({
                ...this.LOCAL_ONLY_PROVIDER_SETTINGS
            });

            if (!result || !result.success) {
                throw new Error((result && result.error) || 'Failed to apply local provider profile');
            }

            this.setProviderStatus('Local provider profile applied', 'success');
            this.showNotification('Local provider profile applied', 'success');
            await this.loadProviderRoutingSettings();
        } catch (error) {
            console.error('GlobalSettingsModal: apply local profile failed', error);
            this.setProviderStatus(error.message || 'Failed applying local provider profile', 'error');
            this.showNotification(error.message || 'Failed applying local provider profile', 'error');
        } finally {
            applyBtn.disabled = false;
            applyBtn.innerHTML = '<i class="fas fa-save"></i> Apply Local Profile';
        }
    },

    async applyApiModeProfile() {
        const btn = this.getEl('globalApplyApiModeBtn');
        if (!btn) return;

        try {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Switching...';

            const result = await API.updateProviderRoutingSettings({
                ...this.API_MODE_SETTINGS
            });

            if (!result || !result.success) {
                throw new Error((result && result.error) || 'Failed to switch to API mode');
            }

            this.setProviderStatus('API mode profile applied', 'success');
            this.showNotification('Switched to API mode', 'success');
            await this.loadProviderRoutingSettings();
        } catch (error) {
            console.error('GlobalSettingsModal: apply API mode failed', error);
            this.setProviderStatus(error.message || 'Failed to switch to API mode', 'error');
            this.showNotification(error.message || 'Failed to switch to API mode', 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-cloud"></i> Switch to API Mode';
        }
    },

    async applyRecommendedSettings() {
        const btn = this.getEl('globalSettingsRecommendedBtn');
        if (!btn) return;

        try {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Applying...';

            await this.setEnvironmentValidation(!!this.RECOMMENDED_SETTINGS.environment_validation_enabled);
            await this.setCooldown(this.RECOMMENDED_SETTINGS.cooldown_seconds);

            const providerResult = await API.updateProviderRoutingSettings({
                ...this.RECOMMENDED_SETTINGS.provider_routing
            });
            if (!providerResult || !providerResult.success) {
                throw new Error((providerResult && providerResult.error) || 'Failed to apply recommended provider settings');
            }

            await this.loadCurrentSettings();
            await this.loadProviderRoutingSettings();
            this.setProviderStatus('Recommended settings applied', 'success');
            this.showNotification('Recommended settings applied', 'success');
        } catch (error) {
            console.error('GlobalSettingsModal: apply recommended failed', error);
            this.setProviderStatus(error.message || 'Failed applying recommended settings', 'error');
            this.showNotification(error.message || 'Failed applying recommended settings', 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-magic"></i> Use Recommended Settings';
        }
    },

    async refreshProvisioningState() {
        if (window.PPEProvisioningStatus && typeof window.PPEProvisioningStatus.refresh === 'function') {
            const state = await window.PPEProvisioningStatus.refresh({
                source: 'global-settings-open',
                force: true,
                notify: false
            });
            this.syncLocalProvisionStateFromPayload(state);
            return;
        }

        const state = await API.getLocalModeProvisioningStatus();
        this.syncLocalProvisionStateFromPayload(state);
    },

    async runLocalModeCheckup() {
        const btn = this.getEl('globalRunLocalModeCheckupBtn');
        if (!btn) return;

        try {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking...';
            this.setProviderStatus('Running local mode checkup...', 'info');

            const options = await API.getReportRecoveryOptions();
            const local = (options && options.local) || {};
            let ready = !!local.local_mode_possible;

            if (!ready) {
                const prep = await API.prepareLocalMode({
                    autoPull: true,
                    setLocalFirst: false,
                    waitSeconds: 8,
                    pullTimeoutSeconds: 600
                });

                ready = !!(prep && prep.success && prep.local && prep.local.local_mode_possible);
                if (!ready) {
                    const prepError = String((prep && prep.error) || 'Local mode is still not ready after setup attempt.');
                    this.setProviderStatus(prepError, 'warning');
                    this.showNotification(prepError, 'warning');
                }
            }

            if (window.PPELocalModePolicy && typeof window.PPELocalModePolicy.set === 'function') {
                window.PPELocalModePolicy.set({
                    checkupCompleted: ready,
                    autoSetupAllowed: ready
                });
            }

            const provisionResult = await API.autoProvisionLocalModeCredentials();
            this.syncLocalProvisionStateFromPayload(provisionResult || {});

            const status = this.normalizeLocalProvisionStatus((provisionResult && provisionResult.status) || 'idle');
            if (status === 'provisioned' || status === 'credentials_present') {
                this.setProviderStatus('Provisioning completed. Cloud sync is now available.', 'success');
                this.showNotification('Provisioning completed. Cloud sync is now available.', 'success');
            } else if (status === 'pending_approval') {
                this.setProviderStatus('Provision request submitted. Waiting for admin approval.', 'warning');
                this.showNotification('Provision request submitted. Waiting for admin approval.', 'warning');
                this.ensureLocalProvisionPolling();
            } else if (status === 'rejected') {
                this.setProviderStatus('Provision request was rejected by administrator.', 'error');
                this.showNotification('Provision request was rejected by administrator.', 'error');
            } else if (ready) {
                this.setProviderStatus('Local mode checkup completed successfully.', 'success');
                this.showNotification('Local mode checkup completed.', 'success');
            }

            await this.refreshProvisioningState();
        } catch (error) {
            console.error('GlobalSettingsModal: local checkup failed', error);
            this.setProviderStatus(error.message || 'Local mode checkup failed', 'error');
            this.showNotification(error.message || 'Local mode checkup failed', 'error');
        } finally {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-wifi"></i> Run Local Mode Checkup';
        }
    },

    ensureLocalProvisionPolling() {
        if (this.localProvisionPollInterval) return;

        this.localProvisionPollInterval = setInterval(async () => {
            if (!this.isOpen) return;

            const status = this.normalizeLocalProvisionStatus(this.localProvisionState.status || 'idle');
            if (status !== 'pending_approval') {
                return;
            }

            try {
                const pollResult = await API.autoProvisionLocalModeCredentials();
                this.syncLocalProvisionStateFromPayload(pollResult || {});
                const pollStatus = this.normalizeLocalProvisionStatus((pollResult && pollResult.status) || 'idle');
                if (pollStatus === 'provisioned' || pollStatus === 'credentials_present' || pollStatus === 'rejected') {
                    this.stopLocalProvisionPolling();
                }
            } catch (error) {
                console.warn('GlobalSettingsModal: silent provision poll failed', error);
            }
        }, 15000);
    },

    stopLocalProvisionPolling() {
        if (!this.localProvisionPollInterval) return;
        clearInterval(this.localProvisionPollInterval);
        this.localProvisionPollInterval = null;
    },

    activateTab(tabKey) {
        const normalized = String(tabKey || 'Dsettings').trim() || 'Dsettings';
        document.querySelectorAll('.global-settings-tab').forEach((tab) => {
            tab.classList.toggle('active', tab.dataset.globalSettingsTab === normalized);
        });

        document.querySelectorAll('.global-settings-section').forEach((section) => {
            section.classList.toggle('active', section.id === `global-settings-tab-${normalized}`);
        });
    },

    focusLocalCheckupControls() {
        this.activateTab('Psettings');
        const btn = this.getEl('globalRunLocalModeCheckupBtn');
        const status = this.getEl('globalLocalModeCheckupStatus');
        if (!btn) return;

        try {
            btn.focus({ preventScroll: true });
        } catch (error) {
            btn.focus();
        }

        try {
            btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
        } catch (error) {
            btn.scrollIntoView();
        }

        btn.style.boxShadow = '0 0 0 3px rgba(224, 156, 46, 0.42)';
        if (status) {
            status.style.boxShadow = '0 0 0 2px rgba(66, 133, 244, 0.24)';
        }

        setTimeout(() => {
            btn.style.boxShadow = '';
            if (status) status.style.boxShadow = '';
        }, 1400);
    },

    async open(options = {}) {
        this.init();

        const modal = this.getEl('globalSettingsModal');
        if (!modal) return;

        this.isOpen = true;
        modal.classList.add('open');
        modal.setAttribute('aria-hidden', 'false');
        this.lockBodyScroll();

        if (typeof Router !== 'undefined' && Router.updateActiveNav) {
            Router.updateActiveNav('settings');
        }

        if (options && options.focusLocalCheckup) {
            this.activateTab('Psettings');
        } else {
            this.activateTab('Dsettings');
        }

        await Promise.all([
            this.loadCurrentSettings(),
            this.loadProviderRoutingSettings(),
            this.refreshProvisioningState()
        ]);

        if (options && options.focusLocalCheckup) {
            setTimeout(() => this.focusLocalCheckupControls(), 40);
        }
    },

    close() {
        const modal = this.getEl('globalSettingsModal');
        if (!modal) return;

        this.isOpen = false;
        modal.classList.remove('open');
        modal.setAttribute('aria-hidden', 'true');
        this.unlockBodyScroll();

        if (typeof Router !== 'undefined' && Router.updateActiveNav) {
            Router.updateActiveNav(APP_STATE.currentPage || 'home');
        }
    },

    bindEvents() {
        const modal = this.getEl('globalSettingsModal');
        const windowEl = this.getEl('globalSettingsWindow');
        const closeBtn = this.getEl('globalSettingsCloseBtn');
        const recommendedBtn = this.getEl('globalSettingsRecommendedBtn');
        const envToggle = this.getEl('globalEnvValidationToggle');
        const cooldownSlider = this.getEl('globalCooldownSlider');
        const cooldownValue = this.getEl('globalCooldownValue');
        const applyCooldownBtn = this.getEl('globalApplyCooldownBtn');
        const applyProviderBtn = this.getEl('globalApplyProviderRoutingBtn');
        const applyApiModeBtn = this.getEl('globalApplyApiModeBtn');
        const reloadProviderBtn = this.getEl('globalReloadProviderRoutingBtn');
        const runCheckupBtn = this.getEl('globalRunLocalModeCheckupBtn');
        const redownloadInstallerBtn = this.getEl('globalRedownloadInstallerBtn');

        document.querySelectorAll('.global-settings-tab').forEach((tab) => {
            tab.addEventListener('click', () => {
                this.activateTab(tab.dataset.globalSettingsTab || 'Dsettings');
            });
        });

        if (closeBtn) {
            this.closeHandler = () => this.close();
            closeBtn.addEventListener('click', this.closeHandler);
        }

        if (recommendedBtn) {
            recommendedBtn.addEventListener('click', () => this.applyRecommendedSettings());
        }

        if (envToggle) {
            envToggle.addEventListener('change', async () => {
                const enabled = !!envToggle.checked;
                try {
                    await this.setEnvironmentValidation(enabled);
                    this.updateEnvValidationStatus(enabled);
                    this.showNotification('Environment validation updated', 'success');
                } catch (error) {
                    envToggle.checked = !enabled;
                    this.showNotification(error.message || 'Failed updating environment validation', 'error');
                }
            });
        }

        if (cooldownSlider && cooldownValue) {
            cooldownSlider.addEventListener('input', () => {
                cooldownValue.textContent = `${cooldownSlider.value}s`;
            });
        }

        if (applyCooldownBtn && cooldownSlider) {
            applyCooldownBtn.addEventListener('click', async () => {
                try {
                    applyCooldownBtn.disabled = true;
                    applyCooldownBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Applying...';
                    await this.setCooldown(parseInt(cooldownSlider.value, 10));
                    this.showNotification(`Cooldown set to ${cooldownSlider.value}s`, 'success');
                } catch (error) {
                    this.showNotification(error.message || 'Failed updating cooldown', 'error');
                } finally {
                    applyCooldownBtn.disabled = false;
                    applyCooldownBtn.innerHTML = '<i class="fas fa-save"></i> Apply Cooldown';
                }
            });
        }

        if (applyProviderBtn) {
            applyProviderBtn.addEventListener('click', () => this.applyProviderRoutingLocalProfile());
        }

        if (applyApiModeBtn) {
            applyApiModeBtn.addEventListener('click', () => this.applyApiModeProfile());
        }

        if (reloadProviderBtn) {
            reloadProviderBtn.addEventListener('click', async () => {
                await this.loadProviderRoutingSettings();
                await this.refreshProvisioningState();
            });
        }

        if (runCheckupBtn) {
            runCheckupBtn.addEventListener('click', () => this.runLocalModeCheckup());
        }

        if (redownloadInstallerBtn) {
            redownloadInstallerBtn.addEventListener('click', () => {
                const status = this.normalizeLocalProvisionStatus(this.localProvisionState.status);
                const machineId = String(this.localProvisionState.machineId || '').trim();

                if (!this.canIssueInstallerRedownload(status, machineId)) {
                    if (!machineId) {
                        this.showNotification('Run Local Mode Checkup first so this device can obtain machine ID.', 'warning');
                        return;
                    }

                    if (status === 'pending_approval') {
                        this.showNotification('Installer re-download is available after admin approval.', 'warning');
                        return;
                    }

                    if (status === 'rejected') {
                        this.showNotification('Provision request was rejected. Contact admin and rerun Local Mode Checkup.', 'error');
                        return;
                    }

                    this.showNotification('Installer re-download is available after this device is approved.', 'warning');
                    return;
                }

                window.location.assign(`${API_CONFIG.BASE_URL}/api/bootstrap/installer/request?machine_id=${encodeURIComponent(machineId)}`);
            });
        }

        if (modal) {
            modal.addEventListener('click', (event) => {
                if (event.target === modal) {
                    this.close();
                }
            });
        }

        if (windowEl) {
            windowEl.addEventListener('click', (event) => event.stopPropagation());
        }

        this.keydownHandler = (event) => {
            if (event.key === 'Escape' && this.isOpen) {
                this.close();
            }
        };
        document.addEventListener('keydown', this.keydownHandler);

        window.addEventListener('ppe-global-settings:open', (event) => {
            const detail = (event && event.detail) || {};
            this.open({
                focusLocalCheckup: !!detail.focusLocalCheckup
            });
        });

        window.addEventListener('ppe-provisioning:status', (event) => {
            this.syncLocalProvisionStateFromPayload((event && event.detail) || {});
        });

        window.addEventListener('ppe-local-mode:policy-changed', () => {
            this.updateLocalModeCheckupStatus();
        });
    },

    init() {
        if (this.initialized) return;

        this.ensureStyles();
        this.ensureDom();
        this.bindEvents();

        this.initialized = true;
    }
};

window.PPEGlobalSettingsModal = GlobalSettingsModal;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        GlobalSettingsModal.init();
    });
} else {
    GlobalSettingsModal.init();
}
