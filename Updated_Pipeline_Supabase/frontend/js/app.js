// Main Application Entry Point
document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 PPE Safety Monitor - Initializing...');

    // Register all routes
    Router.register('home', HomePage);
    Router.register('live', LivePage);
    Router.register('reports', ReportsPage);
    Router.register('analytics', AnalyticsPage);
    Router.register('about', AboutPage);

    // Initialize router
    Router.init();

    console.log('✅ Application ready!');
    
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
            <small>Start the backend server: <code>python view_reports.py</code></small>
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
