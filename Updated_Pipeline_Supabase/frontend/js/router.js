// Simple Router for SPA Navigation
const Router = {
    routes: {},

    // Register a route
    register(path, component) {
        this.routes[path] = component;
    },

    // Navigate to a route
    navigate(path) {
        const component = this.routes[path];
        if (component) {
            APP_STATE.currentPage = path;
            this.render(component);
            this.updateActiveNav(path);

            // Update URL hash
            window.location.hash = path;
        } else {
            console.error(`Route not found: ${path}`);
        }
    },

    // Render component
    render(component) {
        const app = document.getElementById('app');
        app.innerHTML = component.render();

        // Call mount lifecycle if exists
        if (component.mount) {
            component.mount();
        }
    },

    // Update active navigation link
    updateActiveNav(path) {
        document.querySelectorAll('.sidebar-link').forEach(link => {
            link.classList.remove('active');
            if (link.dataset.page === path) {
                link.classList.add('active');
            }
        });
    },

    // Initialize router
    init() {
        // Handle navigation clicks
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('sidebar-link') || e.target.closest('.sidebar-link')) {
                const link = e.target.classList.contains('sidebar-link') ? e.target : e.target.closest('.sidebar-link');

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
            const hash = window.location.hash.slice(1) || 'home';
            this.navigate(hash);
        });

        // Navigate to initial page
        const initialPage = window.location.hash.slice(1) || 'home';
        this.navigate(initialPage);
    }
};
