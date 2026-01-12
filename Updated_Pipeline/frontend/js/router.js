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
        // Tag the page element with a page-specific class so CSS can target it
        const pageEl = app.querySelector('.page');
        if (pageEl) {
            // remove any existing page-* classes
            Array.from(pageEl.classList).forEach(c => {
                if (c.startsWith('page-')) pageEl.classList.remove(c);
            });
            pageEl.classList.add('page-' + (APP_STATE.currentPage || 'home'));
        }
        
        // Call mount lifecycle if exists
        if (component.mount) {
            component.mount();
        }
    },

    // Update active navigation link
    updateActiveNav(path) {
        document.querySelectorAll('.nav-link').forEach(link => {
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
            if (e.target.classList.contains('nav-link') || e.target.closest('.nav-link')) {
                e.preventDefault();
                const link = e.target.classList.contains('nav-link') ? e.target : e.target.closest('.nav-link');
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

// Add body-level toggles when navigating
const ORIGINAL_NAVIGATE = Router.navigate.bind(Router);
Router.navigate = function(path) {
    ORIGINAL_NAVIGATE(path);

    // Footer only on home
    document.body.classList.toggle('show-footer', path === 'home');

    // Allow page scroll only for reports and about
    const allow = (path === 'reports' || path === 'about');
    document.body.classList.toggle('allow-scroll', allow);
};
