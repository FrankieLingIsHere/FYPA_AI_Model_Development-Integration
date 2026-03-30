// Main Application Entry Point
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 PPE Safety Monitor - Initializing...');

    setupResponsiveMobileUX();

    // Register all routes
    Router.register('home', HomePage);
    Router.register('live', LivePage);
    Router.register('reports', ReportsPage);
    Router.register('analytics', AnalyticsPage);
    Router.register('about', AboutPage);

    // Initialize router
    Router.init();

    // Initialize timezone selector (Malaysian Time as default)
    if (typeof TimezoneManager !== 'undefined') {
        TimezoneManager.initSelector('timezoneSelector');
        console.log('🌏 Timezone set to:', TimezoneManager.getTimezoneLabel());
    }

    console.log('✅ Application ready!');

    if (typeof RealtimeSync !== 'undefined' && RealtimeSync.start) {
        RealtimeSync.start();
    }

    // Check backend connection
    checkBackendConnection();
});

// Check if backend is running
async function checkBackendConnection() {
    try {
        const response = await fetch(`${API_CONFIG.BASE_URL}/api/violations`);
        if (response.ok) {
            console.log('✅ Backend server connected');
        } else {
            showBackendWarning();
        }
    } catch (error) {
        showBackendWarning();
    }
}

// Show warning if backend is not running
function showBackendWarning() {
    console.warn('⚠️ Backend server not detected');

    // Add warning banner
    const banner = document.createElement('div');
    banner.className = 'alert alert-warning';
    banner.style.cssText = 'position: fixed; top: 70px; left: 50%; transform: translateX(-50%); z-index: 999; max-width: 600px; box-shadow: 0 4px 12px rgba(0,0,0,0.2);';
    banner.innerHTML = `
        <i class="fas fa-exclamation-triangle"></i>
        <div>
            <strong>Backend Not Running</strong><br>
            <small>Start the backend server: <code>python luna_app.py</code></small>
        </div>
        <button onclick="this.parentElement.remove()" style="margin-left: auto; background: none; border: none; cursor: pointer; font-size: 1.2rem;">×</button>
    `;
    banner.style.display = 'flex';
    banner.style.alignItems = 'center';
    banner.style.gap = '1rem';

    document.body.appendChild(banner);

    // Auto-dismiss after 10 seconds
    setTimeout(() => {
        if (banner.parentElement) {
            banner.remove();
        }
    }, 10000);
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
