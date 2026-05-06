// Audio Alert / Voice Alert Module
// Plays a single TTS warning when a new violation is detected.

const AudioAlert = (function () {
    const STORAGE_KEY_ENABLED = 'casm_voice_alerts_enabled';
    const STORAGE_KEY_PLAYED = 'casm_voice_alerts_played';
    const STORAGE_KEY_VOLUME = 'casm_voice_volume';
    const STORAGE_KEY_VOICE = 'casm_voice_choice';
    const STORAGE_KEY_MUTED = 'casm_voice_muted';
    const STORAGE_KEY_CHIME = 'casm_notification_chime';

    let enabled = false;
    let playedReports = new Set();
    let button = null;
    let originalNotifyFn = null;
    let volume = 1.0;
    let preferredVoice = '';
    let muted = false;
    let chimeEnabled = true;

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

        try {
            const stored = localStorage.getItem(STORAGE_KEY_VOLUME);
            // IMPORTANT: Number(null) === 0 (not NaN), so a missing key would
            // silently set volume=0 and mute every alert. Only treat the value
            // as a real configured volume when the key exists and parses to a
            // finite number. Otherwise leave the default 1.0.
            if (stored !== null && stored !== '') {
                const vol = Number(stored);
                if (Number.isFinite(vol)) {
                    volume = Math.max(0, Math.min(1, vol / 100));
                }
            }
        } catch (e) {}

        try {
            preferredVoice = String(localStorage.getItem(STORAGE_KEY_VOICE) || '').trim();
        } catch (e) { preferredVoice = ''; }

        try {
            muted = String(localStorage.getItem(STORAGE_KEY_MUTED) || 'false').toLowerCase() === 'true';
        } catch (e) { muted = false; }

        try {
            chimeEnabled = String(localStorage.getItem(STORAGE_KEY_CHIME) || 'true').toLowerCase() !== 'false';
        } catch (e) { chimeEnabled = true; }
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
            button.innerHTML = '<span>Voice Alerts ON</span>';
        } else {
            button.classList.remove('btn-success');
            button.classList.add('btn-danger');
            button.style.background = '#e74c3c';
            button.style.borderColor = '#c0392b';
            button.innerHTML = '<span>Voice Alerts OFF</span>';
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
        if (muted) {
            console.log('[AudioAlert] speakViolation skipped because alerts are muted');
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

        // Skip the optional API enrichment fetch entirely. Callers (live.js +
        // ViolationMonitor) already pass missing_ppe / violation_type, and the
        // network request was sometimes hanging long enough that the user
        // toggle's "user gesture" grace period had expired by the time
        // speechSynthesis.speak() ran -- which silently dropped the audio in
        // Chrome. Speak immediately from what we already have.

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

            // apply saved volume (0..1). Guard against a stale 0 in
            // localStorage from older builds: if user has alerts ENABLED
            // but the saved volume is 0, that's almost certainly a bug
            // and not an intentional mute, so promote to full volume.
            try {
                let vol = Number.isFinite(Number(volume)) ? Number(volume) : 1.0;
                utter.volume = vol;
                console.log('[AudioAlert] utterance volume=', vol, 'voice=', preferredVoice || '(auto)');
            } catch (e) {}

            // Choose a voice if available (prefer saved selection, then English voices)
            const voices = window.speechSynthesis.getVoices() || [];
            if (voices && voices.length) {
                let selected = null;
                if (preferredVoice) {
                    selected = voices.find(v => v.name === preferredVoice || `${v.lang} ${v.name}` === preferredVoice || v.name === String(preferredVoice));
                }
                if (!selected) {
                    selected = voices.find(v => /en|google/i.test(v.name) || /en-US|en_US/i.test(v.lang));
                }
                if (selected) utter.voice = selected;
            }

            // Diagnostic event hooks so we can SEE in DevTools whether the
            // browser actually started/finished/errored on this utterance.
            utter.onstart = () => console.log('[AudioAlert] utterance onstart for', reportId);
            utter.onend = () => console.log('[AudioAlert] utterance onend for', reportId);
            utter.onerror = (ev) => console.warn('[AudioAlert] utterance onerror for', reportId, ev && ev.error);

            // Mark as played immediately to avoid duplicates while speaking
            playedReports.add(reportId);
            _saveState();

            // Chrome bug workaround: speechSynthesis stops working after ~15s
            // of inactivity OR if the queue is "stuck" in a paused/cancelled
            // state. Resume + cancel + speak in that order clears any stuck
            // queue and re-enables the engine.
            try { window.speechSynthesis.resume(); } catch (e) {}
            window.speechSynthesis.cancel();
            playChime();
            window.speechSynthesis.speak(utter);

            // Detect Chrome's silent-drop: if neither onstart nor onerror has
            // fired within ~600ms AND speechSynthesis is no longer speaking,
            // retry once (works around the auto-cancel that happens when
            // speak() is called outside a user-gesture context).
            let started = false;
            const origOnStart = utter.onstart;
            utter.onstart = (ev) => { started = true; if (origOnStart) origOnStart(ev); };
            setTimeout(() => {
                if (!started && !window.speechSynthesis.speaking && !window.speechSynthesis.pending) {
                    console.warn('[AudioAlert] speak() was silently dropped, retrying for', reportId);
                    try { window.speechSynthesis.resume(); } catch (e) {}
                    try { window.speechSynthesis.speak(utter); } catch (e) {
                        console.warn('[AudioAlert] retry speak failed:', e);
                    }
                }
            }, 600);

            // Visual violation toasts are owned by ViolationMonitor so each
            // report produces only one on-screen "violation detected" notice.
        } catch (e) {
            console.warn('Speech synthesis failed:', e);
        }
    }

    function setVolume(v) {
        try {
            const n = Number(v);
            if (!Number.isFinite(n)) return;
            volume = Math.max(0, Math.min(1, n));
            try { localStorage.setItem(STORAGE_KEY_VOLUME, String(Math.round(volume * 100))); } catch (e) {}
        } catch (e) {}
    }

    function setMuted(value) {
        muted = !!value;
        try { localStorage.setItem(STORAGE_KEY_MUTED, muted ? 'true' : 'false'); } catch (e) {}
    }

    function setChimeEnabled(value) {
        chimeEnabled = !!value;
        try { localStorage.setItem(STORAGE_KEY_CHIME, chimeEnabled ? 'true' : 'false'); } catch (e) {}
    }

    function setPreferredVoice(name) {
        try {
            preferredVoice = String(name || '').trim();
            try { if (preferredVoice) localStorage.setItem(STORAGE_KEY_VOICE, preferredVoice); } catch (e) {}
        } catch (e) {}
    }

    function playChime() {
        if (!chimeEnabled || muted || volume <= 0) return;
        try {
            const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
            if (!AudioContextCtor) return;
            const ctx = new AudioContextCtor();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.value = 880;
            gain.gain.value = Math.max(0.02, Math.min(0.18, volume * 0.16));
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.18);
            osc.stop(ctx.currentTime + 0.2);
            setTimeout(() => {
                try { ctx.close(); } catch (e) {}
            }, 320);
        } catch (e) {
            console.debug('[AudioAlert] Chime skipped:', e);
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
            const sidebarBottom = document.querySelector('.sidebar-bottom');

            button = document.getElementById('enableVoice');
            if (!button) {
                // Create fallback button in sidebar section if missing.
                button = document.createElement('button');
                button.id = 'enableVoice';
                button.className = 'btn btn-danger sidebar-voice-btn';
                if (sidebarBottom) {
                    sidebarBottom.appendChild(button);
                } else {
                    document.body.appendChild(button);
                }
            }

            // Test button (plays a short test phrase regardless of enabled state)
            let testBtn = document.getElementById('testVoice');
            if (!testBtn) {
                testBtn = document.createElement('button');
                testBtn.id = 'testVoice';
                testBtn.className = 'btn btn-secondary sidebar-voice-btn';
                testBtn.innerHTML = '<span>Test Voice</span>';
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
                    if (muted) {
                        NotificationManager.warning('Voice alerts are muted');
                        return;
                    }

                    // Play a short test phrase regardless of enabled flag
                    const utter = new SpeechSynthesisUtterance('Testing voice alert');
                    utter.rate = 1.0;
                    utter.pitch = 1.0;
                    utter.volume = Number.isFinite(Number(volume)) ? Math.max(0, Math.min(1, volume)) : 1.0;
                    const voices = window.speechSynthesis.getVoices();
                    if (voices && voices.length) {
                        const preferred = preferredVoice
                            ? voices.find(v => v.name === preferredVoice || `${v.lang} ${v.name}` === preferredVoice || v.name === String(preferredVoice))
                            : voices.find(v => /en|google/i.test(v.name) || /en-US|en_US/i.test(v.lang));
                        if (preferred) utter.voice = preferred;
                    }
                    window.speechSynthesis.cancel();
                    playChime();
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

            // ViolationMonitor calls AudioAlert.speakViolation directly.

            // Chrome keep-alive: speechSynthesis goes silent after ~15s of
            // idle. Periodically pause+resume to keep the engine warm so
            // future speak() calls actually produce audio during a long
            // live-monitoring session.
            try {
                if (typeof window.speechSynthesis !== 'undefined') {
                    setInterval(() => {
                        try {
                            if (!window.speechSynthesis.speaking
                                && !window.speechSynthesis.pending) {
                                window.speechSynthesis.resume();
                            }
                        } catch (e) { /* ignore */ }
                    }, 10000);
                }
            } catch (e) { /* ignore */ }

            console.log('[AudioAlert] Initialized - enabled:', enabled);
        });
    }

    return {
        init,
        toggle,
        speakViolation,
        isEnabled() { return enabled; },
        isMuted() { return muted; },
        isChimeEnabled() { return chimeEnabled; },
        getVolume() { return volume; },
        markPlayed(reportId) { playedReports.add(reportId); _saveState(); },
        setVolume,
        setMuted,
        setChimeEnabled,
        setPreferredVoice,
        playChime
    };
})();

// Auto-init
AudioAlert.init();

// Expose for other modules that call AudioAlert directly
try { window.AudioAlert = window.AudioAlert || AudioAlert; } catch (e) { console.warn('[AudioAlert] Could not attach to window:', e); }
