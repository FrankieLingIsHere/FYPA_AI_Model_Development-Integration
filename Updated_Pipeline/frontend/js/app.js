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


// ===== Voice Alert System =====
let voiceEnabled = false;          
const globalAlertedPPE = new Set();  // Tracks PPE already alerted globally

// ===== Enable/Disable Voice Button =====
document.addEventListener('click', (e) => {
    if (!e.target) return;

    const badge = document.getElementById("voiceStatus");

    if (e.target.id === "enableVoice") {
        voiceEnabled = !voiceEnabled;

        if (badge) {
            badge.innerText = voiceEnabled ? "🔊 Voice ON" : "🔇 Voice OFF";
            badge.style.background = voiceEnabled ? "#2ecc71" : "#555";
        }

        const msg = voiceEnabled ? "Voice alerts activated" : "Voice alerts deactivated";
        speechSynthesis.speak(new SpeechSynthesisUtterance(msg));
        console.log(`🔊 Voice alerts ${voiceEnabled ? "enabled" : "disabled"} by user`);

        // Clear alerts when toggling OFF so next missing PPE triggers again
        if (!voiceEnabled) globalAlertedPPE.clear();
    }
});


// ===== Auto Speak Missing PPE =====
function autoVoiceAlert(missingPPE) {
    if (!voiceEnabled || !missingPPE || missingPPE.length === 0) return;

    // Filter out PPE that have already been alerted
    const newAlerts = missingPPE.filter(p => !globalAlertedPPE.has(p));
    if (newAlerts.length === 0) return;

    // Mark these PPE as alerted
    newAlerts.forEach(p => globalAlertedPPE.add(p));

    // Format the message
    const formatted = newAlerts.map(p => p.replace("NO-", "")).join(" and ");
    const msg = `Warning. ${formatted} missing.`;
    console.log("🔊 Voice alert triggered:", msg);
    speechSynthesis.speak(new SpeechSynthesisUtterance(msg));
}

// ===== Poll Backend for Latest Violation =====
setInterval(async () => {
    if (!APP_STATE.liveStreamActive) return;

    try {
        const res = await fetch(`${API_CONFIG.BASE_URL}/api/violations/latest`);
        const data = await res.json();

        if (!data.report_id || !data.missing_ppe) return;

        // Convert all items to uppercase to normalize
        const missingItems = data.missing_ppe.map(p => p.trim().toUpperCase());
        autoVoiceAlert(missingItems);

    } catch (err) {
        console.warn("Violation poll failed", err);
    }
}, 3000);


// ===== Poll Backend for Latest Violation =====
setInterval(async () => {
    if (!APP_STATE.liveStreamActive) return;

    try {
        const res = await fetch(`${API_CONFIG.BASE_URL}/api/violations/latest`);
        const data = await res.json();

        if (!data.report_id || !data.missing_ppe) return;

        autoVoiceAlert(data.missing_ppe.map(p => p.replace("NO-", "")));
    } catch (err) {
        console.warn("Violation poll failed", err);
    }
}, 3000);

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.sidebar-link').forEach(link => {
        link.addEventListener('click', () => {
            document.querySelectorAll('.sidebar-link')
                .forEach(l => l.classList.remove('active'));
            link.classList.add('active');
        });
    });
});
