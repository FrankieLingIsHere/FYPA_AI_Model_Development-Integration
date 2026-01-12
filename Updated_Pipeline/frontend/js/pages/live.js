// Live Monitoring Page Component
const LivePage = {
    render() {
        return `
            <div class="page">
                <div class="card mb-4">
                    <div class="card-header">
                        <span><i class="fas fa-video"></i> Live PPE Monitoring</span>
                        <div style="float: right;">
                            <button id="startLiveBtn" class="btn btn-success" style="margin-right: 10px;">
                                <i class="fas fa-play"></i> Start
                            </button>
                            <button id="stopLiveBtn" class="btn btn-danger" disabled>
                                <i class="fas fa-stop"></i> Stop
                            </button>

                        </div>
                    </div>
                    <div class="card-content">
                        <div id="liveStreamContainer" style="background: transparent; border-radius: 8px; text-align: center; margin-bottom: 1.5rem; position: relative;">
                            <div id="streamPlaceholder" style="padding: 2rem; background: #000; border-radius: 8px; width: 100%;">
                                <i class="fas fa-video" style="font-size: 4rem; color: #fff; opacity: 0.3; margin-bottom: 1rem;"></i>
                                <p style="color: #fff; margin: 0;">Click "Start" to begin live monitoring</p>
                                <p style="color: #aaa; font-size: 0.9rem; margin-top: 0.5rem;">
                                    Real-time YOLO detection with PPE compliance checking
                                </p>
                                
                                <span id="voiceStatus" class="badge">🔇 Voice OFF</span>
                            </div>
                            <img id="liveStream" style="display: none; width: auto; max-width: 100%; height: auto; margin: 0 auto; border-radius: 8px;" />
                            <div id="streamStatus" style="position: absolute; top: 10px; right: 10px; background: rgba(0,0,0,0.7); color: #4CAF50; padding: 8px 16px; border-radius: 20px; font-weight: bold; display: none;">
                                <i class="fas fa-circle" style="animation: blink 1.5s infinite;"></i> LIVE
                            </div>
                        </div>

                        <h3 style="margin-bottom: 1rem;">Instructions:</h3>
                        <ol style="margin-left: 1.5rem; line-height: 2;">
                            <li>Click the <strong>"Start"</strong> button above to begin live monitoring</li>
                            <li>Your webcam will activate and show the live feed</li>
                            <li>YOLO will detect PPE in real-time with bounding boxes</li>
                            <li>When violations are detected, they will be logged automatically</li>
                            <li>Click <strong>"Stop"</strong> to end the monitoring session</li>
                        </ol>

                

                        <h3 style="margin-top: 2rem; margin-bottom: 1rem;">Detection Features:</h3>
                        <div class="grid grid-3">
                            <div class="card" style="background: var(--background-color);">
                                <div class="card-content text-center">
                                    <i class="fas fa-bolt" style="font-size: 2rem; color: var(--warning-color);"></i>
                                    <h4 style="margin-top: 0.5rem;">Real-Time</h4>
                                    <p>Instant PPE detection at 30 FPS</p>
                                </div>
                            </div>
                            <div class="card" style="background: var(--background-color);">
                                <div class="card-content text-center">
                                    <i class="fas fa-brain" style="font-size: 2rem; color: var(--primary-color);"></i>
                                    <h4 style="margin-top: 0.5rem;">AI-Powered</h4>
                                    <p>YOLOv8 trained on 14 PPE classes</p>
                                </div>
                            </div>
                            <div class="card" style="background: var(--background-color);">
                                <div class="card-content text-center">
                                    <i class="fas fa-check-circle" style="font-size: 2rem; color: var(--success-color);"></i>
                                    <h4 style="margin-top: 0.5rem;">Accurate</h4>
                                    <p>95%+ detection accuracy</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Detection Settings -->
                <div class="card">
                    <div class="card-header">
                        <span><i class="fas fa-cog"></i> Detection Settings</span>
                    </div>
                    <div class="card-content">
                        <div class="grid grid-2">
                            <div>
                                <h4 style="margin-bottom: 0.5rem;">Active PPE Classes (14 total):</h4>
                                <div style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 1rem;">
                                    <span class="badge badge-info">Hardhat</span>
                                    <span class="badge badge-info">Safety Vest</span>
                                    <span class="badge badge-info">Mask</span>
                                    <span class="badge badge-info">Gloves</span>
                                    <span class="badge badge-info">Safety Shoes</span>
                                    <span class="badge badge-info">Goggles</span>
                                    <span class="badge badge-info">NO-Hardhat</span>
                                    <span class="badge badge-info">NO-Safety Vest</span>
                                    <span class="badge badge-info">NO-Mask</span>
                                    <span class="badge badge-info">NO-Gloves</span>
                                    <span class="badge badge-info">NO-Safety Shoes</span>
                                    <span class="badge badge-info">NO-Goggles</span>
                                    <span class="badge badge-info">Person</span>
                                    <span class="badge badge-info">Machinery</span>
                                </div>
                            </div>
                            <div>
                                <h4 style="margin-bottom: 0.5rem;">Current Violation Rules:</h4>
                                <ul style="margin-left: 1.5rem; margin-top: 1rem; line-height: 2;">
                                    <li><strong>NO-Hardhat detection</strong> → Triggers violation immediately</li>
                                    <li>Confidence threshold: 10%</li>
                                    <li>Detection quality: High-resolution frames</li>
                                    <li>Processing: GPU-accelerated inference</li>
                                </ul>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    },

    async mount() {
        // Attach event listeners
        const startBtn = document.getElementById('startLiveBtn');
        const stopBtn = document.getElementById('stopLiveBtn');
        const streamImg = document.getElementById('liveStream');
        const placeholder = document.getElementById('streamPlaceholder');
        const statusIndicator = document.getElementById('streamStatus');
        

            // ===== Voice Alert System =====
        let voiceEnabled = false;
        let lastReportId = null;
        let alertedPPE = new Set();

        // ===== Voice Button Toggle =====
        document.addEventListener('click', (e) => {
            if (!e.target) return;

            if (e.target.id === "enableVoice") {
                voiceEnabled = !voiceEnabled;

                const badge = document.getElementById("voiceStatus");
                if (badge) {
                    badge.innerText = voiceEnabled ? "🔊 Voice ON" : "🔇 Voice OFF";
                    badge.style.background = voiceEnabled ? "#2ecc71" : "#555";
                }

                const msg = voiceEnabled ? "Voice alerts activated" : "Voice alerts deactivated";
                speechSynthesis.speak(new SpeechSynthesisUtterance(msg));
                console.log(`🔊 Voice alerts ${voiceEnabled ? "enabled" : "disabled"} by user`);
            }
        });

        function autoVoiceAlert(missingPPE) {
            if (!voiceEnabled || !missingPPE || missingPPE.length === 0) return;
            const msg = `Warning. ${missingPPE.join(" and ")} missing.`;
            console.log("🔊 Voice alert triggered:", msg);
            speechSynthesis.speak(new SpeechSynthesisUtterance(msg));
        }

        // ===== Poll Backend for Latest Violation =====
        setInterval(async () => {
            if (!APP_STATE.liveStreamActive) return;

            try {
                const res = await fetch(`${API_CONFIG.BASE_URL}/api/violations/latest`);
                const data = await res.json();

                if (!data.report_id) return;

                // Update badge
                const badge = document.getElementById("voiceStatus");
                if (badge) {
                    badge.innerText = voiceEnabled ? "🔊 Voice ON" : "🔇 Voice OFF";
                    badge.style.background = voiceEnabled ? "#2ecc71" : "#555";
                }

                // New report → reset alerted PPE
                if (data.report_id !== lastReportId) {
                    lastReportId = data.report_id;
                    alertedPPE.clear();
                }

                // Only alert new PPE items
                const newAlerts = data.missing_ppe.filter(p => !alertedPPE.has(p));
                if (voiceEnabled && newAlerts.length > 0) {
                    newAlerts.forEach(p => alertedPPE.add(p));
                    autoVoiceAlert(newAlerts.map(p => p.replace("NO-", "")));
                }

            } catch (err) {
                console.warn("Violation poll failed", err);
            }
        }, 3000);
        

        // Start live stream
        startBtn.addEventListener('click', async () => {
            try {
                // Disable start button
                startBtn.disabled = true;
                startBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Starting...';

                // Start monitoring on backend
                const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_START}`, {
                    method: 'POST'
                });

                if (!response.ok) {
                    throw new Error('Failed to start monitoring');
                }

                // Sync latest report id to avoid alerting on existing violations
                try {
                    const latestRes = await fetch(`${API_CONFIG.BASE_URL}/api/violations/latest`);
                    if (latestRes.ok) {
                        const latestData = await latestRes.json();
                        if (latestData && latestData.report_id) {
                            lastReportId = latestData.report_id;
                            console.log('Synced lastReportId to', lastReportId);
                        }
                    }
                } catch (err) {
                    console.warn('Failed to sync latest report id', err);
                }

                // Hide placeholder, show stream
                placeholder.style.display = 'none';
                streamImg.style.display = 'block';
                statusIndicator.style.display = 'block';

                // Set stream source
                streamImg.src = `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_STREAM}?t=${Date.now()}`;

                // Enable stop button
                stopBtn.disabled = false;
                startBtn.innerHTML = '<i class="fas fa-play"></i> Start';
                
                // Update state
                APP_STATE.liveStreamActive = true;

            } catch (error) {
                console.error('Error starting live stream:', error);
                alert('Failed to start live monitoring. Please check if the webcam is available.');
                startBtn.disabled = false;
                startBtn.innerHTML = '<i class="fas fa-play"></i> Start';
            }
        });

        // Stop live stream
        stopBtn.addEventListener('click', async () => {
            try {
                // Stop monitoring on backend
                await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_STOP}`, {
                    method: 'POST'
                });

                // Stop stream
                streamImg.src = '';
                streamImg.style.display = 'none';
                placeholder.style.display = 'block';
                statusIndicator.style.display = 'none';

                // Reset buttons
                stopBtn.disabled = true;
                startBtn.disabled = false;
                
                // Update state
                APP_STATE.liveStreamActive = false;

            } catch (error) {
                console.error('Error stopping live stream:', error);
            }
        });

        // Handle stream errors
        streamImg.addEventListener('error', () => {
            console.error('Stream error');
            placeholder.style.display = 'block';
            streamImg.style.display = 'none';
            statusIndicator.style.display = 'none';
            startBtn.disabled = false;
            stopBtn.disabled = true;
        });

        // Check initial status
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_STATUS}`);
            const status = await response.json();
            
            if (status.active) {
                // Stream is already active
                placeholder.style.display = 'none';
                streamImg.style.display = 'block';
                statusIndicator.style.display = 'block';
                streamImg.src = `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_STREAM}?t=${Date.now()}`;
                stopBtn.disabled = false;
                startBtn.disabled = true;
                APP_STATE.liveStreamActive = true;
                // If stream already active, sync latest report to avoid immediate alert
                try {
                    const latestRes = await fetch(`${API_CONFIG.BASE_URL}/api/violations/latest`);
                    if (latestRes.ok) {
                        const latestData = await latestRes.json();
                        if (latestData && latestData.report_id) {
                            lastReportId = latestData.report_id;
                            console.log('Synced lastReportId on init to', lastReportId);
                        }
                    }
                } catch (err) {
                    console.warn('Failed to sync latest report id on init', err);
                }
            }
        } catch (error) {
            console.error('Error checking stream status:', error);
        }
    }
};
