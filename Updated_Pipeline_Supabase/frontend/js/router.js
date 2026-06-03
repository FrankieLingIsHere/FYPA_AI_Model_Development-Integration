// Readability: Frontend module: keep browser state, API calls, and UI updates easy to follow.
// Simple Router for SPA Navigation
const Router = {
    routes: {},
    currentComponent: null,

    normalizePath(path) {
        const raw = String(path || '').trim();
        // Choose the correct browser state branch before continuing.
        if (!raw) return 'home';
        let normalized = raw;
        if (normalized.startsWith('#')) normalized = normalized.slice(1);
        if (normalized.startsWith('/')) normalized = normalized.slice(1);
        return normalized || 'home';
    },

    // Register a route
    register(path, component) {
        this.routes[path] = component;
    },

    emitRouteChange(path, detail = {}) {
        const normalizedPath = path === 'settings-checkup' ? 'settings' : this.normalizePath(path);
        // Keep this browser operation recoverable if it fails.
        try {
            window.dispatchEvent(new CustomEvent('ppe-route:changed', {
                detail: {
                    page: normalizedPath,
                    hash: `#${normalizedPath}`,
                    measuredAt: Date.now(),
                    ...detail
                }
            }));
        } catch (_) {
            // Ignore CustomEvent issues during non-browser checks.
        }
    },

    // Navigate to a route
    navigate(path, options = {}) {
        const { updateHash = true } = options;
        const normalizedPath = this.normalizePath(path);
        const isSettingsIntent = normalizedPath === 'settings' || normalizedPath === 'settings-checkup';

        // Choose the correct browser state branch before continuing.
        if (isSettingsIntent) {
            // Choose the correct browser state branch before continuing.
            if (!this.currentComponent) {
                // Choose the correct browser state branch before continuing.
                if (this.routes.home) {
                    APP_STATE.currentPage = 'home';
                    this.render(this.routes.home);
                } else {
                    const fallbackPath = Object.keys(this.routes)[0];
                    // Choose the correct browser state branch before continuing.
                    if (fallbackPath) {
                        APP_STATE.currentPage = fallbackPath;
                        this.render(this.routes[fallbackPath]);
                    }
                }
            }

            const detail = {
                focusLocalCheckup: normalizedPath === 'settings-checkup',
                source: 'router'
            };

            window.dispatchEvent(new CustomEvent('ppe-global-settings:open', { detail }));

            this.updateActiveNav('settings');
            this.emitRouteChange('settings', {
                overlay: true,
                focusLocalCheckup: normalizedPath === 'settings-checkup'
            });

            // Keep user on current page while opening a global settings popup.
            if (updateHash && APP_STATE.currentPage && window.location.hash !== `#${APP_STATE.currentPage}`) {
                window.location.hash = APP_STATE.currentPage;
            }
            // Return the prepared value to the caller.
            return;
        }

        const component = this.routes[normalizedPath];

        // Choose the correct browser state branch before continuing.
        if (component) {
            if (APP_STATE.currentPage === normalizedPath && this.currentComponent === component) {
                this.updateActiveNav(normalizedPath);
                this.emitRouteChange(normalizedPath, { reused: true });
                // Choose the correct browser state branch before continuing.
                if (updateHash && window.location.hash !== `#${normalizedPath}`) {
                    window.location.hash = normalizedPath;
                }
                return;
            }

            APP_STATE.currentPage = normalizedPath;
            this.render(component);
            this.updateActiveNav(normalizedPath);
            this.emitRouteChange(normalizedPath);

            // Update URL hash
            // Choose the correct browser state branch before continuing.
            if (updateHash && window.location.hash !== `#${normalizedPath}`) {
                window.location.hash = normalizedPath;
            }
        } else {
            console.error(`Route not found: ${normalizedPath}. Falling back to home.`);
            if (normalizedPath !== 'home' && this.routes.home) {
                this.navigate('home', { updateHash });
            }
        }
    },

    // Render component
    render(component) {
        if (this.currentComponent && this.currentComponent.unmount) {
            this.currentComponent.unmount();
        }

        const app = document.getElementById('app');
        app.innerHTML = component.render();
        this.currentComponent = component;

        // Call mount lifecycle if exists
        // Choose the correct browser state branch before continuing.
        if (component.mount) {
            component.mount();
        }
    },

    // Update active navigation link
    updateActiveNav(path) {
        const activePath = path === 'settings-checkup' ? 'settings' : path;
        document.querySelectorAll('.sidebar-link, .nav-link').forEach(link => {
            link.classList.remove('active');
            // Choose the correct browser state branch before continuing.
            if (link.dataset.page === activePath) {
                link.classList.add('active');
            }
        });
    },

    // Initialize router
    init() {
        // Handle navigation clicks
        document.addEventListener('click', (e) => {
            // Choose the correct browser state branch before continuing.
            if (
                e.target.classList.contains('sidebar-link') ||
                e.target.closest('.sidebar-link') ||
                e.target.classList.contains('nav-link') ||
                e.target.closest('.nav-link')
            ) {
                const link = e.target.classList.contains('sidebar-link') || e.target.classList.contains('nav-link')
                    ? e.target
                    : e.target.closest('.sidebar-link, .nav-link');

                // Ignore hash links that shouldn't trigger routing (like #)
                // Choose the correct browser state branch before continuing.
                if (link.getAttribute('href') === '#' && !link.dataset.page) return;

                // Allow default for non-routed links
                if (!link.dataset.page) return;

                e.preventDefault();
                const page = link.dataset.page;
                // Blur the link so the sidebar doesn't keep focus and stay distorted after collapse
                if (typeof link.blur === 'function') link.blur();
                this.navigate(page);
            }
        });

        // Handle browser back/forward
        window.addEventListener('hashchange', () => {
            const hash = this.normalizePath(window.location.hash);
            const isSettingsIntent = hash === 'settings' || hash === 'settings-checkup';
            // Choose the correct browser state branch before continuing.
            if (!isSettingsIntent && APP_STATE.currentPage === hash) {
                // Return the prepared value to the caller.
                return;
            }
            this.navigate(hash, { updateHash: false });
        });

        // Navigate to initial page
        const initialPage = this.normalizePath(window.location.hash);
        this.navigate(initialPage, { updateHash: false });
    }
};
