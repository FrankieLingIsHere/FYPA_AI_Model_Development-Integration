const STARTUP_STATUS_ENDPOINT = '/api/system/startup-status';
const STARTUP_POLL_INTERVAL_MS = 1200;
let appBootstrapped = false;
let networkIndicatorBootstrapped = false;
let pwaBootstrapped = false;
let adaptivePipelineBootstrapped = false;

// Main Application Entry Point
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 PPE Safety Monitor - Initializing...');
    ensurePwaDocumentMarkers();
    initializeNetworkIndicator();
    registerPwaSupport();
    initializeWithStartupGate();
});

function ensurePwaDocumentMarkers() {
    const head = document.head;
    if (!head) return;

    const hasManifest = !!head.querySelector('link[rel="manifest"]');
    if (!hasManifest) {
        const manifest = document.createElement('link');
        manifest.setAttribute('rel', 'manifest');
        manifest.setAttribute('href', '/manifest.json');
        head.appendChild(manifest);
    }

    const hasThemeColor = !!head.querySelector('meta[name="theme-color"]');
    if (!hasThemeColor) {
        const theme = document.createElement('meta');
        theme.setAttribute('name', 'theme-color');
        theme.setAttribute('content', '#e09c2e');
        head.appendChild(theme);
    }
}

async function initializeWithStartupGate() {
    const body = document.body;
    const retryButton = document.getElementById('startupRetryBtn');

    if (retryButton && !retryButton.dataset.bound) {
        retryButton.dataset.bound = 'true';
        retryButton.addEventListener('click', async () => {
            retryButton.hidden = true;
            await initializeWithStartupGate();
        });
    }

    body.classList.add('startup-loading');
    updateStartupUi({
        progress: 0,
        current_step: 'Contacting backend startup service...'
    });

    try {
        await waitForStartupReady();
    } catch (error) {
        showStartupError(error.message || 'Startup validation failed.');
        return;
    }

    if (appBootstrapped) {
        body.classList.remove('startup-loading');
        return;
    }

    setupResponsiveMobileUX();

    Router.register('home', HomePage);
    Router.register('live', LivePage);
    Router.register('reports', ReportsPage);
    Router.register('analytics', AnalyticsPage);
    Router.register('about', AboutPage);
    Router.init();

    if (typeof TimezoneManager !== 'undefined') {
        TimezoneManager.initSelector('timezone-selector');
        console.log('Timezone set to:', TimezoneManager.getTimezoneLabel());
    } else if (typeof TimezoneUtils !== 'undefined' && typeof TimezoneUtils.updateAllTimestamps === 'function') {
        TimezoneUtils.updateAllTimestamps();
        console.log('Timezone utility initialized.');
    }

    if (typeof RealtimeSync !== 'undefined' && RealtimeSync.start) {
        RealtimeSync.start();
    }

    initializeAdaptivePipelineModeManager();

    appBootstrapped = true;
    body.classList.remove('startup-loading');
    console.log('✅ Application ready!');
}

async function waitForStartupReady() {
    const timeoutAt = Date.now() + (10 * 60 * 1000);
    let consecutiveFetchFailures = 0;

    while (Date.now() < timeoutAt) {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}${STARTUP_STATUS_ENDPOINT}`, { cache: 'no-store' });
            const payload = await response.json();
            consecutiveFetchFailures = 0;
            updateStartupUi(payload || {});

            const failedCheck = findFailedStartupCheck(payload);
            if (failedCheck) {
                const detail = failedCheck.detail ? `: ${failedCheck.detail}` : '';
                throw new Error(`${failedCheck.label || 'Startup check failed'}${detail}`);
            }

            if (payload && payload.ready) {
                updateStartupUi({
                    ...payload,
                    progress: 100,
                    current_step: 'Startup checks completed. Launching interface...'
                });
                await sleep(320);
                return;
            }

            if (response.status >= 500 || (payload && payload.status === 'error')) {
                const failureReason = (payload && payload.error_message) || 'Startup setup failed on backend.';
                throw new Error(failureReason);
            }
        } catch (error) {
            if (error && error.message && /startup check failed|startup setup failed|yolo|model path|pipeline|supabase/i.test(error.message)) {
                throw error;
            }
            consecutiveFetchFailures += 1;
            updateStartupUi({
                progress: 5,
                current_step: 'Waiting for backend startup checks to respond...'
            });

            if (consecutiveFetchFailures >= 8) {
                throw new Error(
                    'Unable to reach backend startup API. Check Railway backend URL and CORS ALLOWED_ORIGINS settings.'
                );
            }
        }

        await sleep(STARTUP_POLL_INTERVAL_MS);
    }

    throw new Error('Startup timed out. Please verify model files and Supabase connectivity, then retry.');
}

function findFailedStartupCheck(payload) {
    if (!payload || !payload.checks || typeof payload.checks !== 'object') {
        return null;
    }

    const checks = Object.values(payload.checks);
    const failed = checks.find((item) => item && item.status === 'error');
    return failed || null;
}

function updateStartupUi(payload) {
    const currentStep = document.getElementById('startupCurrentStep');
    const progressFill = document.getElementById('startupProgressFill');
    const progressPercent = document.getElementById('startupProgressPercent');
    const progressBar = document.querySelector('.startup-loader-progress');
    const checklist = document.getElementById('startupChecklist');
    const errorBox = document.getElementById('startupError');

    const progress = Math.max(0, Math.min(100, Number(payload.progress || 0)));
    const step = payload.current_step || 'Preparing startup checks...';

    if (currentStep) currentStep.textContent = step;
    if (progressFill) progressFill.style.width = `${progress}%`;
    if (progressPercent) progressPercent.textContent = `${progress}%`;
    if (progressBar) progressBar.setAttribute('aria-valuenow', `${progress}`);

    if (errorBox) {
        errorBox.hidden = true;
        errorBox.textContent = '';
    }

    if (checklist && payload.checks) {
        const items = Object.values(payload.checks)
            .map((item) => {
                const state = item.status || 'pending';
                const label = item.label || 'Unknown check';
                const detail = item.detail ? ` - ${item.detail}` : '';
                return `<li class="${state}">${label}: ${state.toUpperCase()}${detail}</li>`;
            })
            .join('');
        checklist.innerHTML = items;
    }
}

function showStartupError(message) {
    const errorBox = document.getElementById('startupError');
    const retryButton = document.getElementById('startupRetryBtn');
    if (errorBox) {
        errorBox.textContent = `Startup blocked: ${message}`;
        errorBox.hidden = false;
    }
    if (retryButton) {
        retryButton.hidden = false;
    }
}

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function registerPwaSupport() {
    if (pwaBootstrapped) return;
    pwaBootstrapped = true;

    if (!('serviceWorker' in navigator)) {
        return;
    }

    window.addEventListener('load', async () => {
        try {
            const registration = await navigator.serviceWorker.register('/service-worker.js', { scope: '/' });
            console.log('✅ Service worker registered:', registration.scope);
        } catch (error) {
            console.warn('⚠️ Service worker registration failed:', error);
        }
    }, { once: true });
}

function initializeNetworkIndicator() {
    if (networkIndicatorBootstrapped) return;
    networkIndicatorBootstrapped = true;

    const badge = document.getElementById('networkStatusBadge');
    const label = document.getElementById('networkStatusText');
    if (!badge || !label) return;

    const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    const stateClasses = ['network-strong', 'network-good', 'network-fair', 'network-weak', 'network-offline'];

    const clearStateClasses = () => {
        stateClasses.forEach((cls) => badge.classList.remove(cls));
    };

    const setBadgeState = (stateClass, text, title) => {
        clearStateClasses();
        badge.classList.add(stateClass);
        label.textContent = text;
        badge.title = title;
    };

    const scoreConnection = () => {
        if (!navigator.onLine) {
            return {
                state: 'network-offline',
                text: 'Offline',
                title: 'No internet connection detected. Offline cache mode is active.'
            };
        }

        if (!connection) {
            return {
                state: 'network-good',
                text: 'Online',
                title: 'Online connection detected. Signal details are not available on this browser.'
            };
        }

        const effectiveType = String(connection.effectiveType || '').toLowerCase();
        const downlink = Number(connection.downlink || 0);
        const rtt = Number(connection.rtt || 0);

        let score = 0;
        if (effectiveType === '4g') score += 3;
        else if (effectiveType === '3g') score += 2;
        else if (effectiveType === '2g') score += 1;

        if (downlink >= 10) score += 3;
        else if (downlink >= 5) score += 2;
        else if (downlink >= 1.5) score += 1;

        if (rtt > 0 && rtt < 90) score += 2;
        else if (rtt > 0 && rtt < 220) score += 1;

        const detail = `Type: ${effectiveType || 'n/a'} | Downlink: ${downlink || 'n/a'} Mbps | RTT: ${rtt || 'n/a'} ms`;

        if (score >= 7) {
            return { state: 'network-strong', text: 'Strong', title: `Strong network. ${detail}` };
        }
        if (score >= 5) {
            return { state: 'network-good', text: 'Good', title: `Good network. ${detail}` };
        }
        if (score >= 3) {
            return { state: 'network-fair', text: 'Fair', title: `Moderate network. ${detail}` };
        }
        return { state: 'network-weak', text: 'Weak', title: `Weak network. ${detail}` };
    };

    const refreshNetworkIndicator = () => {
        const next = scoreConnection();
        setBadgeState(next.state, next.text, next.title);
        window.dispatchEvent(new CustomEvent('ppe-network:status', {
            detail: {
                state: next.state,
                text: next.text,
                online: navigator.onLine !== false,
                measuredAt: Date.now()
            }
        }));
    };

    window.addEventListener('online', refreshNetworkIndicator);
    window.addEventListener('offline', refreshNetworkIndicator);
    if (connection && typeof connection.addEventListener === 'function') {
        connection.addEventListener('change', refreshNetworkIndicator);
    }

    refreshNetworkIndicator();
}

function initializeAdaptivePipelineModeManager() {
    if (adaptivePipelineBootstrapped) return;
    adaptivePipelineBootstrapped = true;

    const manager = {
        currentMode: 'unknown',
        switchInFlight: false,
        lastSwitchAttemptAt: 0,
        minSwitchIntervalMs: 90 * 1000,

        notify(message, type = 'info') {
            if (typeof NotificationManager !== 'undefined') {
                if (type === 'success') return NotificationManager.success(message);
                if (type === 'warning') return NotificationManager.warning(message);
                if (type === 'error') return NotificationManager.error(message);
                return NotificationManager.info(message);
            }
            console.log(`[AdaptivePipeline:${type}] ${message}`);
        },

        shouldUseLocal(state) {
            return state === 'network-offline' || state === 'network-weak' || state === 'network-fair';
        },

        canAttemptSwitch() {
            return (Date.now() - this.lastSwitchAttemptAt) >= this.minSwitchIntervalMs;
        },

        async evaluate(networkState) {
            if (this.switchInFlight) return;
            if (!this.canAttemptSwitch()) return;

            if (this.shouldUseLocal(networkState)) {
                if (this.currentMode === 'local') return;
                await this.switchToLocal(`network state ${networkState}`);
                return;
            }

            if (this.currentMode === 'cloud') return;
            await this.switchToCloudAndSync(`network state ${networkState}`);
        },

        async switchToLocal(reason) {
            this.switchInFlight = true;
            this.lastSwitchAttemptAt = Date.now();

            try {
                const options = await API.getReportRecoveryOptions();
                let localReady = !!(options && options.success !== false && options.local && options.local.local_mode_possible);

                if (!localReady) {
                    const prep = await API.prepareLocalMode({
                        autoPull: true,
                        setLocalFirst: true,
                        waitSeconds: 8,
                        pullTimeoutSeconds: 900
                    });
                    localReady = !!(prep && prep.success && prep.after && prep.after.local_mode_possible);
                }

                if (!localReady) {
                    this.notify('Local pipeline is not ready on this host yet; keeping existing routing.', 'warning');
                    return;
                }

                const switchRes = await API.switchPipelineMode('local');
                if (switchRes && switchRes.success === false) {
                    throw new Error(switchRes.error || 'Failed to switch provider routing to local mode');
                }

                await API.executeReportRecovery('local');
                this.currentMode = 'local';
                this.notify(`Pipeline switched to LOCAL mode (${reason}).`, 'success');
            } catch (error) {
                console.warn('Adaptive switch to local failed:', error);
            } finally {
                this.switchInFlight = false;
            }
        },

        async switchToCloudAndSync(reason) {
            this.switchInFlight = true;
            this.lastSwitchAttemptAt = Date.now();

            try {
                const switchRes = await API.switchPipelineMode('cloud');
                if (switchRes && switchRes.success === false) {
                    throw new Error(switchRes.error || 'Failed to switch provider routing to cloud mode');
                }

                const syncRes = await API.syncLocalCacheToSupabase({ limit: 180 });
                if (syncRes && syncRes.success === false) {
                    console.warn('Local-cache reconciliation returned warning:', syncRes.error || syncRes);
                }

                await API.executeReportRecovery('failover');
                this.currentMode = 'cloud';
                this.notify(`Pipeline switched to CLOUD mode and sync queued (${reason}).`, 'info');
            } catch (error) {
                console.warn('Adaptive switch to cloud failed:', error);
            } finally {
                this.switchInFlight = false;
            }
        }
    };

    window.addEventListener('ppe-network:status', (event) => {
        const networkState = event && event.detail ? event.detail.state : 'network-good';
        manager.evaluate(networkState);
    });

    const bootState = !navigator.onLine ? 'network-offline' : 'network-good';
    manager.evaluate(bootState);
}

function setupResponsiveMobileUX() {
    const body = document.body;
    const navToggle = document.getElementById('navToggle');
    const navMoreToggle = document.getElementById('navMoreToggle');
    const navMorePanel = document.getElementById('navMorePanel');
    const overlay = document.getElementById('mobileOrientationOverlay');
    const retryBtn = document.getElementById('orientationRetryBtn');
    const navLinks = Array.from(document.querySelectorAll('.nav-link'));

    if (!body) return;

    const state = {
        alertShownForCurrentPortrait: false,
        wasLocked: false
    };

    const closePhoneMoreMenu = () => {
        body.classList.remove('nav-more-open');
        if (navMoreToggle) navMoreToggle.setAttribute('aria-expanded', 'false');
    };

    const isTouchPhone = () => {
        const ua = (navigator.userAgent || '').toLowerCase();
        const uaDataMobile = !!(navigator.userAgentData && navigator.userAgentData.mobile);
        const mobileUA = /android|iphone|ipod|blackberry|windows phone|mobile/i.test(ua);
        const iPadLike = /ipad/i.test(ua) || (/macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
        const touchCapable = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0) || window.matchMedia('(pointer: coarse)').matches;
        const narrowViewport = window.matchMedia('(max-width: 1024px)').matches;
        const shortestSide = Math.min(window.screen?.width || 0, window.screen?.height || 0);
        const phoneLikeScreen = shortestSide > 0 && shortestSide <= 540;
        const strongPhoneSignal = mobileUA || uaDataMobile || phoneLikeScreen;
        const phoneHeuristic = (strongPhoneSignal || (mobileUA && narrowViewport)) && !iPadLike;
        return touchCapable && phoneHeuristic;
    };

    const isPortrait = () => {
        if (window.matchMedia && window.matchMedia('(orientation: portrait)').matches) {
            return true;
        }
        return window.innerHeight > window.innerWidth;
    };

    const applyMobileUX = () => {
        const phoneDevice = isTouchPhone();
        const portrait = isPortrait();
        const locked = phoneDevice && portrait;

        body.classList.toggle('is-phone-device', phoneDevice);
        body.classList.toggle('mobile-portrait-locked', locked);

        if (!phoneDevice) {
            body.classList.remove('nav-open');
            closePhoneMoreMenu();
        }

        if (overlay) {
            overlay.setAttribute('aria-hidden', locked ? 'false' : 'true');
        }

        if (locked && !state.wasLocked && !state.alertShownForCurrentPortrait) {
            state.alertShownForCurrentPortrait = true;
            window.alert('Please rotate your phone to landscape mode to use PPE Safety Monitor.');
        }

        if (!locked) {
            state.alertShownForCurrentPortrait = false;
        }

        if (locked) {
            body.classList.remove('nav-open');
            closePhoneMoreMenu();
            window.scrollTo({ top: 0, behavior: 'auto' });
        }

        state.wasLocked = locked;
    };

    if (navToggle) {
        navToggle.addEventListener('click', () => {
            if (body.classList.contains('mobile-portrait-locked')) return;
            closePhoneMoreMenu();
            body.classList.toggle('nav-open');
            navToggle.setAttribute('aria-expanded', body.classList.contains('nav-open') ? 'true' : 'false');
        });
    }

    navLinks.forEach((link) => {
        link.addEventListener('click', () => {
            body.classList.remove('nav-open');
            closePhoneMoreMenu();
            if (navToggle) navToggle.setAttribute('aria-expanded', 'false');
        });
    });

    if (navMoreToggle) {
        navMoreToggle.addEventListener('click', () => {
            if (body.classList.contains('mobile-portrait-locked')) return;
            if (!body.classList.contains('is-phone-device')) return;
            body.classList.remove('nav-open');
            if (navToggle) navToggle.setAttribute('aria-expanded', 'false');
            body.classList.toggle('nav-more-open');
            navMoreToggle.setAttribute('aria-expanded', body.classList.contains('nav-more-open') ? 'true' : 'false');
        });
    }

    document.addEventListener('click', (event) => {
        if (!body.classList.contains('nav-more-open')) return;
        if (!navMoreToggle || !navMorePanel) return;
        const insidePanel = navMorePanel.contains(event.target);
        const onToggle = navMoreToggle.contains(event.target);
        if (!insidePanel && !onToggle) {
            closePhoneMoreMenu();
        }
    });

    if (retryBtn) {
        retryBtn.addEventListener('click', () => applyMobileUX());
    }

    window.addEventListener('resize', applyMobileUX, { passive: true });
    window.addEventListener('orientationchange', applyMobileUX, { passive: true });
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) applyMobileUX();
    });
    window.addEventListener('pageshow', applyMobileUX, { passive: true });

    applyMobileUX();
}


document.addEventListener('DOMContentLoaded', () => {
    const modal = document.getElementById('handbookModal');
    const openBtn = document.getElementById('openHandbook');
    const closeBtn = document.getElementById('closeHandbook');

    if (!modal || !openBtn || !closeBtn) return;

    openBtn.addEventListener('click', () => {
        modal.classList.remove('hidden');
    });

    closeBtn.addEventListener('click', () => {
        modal.classList.add('hidden');
    });

    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.add('hidden');
        }
    });

    document.addEventListener('click', (e) => {
        const question = e.target.closest('.faq-question');
        if (!question) return;

        const item = question.parentElement;
        item.classList.toggle('active');
    });


    const handbookLinks = Array.from(modal.querySelectorAll('.handbook-link'));
    const handbookPages = Array.from(modal.querySelectorAll('.handbook-page'));
    const handbookHeader = modal.querySelector('.handbook-header');
    let handbookPagePicker = null;

    const activateHandbookPage = (pageKey) => {
        if (!pageKey) return;

        let activated = false;
        handbookLinks.forEach((link) => {
            const isActive = link.dataset.page === pageKey;
            link.classList.toggle('active', isActive);
            if (isActive) activated = true;
        });

        handbookPages.forEach((page) => {
            page.classList.toggle('active', page.id === `handbook-${pageKey}`);
        });

        if (!activated && handbookLinks.length > 0) {
            const fallbackKey = handbookLinks[0].dataset.page;
            activateHandbookPage(fallbackKey);
            return;
        }

        if (handbookPagePicker) {
            handbookPagePicker.value = pageKey;
        }
    };

    if (handbookHeader && handbookLinks.length > 0) {
        handbookPagePicker = document.createElement('select');
        handbookPagePicker.className = 'handbook-page-picker';
        handbookPagePicker.setAttribute('aria-label', 'Select handbook section');

        handbookLinks.forEach((link) => {
            const option = document.createElement('option');
            option.value = link.dataset.page || '';
            option.textContent = (link.textContent || '').trim().replace(/\s+/g, ' ');
            handbookPagePicker.appendChild(option);
        });

        handbookPagePicker.addEventListener('change', () => {
            activateHandbookPage(handbookPagePicker.value);
        });

        handbookHeader.appendChild(handbookPagePicker);
    }

    handbookLinks.forEach((btn) => {
        btn.addEventListener('click', () => {
            activateHandbookPage(btn.dataset.page);
        });
    });

    const initialActive = handbookLinks.find((link) => link.classList.contains('active'));
    activateHandbookPage((initialActive && initialActive.dataset.page) || (handbookLinks[0] && handbookLinks[0].dataset.page));
});
