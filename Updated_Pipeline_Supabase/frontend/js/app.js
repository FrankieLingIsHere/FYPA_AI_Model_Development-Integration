const STARTUP_STATUS_ENDPOINT = '/api/system/startup-status';
const STARTUP_POLL_INTERVAL_MS = 1200;
let appBootstrapped = false;

// Main Application Entry Point
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 PPE Safety Monitor - Initializing...');
    initializeWithStartupGate();
});

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
        TimezoneManager.initSelector('timezoneSelector');
        console.log('🌏 Timezone set to:', TimezoneManager.getTimezoneLabel());
    }

    if (typeof RealtimeSync !== 'undefined' && RealtimeSync.start) {
        RealtimeSync.start();
    }

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
        const mobileUA = /android|iphone|ipod|blackberry|windows phone|mobile/i.test(ua);
        const touchCapable = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0) || window.matchMedia('(pointer: coarse)').matches;
        const narrowViewport = window.matchMedia('(max-width: 900px)').matches;
        const tabletUA = /ipad|tablet/i.test(ua);
        return touchCapable && (mobileUA || (narrowViewport && !tabletUA));
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
