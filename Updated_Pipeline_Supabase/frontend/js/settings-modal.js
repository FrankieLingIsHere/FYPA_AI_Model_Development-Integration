// Global Settings Modal (page-agnostic popup)
const GlobalSettingsModal = {
    initialized: false,
    isOpen: false,
    closeHandler: null,
    keydownHandler: null,
    localProvisionPollInterval: null,
    heartbeatCountdownInterval: null,
    REMOTE_PROVISION_STATE_KEY: 'ppe.remoteProvisioningState.v1',
    localProvisionState: {
        status: 'idle',
        machineId: '',
        adminPortalUrl: '',
        cloudHeartbeat: null
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
            nlp_model: 'gemma3:4b',
            vision_model: 'gemma3:4b',
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
        nlp_model: 'gemma3:4b',
        vision_model: 'gemma3:4b',
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

            .global-heartbeat-badge {
                display: none;
                margin-top: 0.45rem;
                font-size: 0.78rem;
                padding: 0.3rem 0.6rem;
                border-radius: 999px;
                border: 1px solid transparent;
                width: fit-content;
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
                        <button type="button" class="global-settings-tab" data-global-settings-tab="Asettings">Audio Settings</button>
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
                                        <option value="gemma3:4b">Gemma 3 4B (local, lower memory)</option>
                                        <option value="gemini-2.5-flash">gemini-2.5-flash</option>
                                    </select>
                                </div>
                                <div>
                                    <label style="font-weight: 600;">Vision Model</label>
                                    <select id="globalVisionModelSelect" class="global-provider-input">
                                        <option value="gemma3:4b">Gemma 3 4B (local, lower memory)</option>
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

                        <section id="global-settings-tab-Asettings" class="global-settings-section">
                            <h3 style="margin-top: 0;">Audio Settings</h3>
                            <div class="global-settings-grid">
                                <div class="global-settings-card">
                                    <h4><i class="fas fa-volume-up" style="color: var(--primary-color);"></i> Alert Volume</h4>
                                    <div style="display:flex;align-items:center;gap:0.7rem;margin-top:0.4rem;">
                                        <input type="range" id="globalVolumeSlider" min="0" max="100" value="100" style="flex:1;">
                                        <span id="globalVolumeValue" style="font-weight:700;min-width:54px;text-align:center;">100%</span>
                                    </div>
                                    <button id="globalApplyAudioBtn" class="btn btn-primary" type="button" style="margin-top:0.75rem;width:100%;">
                                        <i class="fas fa-save"></i> Apply Audio Settings
                                    </button>
                                </div>

                                <div class="global-settings-card">
                                    <h4><i class="fas fa-user-voice" style="color: var(--warning-color);"></i> Voice Output</h4>
                                    <label style="font-weight:600;display:block;margin-top:0.35rem;">Preferred Voice</label>
                                    <select id="globalVoiceSelect" class="global-provider-input" style="margin-top:0.35rem;"></select>
                                    <label style="font-weight:600;display:block;margin-top:0.5rem;">Or custom voice name</label>
                                    <input id="globalVoiceCustom" class="global-provider-input" placeholder="Custom voice name" style="margin-top:0.35rem;">
                                    <div style="display:flex;gap:0.6rem;flex-wrap:wrap;margin-top:0.75rem;">
                                        <button id="globalTestVoiceBtn" class="btn btn-secondary" type="button"><i class="fas fa-play"></i> Test Voice</button>
                                    </div>
                                </div>
                            </div>
                        </section>

                        <div class="global-settings-card" style="margin-top: 0.9rem;">
                            <h4><i class="fas fa-wifi" style="color: var(--primary-color);"></i> Local Mode Checkup</h4>
                            <div style="display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 0.35rem;">
                                <button id="globalRunLocalModeCheckupBtn" class="btn btn-secondary" type="button">
                                    <i class="fas fa-wifi"></i> Run Local Mode Checkup
                                </button>
                                <button id="globalRequestProvisioningBtn" class="btn btn-primary" type="button">
                                    <i class="fas fa-paper-plane"></i> Request Provisioning
                                </button>
                                <button id="globalRedownloadInstallerBtn" class="btn btn-secondary" type="button" style="display: inline-flex;">
                                    <i class="fas fa-download"></i> Re-download Installer BAT
                                </button>
                            </div>
                            <div id="globalLocalModeCheckupStatus" class="global-settings-status" style="margin-top: 0.65rem;">
                                Local mode checkup not completed yet. Offline auto-setup remains disabled.
                            </div>
                            <div id="globalLocalModeHeartbeatBadge" class="global-heartbeat-badge"></div>
                        </div>

                        <div class="global-settings-card" style="margin-top: 0.9rem;">
                            <h4><i class="fas fa-flask" style="color: var(--warning-color);"></i> Local Test Mode</h4>
                            <p style="margin: 0 0 0.55rem 0; color: var(--text-secondary); font-size: 0.88rem;">
                                Verify local pipeline health without waiting for the LLM. Use <b>Ping Gemma</b> to confirm
                                the local model responds, and <b>Snapshot</b> to see whether the backend is fully offline.
                            </p>
                            <div style="display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 0.35rem;">
                                <button id="globalPingGemmaBtn" class="btn btn-primary" type="button">
                                    <i class="fas fa-bolt"></i> Ping Gemma
                                </button>
                                <button id="globalLocalSnapshotBtn" class="btn btn-secondary" type="button">
                                    <i class="fas fa-stethoscope"></i> Local Mode Snapshot
                                </button>
                            </div>
                            <div id="globalTestModeStatus" class="global-settings-status" style="margin-top: 0.65rem; white-space: pre-wrap;"></div>
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
        if (normalized === 'active') return 'active';
        if (normalized === 'approved') return 'approved';
        if (normalized === 'provisioned') return 'provisioned';
        if (normalized === 'rejected') return 'rejected';
        if (normalized === 'error') return 'error';
        return normalized || 'idle';
    },

    isCloudEndpointUnreachable(errorText) {
        const normalized = String(errorText || '').toLowerCase();
        if (!normalized) return false;

        const markers = [
            'getaddrinfo failed',
            'nameresolutionerror',
            'failed to resolve',
            'name resolution',
            'cloud.example.test',
            'nxdomain',
            'no address associated with hostname'
        ];
        return markers.some((marker) => normalized.includes(marker));
    },

    isLikelyRemoteBackend() {
        try {
            if (!API_CONFIG.BASE_URL) return false;
            const resolved = new URL(API_CONFIG.BASE_URL, window.location.origin);
            const host = String(resolved.hostname || '').toLowerCase();
            const isLocalHost = host === 'localhost' || host === '127.0.0.1' || host === '0.0.0.0' || host.endsWith('.local');
            return !isLocalHost;
        } catch (error) {
            return false;
        }
    },

    loadRemoteProvisionState() {
        try {
            // Provisioning state (machineId + provision_secret + status) is
            // persisted to localStorage so that tab close, hard refresh, or
            // browser restart does not wipe the credentials needed to
            // re-download the installer BAT from the cloud frontend when no
            // local backend is running. Storing on disk is no more sensitive
            // than the BAT installer's on-disk secret file, and avoids the
            // user being locked out of installer downloads after every
            // refresh.  One-time migration from the legacy sessionStorage
            // location preserves any in-flight session data.
            let raw = localStorage.getItem(this.REMOTE_PROVISION_STATE_KEY);
            if (!raw) {
                const legacy = sessionStorage.getItem(this.REMOTE_PROVISION_STATE_KEY);
                if (legacy) {
                    try { localStorage.setItem(this.REMOTE_PROVISION_STATE_KEY, legacy); } catch (_) {}
                    try { sessionStorage.removeItem(this.REMOTE_PROVISION_STATE_KEY); } catch (_) {}
                    raw = legacy;
                }
            }
            if (!raw) return {};
            const parsed = JSON.parse(raw);
            if (!parsed || typeof parsed !== 'object') return {};
            return parsed;
        } catch (error) {
            return {};
        }
    },

    resolveStableMachineId(currentMachineId = '', candidateMachineId = '', source = 'unknown') {
        const current = String(currentMachineId || '').trim();
        const candidate = String(candidateMachineId || '').trim();
        const isValid = (value) => /^[A-Za-z0-9._:-]{3,120}$/.test(value);

        if (isValid(current) && isValid(candidate) && current !== candidate) {
            console.warn(
                `[Provisioning] Ignoring machine_id mismatch from ${source}. Keeping stable device id.`,
                { currentMachineId: current, candidateMachineId: candidate }
            );
            return current;
        }

        if (isValid(candidate)) return candidate;
        return current;
    },

    saveRemoteProvisionState(nextState = {}) {
        try {
            const current = this.loadRemoteProvisionState();
            const merged = {
                ...current,
                ...nextState,
                machineId: String((nextState.machineId ?? current.machineId) || '').trim(),
                provisionSecret: String((nextState.provisionSecret ?? current.provisionSecret) || '').trim(),
                status: this.normalizeLocalProvisionStatus(nextState.status ?? current.status ?? 'idle'),
                updatedAt: new Date().toISOString()
            };
            if (!merged.machineId) return merged;
            // Persist to localStorage so credentials survive tab close /
            // refresh / browser restart (see loadRemoteProvisionState).
            localStorage.setItem(this.REMOTE_PROVISION_STATE_KEY, JSON.stringify(merged));
            // Clean up any legacy sessionStorage copy.
            try { sessionStorage.removeItem(this.REMOTE_PROVISION_STATE_KEY); } catch (_) {}
            // Also persist the confirmed machineId to localStorage so future sessions
            // (tab close/reopen, hard refresh) still know which edge device to check
            // instead of falling back to a freshly-generated Web-XXXX browser ID.
            // Uses the same key as app.js getOrCreateDeviceMachineId().
            try {
                const localKey = 'ppe.localMode.deviceMachineId.v1';
                const existingLocalMachineId = String(localStorage.getItem(localKey) || '').trim();
                const localMachineId = this.resolveStableMachineId(
                    existingLocalMachineId,
                    merged.machineId,
                    'saveRemoteProvisionState'
                );
                if (localMachineId) {
                    localStorage.setItem(localKey, localMachineId);
                    // Keep session state aligned with the stable local identity.
                    merged.machineId = localMachineId;
                }
            } catch (_) { /* quota / privacy mode — best-effort only */ }
            return merged;
        } catch (error) {
            return this.loadRemoteProvisionState();
        }
    },

    ensureRemoteProvisionMachineId(machineIdHint = '') {
        const hint = String(machineIdHint || '').trim();
        if (/^[A-Za-z0-9._:-]{3,120}$/.test(hint)) {
            return hint;
        }

        // Prefer the global per-device localStorage ID set by app.js so the
        // home-page poll and the settings-modal request agree on a single
        // identity per browser/device. This guarantees that the phone and
        // the laptop are seen as DIFFERENT devices by the backend, and
        // therefore receive their own approval status.
        try {
            if (window.PPEProvisioningStatus && typeof window.PPEProvisioningStatus.getDeviceMachineId === 'function') {
                const deviceId = String(window.PPEProvisioningStatus.getDeviceMachineId() || '').trim();
                if (/^[A-Za-z0-9._:-]{3,120}$/.test(deviceId)) {
                    return deviceId;
                }
            }
        } catch (deviceLookupErr) {
            // fall through to legacy generation below
        }

        const stored = this.loadRemoteProvisionState();
        const storedMachineId = String((stored && stored.machineId) || '').trim();
        if (/^[A-Za-z0-9._:-]{3,120}$/.test(storedMachineId)) {
            return storedMachineId;
        }

        let suffix = '';
        try {
            if (window.crypto && typeof window.crypto.getRandomValues === 'function') {
                const bytes = new Uint8Array(6);
                window.crypto.getRandomValues(bytes);
                suffix = Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
            }
        } catch (error) {
            suffix = '';
        }

        if (!suffix) {
            suffix = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
        }

        const generated = `Web-${suffix}`.replace(/[^A-Za-z0-9._:-]/g, '').slice(0, 120);
        if (generated.length >= 3) {
            return generated;
        }

        return `Web-${Date.now().toString(36)}`;
    },

    async refreshRemoteProvisioningStatus(options = {}) {
        const allowRequest = options.allowRequest !== false;
        const machineIdHint = String(options.machineIdHint || options.machine_id || '').trim();
        const adminPortalUrl = `${API_CONFIG.BASE_URL}/admin/devices`;

        const stored = this.loadRemoteProvisionState();
        const storedStatus = this.normalizeLocalProvisionStatus((stored && stored.status) || 'idle');
        let machineId = this.ensureRemoteProvisionMachineId(machineIdHint || stored.machineId || this.localProvisionState.machineId);
        let provisionSecret = String((stored && stored.provisionSecret) || '').trim();
        const hasStoredProvisionSecret = !!provisionSecret;

        if (allowRequest && (!provisionSecret || options.forceRequest === true)) {
            const requestResult = await API.requestCloudProvisioningApproval({
                machineId,
                // Pass the stored secret (if any) so the backend can authenticate
                // a rotation without an admin token. Brand-new devices have no
                // stored secret and must be admin-approved out-of-band.
                currentProvisionSecret: provisionSecret || ''
            });
            if (!requestResult || requestResult.success === false) {
                return {
                    success: false,
                    status: this.normalizeLocalProvisionStatus((stored && stored.status) || 'idle'),
                    machine_id: machineId,
                    admin_portal_url: adminPortalUrl,
                    error: String((requestResult && requestResult.error) || 'Unable to submit cloud provisioning request.')
                };
            }

            machineId = this.resolveStableMachineId(
                machineId,
                String(requestResult.machine_id || '').trim(),
                'requestCloudProvisioningApproval'
            );
            provisionSecret = String(requestResult.provision_secret || provisionSecret).trim();
            this.saveRemoteProvisionState({
                machineId,
                provisionSecret,
                status: 'pending_approval',
                adminPortalUrl
            });
        }

        if (!provisionSecret) {
            return {
                success: false,
                status: this.normalizeLocalProvisionStatus((stored && stored.status) || 'idle'),
                machine_id: machineId,
                admin_portal_url: adminPortalUrl,
                error: 'Provision request secret is missing. Run Local Mode Checkup again to submit request.'
            };
        }

        let statusResult = await API.getCloudProvisioningStatus({
            machineId,
            provisionSecret
        });

        let attemptedSecretlessRecovery = false;
        let secretlessRecoveryError = '';
        if ((statusResult && statusResult.success === false) && allowRequest) {
            const statusError = String((statusResult && statusResult.error) || '').toLowerCase();
            const invalidSecret = statusError.includes('invalid provision_secret');
            const notFound = statusError.includes('not_found');

            // not_found can be transient when cloud instances are not sharing immediate in-memory state.
            if (notFound && hasStoredProvisionSecret) {
                for (let attempt = 0; attempt < 3; attempt += 1) {
                    await new Promise((resolve) => setTimeout(resolve, 300 * (attempt + 1)));
                    const retryStatusResult = await API.getCloudProvisioningStatus({
                        machineId,
                        provisionSecret
                    });
                    statusResult = retryStatusResult || statusResult;
                    if (retryStatusResult && retryStatusResult.success) {
                        break;
                    }
                }
            }

            const refreshedError = String((statusResult && statusResult.error) || '').toLowerCase();
            const shouldRetryRequest = invalidSecret || (!hasStoredProvisionSecret && refreshedError.includes('not_found'));
            if ((statusResult && statusResult.success === false) && shouldRetryRequest) {
                attemptedSecretlessRecovery = !!invalidSecret;
                const retryRequest = await API.requestCloudProvisioningApproval({
                    machineId,
                    // If the cloud explicitly rejected the cached secret, do
                    // not present it again. Sending a known-bad secret can
                    // trigger credential-desync demotion on the cloud side;
                    // a secretless re-request either refreshes an approved
                    // device or fails without downgrading it.
                    currentProvisionSecret: invalidSecret ? '' : (provisionSecret || '')
                });
                if (retryRequest && retryRequest.success) {
                    machineId = this.resolveStableMachineId(
                        machineId,
                        String(retryRequest.machine_id || '').trim(),
                        'requestCloudProvisioningApproval:retry'
                    );
                    provisionSecret = String(retryRequest.provision_secret || provisionSecret).trim();
                    this.saveRemoteProvisionState({
                        machineId,
                        provisionSecret,
                        status: 'pending_approval',
                        adminPortalUrl
                    });
                    statusResult = await API.getCloudProvisioningStatus({
                        machineId,
                        provisionSecret
                    });
                } else if (attemptedSecretlessRecovery) {
                    secretlessRecoveryError = String((retryRequest && retryRequest.error) || 'Secretless recovery request failed');
                }
            }
        }

        if (!statusResult || statusResult.success === false) {
            // Only trust the cached storedStatus if the failure was a network
            // error (not a 401/403 invalid-secret). A 401 means the device was
            // revoked and the old secret is no longer valid — don't let the
            // stale cached "provisioned" mask that.
            const statusError = String((statusResult && statusResult.error) || '').toLowerCase();
            const isAuthError = statusError.includes('invalid provision_secret')
                || statusError.includes('401')
                || statusError.includes('403');
            if (!isAuthError && (storedStatus === 'approved' || storedStatus === 'provisioned' || storedStatus === 'active')) {
                return {
                    success: true,
                    status: storedStatus,
                    machine_id: machineId,
                    admin_portal_url: adminPortalUrl,
                    cloud_local_heartbeat: options.cloud_local_heartbeat || null
                };
            }

            // PRV5-frontend — when the cloud explicitly rejects our cached
            // provision_secret, scrub it from sessionStorage so the next
            // checkup (or any code reading loadRemoteProvisionState) does not
            // keep displaying a stale "approved" status. Without this, a
            // checkup that runs with allowRequest:false will silently fall
            // back to the cached status and the UI will show green even
            // though the installer download will 401.
            if (isAuthError) {
                if (attemptedSecretlessRecovery) {
                    const fallbackStatus = (storedStatus === 'approved' || storedStatus === 'provisioned' || storedStatus === 'active')
                        ? storedStatus
                        : 'idle';
                    this.saveRemoteProvisionState({
                        machineId,
                        provisionSecret: '',
                        status: fallbackStatus,
                        adminPortalUrl
                    });
                    return {
                        success: false,
                        status: fallbackStatus,
                        machine_id: machineId,
                        admin_portal_url: adminPortalUrl,
                        error: secretlessRecoveryError || String((statusResult && statusResult.error) || 'Cached provision_secret expired; run checkup from the host PC.')
                    };
                }

                this.saveRemoteProvisionState({
                    machineId,
                    provisionSecret: '',
                    status: 'rejected',
                    adminPortalUrl
                });
                return {
                    success: false,
                    status: 'rejected',
                    machine_id: machineId,
                    admin_portal_url: adminPortalUrl,
                    error: String((statusResult && statusResult.error) || 'Cached provision_secret is no longer valid; re-request provisioning.')
                };
            }

            return {
                success: false,
                status: storedStatus,
                machine_id: machineId,
                admin_portal_url: adminPortalUrl,
                error: String((statusResult && statusResult.error) || 'Unable to fetch cloud provisioning status.')
            };
        }

        const normalizedStatus = this.normalizeLocalProvisionStatus(
            (statusResult && statusResult.status) || 'idle'
        );

        // If the device was revoked/rejected, clear the stored provision secret
        // so the next checkup re-registers the device as a fresh request instead
        // of silently falling back to the cached "provisioned" status.
        if (normalizedStatus === 'rejected') {
            this.saveRemoteProvisionState({
                machineId,
                provisionSecret: '',
                status: 'rejected',
                adminPortalUrl
            });
        } else {
            this.saveRemoteProvisionState({
                machineId,
                provisionSecret,
                status: normalizedStatus,
                adminPortalUrl
            });
        }

        return {
            success: true,
            status: normalizedStatus,
            machine_id: machineId,
            admin_portal_url: adminPortalUrl,
            cloud_local_heartbeat: options.cloud_local_heartbeat || null
        };
    },

    normalizeCloudHeartbeatPayload(rawHeartbeat, fallbackHeartbeat = null) {
        const source = rawHeartbeat && typeof rawHeartbeat === 'object' ? rawHeartbeat : {};
        const fallback = fallbackHeartbeat && typeof fallbackHeartbeat === 'object' ? fallbackHeartbeat : {};
        const hasSource = Object.keys(source).length > 0;

        const available = !!(source.available ?? fallback.available);
        const machineId = String(source.machine_id ?? source.machineId ?? fallback.machineId ?? '').trim();
        const status = String(source.status ?? fallback.status ?? 'missing').trim().toLowerCase() || 'missing';
        const isRecent = !!(source.is_recent ?? source.isRecent ?? fallback.isRecent);

        const rawFreshWindow = Number(source.fresh_within_seconds ?? source.freshWithinSeconds ?? fallback.freshWithinSeconds);
        const freshWithinSeconds = Number.isFinite(rawFreshWindow)
            ? Math.max(0, Math.floor(rawFreshWindow))
            : 0;

        const lastSeenAt = String(source.last_seen_at ?? source.lastSeenAt ?? fallback.lastSeenAt ?? '').trim();

        const rawAgeSeconds = Number(source.age_seconds ?? source.ageSeconds);
        const fallbackAgeSeconds = Number(fallback.ageSeconds);
        const ageSeconds = Number.isFinite(rawAgeSeconds)
            ? Math.max(0, Math.floor(rawAgeSeconds))
            : (Number.isFinite(fallbackAgeSeconds) ? Math.max(0, Math.floor(fallbackAgeSeconds)) : null);

        const provisionStatus = this.normalizeLocalProvisionStatus(
            source.provision_status ?? source.provisionStatus ?? fallback.provisionStatus ?? 'idle'
        );

        return {
            available,
            machineId,
            status,
            provisionStatus,
            isRecent,
            freshWithinSeconds,
            lastSeenAt,
            ageSeconds,
            localModePossible: !!(source.local_mode_possible ?? source.localModePossible ?? fallback.localModePossible),
            ollamaInstalled: !!(source.ollama_installed ?? source.ollamaInstalled ?? fallback.ollamaInstalled),
            ollamaRunning: !!(source.ollama_running ?? source.ollamaRunning ?? fallback.ollamaRunning),
            modelAvailable: !!(source.model_available ?? source.modelAvailable ?? fallback.modelAvailable),
            source: String(source.source ?? fallback.source ?? '').trim(),
            error: String(source.error ?? fallback.error ?? '').trim(),
            receivedAtMs: hasSource ? Date.now() : Number(fallback.receivedAtMs || Date.now())
        };
    },

    getCloudHeartbeatAgeSeconds(heartbeat) {
        if (!heartbeat || typeof heartbeat !== 'object') {
            return null;
        }

        const parsedLastSeen = Date.parse(String(heartbeat.lastSeenAt || '').trim());
        if (Number.isFinite(parsedLastSeen)) {
            return Math.max(0, Math.floor((Date.now() - parsedLastSeen) / 1000));
        }

        const baseAge = Number(heartbeat.ageSeconds);
        if (!Number.isFinite(baseAge)) {
            return null;
        }

        const receivedAtMs = Number(heartbeat.receivedAtMs || Date.now());
        const elapsedSeconds = Number.isFinite(receivedAtMs)
            ? Math.max(0, Math.floor((Date.now() - receivedAtMs) / 1000))
            : 0;

        return Math.max(0, Math.floor(baseAge) + elapsedSeconds);
    },

    formatDurationSeconds(rawSeconds) {
        const total = Math.max(0, Math.floor(Number(rawSeconds) || 0));
        if (total < 60) return `${total}s`;
        const mins = Math.floor(total / 60);
        const secs = total % 60;
        if (mins < 60) return `${mins}m ${secs}s`;
        const hours = Math.floor(mins / 60);
        const remMins = mins % 60;
        return `${hours}h ${remMins}m`;
    },

    updateHeartbeatBadge() {
        const badgeEl = this.getEl('globalLocalModeHeartbeatBadge');
        if (!badgeEl) return;

        if (!this.isLikelyRemoteBackend()) {
            badgeEl.style.display = 'none';
            return;
        }

        const heartbeat = this.normalizeCloudHeartbeatPayload(this.localProvisionState.cloudHeartbeat);
        const toneMap = {
            info: {
                color: 'var(--text-secondary)',
                background: 'rgba(148, 163, 184, 0.14)',
                border: 'rgba(148, 163, 184, 0.45)'
            },
            success: {
                color: 'var(--success-color)',
                background: 'rgba(34, 197, 94, 0.15)',
                border: 'rgba(34, 197, 94, 0.45)'
            },
            warning: {
                color: 'var(--warning-color)',
                background: 'rgba(245, 158, 11, 0.15)',
                border: 'rgba(245, 158, 11, 0.45)'
            },
            error: {
                color: 'var(--error-color)',
                background: 'rgba(239, 68, 68, 0.15)',
                border: 'rgba(239, 68, 68, 0.45)'
            }
        };

        const paintBadge = (tone, text) => {
            const resolvedTone = toneMap[tone] || toneMap.info;
            badgeEl.textContent = text;
            badgeEl.style.display = 'inline-flex';
            badgeEl.style.alignItems = 'center';
            badgeEl.style.color = resolvedTone.color;
            badgeEl.style.background = resolvedTone.background;
            badgeEl.style.borderColor = resolvedTone.border;
        };

        if (!heartbeat.available) {
            paintBadge('info', 'Cloud heartbeat: waiting for edge update');
            return;
        }

        const ageSeconds = this.getCloudHeartbeatAgeSeconds(heartbeat);
        const freshWindow = Math.max(0, Number(heartbeat.freshWithinSeconds || 0));
        const ageText = ageSeconds == null ? 'unknown' : this.formatDurationSeconds(ageSeconds);

        if (heartbeat.isRecent) {
            const expiresInSeconds = ageSeconds == null
                ? freshWindow
                : Math.max(0, freshWindow - ageSeconds);
            const expiresText = this.formatDurationSeconds(expiresInSeconds);
            const readinessLabel = heartbeat.localModePossible ? 'ready' : 'not ready';
            paintBadge(
                heartbeat.localModePossible ? 'success' : 'warning',
                `Cloud heartbeat: fresh (${readinessLabel}) • age ${ageText} • expires in ${expiresText}`
            );
            return;
        }

        const staleBySeconds = ageSeconds == null
            ? null
            : Math.max(0, ageSeconds - freshWindow);
        const staleSuffix = staleBySeconds == null ? '' : ` • stale by ${this.formatDurationSeconds(staleBySeconds)}`;
        paintBadge('error', `Cloud heartbeat: stale • last seen ${ageText} ago${staleSuffix}`);
    },

    ensureHeartbeatCountdown() {
        if (this.heartbeatCountdownInterval) return;
        this.heartbeatCountdownInterval = setInterval(() => {
            this.updateHeartbeatBadge();
        }, 1000);
    },

    stopHeartbeatCountdown() {
        if (!this.heartbeatCountdownInterval) return;
        clearInterval(this.heartbeatCountdownInterval);
        this.heartbeatCountdownInterval = null;
    },

    syncLocalProvisionStateFromPayload(payload) {
        const source = payload && typeof payload === 'object' ? payload : {};
        const normalizedHeartbeat = this.normalizeCloudHeartbeatPayload(
            source.cloudHeartbeat || source.cloud_local_heartbeat,
            this.localProvisionState.cloudHeartbeat
        );
        const previousStatus = this.normalizeLocalProvisionStatus(this.localProvisionState.status || 'idle');
        const previousMeasuredAt = Number(this.localProvisionState.measuredAt || 0);
        const sourceStatus = String(source.status || '').trim().toLowerCase() === 'stored'
            ? (source.device_status || source.provisioning_status || source.status)
            : source.status;
        let normalizedStatus = this.normalizeLocalProvisionStatus(sourceStatus || previousStatus);
        const heartbeatProvisionStatus = this.normalizeLocalProvisionStatus(normalizedHeartbeat.provisionStatus || 'idle');
        if (this.isLikelyRemoteBackend()) {
            const previousIsApprovedLike = previousStatus === 'approved' || previousStatus === 'provisioned' || previousStatus === 'active';
            const incomingIsWeakerStatus = (
                normalizedStatus === 'idle'
                || normalizedStatus === 'pending_approval'
                || normalizedStatus === 'credentials_present'
                || normalizedStatus === 'error'
            );
            // Time-bound the downgrade protection. A long-lived 'approved'
            // value would otherwise stick across page loads and ignore
            // legitimate backend downgrades (admin revoke, secret rotation,
            // viewing from a non-approved device, etc).
            const previousAgeMs = previousMeasuredAt > 0 ? (Date.now() - previousMeasuredAt) : Infinity;
            const PROTECTION_WINDOW_MS = 60 * 1000;
            const protectionStillFresh = previousIsApprovedLike
                && incomingIsWeakerStatus
                && previousAgeMs < PROTECTION_WINDOW_MS;
            if (protectionStillFresh) {
                normalizedStatus = previousStatus;
            }

            if ((normalizedStatus === 'idle' || normalizedStatus === 'credentials_present') && heartbeatProvisionStatus !== 'idle') {
                normalizedStatus = heartbeatProvisionStatus;
            }
        }

        this.localProvisionState = {
            status: normalizedStatus,
            machineId: String(source.machineId || source.machine_id || normalizedHeartbeat.machineId || this.localProvisionState.machineId || '').trim(),
            adminPortalUrl: String(source.adminPortalUrl || source.admin_portal_url || this.localProvisionState.adminPortalUrl || '').trim(),
            cloudHeartbeat: normalizedHeartbeat,
            measuredAt: Date.now()
        };

        this.updateLocalModeCheckupStatus();
        this.updateInstallerRedownloadButton();
        this.updateRequestProvisioningButton();
        this.updateHeartbeatBadge();

        // Propagate the resolved per-device status into the global
        // PPEProvisioningStatus tracker so the home page badge and any
        // other listeners reflect the same state. This is critical when
        // the user is viewing the cloud frontend: refreshRemoteProvisioningStatus
        // (which uses the per-device provision_secret stored in localStorage)
        // and runLocalModeCheckup both update settings.localProvisionState
        // directly, but without this push the global tracker stays at the
        // host-level 'credentials_present' and the home badge keeps showing
        // "Not Requested" / "Credentials Detected" even though the device
        // is actually provisioned.
        try {
            if (window.PPEProvisioningStatus && typeof window.PPEProvisioningStatus.update === 'function') {
                const pushPayload = {
                    status: this.localProvisionState.status,
                    machineId: this.localProvisionState.machineId,
                    machine_id: this.localProvisionState.machineId,
                    adminPortalUrl: this.localProvisionState.adminPortalUrl,
                    admin_portal_url: this.localProvisionState.adminPortalUrl,
                    cloudHeartbeat: this.localProvisionState.cloudHeartbeat,
                    cloud_local_heartbeat: this.localProvisionState.cloudHeartbeat
                };
                window.PPEProvisioningStatus.update(pushPayload, {
                    source: 'settings-modal-sync',
                    notify: false
                });
            }
        } catch (publishErr) {
            console.warn('GlobalSettingsModal: failed to publish provisioning state to global tracker', publishErr);
        }
    },

    canIssueInstallerRedownload(statusRaw, machineIdRaw) {
        const status = this.normalizeLocalProvisionStatus(statusRaw);
        const machineId = String(machineIdRaw || '').trim();
        if (!machineId) return false;
        // Only allow re-download for explicitly admin-approved or provisioned devices.
        // credentials_present is NOT sufficient — those credentials may not be admin-authorised.
        return status === 'approved' || status === 'provisioned' || status === 'active';
    },

    getStoredProvisionSecretForMachine(machineIdRaw = '') {
        const stored = this.loadRemoteProvisionState() || {};
        const requestedMachineId = String(machineIdRaw || '').trim();
        const storedMachineId = String(stored.machineId || '').trim();
        const provisionSecret = String(stored.provisionSecret || '').trim();
        if (!provisionSecret) return '';
        if (requestedMachineId && storedMachineId && requestedMachineId !== storedMachineId) {
            return '';
        }
        return provisionSecret;
    },

    async recoverRemoteInstallerCredentials(machineIdRaw = '') {
        if (!this.isLikelyRemoteBackend()) {
            return this.loadRemoteProvisionState() || {};
        }

        const machineId = String(
            machineIdRaw
            || this.localProvisionState.machineId
            || (this.loadRemoteProvisionState() || {}).machineId
            || ''
        ).trim();
        if (!machineId) {
            return this.loadRemoteProvisionState() || {};
        }

        if (this.getStoredProvisionSecretForMachine(machineId)) {
            return this.loadRemoteProvisionState() || {};
        }

        const knownStatus = this.normalizeLocalProvisionStatus(
            this.localProvisionState.status
            || (this.loadRemoteProvisionState() || {}).status
            || 'idle'
        );
        if (knownStatus !== 'approved' && knownStatus !== 'provisioned' && knownStatus !== 'active') {
            return this.loadRemoteProvisionState() || {};
        }

        const refreshed = await this.refreshRemoteProvisioningStatus({
            allowRequest: true,
            forceRequest: true,
            machineIdHint: machineId
        });
        if (refreshed && typeof refreshed === 'object') {
            this.syncLocalProvisionStateFromPayload(refreshed);
        }
        return this.loadRemoteProvisionState() || {};
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
            if (status === 'credentials_present') {
                btn.title = 'Issue a fresh installer BAT to recover cloud sync linkage while credentials are already present.';
                return;
            }
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

    updateRequestProvisioningButton() {
        const btn = this.getEl('globalRequestProvisioningBtn');
        if (!btn) return;
        const status = this.normalizeLocalProvisionStatus(this.localProvisionState.status);
        const isApproved = status === 'approved' || status === 'provisioned' || status === 'active';
        const isPending = status === 'pending_approval';

        btn.disabled = isApproved || isPending;
        btn.style.opacity = (isApproved || isPending) ? '0.45' : '';
        btn.style.cursor = (isApproved || isPending) ? 'not-allowed' : '';

        if (isApproved) {
            btn.title = 'Device is already approved — no provisioning request needed.';
            btn.innerHTML = '<i class="fas fa-check-circle"></i> Already Approved';
        } else if (isPending) {
            btn.title = 'Provisioning request already submitted. Waiting for admin approval.';
            btn.innerHTML = '<i class="fas fa-clock"></i> Pending Approval…';
        } else {
            btn.title = 'Send a provisioning request to the administrator for approval.';
            btn.innerHTML = '<i class="fas fa-paper-plane"></i> Request Provisioning';
        }
    },

    async requestProvisioning() {
        const btn = this.getEl('globalRequestProvisioningBtn');
        if (!btn || btn.disabled) return;

        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Sending…';

        try {
            const stored = this.loadRemoteProvisionState();
            const localStoredId = (() => {
                try { return String(localStorage.getItem('ppe.localMode.deviceMachineId.v1') || '').trim(); } catch (_) { return ''; }
            })();
            const machineIdHint = String(this.localProvisionState.machineId || stored.machineId || localStoredId || '').trim();
            const machineId = this.ensureRemoteProvisionMachineId(machineIdHint);

            const requestResult = await API.requestCloudProvisioningApproval({
                machineId,
                currentProvisionSecret: String(stored.provisionSecret || '').trim()
            });

            if (!requestResult || requestResult.success === false) {
                const errMsg = String((requestResult && requestResult.error) || 'Failed to submit provisioning request.');
                this.setProviderStatus(errMsg, 'error');
                this.showNotification(errMsg, 'error');
                btn.disabled = false;
                this.updateRequestProvisioningButton();
                return;
            }

            const newMachineId = String(requestResult.machine_id || machineId).trim() || machineId;
            const newSecret = String(requestResult.provision_secret || '').trim();
            const adminPortalUrl = `${API_CONFIG.BASE_URL}/admin/devices`;
            const requestStatus = this.normalizeLocalProvisionStatus(
                requestResult.status || requestResult.device_status || 'pending_approval'
            );

            this.saveRemoteProvisionState({
                machineId: newMachineId,
                provisionSecret: newSecret,
                status: requestStatus,
                adminPortalUrl
            });
            this.syncLocalProvisionStateFromPayload({
                machine_id: newMachineId,
                status: requestStatus,
                admin_portal_url: adminPortalUrl
            });

            this.updateLocalModeCheckupStatus();
            this.updateRequestProvisioningButton();
            if (requestStatus === 'pending_approval') {
                this.ensureLocalProvisionPolling();
                const successMsg = `Provisioning request sent for machine ${newMachineId}. Waiting for admin approval.`;
                this.setProviderStatus(successMsg, 'warning');
                this.showNotification('Provisioning request submitted. Waiting for admin approval.', 'warning');
            } else if (requestStatus === 'active') {
                this.setProviderStatus('Device provisioned and active. Local backend is running.', 'success');
                this.showNotification('Device provisioned and active.', 'success');
            } else if (requestStatus === 'approved' || requestStatus === 'provisioned') {
                this.setProviderStatus('Device is already provisioned. Installer access is available.', 'success');
                this.showNotification('Device is already provisioned.', 'success');
            } else {
                this.setProviderStatus(`Provisioning status: ${requestStatus}`, 'info');
            }
        } catch (error) {
            const errMsg = (error && error.message) || 'Failed to submit provisioning request.';
            this.setProviderStatus(errMsg, 'error');
            this.showNotification(errMsg, 'error');
            btn.disabled = false;
            this.updateRequestProvisioningButton();
        }
    },

    updateLocalModeCheckupStatus() {
        const statusEl = this.getEl('globalLocalModeCheckupStatus');
        if (!statusEl) return;

        this.updateHeartbeatBadge();

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

        if (status === 'active') {
            statusEl.textContent = 'Device provisioned and active. Local backend is running.';
            statusEl.style.color = 'var(--success-color)';
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
            statusEl.textContent = 'Local mode checkup passed. Cloud credentials are present; use installer re-download below if you need to refresh launcher linkage while heartbeat sync catches up.';
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

    async loadAudioSettings() {
        try {
            const volumeSlider = this.getEl('globalVolumeSlider');
            const volumeValue = this.getEl('globalVolumeValue');
            const voiceSelect = this.getEl('globalVoiceSelect');
            const voiceCustom = this.getEl('globalVoiceCustom');

            // Load from localStorage fallback
            const storedVolume = Number(localStorage.getItem('luna_voice_volume'));
            const storedVoice = String(localStorage.getItem('luna_voice_choice') || '').trim();

            if (volumeSlider && !Number.isNaN(storedVolume)) {
                volumeSlider.value = String(Math.max(0, Math.min(100, Math.round(storedVolume))));
            }
            if (volumeValue) {
                volumeValue.textContent = `${volumeSlider ? volumeSlider.value : (Number.isFinite(storedVolume) ? storedVolume : 100)}%`;
            }

            // Populate voices if available
            if (voiceSelect && typeof window.speechSynthesis !== 'undefined') {
                const populate = () => {
                    const voices = window.speechSynthesis.getVoices() || [];
                    voiceSelect.innerHTML = '';
                    voices.forEach((v) => {
                        const opt = document.createElement('option');
                        opt.value = v.name || `${v.lang} ${v.name}`;
                        opt.textContent = `${v.name} (${v.lang})`;
                        voiceSelect.appendChild(opt);
                    });
                    if (storedVoice) {
                        const found = Array.from(voiceSelect.options).find(o => o.value === storedVoice || o.text === storedVoice);
                        if (found) voiceSelect.value = found.value;
                        else voiceCustom.value = storedVoice;
                    }
                };

                populate();
                // Some browsers populate asynchronously
                setTimeout(populate, 250);
            } else if (voiceCustom) {
                voiceCustom.value = storedVoice || '';
            }
        } catch (e) {
            console.warn('loadAudioSettings failed', e);
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

            // Redirect API traffic to the local backend now that the profile has switched.
            // Without this, all subsequent API calls (generate-now, live/start, etc.) would
            // still go to the cloud URL even though the NLP profile is set to local.
            if (this.isLikelyRemoteBackend()) {
                this.setProviderStatus(
                    'Local profile applied. Note: you are on the HTTPS deployed frontend. ' +
                    'Browsers block requests to http://localhost:5000 from HTTPS pages (mixed content). ' +
                    'Open http://127.0.0.1:5000 directly in your browser to use local mode.',
                    'warning'
                );
            } else if (typeof window.PPEResolveWorkingBackendBaseUrl === 'function') {
                try {
                    await window.PPEResolveWorkingBackendBaseUrl({ preferLocal: true, force: true });
                } catch (resolveErr) {
                    console.warn('GlobalSettingsModal: backend URL resolution after local profile apply failed', resolveErr);
                }
            }
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
                notify: false,
                machineId: this.localProvisionState.machineId || ''
            });
            this.syncLocalProvisionStateFromPayload(state);

            const normalized = this.normalizeLocalProvisionStatus((state && state.status) || 'idle');
            if (this.isLikelyRemoteBackend() && (normalized === 'idle' || normalized === 'error')) {
                const remoteState = await this.refreshRemoteProvisioningStatus({
                    allowRequest: false,
                    machineIdHint: this.localProvisionState.machineId
                });
                if (remoteState && (remoteState.status === 'pending_approval' || remoteState.status === 'approved' || remoteState.status === 'provisioned' || remoteState.status === 'active' || remoteState.status === 'rejected')) {
                    this.syncLocalProvisionStateFromPayload(remoteState);
                }
            }
            return;
        }

        const state = await API.getLocalModeProvisioningStatus({
            machineId: this.localProvisionState.machineId || ''
        });
        this.syncLocalProvisionStateFromPayload(state);

        const normalized = this.normalizeLocalProvisionStatus((state && state.status) || 'idle');
        if (this.isLikelyRemoteBackend() && (normalized === 'idle' || normalized === 'error')) {
            const remoteState = await this.refreshRemoteProvisioningStatus({
                allowRequest: false,
                machineIdHint: this.localProvisionState.machineId
            });
            if (remoteState && (remoteState.status === 'pending_approval' || remoteState.status === 'approved' || remoteState.status === 'provisioned' || remoteState.status === 'active' || remoteState.status === 'rejected')) {
                this.syncLocalProvisionStateFromPayload(remoteState);
            }
        }
    },

    _restoreLocalCheckupButton() {
        const btn = this.getEl('globalRunLocalModeCheckupBtn');
        if (!btn) return;
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-wifi"></i> Run Local Mode Checkup';
    },

    async runLocalModeCheckup() {
        // Re-entrancy guard: prevent double-clicks while a previous run is
        // still awaiting cloud round-trips. Without this guard the button
        // would visually reset, then a second click would race the first
        // and one of them would re-disable the button after it finished.
        if (this._localCheckupRunning) {
            return;
        }
        const btn = this.getEl('globalRunLocalModeCheckupBtn');
        if (!btn) return;

        this._localCheckupRunning = true;

        // Watchdog: if anything below hangs (cloud unreachable + missing
        // fetch timeout, browser tab throttled, etc.), force the button back
        // to a usable state after 60s instead of trapping the user in a
        // permanent "Checking..." spinner.
        const watchdog = setTimeout(() => {
            try {
                this._restoreLocalCheckupButton();
                this.setProviderStatus(
                    'Local mode checkup is taking longer than expected. The check will continue in the background; you can rerun it.',
                    'warning'
                );
            } catch (_) { /* best-effort */ }
        }, 60000);

        try {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Checking...';
            this.setProviderStatus('Running local mode checkup...', 'info');

            const isLikelyRemoteBackend = this.isLikelyRemoteBackend();

            const options = await API.getReportRecoveryOptions({
                machineId: (this.localProvisionState && this.localProvisionState.machineId) || ''
            });
            const local = (options && options.local) || {};
            const cloudHeartbeat = (options && options.cloud_local_heartbeat) || {};
            const heartbeatMachineId = String(cloudHeartbeat.machine_id || '').trim();
            const heartbeatRecent = !!cloudHeartbeat.is_recent;
            const heartbeatFreshWindow = Number(cloudHeartbeat.fresh_within_seconds || 0) || 0;
            this.syncLocalProvisionStateFromPayload({
                machine_id: heartbeatMachineId || this.localProvisionState.machineId,
                cloud_local_heartbeat: cloudHeartbeat
            });
            const useHeartbeatDiagnostics = isLikelyRemoteBackend && heartbeatRecent;
            let ready = useHeartbeatDiagnostics
                ? !!cloudHeartbeat.local_mode_possible
                : !!local.local_mode_possible;

            if (!ready) {
                if (isLikelyRemoteBackend) {
                    // Distinguish three cases so the message reflects reality:
                    //  (a) heartbeat arrived but local mode itself isn't ready yet
                    //      → genuine local-mode problem, warn.
                    //  (b) no recent heartbeat AND device was never provisioned
                    //      → genuine setup problem, warn + show installer hint.
                    //  (c) no recent heartbeat BUT device IS provisioned
                    //      → the host PC's local backend simply isn't running
                    //        right now. That's expected when the user is on
                    //        cloud mode from another browser/device. Show an
                    //        info-level inline status only — do NOT toast it
                    //        as a warning, since nothing is broken.
                    const provisionStatus = String((this.localProvisionState && this.localProvisionState.status) || '').toLowerCase();
                    // Also consult the canonical global tracker, because
                    // settings.localProvisionState lags behind it on first
                    // mount until syncLocalProvisionStateFromPayload runs.
                    const globalProvisionStatus = String(
                        (window.PPEProvisioningStatus && typeof window.PPEProvisioningStatus.get === 'function'
                            && (window.PPEProvisioningStatus.get() || {}).status)
                        || ''
                    ).toLowerCase();
                    const isProvisioned = (
                        provisionStatus === 'provisioned'
                        || provisionStatus === 'approved'
                        || provisionStatus === 'active'
                        || globalProvisionStatus === 'provisioned'
                        || globalProvisionStatus === 'approved'
                        || globalProvisionStatus === 'active'
                    );

                    if (heartbeatRecent) {
                        const remoteHint = `Edge heartbeat${heartbeatMachineId ? ` (${heartbeatMachineId})` : ''} reports local mode is not ready yet.`;
                        this.setProviderStatus(remoteHint, 'warning');
                        this.showNotification(remoteHint, 'warning');
                    } else if (isProvisioned) {
                        const idleHint = `Local backend on the host PC is not running right now${heartbeatMachineId ? ` (last paired as ${heartbeatMachineId})` : ''}. Cloud mode continues to work normally. To use local mode, start CASM_LOCALINSTALLER (or start.bat) on the host PC and rerun checkup.`;
                        this.setProviderStatus(idleHint, 'info');
                        // Intentionally no toast — this is a normal state, not an error.
                    } else {
                        const remoteHint = `No recent edge heartbeat was received${heartbeatFreshWindow ? ` within ${heartbeatFreshWindow}s` : ''}. Start CASM_LOCALINSTALLER on the host PC, wait for the first sync/provisioning request, then rerun checkup.`;
                        this.setProviderStatus(remoteHint, 'warning');
                        this.showNotification(remoteHint, 'warning');
                    }
                } else {
                    const configuredWaitSeconds = Number(
                        (window && (window.CASM_LOCAL_CHECKUP_WAIT_SECONDS ?? window.__CASM_LOCAL_CHECKUP_WAIT_SECONDS)) ?? 8
                    );
                    const configuredPullTimeoutSeconds = Number(
                        (window && (window.CASM_LOCAL_CHECKUP_PULL_TIMEOUT_SECONDS ?? window.__CASM_LOCAL_CHECKUP_PULL_TIMEOUT_SECONDS)) ?? 120
                    );
                    const waitSeconds = Number.isFinite(configuredWaitSeconds)
                        ? Math.max(3, Math.min(30, Math.round(configuredWaitSeconds)))
                        : 8;
                    const pullTimeoutSeconds = Number.isFinite(configuredPullTimeoutSeconds)
                        ? Math.max(60, Math.min(900, Math.round(configuredPullTimeoutSeconds)))
                        : 120;

                    const prep = await API.prepareLocalMode({
                        autoPull: true,
                        setLocalFirst: false,
                        waitSeconds,
                        pullTimeoutSeconds
                    });

                    ready = !!(prep && prep.success && prep.local && prep.local.local_mode_possible);
                    if (!ready) {
                        const prepError = String((prep && prep.error) || 'Local mode is still not ready after setup attempt.');
                        this.setProviderStatus(prepError, 'warning');
                        this.showNotification(prepError, 'warning');
                    }
                }
            }

            if (window.PPELocalModePolicy && typeof window.PPELocalModePolicy.set === 'function') {
                window.PPELocalModePolicy.set({
                    checkupCompleted: ready,
                    autoSetupAllowed: ready
                });
            }

            const provisionResult = isLikelyRemoteBackend
                ? await this.refreshRemoteProvisioningStatus({
                    allowRequest: false,   // checkup is health-check only — use the dedicated button to request provisioning
                    machineIdHint: heartbeatMachineId || this.localProvisionState.machineId,
                    cloud_local_heartbeat: cloudHeartbeat
                })
                : await API.autoProvisionLocalModeCredentials();
            this.syncLocalProvisionStateFromPayload(provisionResult || {});

            const status = this.normalizeLocalProvisionStatus((provisionResult && provisionResult.status) || 'idle');
            if (status === 'active') {
                this.setProviderStatus('Device provisioned and active. Local backend is running.', 'success');
            } else if (status === 'provisioned') {
                this.setProviderStatus('Device is provisioned. Cloud sync is active.', 'success');
            } else if (status === 'approved') {
                this.setProviderStatus('Device is approved. Cloud sync is available.', 'success');
            } else if (status === 'credentials_present') {
                this.setProviderStatus('Cloud credentials are present on this device.', 'info');
            } else if (status === 'pending_approval') {
                this.setProviderStatus('Provisioning request is pending admin approval.', 'warning');
                this.ensureLocalProvisionPolling();
            } else if (status === 'rejected' && isLikelyRemoteBackend) {
                // Only show 'rejected' immediately when connected to the remote backend
                // (where the response is authoritative). When connected to the local
                // backend the disk state may be stale — defer to the finalStatus block
                // after refreshProvisioningState() has done a live cloud check.
                this.setProviderStatus('Provisioning request was rejected. Use "Request Provisioning" to re-apply.', 'error');
            } else if (ready) {
                // No provisioning info yet — health check passed, prompt user to use the button
                this.setProviderStatus(
                    useHeartbeatDiagnostics
                        ? `Health check passed via edge heartbeat${heartbeatMachineId ? ` (${heartbeatMachineId})` : ''}. Use "Request Provisioning" to register this device.`
                        : 'Health check completed. Use "Request Provisioning" to register this device for cloud sync.',
                    'info'
                );
            } else if (this.isCloudEndpointUnreachable(String((provisionResult && provisionResult.error) || ''))) {
                this.setProviderStatus('Cloud endpoint is unreachable. Local mode remains available.', 'warning');
            }

            const shouldSkipRemoteRefresh = isLikelyRemoteBackend
                && (
                    status === 'pending_approval'
                    || status === 'approved'
                    || status === 'provisioned'
                    || status === 'active'
                    || status === 'rejected'
                );
            if (!shouldSkipRemoteRefresh) {
                await this.refreshProvisioningState();
            }

            let finalStatus = this.normalizeLocalProvisionStatus(
                (this.localProvisionState && this.localProvisionState.status) || status || 'idle'
            );

            const provisionResultStatus = this.normalizeLocalProvisionStatus(status || 'idle');
            const finalIsWeaker = (
                finalStatus === 'idle'
                || finalStatus === 'pending_approval'
                || finalStatus === 'credentials_present'
                || finalStatus === 'error'
            );
            if ((provisionResultStatus === 'approved' || provisionResultStatus === 'provisioned' || provisionResultStatus === 'active') && finalIsWeaker) {
                finalStatus = provisionResultStatus;
                this.localProvisionState.status = provisionResultStatus;
                this.updateLocalModeCheckupStatus();
            }

            if (
                isLikelyRemoteBackend
                && (finalStatus === 'approved' || finalStatus === 'provisioned' || finalStatus === 'active')
                && !this.getStoredProvisionSecretForMachine(this.localProvisionState.machineId)
            ) {
                try {
                    const refreshedStored = await this.recoverRemoteInstallerCredentials(this.localProvisionState.machineId);
                    if (String((refreshedStored || {}).provisionSecret || '').trim()) {
                        finalStatus = this.normalizeLocalProvisionStatus(
                            this.localProvisionState.status || refreshedStored.status || finalStatus
                        );
                        this.setProviderStatus('Installer access refreshed. You can re-download the BAT now.', 'success');
                    }
                } catch (installerRefreshErr) {
                    console.warn('GlobalSettingsModal: installer access refresh during checkup failed', installerRefreshErr);
                }
            }

            if (finalStatus === 'active') {
                this.setProviderStatus('Device provisioned and active. Local backend is running.', 'success');
            } else if (finalStatus === 'provisioned') {
                this.setProviderStatus('Provisioning completed. Cloud sync is now available.', 'success');
            } else if (finalStatus === 'approved') {
                this.setProviderStatus('Device is approved. You can re-issue installer BAT from this panel.', 'success');
            } else if (finalStatus === 'rejected') {
                this.setProviderStatus('Provisioning request was rejected. Use "Request Provisioning" to re-apply.', 'error');
            }
        } catch (error) {
            console.error('GlobalSettingsModal: local checkup failed', error);
            const message = (error && error.name === 'TimeoutError')
                ? 'Local mode checkup timed out waiting for the cloud. Local mode can still run offline; rerun once connectivity returns.'
                : (error && error.message) || 'Local mode checkup failed';
            this.setProviderStatus(message, 'error');
            this.showNotification(message, 'error');
        } finally {
            clearTimeout(watchdog);
            this._localCheckupRunning = false;
            this._restoreLocalCheckupButton();
        }
    },

    async pingGemma() {
        const btn = this.getEl('globalPingGemmaBtn');
        const statusEl = this.getEl('globalTestModeStatus');
        if (!btn) return;

        const originalLabel = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Pinging Gemma...';
        if (statusEl) {
            statusEl.textContent = 'Sending tiny prompt to local LLM...';
            statusEl.style.color = 'var(--text-secondary)';
        }

        // "Local Test Mode" pings the LOCAL backend (which talks to local Ollama),
        // never the cloud backend. Otherwise on Vercel we'd be asking the Railway
        // container to reach its own (non-existent) localhost:11434.
        const localBase = (API_CONFIG.LOCAL_BACKEND_URL || 'http://localhost:5000').replace(/\/+$/, '');
        const pingUrl = `${localBase}/api/llm/ping`;

        try {
            const resp = await fetch(pingUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt: 'Reply with the single word: PONG' })
            });
            const data = await resp.json().catch(() => ({}));

            if (resp.ok && data.ok) {
                if (statusEl) {
                    statusEl.textContent =
                        `\u2705 Gemma is working\n` +
                        `Model: ${data.model || '?'}\n` +
                        `Latency: ${data.latency_ms ?? '?'} ms\n` +
                        `Reply: ${data.response_preview || '(empty)'}`;
                    statusEl.style.color = 'var(--success-color)';
                }
            } else {
                const errMsg = data.error || `HTTP ${resp.status}`;
                if (statusEl) {
                    statusEl.textContent =
                        `\u274C Gemma is not responding\n` +
                        `Model: ${data.model || '?'}\n` +
                        `Base URL: ${data.base_url || '?'}\n` +
                        `Ollama running: ${data.ollama_running ? 'yes' : 'no'}\n` +
                        `Model pulled: ${data.model_available ? 'yes' : 'no'}\n` +
                        `Error: ${errMsg}`;
                    statusEl.style.color = 'var(--error-color)';
                }
            }
        } catch (err) {
            if (statusEl) {
                statusEl.textContent =
                    `\u274C Could not reach local backend at ${pingUrl}\n` +
                    `Local Test Mode requires start.bat to be running on this PC.\n` +
                    `Error: ${err.message || err}`;
                statusEl.style.color = 'var(--error-color)';
            }
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalLabel;
        }
    },

    async fetchLocalModeSnapshot() {
        const btn = this.getEl('globalLocalSnapshotBtn');
        const statusEl = this.getEl('globalTestModeStatus');
        if (!btn) return;

        const originalLabel = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading...';

        try {
            const resp = await fetch(`${API_CONFIG.BASE_URL}/api/system/local-mode-snapshot`);
            const data = await resp.json().catch(() => ({}));
            if (statusEl) {
                const lines = [
                    `Routing profile: ${data.routing_profile}`,
                    `Pure offline mode: ${data.pure_offline_active ? 'YES (no Supabase)' : 'no'}`,
                    `Supabase DB active: ${data.supabase_db_active ? 'yes' : 'no'}`,
                    `Cloud credentials present: ${data.supabase_credentials_present ? 'yes' : 'no'}`,
                    `Mock report mode (env): ${data.mock_reports_enabled ? 'ON' : 'off'}`,
                    `Local reports dir: ${data.local_reports_dir || '(unknown)'}`,
                    `Local report count: ${data.local_report_count}`,
                ];
                statusEl.textContent = lines.join('\n');
                statusEl.style.color = data.pure_offline_active
                    ? 'var(--success-color)'
                    : 'var(--text-secondary)';
            }
        } catch (err) {
            if (statusEl) {
                statusEl.textContent = `Snapshot failed: ${err.message || err}`;
                statusEl.style.color = 'var(--error-color)';
            }
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalLabel;
        }
    },

    ensureLocalProvisionPolling() {
        if (this.localProvisionPollInterval) return;

        // Adaptive cadence: poll fast right after the request was submitted so
        // the UI flips green within ~5s of admin approval, then back off to
        // avoid hammering the cloud once it's been pending for a while.
        const FAST_INTERVAL_MS = 5000;     // first ~2 minutes
        const SLOW_INTERVAL_MS = 15000;    // after that
        const FAST_WINDOW_MS = 2 * 60 * 1000;
        const startedAt = Date.now();
        let currentIntervalMs = FAST_INTERVAL_MS;

        const scheduleNext = () => {
            const elapsed = Date.now() - startedAt;
            const desired = elapsed > FAST_WINDOW_MS ? SLOW_INTERVAL_MS : FAST_INTERVAL_MS;
            if (desired !== currentIntervalMs) {
                clearInterval(this.localProvisionPollInterval);
                currentIntervalMs = desired;
                this.localProvisionPollInterval = setInterval(tick, currentIntervalMs);
            }
        };

        const tick = async () => {
            if (!this.isOpen) return;

            const status = this.normalizeLocalProvisionStatus(this.localProvisionState.status || 'idle');
            if (status !== 'pending_approval') {
                return;
            }

            try {
                const pollResult = this.isLikelyRemoteBackend()
                    ? await this.refreshRemoteProvisioningStatus({
                        allowRequest: false,
                        machineIdHint: this.localProvisionState.machineId
                    })
                    : await API.autoProvisionLocalModeCredentials();
                this.syncLocalProvisionStateFromPayload(pollResult || {});
                const pollStatus = this.normalizeLocalProvisionStatus((pollResult && pollResult.status) || 'idle');
                if (pollStatus === 'approved' || pollStatus === 'provisioned' || pollStatus === 'active' || pollStatus === 'credentials_present' || pollStatus === 'rejected') {
                    this.stopLocalProvisionPolling();
                    return;
                }
            } catch (error) {
                console.warn('GlobalSettingsModal: silent provision poll failed', error);
            }

            scheduleNext();
        };

        this.localProvisionPollInterval = setInterval(tick, currentIntervalMs);
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
        this.ensureHeartbeatCountdown();

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
            this.refreshProvisioningState(),
            this.loadAudioSettings()
        ]);
        this.updateHeartbeatBadge();

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
        this.stopHeartbeatCountdown();

        if (typeof Router !== 'undefined' && Router.updateActiveNav) {
            Router.updateActiveNav(APP_STATE.currentPage || 'home');
        }
    },

    async redownloadInstaller() {
        const storedBefore = this.loadRemoteProvisionState() || {};
        if (
            storedBefore.machineId
            && (storedBefore.status === 'approved' || storedBefore.status === 'provisioned' || storedBefore.status === 'active')
            && this.normalizeLocalProvisionStatus(this.localProvisionState.status) !== 'approved'
            && this.normalizeLocalProvisionStatus(this.localProvisionState.status) !== 'provisioned'
            && this.normalizeLocalProvisionStatus(this.localProvisionState.status) !== 'active'
        ) {
            this.syncLocalProvisionStateFromPayload({
                machine_id: storedBefore.machineId,
                status: storedBefore.status,
                admin_portal_url: storedBefore.adminPortalUrl || ''
            });
        }

        let status = this.normalizeLocalProvisionStatus(this.localProvisionState.status);
        let machineId = String(this.localProvisionState.machineId || '').trim();

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

        const currentProtocol = String(window.location.protocol || '').toLowerCase();
        if (currentProtocol === 'chrome-error:' || currentProtocol === 'about:' || currentProtocol === 'data:') {
            this.showNotification(
                'This page is in an error state. Refresh the tab from the backend URL and try again.',
                'error'
            );
            return;
        }

        const apiBase = String(API_CONFIG.BASE_URL || '').replace(/\/+$/, '');
        const isRemoteBackend = this.isLikelyRemoteBackend();

        if (isRemoteBackend && !this.getStoredProvisionSecretForMachine(machineId)) {
            try {
                this.setProviderStatus('Refreshing installer access for this approved device...', 'info');
                await this.recoverRemoteInstallerCredentials(machineId);
                status = this.normalizeLocalProvisionStatus(this.localProvisionState.status);
                machineId = String(this.localProvisionState.machineId || machineId || '').trim();
            } catch (recoverErr) {
                console.warn('GlobalSettingsModal: installer credential refresh failed', recoverErr);
            }
        }

        const tryDirectCloudDownload = () => {
            const stored = this.loadRemoteProvisionState() || {};
            const machineIdStored = String(stored.machineId || this.localProvisionState.machineId || machineId || '').trim();
            const provisionSecretStored = String(stored.provisionSecret || '').trim();

            if (!machineIdStored || !provisionSecretStored) {
                return false;
            }

            let cloudBase = '';
            if (isRemoteBackend) {
                cloudBase = apiBase;
            } else {
                cloudBase = String(stored.cloudUrl || window.CLOUD_URL || '').replace(/\/+$/, '');
            }

            if (!cloudBase) {
                return false;
            }

            const params = new URLSearchParams({
                machine_id: machineIdStored,
                provision_secret: provisionSecretStored,
                _ts: String(Date.now())
            });
            window.location.assign(`${cloudBase}/api/bootstrap/installer/request?${params.toString()}`);
            return true;
        };

        if (!isRemoteBackend) {
            const proxyUrl = `${apiBase}/api/local-mode/installer/redirect?_ts=${Date.now()}`;
            try {
                const probeController = new AbortController();
                const probeTimer = setTimeout(() => probeController.abort(), 4000);
                const probeResp = await fetch(`${apiBase}/api/system/startup-status`, {
                    cache: 'no-store',
                    signal: probeController.signal
                }).finally(() => clearTimeout(probeTimer));
                if (probeResp && (probeResp.status < 500 || probeResp.status === 503)) {
                    window.location.assign(proxyUrl);
                    return;
                }
            } catch (probeErr) {
                console.warn('GlobalSettingsModal: local backend probe failed; falling back to direct cloud download', probeErr);
            }
        }

        if (tryDirectCloudDownload()) {
            return;
        }

        if (isRemoteBackend) {
            const localBase = String(
                (window.API_CONFIG && window.API_CONFIG.LOCAL_BACKEND_URL)
                || 'http://localhost:5000'
            ).replace(/\/+$/, '');
            let localBackendUp = false;
            try {
                const probeController = new AbortController();
                const probeTimer = setTimeout(() => probeController.abort(), 1500);
                const probeResp = await fetch(`${localBase}/api/system/startup-status`, {
                    cache: 'no-store',
                    signal: probeController.signal,
                    mode: 'no-cors'
                }).finally(() => clearTimeout(probeTimer));
                if (probeResp) {
                    localBackendUp = true;
                }
            } catch (probeErr) {
                localBackendUp = false;
            }

            if (localBackendUp) {
                window.location.assign(`${localBase}/api/local-mode/installer/redirect?_ts=${Date.now()}`);
                return;
            }

            this.showNotification(
                'Cannot download installer: provisioning credentials could not be refreshed in this browser '
                + 'and the local backend on localhost:5000 is not running. Start the local backend or rerun '
                + 'Local Mode Checkup from the host PC.',
                'error'
            );
            return;
        }

        this.showNotification(
            'Local backend is offline and stored cloud credentials are missing. Run Local Mode Checkup, then try again.',
            'error'
        );
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
        const requestProvisioningBtn = this.getEl('globalRequestProvisioningBtn');
        const redownloadInstallerBtn = this.getEl('globalRedownloadInstallerBtn');
        const pingGemmaBtn = this.getEl('globalPingGemmaBtn');
        const localSnapshotBtn = this.getEl('globalLocalSnapshotBtn');

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

        if (requestProvisioningBtn) {
            requestProvisioningBtn.addEventListener('click', () => this.requestProvisioning());
        }

        if (pingGemmaBtn) {
            pingGemmaBtn.addEventListener('click', () => this.pingGemma());
        }

        if (localSnapshotBtn) {
            localSnapshotBtn.addEventListener('click', () => this.fetchLocalModeSnapshot());
        }

        if (redownloadInstallerBtn) {
            redownloadInstallerBtn.addEventListener('click', async () => {
                await this.redownloadInstaller();
                return;

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

                // Refuse to navigate when the page itself is in a chrome-error
                // or other invalid context. This prevents the user-facing
                // "Unsafe attempt to load URL ... from frame with URL
                // chrome-error://chromewebdata/" warning.
                const currentProtocol = String(window.location.protocol || '').toLowerCase();
                if (currentProtocol === 'chrome-error:' || currentProtocol === 'about:' || currentProtocol === 'data:') {
                    this.showNotification(
                        'This page is in an error state. Refresh the tab from the backend URL and try again.',
                        'error'
                    );
                    return;
                }

                // Two scenarios:
                //   (A) Page is hosted on the local backend (localhost). The local
                //       backend has provision_secret on disk and can issue a
                //       302 to cloud via /api/local-mode/installer/redirect.
                //   (B) Page is hosted on the cloud frontend (Vercel) OR the
                //       local backend is offline. We must call the cloud
                //       installer endpoint directly using the machine_id +
                //       provision_secret that the checkup persisted into
                //       sessionStorage (see saveRemoteProvisionState).
                const apiBase = String(API_CONFIG.BASE_URL || '').replace(/\/+$/, '');
                const isRemoteBackend = this.isLikelyRemoteBackend();

                // Helper: perform direct cloud installer download using stored
                // provision_secret. Returns true on success (navigation issued),
                // false if credentials are missing.
                const tryDirectCloudDownload = () => {
                    const stored = this.loadRemoteProvisionState() || {};
                    const machineIdStored = String(stored.machineId || this.localProvisionState.machineId || '').trim();
                    const provisionSecretStored = String(stored.provisionSecret || '').trim();

                    if (!machineIdStored || !provisionSecretStored) {
                        return false;
                    }

                    // Resolve cloud URL. When the page is already pointed at the
                    // cloud, API_CONFIG.BASE_URL is the cloud. Otherwise fall
                    // back to a stored cloud URL hint or window.location.origin.
                    let cloudBase = '';
                    if (isRemoteBackend) {
                        cloudBase = apiBase;
                    } else {
                        cloudBase = String(stored.cloudUrl || window.CLOUD_URL || '').replace(/\/+$/, '');
                    }

                    if (!cloudBase) {
                        return false;
                    }

                    const params = new URLSearchParams({
                        machine_id: machineIdStored,
                        provision_secret: provisionSecretStored,
                        _ts: String(Date.now())
                    });
                    const cloudUrl = `${cloudBase}/api/bootstrap/installer/request?${params.toString()}`;
                    window.location.assign(cloudUrl);
                    return true;
                };

                // Path A — page is served by the local backend. Try the local
                // proxy redirect first (no need to expose secret in URL bar).
                if (!isRemoteBackend) {
                    const proxyUrl = `${apiBase}/api/local-mode/installer/redirect?_ts=${Date.now()}`;
                    try {
                        const probeController = new AbortController();
                        const probeTimer = setTimeout(() => probeController.abort(), 4000);
                        const probeResp = await fetch(`${apiBase}/api/system/startup-status`, {
                            cache: 'no-store',
                            signal: probeController.signal
                        }).finally(() => clearTimeout(probeTimer));
                        if (probeResp && (probeResp.status < 500 || probeResp.status === 503)) {
                            window.location.assign(proxyUrl);
                            return;
                        }
                    } catch (probeErr) {
                        console.warn('GlobalSettingsModal: local backend probe failed; falling back to direct cloud download', probeErr);
                    }
                }

                // Path B — direct cloud download with stored credentials.
                if (tryDirectCloudDownload()) {
                    return;
                }

                // Path C — page is on the cloud frontend (Vercel) but the browser's
                // sessionStorage has no provision_secret (e.g. cleared by an earlier
                // rejected flow, or a fresh browser session). If a local backend is
                // running on localhost:5000 it has the provision_secret on disk and
                // can 302 us to the cloud installer URL via its loopback-only
                // installer/redirect endpoint. We must PROBE first — top-level
                // navigation to a non-running localhost shows a confusing
                // "site can't be reached" page, so only redirect if the probe
                // confirms the local backend is up.
                if (isRemoteBackend) {
                    const localBase = String(
                        (window.API_CONFIG && window.API_CONFIG.LOCAL_BACKEND_URL)
                        || 'http://localhost:5000'
                    ).replace(/\/+$/, '');
                    let localBackendUp = false;
                    try {
                        const probeController = new AbortController();
                        const probeTimer = setTimeout(() => probeController.abort(), 1500);
                        // Use no-cors so a cross-origin HTTPS→HTTP-localhost probe
                        // doesn't get rejected by CORS preflight. With no-cors,
                        // a reachable server yields an opaque response (status 0)
                        // and only true network errors / timeouts throw.
                        const probeResp = await fetch(`${localBase}/api/system/startup-status`, {
                            cache: 'no-store',
                            signal: probeController.signal,
                            mode: 'no-cors'
                        }).finally(() => clearTimeout(probeTimer));
                        if (probeResp) {
                            localBackendUp = true;
                        }
                    } catch (probeErr) {
                        localBackendUp = false;
                    }

                    if (localBackendUp) {
                        const localProxyUrl = `${localBase}/api/local-mode/installer/redirect?_ts=${Date.now()}`;
                        window.location.assign(localProxyUrl);
                        return;
                    }

                    // No local backend reachable AND no browser secret → the user has
                    // no credentials to authenticate the device-flow installer
                    // download. Clear, actionable guidance is the only safe option:
                    // they must either (a) start the local backend so the disk
                    // secret can be used, or (b) re-run Local Mode Checkup which
                    // will repopulate sessionStorage with the provision_secret.
                    this.showNotification(
                        'Cannot download installer: this browser has no stored provisioning '
                        + 'credentials and the local backend on localhost:5000 is not running. '
                        + 'Either start the local backend (run start.bat) and try again, or '
                        + 'open this dashboard from the local backend URL to re-run Local Mode '
                        + 'Checkup.',
                        'error'
                    );
                    return;
                }

                this.showNotification(
                    'Local backend is offline and stored cloud credentials are missing. '
                    + 'Run Local Mode Checkup, then try again.',
                    'error'
                );
            });
        }

        // Audio settings bindings
        const volumeSlider = this.getEl('globalVolumeSlider');
        const volumeValue = this.getEl('globalVolumeValue');
        const applyAudioBtn = this.getEl('globalApplyAudioBtn');
        const voiceSelect = this.getEl('globalVoiceSelect');
        const voiceCustom = this.getEl('globalVoiceCustom');
        const testVoiceBtn = this.getEl('globalTestVoiceBtn');

        if (volumeSlider && volumeValue) {
            volumeSlider.addEventListener('input', () => {
                volumeValue.textContent = `${volumeSlider.value}%`;
            });
        }

        if (applyAudioBtn) {
            applyAudioBtn.addEventListener('click', () => {
                try {
                    const vol = Number(volumeSlider ? volumeSlider.value : 100);
                    const voiceChoice = (voiceSelect && voiceSelect.value) ? voiceSelect.value : (voiceCustom ? voiceCustom.value : '');
                    localStorage.setItem('luna_voice_volume', String(Math.max(0, Math.min(100, Math.round(vol)))));
                    if (voiceChoice && String(voiceChoice || '').trim()) localStorage.setItem('luna_voice_choice', String(voiceChoice).trim());
                    this.showNotification('Audio settings saved', 'success');
                    // Propagate to runtime AudioAlert if available
                    try {
                        if (window.AudioAlert && typeof window.AudioAlert.setVolume === 'function') {
                            window.AudioAlert.setVolume(Math.max(0, Math.min(100, Math.round(vol))) / 100);
                        }
                        if (window.AudioAlert && typeof window.AudioAlert.setPreferredVoice === 'function' && voiceChoice) {
                            window.AudioAlert.setPreferredVoice(String(voiceChoice).trim());
                        }
                    } catch (e) { /* ignore */ }
                } catch (e) {
                    console.warn('Failed saving audio settings', e);
                    this.showNotification('Failed saving audio settings', 'error');
                }
            });
        }

        if (testVoiceBtn) {
            testVoiceBtn.addEventListener('click', () => {
                try {
                    if (typeof window.speechSynthesis === 'undefined') {
                        this.showNotification('SpeechSynthesis not supported', 'error');
                        return;
                    }
                    const utter = new SpeechSynthesisUtterance('This is a voice test.');
                    utter.rate = 1.0; utter.pitch = 1.0;
                    const storedVoice = (voiceSelect && voiceSelect.value) ? voiceSelect.value : (voiceCustom ? voiceCustom.value : '');
                    const voices = window.speechSynthesis.getVoices() || [];
                    if (storedVoice && voices.length) {
                        const preferred = voices.find(v => v.name === storedVoice || `${v.lang} ${v.name}` === storedVoice || v.name === String(storedVoice));
                        if (preferred) utter.voice = preferred;
                    }
                    const storedVol = Number(localStorage.getItem('luna_voice_volume'));
                    utter.volume = Number.isFinite(storedVol) ? Math.max(0, Math.min(1, storedVol / 100)) : 1.0;
                    window.speechSynthesis.cancel(); window.speechSynthesis.speak(utter);
                    this.showNotification('Playing test voice', 'info');
                } catch (err) {
                    console.warn('Test voice failed', err);
                    this.showNotification('Test voice failed', 'error');
                }
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
            this.updateRequestProvisioningButton();
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
