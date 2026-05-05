// Notification System for CASM PPE Monitor
// ==========================================
// Toast notifications for violation detection and report generation
// Enhanced: Bottom-right positioning, grouped notifications, max 3 visible

const NotificationManager = {
    container: null,
    notifications: [],
    maxVisible: 3,  // Maximum notifications shown at once (desktop)
    groupedCount: 0,  // Count of hidden notifications
    recentByKey: new Map(),

    // Startup-quiet window: for the first N ms after page load, route
    // info/success straight to the bell history with no on-screen toast.
    // Avoids the "bombarded on first enter" feeling on mobile, where
    // provisioning/network/policy banners all fire within the first second.
    QUIET_STARTUP_MS: 2500,
    _bootTs: Date.now(),

    isMobileViewport() {
        try {
            return window.matchMedia('(max-width: 640px)').matches;
        } catch (_) {
            return (window.innerWidth || 0) <= 640;
        }
    },

    inStartupQuietWindow() {
        return (Date.now() - this._bootTs) < this.QUIET_STARTUP_MS;
    },

    // Decide whether a toast should pop on screen, or be silently logged
    // to the bell. Returns true = silent (history only).
    shouldRouteToHistoryOnly(type, options = {}) {
        if (options.forceToast === true) return false;
        const isMobile = this.isMobileViewport();
        const quiet = this.inStartupQuietWindow();
        const lowValue = (type === 'info' || type === 'success' || type === 'report');
        // Mobile + low-value -> always silent (bell only).
        if (isMobile && lowValue) return true;
        // Any platform + still inside startup quiet window + low-value -> silent.
        if (quiet && lowValue) return true;
        return false;
    },

    // ---- History center (S3) ----
    HISTORY_STORAGE_KEY: 'ppe.notifications.history.v1',
    HISTORY_MAX: 200,
    history: [],
    unreadCount: 0,
    historyListeners: [],

    loadHistory() {
        try {
            const raw = localStorage.getItem(this.HISTORY_STORAGE_KEY);
            if (!raw) {
                this.history = [];
                this.unreadCount = 0;
                return;
            }
            const parsed = JSON.parse(raw);
            if (parsed && Array.isArray(parsed.entries)) {
                this.history = parsed.entries.slice(-this.HISTORY_MAX);
                this.unreadCount = this.history.reduce((acc, e) => acc + (e.read ? 0 : 1), 0);
            }
        } catch (e) {
            console.warn('Failed to load notification history:', e);
            this.history = [];
            this.unreadCount = 0;
        }
    },

    persistHistory() {
        try {
            localStorage.setItem(
                this.HISTORY_STORAGE_KEY,
                JSON.stringify({ entries: this.history.slice(-this.HISTORY_MAX) })
            );
        } catch (e) {
            // Storage quota exceeded; trim and try once more
            this.history = this.history.slice(-Math.floor(this.HISTORY_MAX / 2));
            try {
                localStorage.setItem(
                    this.HISTORY_STORAGE_KEY,
                    JSON.stringify({ entries: this.history })
                );
            } catch (_) { /* give up */ }
        }
    },

    addToHistory(entry) {
        const record = {
            id: entry.id,
            ts: Date.now(),
            type: entry.type || 'info',
            category: entry.category || this.inferCategory(entry.type, entry.title, entry.message),
            priority: entry.priority || this.inferPriority(entry.type),
            title: entry.title || '',
            message: entry.message || '',
            read: false
        };
        this.history.push(record);
        if (this.history.length > this.HISTORY_MAX) {
            this.history = this.history.slice(-this.HISTORY_MAX);
        }
        this.unreadCount += 1;
        this.persistHistory();
        this.updateBellBadge();
        this.notifyHistoryListeners();
    },

    inferCategory(type, title, message) {
        const t = String(title || '').toLowerCase();
        const m = String(message || '').toLowerCase();
        if (type === 'violation' || t.includes('violation') || m.includes('violation')) return 'detection';
        if (type === 'report' || t.includes('report') || m.includes('report')) return 'report';
        if (m.includes('sync') || m.includes('cloud') || m.includes('supabase')) return 'sync';
        if (m.includes('admin') || m.includes('approval') || m.includes('provision')) return 'admin';
        if (type === 'error' || m.includes('failed') || m.includes('error')) return 'system';
        return 'system';
    },

    inferPriority(type) {
        if (type === 'error' || type === 'violation') return 'high';
        if (type === 'warning') return 'medium';
        return 'low';
    },

    notifyHistoryListeners() {
        this.historyListeners.forEach((fn) => {
            try { fn(this.history, this.unreadCount); } catch (_) { /* swallow */ }
        });
    },

    markAllRead() {
        this.history.forEach((e) => { e.read = true; });
        this.unreadCount = 0;
        this.persistHistory();
        this.updateBellBadge();
        this.notifyHistoryListeners();
    },

    clearHistory() {
        this.history = [];
        this.unreadCount = 0;
        this.persistHistory();
        this.updateBellBadge();
        this.notifyHistoryListeners();
    },

    updateBellBadge() {
        const badges = [
            document.getElementById('notif-bell-badge'),
            document.getElementById('mobileTopbarBellBadge')
        ].filter(Boolean);
        const visibleText = this.unreadCount > 99 ? '99+' : String(this.unreadCount);
        badges.forEach((badge) => {
            if (this.unreadCount > 0) {
                badge.textContent = visibleText;
                badge.style.display = 'inline-flex';
            } else {
                badge.style.display = 'none';
            }
        });
    },

    openHistoryCenter() {
        this.ensureHistoryModal();
        const modal = document.getElementById('notif-history-modal');
        if (!modal) return;
        modal.style.display = 'flex';
        this.renderHistoryList();
    },

    closeHistoryCenter() {
        const modal = document.getElementById('notif-history-modal');
        if (modal) modal.style.display = 'none';
    },

    ensureHistoryModal() {
        if (document.getElementById('notif-history-modal')) return;
        const overlay = document.createElement('div');
        overlay.id = 'notif-history-modal';
        overlay.style.cssText = `
            position: fixed; inset: 0; background: rgba(15,23,42,0.55);
            z-index: 10050; display: none; align-items: center; justify-content: center;
            padding: 1rem;
        `;
        overlay.innerHTML = `
            <div style="background:#fff; border-radius:14px; max-width:560px; width:100%;
                        max-height:78vh; display:flex; flex-direction:column; overflow:hidden;
                        box-shadow:0 20px 60px rgba(0,0,0,.25);">
                <div style="display:flex; align-items:center; justify-content:space-between;
                            padding:1rem 1.1rem; border-bottom:1px solid #e5e7eb; gap:.5rem;">
                    <div style="display:flex; align-items:center; gap:.55rem;">
                        <i class="fas fa-bell" style="color:#3498db;"></i>
                        <strong style="font-size:1rem; color:#0f172a;">Notification History</strong>
                    </div>
                    <div style="display:flex; gap:.4rem;">
                        <button id="notif-history-mark-read" class="btn btn-secondary" style="padding:.35rem .7rem; font-size:.78rem;">Mark all read</button>
                        <button id="notif-history-clear" class="btn btn-secondary" style="padding:.35rem .7rem; font-size:.78rem;">Clear</button>
                        <button id="notif-history-close" class="btn btn-secondary" style="padding:.35rem .7rem; font-size:.78rem;" aria-label="Close">&times;</button>
                    </div>
                </div>
                <div id="notif-history-filters" style="display:flex; flex-wrap:wrap; gap:.4rem; padding:.6rem 1.1rem;
                            border-bottom:1px solid #f1f5f9; background:#f8fafc;">
                    ${['all','detection','report','sync','admin','system'].map((c) => `
                        <button class="notif-cat-chip" data-cat="${c}" style="
                            padding:.25rem .65rem; border-radius:999px; border:1px solid #cbd5e1;
                            background:#fff; cursor:pointer; font-size:.72rem; text-transform:uppercase;
                            letter-spacing:.04em; color:#475569;">${c}</button>
                    `).join('')}
                </div>
                <div id="notif-history-list" style="overflow-y:auto; flex:1; padding:.4rem 0;"></div>
            </div>
        `;
        document.body.appendChild(overlay);

        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) this.closeHistoryCenter();
        });
        document.getElementById('notif-history-close').addEventListener('click', () => this.closeHistoryCenter());
        document.getElementById('notif-history-mark-read').addEventListener('click', () => {
            this.markAllRead();
            this.renderHistoryList();
        });
        document.getElementById('notif-history-clear').addEventListener('click', () => {
            if (confirm('Clear all notification history?')) {
                this.clearHistory();
                this.renderHistoryList();
            }
        });
        overlay.querySelectorAll('.notif-cat-chip').forEach((chip) => {
            chip.addEventListener('click', () => {
                overlay.querySelectorAll('.notif-cat-chip').forEach((c) => {
                    c.style.background = '#fff';
                    c.style.color = '#475569';
                    c.style.borderColor = '#cbd5e1';
                });
                chip.style.background = '#0f172a';
                chip.style.color = '#fff';
                chip.style.borderColor = '#0f172a';
                this._historyCategoryFilter = chip.dataset.cat;
                this.renderHistoryList();
            });
        });

        // Default selection: all
        const allChip = overlay.querySelector('.notif-cat-chip[data-cat="all"]');
        if (allChip) {
            allChip.style.background = '#0f172a';
            allChip.style.color = '#fff';
            allChip.style.borderColor = '#0f172a';
        }
        this._historyCategoryFilter = 'all';
    },

    renderHistoryList() {
        const list = document.getElementById('notif-history-list');
        if (!list) return;

        const cat = this._historyCategoryFilter || 'all';
        const filtered = (cat === 'all' ? this.history : this.history.filter((e) => e.category === cat));
        const ordered = filtered.slice().reverse();

        if (!ordered.length) {
            list.innerHTML = `
                <div style="text-align:center; color:#94a3b8; padding:2rem 1rem;">
                    <i class="fas fa-inbox" style="font-size:1.6rem; margin-bottom:.5rem;"></i>
                    <div>No notifications in history.</div>
                </div>`;
            return;
        }

        const colors = { high: '#e74c3c', medium: '#f39c12', low: '#3498db' };
        const catIcons = {
            detection: 'fa-hard-hat', report: 'fa-file-alt', sync: 'fa-cloud',
            admin: 'fa-user-shield', system: 'fa-cog'
        };

        list.innerHTML = ordered.map((e) => {
            const ts = new Date(e.ts);
            const tsStr = ts.toLocaleString();
            const unreadDot = e.read ? '' : `<span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#3498db; margin-right:.4rem;"></span>`;
            return `
                <div style="display:flex; align-items:flex-start; gap:.65rem; padding:.65rem 1.1rem; border-bottom:1px solid #f1f5f9;">
                    <div style="flex-shrink:0; width:32px; height:32px; border-radius:8px; background:${colors[e.priority] || colors.low}1a; color:${colors[e.priority] || colors.low}; display:flex; align-items:center; justify-content:center;">
                        <i class="fas ${catIcons[e.category] || 'fa-bell'}"></i>
                    </div>
                    <div style="flex:1; min-width:0;">
                        <div style="font-size:.82rem; color:#0f172a; font-weight:600;">
                            ${unreadDot}${e.title || e.category || 'Notification'}
                        </div>
                        <div style="font-size:.78rem; color:#475569; margin-top:.15rem; word-wrap:break-word;">${e.message}</div>
                        <div style="font-size:.68rem; color:#94a3b8; margin-top:.3rem; display:flex; gap:.6rem;">
                            <span><i class="far fa-clock"></i> ${tsStr}</span>
                            <span style="text-transform:uppercase; letter-spacing:.04em;">${e.category} &middot; ${e.priority}</span>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    },

    init() {
        if (this.container) return;

        // Create notification container.
        // - Desktop: bottom-right floating column.
        // - Mobile (<=640px): full-width bar pinned to the TOP of the
        //   viewport, just under the mobile app-bar (~56px) so toasts
        //   slide in from above instead of covering the bottom nav.
        this.container = document.createElement('div');
        this.container.id = 'notification-container';
        const isMobile = this.isMobileViewport();
        this.container.style.cssText = isMobile
            ? `
                position: fixed;
                top: calc(56px + env(safe-area-inset-top, 0px) + 8px);
                left: 12px;
                right: 12px;
                z-index: 10000;
                display: flex;
                flex-direction: column;
                gap: 6px;
                max-width: 100%;
                max-height: 60vh;
                pointer-events: none;
            `
            : `
                position: fixed;
                bottom: 20px;
                right: 20px;
                z-index: 10000;
                display: flex;
                flex-direction: column-reverse;
                gap: 10px;
                max-width: 380px;
                max-height: calc(100vh - 100px);
                pointer-events: none;
            `;
        // Mobile: only one toast on screen at a time; rest collapse to bell.
        if (isMobile) {
            this.maxVisible = 1;
        }
        document.body.appendChild(this.container);

        // Create summary badge for grouped notifications
        this.summaryBadge = document.createElement('div');
        this.summaryBadge.id = 'notification-summary';
        this.summaryBadge.style.cssText = `
            display: none;
            background: linear-gradient(135deg, #3498db, #2980b9);
            color: white;
            padding: 12px 16px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            pointer-events: auto;
            text-align: center;
        `;
        this.summaryBadge.innerHTML = `
            <i class="fas fa-bell"></i>
            <span id="grouped-count">0</span> more notifications
            <span style="display: block; font-size: 12px; opacity: 0.8; margin-top: 4px;">
                Click to dismiss all
            </span>
        `;
        this.summaryBadge.addEventListener('click', () => this.dismissAll());
        this.container.appendChild(this.summaryBadge);

        // History bell — preferred mount: dedicated host in the top status
        // bar (#notifBellHost). That avoids overlapping the sidebar voice
        // controls at the bottom-left. Fallback: float at bottom-left, but
        // raised above the voice buttons so it never covers them.
        this.loadHistory();
        const statusbarHost = document.getElementById('notifBellHost');
        if (statusbarHost && !statusbarHost.dataset.notifBound) {
            statusbarHost.dataset.notifBound = '1';
            // The host already contains <i.fa-bell> and <span#notif-bell-badge>
            // from index.html — just wire the click handler.
            statusbarHost.addEventListener('click', () => this.openHistoryCenter());
        }
        // Mobile topbar bell — same handler, separate badge element so the
        // count stays in sync regardless of which bell is currently visible.
        const topbarBell = document.getElementById('mobileTopbarBellBtn');
        if (topbarBell && !topbarBell.dataset.notifBound) {
            topbarBell.dataset.notifBound = '1';
            topbarBell.addEventListener('click', () => this.openHistoryCenter());
        }
        if (!statusbarHost && !topbarBell
            && !document.getElementById('notif-bell-btn')) {
            const bell = document.createElement('button');
            bell.id = 'notif-bell-btn';
            bell.setAttribute('aria-label', 'Notification history');
            bell.title = 'Notification history';
            bell.style.cssText = `
                position: fixed;
                bottom: 20px;
                left: 20px;
                z-index: 9999;
                width: 44px; height: 44px; border-radius: 50%;
                border: none; cursor: pointer;
                background: #d17508; color: #fff;
                box-shadow: 0 6px 18px rgba(209,117,8,.35);
                display: flex; align-items: center; justify-content: center;
                font-size: 16px;
            `;
            bell.innerHTML = `
                <i class="fas fa-bell"></i>
                <span id="notif-bell-badge" style="
                    position:absolute; top:-4px; right:-4px;
                    background:#e74c3c; color:#fff; border-radius:999px;
                    min-width:18px; height:18px; padding:0 5px;
                    font-size:10px; font-weight:700;
                    display:none; align-items:center; justify-content:center;
                    line-height:1; box-shadow:0 0 0 2px #fff;
                "></span>
            `;
            bell.addEventListener('click', () => this.openHistoryCenter());
            document.body.appendChild(bell);
        }
        this.updateBellBadge();
    },

    updateSummaryBadge() {
        const visibleCount = this.notifications.length;
        const hiddenCount = Math.max(0, visibleCount - this.maxVisible);

        if (hiddenCount > 0) {
            this.summaryBadge.style.display = 'block';
            document.getElementById('grouped-count').textContent = hiddenCount;
        } else {
            this.summaryBadge.style.display = 'none';
        }

        // Hide older notifications when over limit
        this.notifications.forEach((notif, index) => {
            if (index < visibleCount - this.maxVisible) {
                notif.element.style.display = 'none';
            } else {
                notif.element.style.display = 'flex';
            }
        });
    },

    pruneRecentKeys(nowTs = Date.now()) {
        if (!(this.recentByKey instanceof Map)) return;
        this.recentByKey.forEach((entry, key) => {
            const ts = Number((entry && entry.ts) || 0);
            const ttlMs = Number((entry && entry.ttlMs) || 0);
            if (!Number.isFinite(ts) || !Number.isFinite(ttlMs) || ttlMs <= 0 || (nowTs - ts) > ttlMs) {
                this.recentByKey.delete(key);
            }
        });
    },

    show(message, type = 'info', duration = 5000, options = {}) {
        this.init();

        const nowTs = Date.now();
        this.pruneRecentKeys(nowTs);

        const dedupeEnabled = options.dedupe !== false;
        const dedupeKey = dedupeEnabled
            ? String(options.dedupeKey || `${type}|${options.title || ''}|${message}`).trim()
            : '';
        const requestedDedupeTtlMs = Number(options.dedupeTtlMs);
        const dedupeTtlMs = Number.isFinite(requestedDedupeTtlMs)
            ? Math.max(250, Math.min(Math.floor(requestedDedupeTtlMs), 120000))
            : 5000;

        if (dedupeKey) {
            const existing = this.recentByKey.get(dedupeKey);
            if (existing && Number.isFinite(Number(existing.ts)) && (nowTs - Number(existing.ts)) <= dedupeTtlMs) {
                return existing.id;
            }
        }

        // Priority + startup gating: route low-value notifications straight
        // to the bell (history) without rendering an on-screen toast. The
        // user can still review them via the bell badge.
        if (this.shouldRouteToHistoryOnly(type, options) && options.persistHistory !== false) {
            const silentId = nowTs + Math.random();
            this.addToHistory({
                id: silentId,
                type,
                title: options.title || '',
                message,
                category: options.category,
                priority: options.priority
            });
            if (dedupeKey) {
                this.recentByKey.set(dedupeKey, { id: silentId, ts: nowTs, ttlMs: dedupeTtlMs });
            }
            return silentId;
        }

        const id = nowTs + Math.random();

        const notification = document.createElement('div');
        notification.id = `notif-${id}`;
        notification.className = `notification notification-${type}`;

        const icons = {
            'success': 'fa-check-circle',
            'error': 'fa-exclamation-circle',
            'warning': 'fa-exclamation-triangle',
            'info': 'fa-info-circle',
            'violation': 'fa-hard-hat',
            'report': 'fa-file-alt'
        };

        const colors = {
            'success': '#2ecc71',
            'error': '#e74c3c',
            'warning': '#f39c12',
            'info': '#3498db',
            'violation': '#e74c3c',
            'report': '#3498db'
        };

        const compact = this.isMobileViewport();
        notification.style.cssText = `
            background: white;
            border-left: ${compact ? '3px' : '4px'} solid ${colors[type] || colors.info};
            border-radius: ${compact ? '6px' : '8px'};
            padding: ${compact ? '8px 10px' : '14px'};
            box-shadow: 0 ${compact ? '2px 6px' : '4px 12px'} rgba(0,0,0,0.15);
            display: flex;
            align-items: center;
            gap: ${compact ? '8px' : '10px'};
            min-width: ${compact ? '0' : '280px'};
            max-width: 100%;
            animation: slideInUp 0.3s ease-out;
            cursor: pointer;
            pointer-events: auto;
            font-size: ${compact ? '13px' : '14px'};
        `;

        // Simplified content for cleaner look. On mobile we collapse the
        // toast to a single-row bar: smaller icon, no separate title row,
        // action rendered as an inline text link instead of a big button,
        // so the whole thing stays under ~50px tall.
        const titleHtml = options.title && !compact
            ? `<div style="font-weight: 600; margin-bottom: 2px; color: #2c3e50; font-size: 13px;">${options.title}</div>`
            : '';

        // Combine title into message body when compact, so a single-line
        // toast can still convey the type ("Failed Reports — 43 reports
        // failed to generate").
        const compactMessage = (compact && options.title)
            ? `<span style="font-weight:600;color:#2c3e50;">${options.title}</span> <span style="opacity:.85;">${message}</span>`
            : message;

        const actionHtml = options.action
            ? (compact
                ? `<button class="notification-action-btn" style="
                        margin-left: 8px;
                        padding: 0;
                        background: none;
                        color: ${colors[type]};
                        border: none;
                        cursor: pointer;
                        font-size: 12px;
                        font-weight: 600;
                        white-space: nowrap;
                        flex-shrink: 0;
                        text-decoration: underline;
                    ">${options.action.text}</button>`
                : `<button class="notification-action-btn" style="
                        margin-top: 8px;
                        padding: 5px 10px;
                        background: ${colors[type]};
                        color: white;
                        border: none;
                        border-radius: 4px;
                        cursor: pointer;
                        font-size: 12px;
                    ">${options.action.text}</button>`)
            : '';

        if (compact) {
            // Single-row layout: icon — message+action — close.
            notification.innerHTML = `
                <div style="flex-shrink: 0; font-size: 14px; color: ${colors[type]}; line-height: 1;">
                    <i class="fas ${icons[type] || icons.info}"></i>
                </div>
                <div style="flex: 1; min-width: 0; color: #5d6d7e; font-size: 13px; line-height: 1.35; display: flex; align-items: center; gap: 6px; flex-wrap: wrap;">
                    <span style="flex: 1; min-width: 0; word-wrap: break-word;">${compactMessage}</span>
                    ${actionHtml}
                </div>
                <button class="notification-close-btn" aria-label="Dismiss" style="
                    background: none;
                    border: none;
                    color: #bdc3c7;
                    cursor: pointer;
                    font-size: 13px;
                    flex-shrink: 0;
                    padding: 2px 4px;
                    line-height: 1;
                ">
                    <i class="fas fa-times"></i>
                </button>
            `;
        } else {
            notification.innerHTML = `
                <div style="flex-shrink: 0; font-size: 20px; color: ${colors[type]};">
                    <i class="fas ${icons[type] || icons.info}"></i>
                </div>
                <div style="flex: 1; min-width: 0;">
                    ${titleHtml}
                    <div style="color: #7f8c8d; font-size: 13px; word-wrap: break-word; line-height: 1.4;">${message}</div>
                    ${actionHtml}
                </div>
                <button class="notification-close-btn" style="
                    background: none;
                    border: none;
                    color: #bdc3c7;
                    cursor: pointer;
                    font-size: 14px;
                    flex-shrink: 0;
                    padding: 0;
                ">
                    <i class="fas fa-times"></i>
                </button>
            `;
        }

        const closeBtn = notification.querySelector('.notification-close-btn');
        if (closeBtn) {
            closeBtn.addEventListener('click', (event) => {
                event.stopPropagation();
                this.dismiss(id);
            });
        }

        const actionBtn = notification.querySelector('.notification-action-btn');
        if (actionBtn && options.action) {
            actionBtn.addEventListener('click', (event) => {
                event.stopPropagation();
                try {
                    if (typeof options.action.onClickFn === 'function') {
                        options.action.onClickFn();
                    } else if (typeof options.action.onClick === 'function') {
                        options.action.onClick();
                    } else if (typeof options.action.onClick === 'string' && options.action.onClick.trim()) {
                        const fn = new Function(options.action.onClick);
                        fn();
                    }
                } catch (err) {
                    console.error('Notification action failed:', err);
                }
            });
        }

        // Click anywhere to dismiss
        notification.addEventListener('click', (e) => {
            if (!e.target.closest('button')) {
                this.dismiss(id);
            }
        });

        this.container.insertBefore(notification, this.summaryBadge);
        this.notifications.push({ id, element: notification, type, timestamp: Date.now() });
        if (dedupeKey) {
            this.recentByKey.set(dedupeKey, {
                id,
                ts: nowTs,
                ttlMs: dedupeTtlMs
            });
        }

        // Persist to history center (S3) — skip very low-value transients
        if (options.persistHistory !== false) {
            try {
                this.addToHistory({
                    id,
                    type,
                    title: options.title || '',
                    message,
                    category: options.category,
                    priority: options.priority
                });
            } catch (e) {
                console.warn('Failed to add notification to history:', e);
            }
        }

        this.updateSummaryBadge();

        // Auto dismiss
        if (duration > 0) {
            setTimeout(() => this.dismiss(id), duration);
        }

        return id;
    },

    dismiss(id) {
        const index = this.notifications.findIndex(n => n.id == id);
        if (index !== -1) {
            const notif = this.notifications[index];
            if (notif.isDismissing) {
                return;
            }

            notif.isDismissing = true;
            notif.element.style.animation = 'slideOutDown 0.3s ease-out';
            setTimeout(() => {
                notif.element.remove();
                const currentIndex = this.notifications.findIndex(n => n.id == id);
                if (currentIndex !== -1) {
                    this.notifications.splice(currentIndex, 1);
                }
                this.updateSummaryBadge();
            }, 300);
        }
    },

    dismissAll() {
        const ids = this.notifications.map(n => n.id);
        ids.forEach(id => this.dismiss(id));
    },

    // Convenience methods. Durations tuned shorter than v1 — info/success
    // 3s (was 4s), errors 5s (was 6s), warnings 4.5s (was 5s) to feel less
    // intrusive on mobile. Long-form notices belong in the bell history.
    success(message, options = {}) {
        return this.show(message, 'success', options.duration || 3000, options);
    },

    error(message, options = {}) {
        return this.show(message, 'error', options.duration || 5000, options);
    },

    warning(message, options = {}) {
        return this.show(message, 'warning', options.duration || 4500, options);
    },

    info(message, options = {}) {
        return this.show(message, 'info', options.duration || 3000, options);
    },

    violation(message, reportId, options = {}) {
        return this.show(message, 'violation', 8000, {
            title: '🚨 Violation Detected',
            action: {
                text: 'View Reports',
                onClick: `Router.navigate('reports')`
            },
            dedupeKey: reportId ? `violation:${reportId}` : undefined,
            dedupeTtlMs: 12000,
            ...options
        });
    },

    reportGenerating(reportId, options = {}) {
        const defaultAction = {
            text: 'View Progress',
            onClickFn: () => {
                try {
                    if (typeof ReportsPage !== 'undefined' && typeof ReportsPage.focusReport === 'function') {
                        ReportsPage.focusReport(reportId, { openModal: true });
                        return;
                    }
                } catch (e) {
                    console.warn('ReportsPage focusReport unavailable:', e);
                }
                Router.navigate('reports');
            }
        };

        return this.show(
            'Generating safety report...',
            'report',
            8000,
            {
                title: '📝 Processing',
                action: defaultAction,
                dedupeKey: reportId ? `report-generating:${reportId}` : 'report-generating:unknown',
                dedupeTtlMs: reportId ? 45000 : 8000,
                ...options
            }
        );
    },

    reportReady(reportId, options = {}) {
        return this.show(
            'Report ready for review',
            'success',
            6000,
            {
                title: '✅ Complete',
                action: {
                    text: 'Open',
                    onClickFn: () => {
                        const url = (typeof API !== 'undefined' && typeof API.getReportUrl === 'function')
                            ? API.getReportUrl(reportId)
                            : `${API_CONFIG.BASE_URL}/report/${reportId}`;
                        window.open(url, '_blank');
                    }
                },
                dedupeKey: reportId ? `report-ready:${reportId}` : 'report-ready:unknown',
                dedupeTtlMs: 60000,
                ...options
            }
        );
    }
};

// Add CSS animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInUp {
        from {
            transform: translateY(100px);
            opacity: 0;
        }
        to {
            transform: translateY(0);
            opacity: 1;
        }
    }

    @keyframes slideOutDown {
        from {
            transform: translateY(0);
            opacity: 1;
        }
        to {
            transform: translateY(100px);
            opacity: 0;
        }
    }

    /* Mobile: container is anchored to the TOP of the viewport, so toasts
       should slide DOWN into view rather than up from the bottom. */
    @media (max-width: 640px) {
        #notification-container .notification {
            animation: slideInDown 0.28s ease-out !important;
        }
    }

    @keyframes slideInDown {
        from {
            transform: translateY(-120%);
            opacity: 0;
        }
        to {
            transform: translateY(0);
            opacity: 1;
        }
    }

    .notification:hover {
        box-shadow: 0 6px 16px rgba(0,0,0,0.2);
        transform: translateY(-2px);
        transition: all 0.2s ease;
    }
    
    #notification-summary:hover {
        background: linear-gradient(135deg, #2980b9, #1a5276);
        transform: scale(1.02);
        transition: all 0.2s ease;
    }
`;
document.head.appendChild(style);

// Initialize on load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => NotificationManager.init());
} else {
    NotificationManager.init();
}

