// Audio Alert / Voice Alert Module
// Plays a single TTS warning when a new violation is detected.

const AudioAlert = (function () {
    const STORAGE_KEY_ENABLED = 'luna_voice_alerts_enabled';
    const STORAGE_KEY_PLAYED = 'luna_voice_alerts_played';

    let enabled = false;
    let playedReports = new Set();
    let button = null;
    let originalNotifyFn = null;

    function _loadState() {
        try {
            const v = localStorage.getItem(STORAGE_KEY_ENABLED);
            enabled = v === 'true';
        } catch (e) {
            enabled = false;
        }

        try {
            const played = JSON.parse(localStorage.getItem(STORAGE_KEY_PLAYED) || '[]');
            playedReports = new Set(Array.isArray(played) ? played : []);
        } catch (e) {
            playedReports = new Set();
        }
    }

    function _saveState() {
        try { localStorage.setItem(STORAGE_KEY_ENABLED, enabled ? 'true' : 'false'); } catch (e) {}
        try { localStorage.setItem(STORAGE_KEY_PLAYED, JSON.stringify([...playedReports])); } catch (e) {}
    }

    function _updateButtonVisual() {
        if (!button) return;
        if (enabled) {
            button.classList.remove('btn-danger');
            button.classList.add('btn-success');
            button.style.background = '#27ae60';
            button.style.borderColor = '#1e8449';
            button.innerHTML = '🔊 <span>Voice Alerts ON</span>';
        } else {
            button.classList.remove('btn-success');
            button.classList.add('btn-danger');
            button.style.background = '#e74c3c';
            button.style.borderColor = '#c0392b';
            button.innerHTML = '🔊 <span>Voice Alerts OFF</span>';
        }
    }

    function toggle() {
        enabled = !enabled;
        _saveState();
        _updateButtonVisual();
        if (enabled) {
            NotificationManager.info('Voice alerts enabled');
            // Try to prime speech synthesis (some browsers require a user gesture)
            try {
                if (window.speechSynthesis) {
                    const primer = new SpeechSynthesisUtterance('Voice alerts enabled');
                    primer.rate = 1.0;
                    primer.pitch = 1.0;
                    // Cancel any existing speech and speak a short primer
                    window.speechSynthesis.cancel();
                    window.speechSynthesis.speak(primer);
                }
            } catch (e) {
                console.warn('[AudioAlert] Could not prime speech synthesis:', e);
            }
        } else {
            NotificationManager.info('Voice alerts disabled');
        }
    }

    async function speakViolation(violation) {
        if (!enabled) {
            console.log('[AudioAlert] speakViolation called but alerts disabled');
            return;
        }
        if (typeof window.speechSynthesis === 'undefined') {
            console.warn('[AudioAlert] SpeechSynthesis API not available in this browser');
            return;
        }
        const reportId = violation && violation.report_id ? String(violation.report_id) : null;
        if (!reportId) {
            console.warn('[AudioAlert] speakViolation: no report_id present');
            return;
        }
        if (playedReports.has(reportId)) {
            console.log('[AudioAlert] speakViolation: already played for', reportId);
            return; // already played
        }

        console.log('[AudioAlert] speakViolation starting for', reportId, 'violation object:', violation);

        // Helper to extract missing PPE array and a friendly type string from multiple possible fields
        function extractMissingAndType(v) {
            let missing = [];
            // Common fields
            if (Array.isArray(v.missing_ppe) && v.missing_ppe.length > 0) missing = v.missing_ppe.slice();
            // nested detection data
            if ((!missing || missing.length === 0) && v.detection_data) {
                if (Array.isArray(v.detection_data.missing_ppe) && v.detection_data.missing_ppe.length > 0) missing = v.detection_data.missing_ppe.slice();
                if ((!missing || missing.length === 0) && Array.isArray(v.detection_data.missing) && v.detection_data.missing.length > 0) missing = v.detection_data.missing.slice();
            }
            // captions/validation contradictions
            if ((!missing || missing.length === 0) && v.detection_data && v.detection_data.caption_validation && Array.isArray(v.detection_data.caption_validation.contradictions)) {
                const contr = v.detection_data.caption_validation.contradictions[0] || '';
                const m = (contr.match(/Missing:?\s*([^\.\n]+)/i) || contr.match(/PPE Mismatch:?\s*(.+)/i));
                if (m && m[1]) missing = m[1].split(',').map(x => x.trim()).filter(Boolean);
            }

            // Try parsing violation_summary
            if ((!missing || missing.length === 0) && v.violation_summary) {
                const s = v.violation_summary;
                const m = s.match(/Missing:?\s*([^\.\n]+)/i) || s.match(/PPE Violation Detected:?\s*(.+)/i);
                if (m && m[1]) missing = m[1].split(',').map(x => x.trim()).filter(Boolean);
            }

            // Derive friendly type
            let derivedType = null;
            if (v.violation_type && v.violation_type !== 'PPE Violation') derivedType = v.violation_type;
            if (!derivedType && missing && missing.length > 0) {
                if (missing.length === 1) derivedType = `Missing ${missing[0]}`;
                else if (missing.length === 2) derivedType = `Missing ${missing[0]} and ${missing[1]}`;
                else derivedType = `Missing ${missing.slice(0,5).join(', ')}`;
            }
            if (!derivedType && v.label) derivedType = v.label;
            if (!derivedType && v.caption) derivedType = v.caption;
            if (!derivedType && v.violation_summary) {
                const s2 = v.violation_summary.split('\n')[0];
                derivedType = s2.length > 0 ? s2 : null;
            }
            if (!derivedType) derivedType = 'PPE Violation';

            return { missing, derivedType };
        }

        // Try to fetch fuller details if missing data
        if (typeof window.API !== 'undefined' && typeof window.API.getViolation === 'function') {
            try {
                const full = await window.API.getViolation(reportId);
                if (full) {
                    // shallow merge so nested fields are present
                    violation = Object.assign({}, violation, full);
                    console.log('[AudioAlert] Fetched full violation for', reportId, full);
                }
            } catch (e) {
                console.warn('[AudioAlert] Failed to fetch full violation:', e);
            }
        }

        const extracted = extractMissingAndType(violation || {});
        const missing = extracted.missing || [];
        const derivedType = extracted.derivedType || 'PPE Violation';

        let message = `Warning. ${derivedType}.`;
        if (missing.length > 0) {
            if (missing.length === 1) message += ` Missing: ${missing[0]}.`;
            else if (missing.length === 2) message += ` Missing: ${missing[0]} and ${missing[1]}.`;
            else message += ` Missing: ${missing.slice(0, 5).join(', ')}.`;
        }

        try {
            const utter = new SpeechSynthesisUtterance(message);
            utter.rate = 1.0;
            utter.pitch = 1.0;

            // Choose a voice if available (prefer English voices)
            const voices = window.speechSynthesis.getVoices();
            if (voices && voices.length) {
                const preferred = voices.find(v => /en|google/i.test(v.name) || /en-US|en_US/i.test(v.lang));
                if (preferred) utter.voice = preferred;
            }

            // Mark as played immediately to avoid duplicates while speaking
            playedReports.add(reportId);
            _saveState();

            window.speechSynthesis.cancel(); // stop any in-progress TTS
            window.speechSynthesis.speak(utter);

            // Optionally notify visually
            NotificationManager.violation(message, reportId);
        } catch (e) {
            console.warn('Speech synthesis failed:', e);
        }
    }

    function patchViolationMonitor() {
        // Wait until ViolationMonitor is defined
        const waitForMonitor = setInterval(() => {
            if (window.ViolationMonitor && typeof window.ViolationMonitor._notifyViolationDetected === 'function') {
                clearInterval(waitForMonitor);

                try {
                    originalNotifyFn = window.ViolationMonitor._notifyViolationDetected.bind(window.ViolationMonitor);

                    window.ViolationMonitor._notifyViolationDetected = function (violation) {
                        // Call original behavior
                        try { originalNotifyFn(violation); } catch (e) { console.error(e); }

                        // Debug: log that we received a violation
                        try { console.log('[AudioAlert] Violation detected patch received:', violation && violation.report_id); } catch (e) {}

                        // Play audio alert (once per report)
                        try { speakViolation(violation); } catch (e) { console.error(e); }
                    };

                    console.log('[AudioAlert] Patched ViolationMonitor._notifyViolationDetected');
                } catch (e) {
                    console.error('[AudioAlert] Failed to patch ViolationMonitor:', e);
                }
            }
        }, 200);
    }

    function init() {
        document.addEventListener('DOMContentLoaded', () => {
            _loadState();

            button = document.getElementById('enableVoice');
            if (!button) {
                // Create fallback button in footer if missing
                button = document.createElement('button');
                button.id = 'enableVoice';
                button.className = 'btn btn-danger sidebar-voice-btn';
                document.body.appendChild(button);
            }

            // Test button (plays a short test phrase regardless of enabled state)
            let testBtn = document.getElementById('testVoice');
            if (!testBtn) {
                // try to append to sidebar-bottom if present
                const sidebarBottom = document.querySelector('.sidebar-bottom');
                testBtn = document.createElement('button');
                testBtn.id = 'testVoice';
                testBtn.className = 'btn btn-secondary sidebar-voice-btn';
                testBtn.innerHTML = '🔈 <span>Test Voice</span>';
                if (sidebarBottom) sidebarBottom.appendChild(testBtn);
                else document.body.appendChild(testBtn);
            }

            testBtn.addEventListener('click', (e) => {
                e.preventDefault();
                try {
                    if (typeof window.speechSynthesis === 'undefined') {
                        NotificationManager.error('SpeechSynthesis not supported in this browser');
                        return;
                    }

                    // Play a short test phrase regardless of enabled flag
                    const utter = new SpeechSynthesisUtterance('Testing voice alert');
                    utter.rate = 1.0;
                    utter.pitch = 1.0;
                    const voices = window.speechSynthesis.getVoices();
                    if (voices && voices.length) {
                        const preferred = voices.find(v => /en|google/i.test(v.name) || /en-US|en_US/i.test(v.lang));
                        if (preferred) utter.voice = preferred;
                    }
                    window.speechSynthesis.cancel();
                    window.speechSynthesis.speak(utter);
                    NotificationManager.info('Playing test voice');
                } catch (err) {
                    console.warn('[AudioAlert] Test speak failed:', err);
                    NotificationManager.error('Test voice failed');
                }
            });

            button.addEventListener('click', (e) => {
                e.preventDefault();
                toggle();
            });

            _updateButtonVisual();

            // Patch monitor to play audio on new violations
            patchViolationMonitor();

            console.log('[AudioAlert] Initialized - enabled:', enabled);
        });
    }

    return {
        init,
        toggle,
        speakViolation,
        isEnabled() { return enabled; },
        markPlayed(reportId) { playedReports.add(reportId); _saveState(); }
    };
})();

// Auto-init
AudioAlert.init();

// Expose for other modules that call AudioAlert directly
try { window.AudioAlert = window.AudioAlert || AudioAlert; } catch (e) { console.warn('[AudioAlert] Could not attach to window:', e); }
