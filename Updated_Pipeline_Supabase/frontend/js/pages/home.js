// Home Page Component
const HomePage = {
    _realtimeHandler: null,
    _connectionHandler: null,
    _timezoneChangeHandler: null,
    _provisioningHandler: null,
    _runLocalCheckupHandler: null,
    _redownloadInstallerHandler: null,
    _latestProvisioningStatus: null,
    _realtimeRefreshTimer: null,
    _fallbackInterval: null,

    render() {
        return `
        <div class="home-dashboard">
            <section class="ops-hero home-ops-hero" aria-label="Site safety command overview">
                <span class="hero-live-badge" aria-label="Live monitoring active"><span class="dot"></span> Live monitoring</span>
                <div class="ops-hero-copy">
                    <span class="ops-kicker"><i class="fas fa-shield-halved"></i> Construction safety operations</span>
                    <h1>Site Safety Command</h1>
                    <p>Live PPE compliance, report generation, and local edge readiness in one field-ready workspace.</p>
                    <div class="ops-hero-actions">
                        <button class="btn btn-primary" type="button" onclick="Router.navigate('live')">
                            <i class="fas fa-video"></i> Open Live Monitor
                        </button>
                        <button class="btn btn-secondary" type="button" onclick="Router.navigate('reports')">
                            <i class="fas fa-clipboard-check"></i> Review Reports
                        </button>
                    </div>
                    <div id="hero-datetime" style="margin-top:1rem; font-size:0.85rem; font-weight:600; color:rgba(26,15,0,0.7); letter-spacing:0.02em;">
                        <i class="fas fa-clock" style="margin-right:0.4rem;"></i><span id="hero-clock"></span>
                    </div>
                </div>
                <div class="ppe-standards-strip" aria-label="PPE standards visual reference">
                    <figure>
                        <img src="/static/images/standards/ms183_helmet.jpg" alt="Safety helmet standard reference" loading="lazy" decoding="async">
                        <figcaption>Helmet</figcaption>
                    </figure>
                    <figure>
                        <img src="/static/images/standards/ms1731_vest.jpg" alt="Safety vest standard reference" loading="lazy" decoding="async">
                        <figcaption>Vest</figcaption>
                    </figure>
                    <figure>
                        <img src="/static/images/standards/iso20345_boots.jpg" alt="Safety boot standard reference" loading="lazy" decoding="async">
                        <figcaption>Boots</figcaption>
                    </figure>
                    <figure>
                        <img src="/static/images/standards/ms2323_mask.png" alt="Respirator mask standard reference" loading="lazy" decoding="async">
                        <figcaption>Mask</figcaption>
                    </figure>
                </div>
            </section>

            <div class="trust-strip" aria-label="Site safety metrics at a glance">
                <div class="trust-metric">
                    <span class="num" id="trustViolationsTotal">0</span>
                    <span class="lbl">Violations Caught</span>
                </div>
                <div class="trust-metric">
                    <span class="num" id="trustReportsTotal">0</span>
                    <span class="lbl">Reports Generated</span>
                </div>
                <div class="trust-metric">
                    <span class="num" id="trustComplianceRate">--%</span>
                    <span class="lbl">Compliance Score</span>
                </div>
            </div>

            <div class="dashboard-section-label">
                <span><i class="fas fa-th-large"></i> Dashboard Overview</span>
            </div>

            <div class="home-grid">

                <!-- OVERVIEW -->
                <div class="card home-summary-card">
                    <div class="card-header">
                        <span><i class="fas fa-chart-line"></i> Violations Overview</span>
                    </div>
                    <div class="card-content">
                        <div class="summary-grid">

                            <div class="summary-block">
                                <span class="label">Today</span>
                                <span class="value" id="todayCount">0</span>
                                <span class="delta" id="todayDelta"></span>
                            </div>

                            <div class="summary-block">
                                <span class="label">This Week</span>
                                <span class="value" id="weekCount">0</span>
                                <span class="delta" id="weekDelta"></span>
                            </div>

                            <div class="summary-block">
                                <span class="label">High Severity</span>
                                <span class="value" id="highSeverityCount">0</span>
                            </div>

                        </div>
                    </div>
                </div>

                <!-- SAFETY SCORE -->
                <div class="card home-score-card">
                    <div class="card-header">
                        <span><i class="fas fa-trophy"></i> Safety Compliance Score</span>
                    </div>
                    <div class="card-content" style="text-align:center;">
                        <div id="safety-score"
                             style="font-size:4rem;font-weight:700;margin-bottom:1rem;">
                            --
                        </div>

                        <p style="font-size:1.2rem;margin-bottom:1rem;">
                            Overall Safety Compliance
                        </p>

                        <div style="
                            max-width:600px;
                            height:20px;
                            background:var(--background-color);
                            border-radius:10px;
                            margin:0 auto;
                            overflow:hidden;">
                            <div id="safety-bar"
                                 style="height:100%;width:0%;transition:width 0.5s ease;">
                            </div>
                        </div>

                        <p style="color:#7f8c8d;margin-top:1rem;font-size:0.9rem;">
                            Based on violation frequency and severity
                        </p>
                        <p id="safety-benchmark-note" style="color:#6b7280;margin-top:0.35rem;font-size:0.82rem;"></p>
                    </div>
                </div>

                <!-- VIOLATION TYPES -->
                <div class="card home-violation-card home-violation-types-card">
                    <div class="card-header">
                        <span><i class="fas fa-pie-chart"></i> Violation Types</span>
                    </div>
                    <div class="card-content home-violation-content" id="violation-types">
                        <div class="spinner"></div>
                    </div>
                </div>


                <!-- REPORTS OVERVIEW -->
                <div class="card home-reports-card">
                    <div class="card-header">
                        <span><i class="fas fa-file-alt"></i> Reports Overview</span>
                    </div>
                    <div class="card-content">
                        <div class="summary-grid">
                            <div class="summary-block">
                                <span class="label">Pending</span>
                                <span class="value" id="pendingCount">0</span>
                            </div>

                            <div class="summary-block">
                                <span class="label">Processing</span>
                                <span class="value" id="processingCount">0</span>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- RECENT VIOLATIONS -->
                <div class="card home-violation-card home-recent-violations-card">
                    <div class="recent-header">
                        <span><i class="fas fa-exclamation-triangle"></i> Recent Violations</span>
                        <button class="btn btn-secondary"
                                onclick="Router.navigate('reports')">
                            View All
                        </button>
                    </div>
                    <div id="recent-violations" class="recent-content home-recent-content">
                        <div class="spinner"></div>
                    </div>
                </div>

                <div class="card home-local-mode-card">
                    <div class="card-header home-local-mode-header">
                        <span><i class="fas fa-plug-circle-check"></i> Local Mode Approval</span>
                    </div>
                    <div class="card-content home-local-mode-content">
                        <p id="homeProvisionMessage" style="margin: 0; color: var(--text-color);">
                            Loading latest local mode provisioning status...
                        </p>
                        <p id="homeProvisionMachine" style="margin: 0.45rem 0 0 0; color: var(--text-secondary); font-size: 0.9rem;"></p>
                        <div class="home-local-mode-actions" style="display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 1rem;">
                            <button id="homeRunLocalCheckupBtn" class="btn btn-primary" type="button">
                                <i class="fas fa-wifi"></i> Local Mode Checkup
                            </button>
                            <button id="homeRedownloadInstallerBtn" class="btn btn-secondary" type="button" style="display: none;">
                                <i class="fas fa-download"></i> Re-download Installer BAT
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        `;
    },

    async mount() {
        await this.refreshData();

        this._realtimeHandler = () => {
            if (this._realtimeRefreshTimer) return;
            this._realtimeRefreshTimer = setTimeout(async () => {
                this._realtimeRefreshTimer = null;
                await this.refreshData();
            }, 800);
        };
        window.addEventListener('ppe-realtime:update', this._realtimeHandler);

        this._connectionHandler = () => this.syncFallbackPolling();
        window.addEventListener('ppe-realtime:connection', this._connectionHandler);

        this._timezoneChangeHandler = () => this.refreshData();
        window.addEventListener('ppe-timezone:changed', this._timezoneChangeHandler);

        // Live clock in hero
        const heroClock = document.getElementById('hero-clock');
        const updateClock = () => {
            if (!heroClock) return;
            const now = new Date();
            heroClock.textContent = now.toLocaleString('en-MY', {
                weekday: 'short', year: 'numeric', month: 'short',
                day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit'
            });
        };
        updateClock();
        this._clockInterval = setInterval(updateClock, 1000);

        this._provisioningHandler = (event) => {
            this.renderProvisioningStatus((event && event.detail) || null);
        };
        window.addEventListener('ppe-provisioning:status', this._provisioningHandler);

        const runCheckupBtn = document.getElementById('homeRunLocalCheckupBtn');
        if (runCheckupBtn) {
            this._runLocalCheckupHandler = () => {
                Router.navigate('settings-checkup');
            };
            runCheckupBtn.addEventListener('click', this._runLocalCheckupHandler);
        }

        const redownloadInstallerBtn = document.getElementById('homeRedownloadInstallerBtn');
        if (redownloadInstallerBtn) {
            this._redownloadInstallerHandler = async () => {
                const latest = this._latestProvisioningStatus || {};
                const status = String(latest.status || '').toLowerCase();
                const machineId = String(latest.machineId || latest.machine_id || '').trim();
                const isProvisioned = status === 'provisioned' || status === 'approved' || status === 'active';

                if (!isProvisioned || !machineId) {
                    const message = 'Installer re-download is available after this device is fully provisioned.';
                    if (typeof NotificationManager !== 'undefined') {
                        NotificationManager.warning(message);
                    } else {
                        alert(message);
                    }
                    return;
                }

                if (
                    typeof GlobalSettingsModal !== 'undefined'
                    && GlobalSettingsModal
                    && typeof GlobalSettingsModal.redownloadInstaller === 'function'
                ) {
                    if (typeof GlobalSettingsModal.init === 'function') {
                        GlobalSettingsModal.init();
                    }
                    if (typeof GlobalSettingsModal.syncLocalProvisionStateFromPayload === 'function') {
                        GlobalSettingsModal.syncLocalProvisionStateFromPayload(latest);
                    }
                    await GlobalSettingsModal.redownloadInstaller();
                    return;
                }

                const stored = (() => {
                    try {
                        return JSON.parse(localStorage.getItem('ppe.remoteProvisioningState.v1') || '{}') || {};
                    } catch (_) {
                        return {};
                    }
                })();
                const provisionSecret = String(stored.provisionSecret || '').trim();
                if (provisionSecret) {
                    const params = new URLSearchParams({
                        machine_id: machineId,
                        provision_secret: provisionSecret,
                        _ts: String(Date.now())
                    });
                    window.location.assign(`${API_CONFIG.BASE_URL}/api/bootstrap/installer/request?${params.toString()}`);
                    return;
                }

                const message = 'Run Local Mode Checkup to refresh installer access, then try again.';
                if (typeof NotificationManager !== 'undefined') {
                    NotificationManager.warning(message);
                } else {
                    alert(message);
                }
            };
            redownloadInstallerBtn.addEventListener('click', this._redownloadInstallerHandler);
        }

        if (window.PPEProvisioningStatus && typeof window.PPEProvisioningStatus.get === 'function') {
            this.renderProvisioningStatus(window.PPEProvisioningStatus.get());
        } else {
            this.renderProvisioningStatus(null);
        }

        if (window.PPEProvisioningStatus && typeof window.PPEProvisioningStatus.refresh === 'function') {
            window.PPEProvisioningStatus.refresh({
                source: 'home-mount',
                force: true,
                notify: false
            });
        }

        this.syncFallbackPolling();
    },

    unmount() {
        if (this._clockInterval) {
            clearInterval(this._clockInterval);
            this._clockInterval = null;
        }
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
        if (this._provisioningHandler) {
            window.removeEventListener('ppe-provisioning:status', this._provisioningHandler);
            this._provisioningHandler = null;
        }

        const runCheckupBtn = document.getElementById('homeRunLocalCheckupBtn');
        if (runCheckupBtn && this._runLocalCheckupHandler) {
            runCheckupBtn.removeEventListener('click', this._runLocalCheckupHandler);
        }
        this._runLocalCheckupHandler = null;

        const redownloadInstallerBtn = document.getElementById('homeRedownloadInstallerBtn');
        if (redownloadInstallerBtn && this._redownloadInstallerHandler) {
            redownloadInstallerBtn.removeEventListener('click', this._redownloadInstallerHandler);
        }
        this._redownloadInstallerHandler = null;
        this._latestProvisioningStatus = null;

        if (this._fallbackInterval) {
            clearInterval(this._fallbackInterval);
            this._fallbackInterval = null;
        }
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

    async refreshData() {
        const [stats, pendingReports] = await Promise.all([
            API.getStats(),
            API.getPendingReports()
        ]);

        this.renderHomeSummary(stats);
        this.renderViolationTypes(stats);
        this.renderRecentViolations(stats.recentViolations || []);
        this.calculateSafetyScore(stats);
        this.renderReportsOverview(stats, pendingReports || []);
        this.renderTrustStrip(stats, pendingReports || []);
    },

    /* ================= COUNT-UP HELPER ================= */
    countUp(el, target, opts) {
        if (!el) return;
        const t = Number(target);
        if (!Number.isFinite(t)) { el.textContent = target; return; }
        const suffix = (opts && opts.suffix) || '';
        const duration = (opts && opts.duration) || 700;
        // Skip animation on subsequent updates
        const current = parseFloat(String(el.textContent).replace(/[^0-9.\-]/g, ''));
        const start = Number.isFinite(current) ? current : 0;
        if (start === t) { el.textContent = `${t}${suffix}`; return; }
        const startTime = performance.now();
        const step = (now) => {
            const p = Math.min(1, (now - startTime) / duration);
            // ease-out cubic
            const eased = 1 - Math.pow(1 - p, 3);
            const value = Math.round(start + (t - start) * eased);
            el.textContent = `${value}${suffix}`;
            if (p < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
    },

    /* ================= TRUST STRIP ================= */
    renderTrustStrip(stats, pendingReports) {
        const violationsEl = document.getElementById('trustViolationsTotal');
        const reportsEl = document.getElementById('trustReportsTotal');
        const complianceEl = document.getElementById('trustComplianceRate');
        if (!violationsEl || !reportsEl || !complianceEl) return;

        const totalViolations = Number(stats.total)
            || Number(stats.totalViolations)
            || (Array.isArray(stats.recentViolations) ? stats.recentViolations.length : 0)
            || 0;

        // /api/stats returns `completed` for finished reports — not totalReports/reportsTotal.
        // Secondary fallback: sum completed + pending so the number is never zero when data exists.
        const totalReports = Number(stats.reportsGenerated)
            || Number(stats.reports_generated)
            || Number(stats.totalReports)
            || Number(stats.reportsTotal)
            || Number(stats.completed)
            || (Number(stats.completed || 0) + Number(stats.pending || 0))
            || (Array.isArray(pendingReports) ? pendingReports.length : 0)
            || 0;

        const safety = (typeof API !== 'undefined' && API.computeSafetyCompliance)
            ? API.computeSafetyCompliance(stats || {})
            : { score: 0 };
        const score = Math.max(0, Math.min(100, Math.round(Number(safety.score) || 0)));

        this.countUp(violationsEl, totalViolations);
        this.countUp(reportsEl, totalReports);
        this.countUp(complianceEl, score, { suffix: '%' });
    },

    renderReportsOverview(stats, pendingReports) {
        const pendingEl = document.getElementById('pendingCount');
        const processingEl = document.getElementById('processingCount');
        if (!pendingEl || !processingEl) return;

        const pendingCount = Number.isFinite(Number(stats.pending)) ? Number(stats.pending) : (Array.isArray(pendingReports) ? pendingReports.length : 0);
        const processingCount = Array.isArray(pendingReports)
            ? pendingReports.filter((r) => {
                const s = String(r.status || '').toLowerCase();
                return s === 'processing' || s === 'generating' || s === 'queued';
            }).length
            : 0;

        this.countUp(pendingEl, pendingCount);
        this.countUp(processingEl, processingCount);
    },

    renderProvisioningStatus(statusPayload) {
        const badgeEl = document.getElementById('homeProvisionBadge'); // removed in v78; tolerate absence
        const messageEl = document.getElementById('homeProvisionMessage');
        const machineEl = document.getElementById('homeProvisionMachine');
        const redownloadInstallerBtn = document.getElementById('homeRedownloadInstallerBtn');

        if (!messageEl || !machineEl) {
            return;
        }

        this._latestProvisioningStatus = statusPayload && typeof statusPayload === 'object'
            ? { ...statusPayload }
            : null;

        const status = String((statusPayload && statusPayload.status) || 'idle').toLowerCase();
        const machineId = String((statusPayload && (statusPayload.machineId || statusPayload.machine_id)) || '').trim();
        const adminPortalUrl = String((statusPayload && (statusPayload.adminPortalUrl || statusPayload.admin_portal_url)) || '').trim();
            const isProvisioned = status === 'provisioned' || status === 'approved' || status === 'active';

        if (redownloadInstallerBtn) {
            const canRedownload = isProvisioned && !!machineId;
            redownloadInstallerBtn.style.display = canRedownload ? 'inline-flex' : 'none';
            redownloadInstallerBtn.disabled = !canRedownload;
            redownloadInstallerBtn.title = canRedownload
                ? 'Download a fresh one-time installer link'
                : 'Installer re-download is available after provisioning completes.';
        }

        // Helper: write to the badge only if it still exists in the DOM
        // (the badge was removed in v78 to keep status purely message-driven).
        const setBadge = (cls, text) => {
            if (!badgeEl) return;
            badgeEl.className = cls;
            badgeEl.textContent = text;
        };

        machineEl.textContent = '';

        if (status === 'active') {
            setBadge('badge badge-success', 'Active');
            messageEl.textContent = 'Device provisioned and active. Local backend is running.';
        } else if (status === 'provisioned') {
            setBadge('badge badge-success', 'Provisioned');
            messageEl.textContent = 'Approved and active. Cloud credentials are already configured on this backend.';
        } else if (status === 'approved') {
            // Admin has approved this device. Treat as a green
            // success state — the only difference vs. 'provisioned'
            // is that the launcher hasn't reported full handoff yet.
            setBadge('badge badge-success', 'Approved');
            messageEl.textContent = 'Approved by admin. Cloud sync is active.';
        } else if (status === 'credentials_present') {
            const viewingThroughCloud = (typeof isLikelyRemoteBackend === 'function')
                ? isLikelyRemoteBackend()
                : false;
            if (viewingThroughCloud) {
                setBadge('badge badge-info', 'Not Requested');
                messageEl.textContent = 'No approval request from this device yet. Cloud mode is available now; to enable local mode, run Local Mode Checkup from the host PC.';
            } else {
                setBadge('badge badge-success', 'Credentials Detected');
                messageEl.textContent = 'Cloud credentials are present on this backend, but this machine is not approved/provisioned yet.';
            }
        } else if (status === 'pending_approval') {
            setBadge('badge badge-warning', 'Pending Approval');
            messageEl.textContent = 'Approval request is pending. This page updates automatically when admin approves.';
        } else if (status === 'rejected') {
            setBadge('badge badge-danger', 'Rejected');
            messageEl.textContent = 'Approval request was rejected. Open Local Mode Checkup to submit a new request.';
        } else if (status === 'error') {
            setBadge('badge badge-warning', 'Status Error');
            messageEl.textContent = 'Unable to refresh provisioning status right now. Retrying in background.';
        } else {
            setBadge('badge badge-info', 'Not Requested');
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

    /* ================= SUMMARY ================= */

    renderHomeSummary(stats) {
        // Use real deltas from backend (defaults to 0 if undefined)
        const todayDelta = stats.todayDelta !== undefined ? stats.todayDelta : 0;
        const weekDelta = stats.weekDelta !== undefined ? stats.weekDelta : 0;

        const todayCountEl = document.getElementById("todayCount");
        const weekCountEl = document.getElementById("weekCount");
        const highSeverityCountEl = document.getElementById("highSeverityCount");
        const todayDeltaEl = document.getElementById("todayDelta");
        const weekDeltaEl = document.getElementById("weekDelta");

        if (!todayCountEl || !weekCountEl || !highSeverityCountEl || !todayDeltaEl || !weekDeltaEl) {
            return;
        }

        this.countUp(todayCountEl, Number(stats.today) || 0);
        this.countUp(weekCountEl, Number(stats.thisWeek) || 0);
        this.countUp(highSeverityCountEl, Number(stats.severity?.high ?? 0));

        todayDeltaEl.textContent =
            todayDelta > 0 ? `+${todayDelta}` : `${todayDelta}`;
        todayDeltaEl.style.color =
            todayDelta > 0 ? 'var(--error-color)' : 'var(--success-color)';

        weekDeltaEl.textContent =
            weekDelta > 0 ? `+${weekDelta}` : `${weekDelta}`;
        weekDeltaEl.style.color =
            weekDelta > 0 ? 'var(--error-color)' : 'var(--success-color)';
    },

    /* ================= SAFETY SCORE ================= */

    calculateSafetyScore(stats) {
        const safety = API.computeSafetyCompliance(stats || {});
        const score = safety.score;

        const scoreEl = document.getElementById("safety-score");
        const barEl = document.getElementById("safety-bar");
        const benchmarkEl = document.getElementById("safety-benchmark-note");

        if (!scoreEl || !barEl) {
            return;
        }

        scoreEl.textContent = `${score}%`;
        barEl.style.width = `${score}%`;
        if (benchmarkEl) {
            benchmarkEl.textContent = safety.benchmarkNote;
        }

        if (score >= 80) {
            scoreEl.style.color = 'var(--success-color)';
            barEl.style.background =
                'linear-gradient(90deg, var(--success-color), #27ae60)';
        } else if (score >= 60) {
            scoreEl.style.color = 'var(--warning-color)';
            barEl.style.background =
                'linear-gradient(90deg, var(--warning-color), #e67e22)';
        } else {
            scoreEl.style.color = 'var(--error-color)';
            barEl.style.background =
                'linear-gradient(90deg, var(--error-color), #c0392b)';
        }
    },

    /* ================= VIOLATION TYPES ================= */

    renderViolationTypes(stats) {
        const container = document.getElementById("violation-types");
        if (!container) return;
        const breakdown = stats.breakdown || {};

        // Data mapping
        const types = [
            { name: "Missing Hardhat", count: breakdown['NO-Hardhat'] || 0, color: "var(--error-color)" },
            { name: "Missing Vest", count: breakdown['NO-Safety Vest'] || 0, color: "var(--warning-color)" },
            { name: "Missing Gloves", count: breakdown['NO-Gloves'] || 0, color: "var(--info-color)" },
            { name: "Missing Mask", count: breakdown['NO-Mask'] || 0, color: "#9b59b6" },
            { name: "Missing Goggles", count: breakdown['NO-Goggles'] || 0, color: "#e67e22" },
            { name: "Missing Safety Shoes", count: breakdown['NO-Safety Shoes'] || 0, color: "#16a085" }
        ];

        // Calculate total for percentages
        const totalViolations = types.reduce((sum, t) => sum + t.count, 0);

        container.innerHTML = `
            <div class="home-violation-list" style="display:flex;flex-direction:column;gap:1.15rem;">
                ${types.map(t => `
                    <div class="violation-stat-row">
                        <div style="display:flex;justify-content:space-between;margin-bottom:0.25rem;">
                            <span style="font-size:0.9rem;">${t.name}</span>
                            <strong style="color:${t.color}">${t.count}</strong>
                        </div>
                        <div style="height:8px;background:var(--background-color);border-radius:4px;overflow:hidden;">
                            <div style="
                                height:100%;
                                width:${totalViolations ? (t.count / totalViolations * 100) : 0}%;
                                background:${t.color};
                                transition:width 0.5s ease;">
                            </div>
                        </div>
                    </div>
                `).join("")}
            </div>
        `;
    },

    /* ================= RECENT ================= */

    renderRecentViolations(violations) {
        const container = document.getElementById("recent-violations");
        if (!container) return;

        if (!violations.length) {
            container.innerHTML = `
                <div class="alert alert-success" style="padding:1.5rem;text-align:center;">
                    <i class="fas fa-check-circle" style="font-size:2rem;display:block;margin-bottom:0.5rem;"></i>
                    No recent violations detected
                </div>`;
            return;
        }

        container.innerHTML = `
            <div class="recent-list" style="display:flex; flex-direction:column; gap:0.65rem;">
                ${violations.map(v => `
                    <div class="recent-item" 
                         onclick="if (typeof ReportsPage !== 'undefined') ReportsPage.openReport('${v.report_id}'); else window.open(typeof API !== 'undefined' && API.getReportNavigationUrl ? API.getReportNavigationUrl('${v.report_id}') : '/report/${v.report_id}', '_blank');"
                         style="
                            display:flex; 
                            justify-content:space-between; 
                            align-items:center;
                            padding:0.9rem 1rem;
                            background:var(--background-color);
                            border-radius:8px;
                            cursor:pointer;
                            border-left: 4px solid ${v.severity === 'HIGH' ? 'var(--error-color)' : 'var(--warning-color)'};
                            transition: background 0.18s;
                            min-width: 0;
                         "
                         onmouseover="this.style.background='var(--card-border)'"
                         onmouseout="this.style.background='var(--background-color)'">
                        
                        <div>
                            <h5 style="margin:0 0 0.25rem 0;color:var(--text-color);">#${v.report_id}</h5>
                            <span style="font-size:0.8rem;color:#7f8c8d;">
                                ${typeof TimezoneManager !== 'undefined' ? TimezoneManager.formatDateTime(v.timestamp) : new Date(v.timestamp).toLocaleString()}
                            </span>
                        </div>
                        
                        <div style="text-align:right;">
                            <span class="badge ${v.severity === 'HIGH' ? 'badge-danger' : 'badge-warning'}" 
                                  style="font-size:0.75rem;padding:0.25rem 0.5rem;">
                                ${v.severity || 'MEDIUM'}
                            </span>
                        </div>
                    </div>
                `).join("")}
            </div>
        `;
    }
};
