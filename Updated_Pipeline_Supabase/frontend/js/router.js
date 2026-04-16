// Simple Router for SPA Navigation
const Router = {
    routes: {},
    currentComponent: null,

    normalizePath(path) {
        const raw = String(path || '').trim();
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

    // Navigate to a route
    navigate(path, options = {}) {
        const { updateHash = true } = options;
        const normalizedPath = this.normalizePath(path);
        const component = this.routes[normalizedPath];
        if (component) {
            if (APP_STATE.currentPage === normalizedPath && this.currentComponent === component) {
                this.updateActiveNav(normalizedPath);
                if (updateHash && window.location.hash !== `#${normalizedPath}`) {
                    window.location.hash = normalizedPath;
                }
                return;
            }

            APP_STATE.currentPage = normalizedPath;
            this.render(component);
            this.updateActiveNav(normalizedPath);

            // Update URL hash
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
        if (component.mount) {
            component.mount();
        }
    },

    // Update active navigation link
    updateActiveNav(path) {
        const activePath = path === 'settings-checkup' ? 'settings' : path;
        document.querySelectorAll('.sidebar-link, .nav-link').forEach(link => {
            link.classList.remove('active');
            if (link.dataset.page === activePath) {
                link.classList.add('active');
            }
        });
    },

    // Initialize router
    init() {
        // Handle navigation clicks
        document.addEventListener('click', (e) => {
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
                if (link.getAttribute('href') === '#' && !link.dataset.page) return;

                // Allow default for non-routed links
                if (!link.dataset.page) return;

                e.preventDefault();
                const page = link.dataset.page;
                this.navigate(page);
            }
        });

        // Handle browser back/forward
        window.addEventListener('hashchange', () => {
            const hash = this.normalizePath(window.location.hash);
            if (APP_STATE.currentPage === hash) {
                return;
            }
            this.navigate(hash, { updateHash: false });
        });

        // Navigate to initial page
        const initialPage = this.normalizePath(window.location.hash);
        this.navigate(initialPage, { updateHash: false });
    }
};
