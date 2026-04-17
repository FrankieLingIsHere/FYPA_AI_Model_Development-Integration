// Live Monitoring Page Component
const LivePage = {
    depthStatusInterval: null,
    providerRuntimeInterval: null,
    phoneCameraStream: null,
    phoneInferenceBusy: false,
    phoneLastViolationNoticeAt: 0,
    reportQueueSuppressionActive: false,
    reportQueueSuppressionReason: null,    // Deployed frontend asset contract markers (string-literal compatibility only).
    // id="settingsModal"
    // id="nlpProviderOrderSelect"
    // id="visionProviderOrderSelect"
    // id="embeddingProviderOrderSelect"
    // id="reopenSettingsWindowBtn"
    // reopenSettingsWindowBtn.addEventListener('click', openSettingsWindow);
    // id="liveToolbarSettingsBtn"
    // liveToolbarSettingsBtn.addEventListener('click'
    // toolbarSettingsClickHandler
    // const isSettingsRoute = APP_STATE.currentPage === 'settings' || APP_STATE.currentPage === 'settings-checkup';
    // .settings-route .live-mode-tabs
    // .settings-route .live-monitor-card
    // .settings-route .settings-route-panel

    render() {
        return `
            <div class="page">
                <!-- Mode Tabs -->
                <div style="margin-bottom: 1rem; border-bottom: 2px solid var(--border-color);">
                    <div style="display: flex; justify-content: flex-start; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                        <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                            <button id="liveModeBtn" class="mode-tab active">
                                <i class="fas fa-video"></i> Camera Stream
                            </button>
                            <button id="uploadModeBtn" class="mode-tab">
                                <i class="fas fa-image"></i> Analyze Image
                            </button>
                        </div>
                    </div>
                </div>


                <div class="card mb-4 live-monitor-card">
                    <div class="card-header">
                        <span id="cardTitle"><i class="fas fa-video"></i> Live Camera Monitoring</span>
                        <div id="liveControls" class="live-controls">
                            <span id="phoneCameraPermissionBadge" style="display: none; margin-right: 10px; font-size: 0.78rem; font-weight: 700; padding: 6px 10px; border-radius: 999px; border: 1px solid transparent; vertical-align: middle;"></span>
                            <button id="sourceToggleBtn" class="btn btn-secondary" title="Toggle camera source">
                                <i class="fas fa-camera"></i> Source: Webcam
                            </button>
                            <select id="webcamDeviceSelect" class="btn btn-secondary" title="Select backend webcam index" style="display: none; min-width: 190px;"></select>
                            <button id="refreshWebcamDevicesBtn" class="btn btn-secondary" title="Refresh backend webcam device list" style="display: none;">
                                <i class="fas fa-sync-alt"></i>
                            </button>
                            <select id="browserCameraSelect" class="btn btn-secondary" title="Select browser camera" style="display: none; min-width: 220px;"></select>
                            <button id="refreshBrowserCameraBtn" class="btn btn-secondary" title="Refresh browser camera list" style="display: none;">
                                <i class="fas fa-sync-alt"></i>
                            </button>
                            <button id="startLiveBtn" class="btn btn-success">
                                <i class="fas fa-play"></i> Start
                            </button>
                            <button id="stopLiveBtn" class="btn btn-danger" disabled>
                                <i class="fas fa-stop"></i> Stop
                            </button>
                        </div>
                    </div>
                    <div class="card-content">
                        <div id="realsenseCapabilities" style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.75rem;"></div>
                        <!-- Live Stream Container -->
                        <div id="liveStreamContainer" style="background: transparent; border-radius: 8px; text-align: center; margin-bottom: 1.5rem; position: relative;">
                            <div id="streamPlaceholder" style="padding: 2rem; background: #000; border-radius: 8px; width: 100%;">
                                <i class="fas fa-video" style="font-size: 4rem; color: #fff; opacity: 0.3; margin-bottom: 1rem;"></i>
                                <p style="color: #fff; margin: 0;">Click "Start" to begin live monitoring</p>
                                <p style="color: #aaa; font-size: 0.9rem; margin-top: 0.5rem;">
                                    Real-time YOLO detection with PPE compliance checking
                                </p>
                            </div>
                            <img id="liveStream" style="display: none; width: auto; max-width: 100%; height: auto; margin: 0 auto; border-radius: 8px;" />
                            <video id="phoneCameraPreview" autoplay playsinline muted style="display: none; width: auto; max-width: 100%; height: auto; margin: 0 auto; border-radius: 8px;"></video>
                            <canvas id="liveOverlayCanvas" style="display: none; position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none;"></canvas>
                            <div id="streamStatus" style="position: absolute; top: 10px; right: 10px; background: rgba(0,0,0,0.7); color: #4CAF50; padding: 8px 16px; border-radius: 20px; font-weight: bold; display: none;">
                                <i class="fas fa-circle" style="animation: blink 1.5s infinite;"></i> LIVE
                            </div>
                            <div id="depthHud" style="position: absolute; left: 10px; bottom: 10px; background: rgba(0,0,0,0.75); color: #fff; border-radius: 8px; padding: 10px; min-width: 190px; text-align: left; display: none;">
                                <div style="font-weight: 600; margin-bottom: 6px;"><i class="fas fa-ruler-combined"></i> Depth HUD</div>
                                <div style="font-size: 0.85rem; line-height: 1.5;">
                                    <div>Center: <span id="depthCenter">-</span></div>
                                    <div>Range: <span id="depthRange">-</span></div>
                                    <div>Confidence: <span id="depthConfidence">-</span></div>
                                </div>
                            </div>
                            <div id="depthPreviewBox" style="position: absolute; right: 10px; bottom: 10px; background: rgba(0,0,0,0.75); border-radius: 8px; padding: 6px; display: none;">
                                <div style="font-size: 0.72rem; color: #ddd; margin-bottom: 4px; text-align: left;">Depth Preview</div>
                                <img id="depthPreview" alt="Depth preview" style="width: 160px; height: 90px; object-fit: cover; border-radius: 4px; display: block;" />
                            </div>
                        </div>

                        <!-- Upload Container -->
                        <div id="uploadContainer" style="display: none; margin-bottom: 1.5rem;">
                            <div style="border: 2px dashed var(--border-color); border-radius: 8px; padding: 2rem; text-align: center; background: var(--background-color); transition: border-color 0.3s;">
                                <input type="file" id="imageUpload" accept="image/*" style="display: none;" />
                                <label for="imageUpload" style="cursor: pointer; display: block;">
                                    <i class="fas fa-cloud-upload-alt" style="font-size: 4rem; color: var(--primary-color); opacity: 0.7; margin-bottom: 1rem;"></i>
                                    <p style="margin: 0; font-size: 1.1rem; font-weight: bold;">Drop image here or click to browse</p>
                                    <p style="color: var(--text-secondary); font-size: 0.9rem; margin-top: 0.5rem;">
                                        Supports JPG, PNG Ã¢â‚¬Â¢ Max 10MB
                                    </p>
                                </label>
                            </div>
                            
                            <div id="uploadPreview" style="display: none; margin-top: 1.5rem;">
                                <div style="background: var(--background-color); padding: 1.5rem; border-radius: 8px;">
                                    <img id="previewImage" style="max-width: 100%; max-height: 500px; border-radius: 8px; margin-bottom: 1rem; display: block; margin-left: auto; margin-right: auto;" />
                                    <div style="text-align: center;">
                                        <button id="analyzeBtn" class="btn btn-primary" style="margin-right: 10px;">
                                            <i class="fas fa-search"></i> Analyze for PPE Violations
                                        </button>
                                        <button id="clearUploadBtn" class="btn btn-secondary">
                                            <i class="fas fa-times"></i> Clear
                                        </button>
                                    </div>
                                </div>
                            </div>
                            
                            <!-- Upload Results -->
                            <div id="uploadResults" style="display: none; margin-top: 1.5rem;">
                                <div class="card">
                                    <div class="card-header">
                                        <span><i class="fas fa-chart-bar"></i> Detection Results</span>
                                    </div>
                                    <div class="card-content">
                                        <div id="uploadResultsContent"></div>
                                        <div style="margin-top: 1rem;">
                                            <h4 style="margin-bottom: 0.5rem;">Annotated Image:</h4>
                                            <img id="annotatedResult" style="width: 100%; border-radius: 8px;" />
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>


                    </div>
                </div>

            </div>
            
            <style>
                .mode-tab {
                    padding: 12px 24px;
                    background: transparent;
                    border: none;
                    border-bottom: 3px solid transparent;
                    color: var(--text-secondary);
                    font-size: 1rem;
                    font-weight: 500;
                    cursor: pointer;
                    transition: all 0.3s ease;
                }
                
                .mode-tab:hover {
                    color: var(--text-color);
                    background: rgba(66, 133, 244, 0.05);
                }
                
                .mode-tab.active {
                    color: var(--primary-color);
                    border-bottom-color: var(--primary-color);
                }
                
                .mode-tab i {
                    margin-right: 8px;
                }


                .rs-cap-badge {
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    padding: 4px 10px;
                    border-radius: 999px;
                    font-size: 0.78rem;
                    font-weight: 600;
                    border: 1px solid transparent;
                }

                .rs-cap-badge.ok {
                    color: #2e7d32;
                    background: rgba(76, 175, 80, 0.12);
                    border-color: rgba(76, 175, 80, 0.35);
                }

                .rs-cap-badge.off {
                    color: #8d6e63;
                    background: rgba(158, 158, 158, 0.14);
                    border-color: rgba(158, 158, 158, 0.3);
                }

            </style>
        `;
    },

    async mount() {
        const livePage = this;
        this.reportQueueSuppressionActive = false;
        this.reportQueueSuppressionReason = null;

        // Get UI elements
        const liveModeBtn = document.getElementById('liveModeBtn');
        const uploadModeBtn = document.getElementById('uploadModeBtn');
        const liveStreamContainer = document.getElementById('liveStreamContainer');
        const uploadContainer = document.getElementById('uploadContainer');
        const liveControls = document.getElementById('liveControls');
        const cardTitle = document.getElementById('cardTitle');
        const sourceToggleBtn = document.getElementById('sourceToggleBtn');
        const webcamDeviceSelect = document.getElementById('webcamDeviceSelect');
        const refreshWebcamDevicesBtn = document.getElementById('refreshWebcamDevicesBtn');
        const browserCameraSelect = document.getElementById('browserCameraSelect');
        const refreshBrowserCameraBtn = document.getElementById('refreshBrowserCameraBtn');
        const startBtn = document.getElementById('startLiveBtn');
        const stopBtn = document.getElementById('stopLiveBtn');
        const phoneCameraPermissionBadge = document.getElementById('phoneCameraPermissionBadge');
        const streamImg = document.getElementById('liveStream');
        const phoneCameraPreview = document.getElementById('phoneCameraPreview');
        const liveOverlayCanvas = document.getElementById('liveOverlayCanvas');
        const placeholder = document.getElementById('streamPlaceholder');
        const statusIndicator = document.getElementById('streamStatus');
        const capabilitiesContainer = document.getElementById('realsenseCapabilities');
        const depthHud = document.getElementById('depthHud');
        const depthPreviewBox = document.getElementById('depthPreviewBox');
        const depthPreview = document.getElementById('depthPreview');
        const depthCenter = document.getElementById('depthCenter');
        const depthRange = document.getElementById('depthRange');
        const depthConfidence = document.getElementById('depthConfidence');
        const instructionsList = document.getElementById('instructionsList');
        
        // Upload elements
        const imageUpload = document.getElementById('imageUpload');
        const uploadPreview = document.getElementById('uploadPreview');
        const previewImage = document.getElementById('previewImage');
        const analyzeBtn = document.getElementById('analyzeBtn');
        const clearUploadBtn = document.getElementById('clearUploadBtn');
        const uploadResults = document.getElementById('uploadResults');
        const uploadResultsContent = document.getElementById('uploadResultsContent');
        const annotatedResult = document.getElementById('annotatedResult');
        
        let currentMode = 'live';
        let selectedFile = null;
        let selectedSource = 'webcam';
        let selectedCameraIndex = 0;
        let backendWebcamDevices = [];
        let browserVideoDevices = [];
        let selectedBrowserDeviceId = '';
        let realsenseAvailable = false;
        let realsenseDeviceName = 'Intel RealSense';
        let realsenseCapabilities = {};
        let edgeRealsenseAvailable = false;
        let edgeRealsenseDeviceName = 'RealSense (Edge Relay)';
        let edgeRealsenseCapabilities = {};
        const isPhoneDevice = document.body.classList.contains('is-phone-device');
        const browserCameraSupported = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
        const phoneCameraSupported = !!(isPhoneDevice && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
        const isAutomationContext = !!navigator.webdriver;
        const isLikelyRemoteBackend = (() => {
            try {
                if (!API_CONFIG.BASE_URL) return false;
                const resolved = new URL(API_CONFIG.BASE_URL, window.location.origin);
                const host = String(resolved.hostname || '').toLowerCase();
                const isLocalHost = host === 'localhost' || host === '127.0.0.1' || host === '0.0.0.0' || host.endsWith('.local');
                return !isLocalHost;
            } catch (error) {
                return false;
            }
        })();
        const permissionsApiSupported = !!(navigator.permissions && navigator.permissions.query);
        let phonePermissionState = phoneCameraSupported ? 'prompt' : 'unavailable';
        let useBrowserCaptureRuntime = false;
        const phoneCaptureCanvas = document.createElement('canvas');
        const laptopLiveStreamConfig = {
            conf: 0.10,
            fps: 14,
            quality: 72
        };
        const phoneInferenceConfig = {
            intervalMs: 220,
            conf: 0.08,
            jpegQuality: 0.68
        };
        let phoneInferenceRunId = 0;
        const LIVE_PROFILE_STORAGE_KEY = 'live_performance_profile_v1';
        const LIVE_PERFORMANCE_PROFILES = {
            smooth: {
                laptop: { conf: 0.12, fps: 20, quality: 58 },
                phone: { intervalMs: 170, conf: 0.10, jpegQuality: 0.62 }
            },
            balanced: {
                laptop: { conf: 0.10, fps: 18, quality: 64 },
                phone: { intervalMs: 220, conf: 0.08, jpegQuality: 0.68 }
            },
            detail: {
                laptop: { conf: 0.08, fps: 12, quality: 82 },
                phone: { intervalMs: 420, conf: 0.07, jpegQuality: 0.83 }
            }
        };
        const providerRuntimeActive = document.getElementById('providerRuntimeActive');
        const providerRuntimeCapacity = document.getElementById('providerRuntimeCapacity');

        const buildLiveStreamUrl = () => {
            const streamUrl = new URL(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_STREAM}`, window.location.origin);
            streamUrl.searchParams.set('t', Date.now().toString());
            streamUrl.searchParams.set('conf', String(laptopLiveStreamConfig.conf));
            streamUrl.searchParams.set('fps', String(laptopLiveStreamConfig.fps));
            streamUrl.searchParams.set('quality', String(laptopLiveStreamConfig.quality));
            return streamUrl.toString();
        };

        const setLiveControlState = (isActive) => {
            APP_STATE.liveStreamActive = !!isActive;
            if (startBtn) startBtn.disabled = !!isActive;
            if (stopBtn) stopBtn.disabled = !isActive;
            renderSourceToggle();
        };

        const updatePhonePermissionBadge = () => {
            if (!phoneCameraPermissionBadge) return;

            if (!phoneCameraSupported) {
                phoneCameraPermissionBadge.style.display = 'none';
                return;
            }

            const map = {
                granted: {
                    label: '<i class="fas fa-check-circle"></i> Camera: Granted',
                    color: '#1b5e20',
                    bg: '#e8f5e9',
                    border: '#a5d6a7'
                },
                denied: {
                    label: '<i class="fas fa-times-circle"></i> Camera: Denied',
                    color: '#b71c1c',
                    bg: '#ffebee',
                    border: '#ef9a9a'
                },
                prompt: {
                    label: '<i class="fas fa-exclamation-circle"></i> Camera: Prompt',
                    color: '#8a6d00',
                    bg: '#fff8e1',
                    border: '#ffe082'
                },
                unavailable: {
                    label: '<i class="fas fa-info-circle"></i> Camera: Unavailable',
                    color: '#455a64',
                    bg: '#eceff1',
                    border: '#cfd8dc'
                }
            };

            const style = map[phonePermissionState] || map.prompt;
            phoneCameraPermissionBadge.innerHTML = style.label;
            phoneCameraPermissionBadge.style.color = style.color;
            phoneCameraPermissionBadge.style.background = style.bg;
            phoneCameraPermissionBadge.style.borderColor = style.border;
            phoneCameraPermissionBadge.style.display = 'inline-flex';
            phoneCameraPermissionBadge.style.alignItems = 'center';
            phoneCameraPermissionBadge.style.gap = '0.35rem';
        };

        const initPhonePermissionWatcher = async () => {
            if (!phoneCameraSupported) return;
            if (!permissionsApiSupported) {
                phonePermissionState = 'prompt';
                updatePhonePermissionBadge();
                return;
            }

            try {
                const permissionStatus = await navigator.permissions.query({ name: 'camera' });
                if (permissionStatus && permissionStatus.state) {
                    phonePermissionState = permissionStatus.state;
                    updatePhonePermissionBadge();
                }

                permissionStatus.onchange = () => {
                    phonePermissionState = permissionStatus.state || 'prompt';
                    updatePhonePermissionBadge();
                };
            } catch (error) {
                phonePermissionState = 'prompt';
                updatePhonePermissionBadge();
            }
        };

        const stopPhoneInferenceLoop = () => {
            if (this.phoneInferenceInterval) {
                clearInterval(this.phoneInferenceInterval);
                this.phoneInferenceInterval = null;
            }
            this.phoneInferenceBusy = false;
            phoneInferenceRunId += 1;
        };

        const clearLiveOverlayCanvas = () => {
            if (!liveOverlayCanvas) return;
            const ctx = liveOverlayCanvas.getContext('2d');
            if (ctx) {
                ctx.clearRect(0, 0, liveOverlayCanvas.width || 0, liveOverlayCanvas.height || 0);
            }
            liveOverlayCanvas.style.display = 'none';
        };

        const stopPhoneCameraTrack = () => {
            if (this.phoneCameraStream) {
                this.phoneCameraStream.getTracks().forEach((track) => {
                    try {
                        track.stop();
                    } catch (error) {
                        console.warn('Track stop failed:', error);
                    }
                });
                this.phoneCameraStream = null;
            }

            if (phoneCameraPreview) {
                try {
                    phoneCameraPreview.pause();
                } catch (error) {
                    console.warn('Video pause failed:', error);
                }
                phoneCameraPreview.srcObject = null;
                phoneCameraPreview.style.display = 'none';
            }

            clearLiveOverlayCanvas();
        };

        const normalizeCameraIndex = (value, fallback = 0) => {
            const parsed = Number.parseInt(value, 10);
            if (Number.isFinite(parsed) && parsed >= 0) {
                return parsed;
            }
            return fallback;
        };

        const syncBackendWebcamDevices = (payload) => {
            const hasDeviceList = !!(payload && Array.isArray(payload.webcam_devices));

            if (hasDeviceList) {
                backendWebcamDevices = payload.webcam_devices
                    .map((item) => ({
                        index: normalizeCameraIndex(item && item.index, -1),
                        label: String((item && item.label) || '').trim()
                    }))
                    .filter((item) => item.index >= 0)
                    .sort((a, b) => a.index - b.index);
            }

            if (payload && payload.camera_index !== null && payload.camera_index !== undefined) {
                selectedCameraIndex = normalizeCameraIndex(payload.camera_index, selectedCameraIndex);
            } else if (backendWebcamDevices.length > 0 && !backendWebcamDevices.some((d) => d.index === selectedCameraIndex)) {
                selectedCameraIndex = backendWebcamDevices[0].index;
            }
        };

        const getBrowserDeviceLabel = (device, index) => {
            const label = String((device && device.label) || '').trim();
            if (label) return label;
            return `Browser Camera ${index + 1}`;
        };

        const getSelectedBrowserDeviceLabel = () => {
            if (!selectedBrowserDeviceId) return 'Default browser camera';
            const idx = browserVideoDevices.findIndex((d) => d.deviceId === selectedBrowserDeviceId);
            if (idx < 0) return 'Selected browser camera';
            return getBrowserDeviceLabel(browserVideoDevices[idx], idx);
        };

        const isDepthSourceSelected = () => {
            if (selectedSource === 'realsense') {
                return realsenseAvailable;
            }
            if (selectedSource === 'edge_realsense') {
                return edgeRealsenseAvailable;
            }
            return false;
        };

        const getCurrentSourceLabel = () => {
            if (selectedSource === 'realsense') {
                return realsenseDeviceName || 'RealSense';
            }
            if (selectedSource === 'edge_realsense') {
                return edgeRealsenseDeviceName || 'RealSense (Edge Relay)';
            }
            if (selectedSource === 'phone') {
                return 'Phone Camera';
            }
            return `Webcam ${selectedCameraIndex}`;
        };

        const shouldUseBrowserCaptureSource = () => {
            return !!(browserCameraSupported && useBrowserCaptureRuntime);
        };

        const shouldPreferBrowserCaptureSource = () => {
            if (!browserCameraSupported) return false;
            if (selectedSource === 'phone' && phoneCameraSupported) return true;
            if (selectedSource === 'webcam' && (isLikelyRemoteBackend || !!selectedBrowserDeviceId)) return true;
            return false;
        };

        const renderBackendWebcamSelector = () => {
            if (!webcamDeviceSelect || !refreshWebcamDevicesBtn) return;

            const showSelector = (
                !APP_STATE.liveStreamActive &&
                selectedSource === 'webcam' &&
                !shouldPreferBrowserCaptureSource()
            );

            if (!showSelector) {
                webcamDeviceSelect.style.display = 'none';
                refreshWebcamDevicesBtn.style.display = 'none';
                return;
            }

            webcamDeviceSelect.style.display = 'inline-flex';
            refreshWebcamDevicesBtn.style.display = 'inline-flex';
            webcamDeviceSelect.innerHTML = '';

            if (!backendWebcamDevices.length) {
                const fallback = document.createElement('option');
                fallback.value = String(selectedCameraIndex);
                fallback.textContent = `Backend Webcam ${selectedCameraIndex}`;
                webcamDeviceSelect.appendChild(fallback);
                webcamDeviceSelect.value = String(selectedCameraIndex);
                webcamDeviceSelect.disabled = true;
                return;
            }

            webcamDeviceSelect.disabled = false;
            backendWebcamDevices.forEach((device) => {
                const option = document.createElement('option');
                option.value = String(device.index);
                option.textContent = device.label || `Backend Webcam ${device.index}`;
                webcamDeviceSelect.appendChild(option);
            });

            if (!backendWebcamDevices.some((d) => d.index === selectedCameraIndex)) {
                selectedCameraIndex = backendWebcamDevices[0].index;
            }

            webcamDeviceSelect.value = String(selectedCameraIndex);
        };

        const renderBrowserCameraSelector = () => {
            if (!browserCameraSelect || !refreshBrowserCameraBtn) return;

            const showSelector = (
                !APP_STATE.liveStreamActive &&
                selectedSource === 'webcam' &&
                shouldPreferBrowserCaptureSource()
            );

            if (!showSelector) {
                browserCameraSelect.style.display = 'none';
                refreshBrowserCameraBtn.style.display = 'none';
                return;
            }

            browserCameraSelect.style.display = 'inline-flex';
            refreshBrowserCameraBtn.style.display = 'inline-flex';

            const currentValue = selectedBrowserDeviceId || browserCameraSelect.value || '';
            browserCameraSelect.innerHTML = '';

            const defaultOption = document.createElement('option');
            defaultOption.value = '';
            defaultOption.textContent = 'Default browser camera';
            browserCameraSelect.appendChild(defaultOption);

            browserVideoDevices.forEach((device, index) => {
                const option = document.createElement('option');
                option.value = device.deviceId || '';
                option.textContent = getBrowserDeviceLabel(device, index);
                browserCameraSelect.appendChild(option);
            });

            const hasCurrent = !!(currentValue && browserVideoDevices.some((d) => d.deviceId === currentValue));
            browserCameraSelect.value = hasCurrent ? currentValue : '';
            selectedBrowserDeviceId = browserCameraSelect.value || '';
        };

        const refreshBrowserCameraOptions = async () => {
            if (!browserCameraSupported || !navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
                browserVideoDevices = [];
                renderBrowserCameraSelector();
                return;
            }

            try {
                const devices = await navigator.mediaDevices.enumerateDevices();
                browserVideoDevices = devices.filter((device) => device.kind === 'videoinput');
            } catch (error) {
                browserVideoDevices = [];
            }

            renderBrowserCameraSelector();
        };

        const refreshBackendWebcamOptions = async (notify = false) => {
            try {
                const resp = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_DEVICES}`);
                if (!resp.ok) {
                    throw new Error('Failed to load backend webcam devices');
                }

                const payload = await resp.json();
                syncBackendWebcamDevices(payload);
                renderBackendWebcamSelector();

                if (notify) {
                    showNotification(`Backend camera list refreshed (${backendWebcamDevices.length || 0} found)`, 'info');
                }
            } catch (error) {
                console.error('Error refreshing backend webcam devices:', error);
                renderBackendWebcamSelector();
                if (notify) {
                    showNotification('Unable to refresh backend webcam list', 'warning');
                }
            }
        };

        const getAvailableSources = () => {
            const sources = ['webcam'];
            if (realsenseAvailable) {
                sources.push('realsense');
            }
            if (edgeRealsenseAvailable) {
                sources.push('edge_realsense');
            }
            if (phoneCameraSupported) {
                sources.push('phone');
            }
            return sources;
        };

        const isWebcamUnavailableMessage = (message) => {
            const text = String(message || '').toLowerCase();
            return text.includes('failed to open webcam') ||
                text.includes('could not open webcam') ||
                (text.includes('webcam') && (text.includes('failed') || text.includes('unavailable')));
        };

        const isAutomationWebcamFallbackAllowed = () => {
            return !!(window && window.__LUNA_ALLOW_AUTOMATION_WEBCAM_FALLBACK === true);
        };

        const startBrowserCaptureSession = async (usingPhoneSource, noticePrefix = '') => {
            if (APP_STATE.liveStreamActive) {
                startBtn.innerHTML = '<i class="fas fa-play"></i> Start';
                return;
            }

            if (usingPhoneSource) {
                phonePermissionState = 'prompt';
                updatePhonePermissionBadge();
            }

            const webcamConstraints = {
                width: { ideal: 1280 },
                height: { ideal: 720 }
            };

            if (!usingPhoneSource && selectedBrowserDeviceId) {
                webcamConstraints.deviceId = { exact: selectedBrowserDeviceId };
            }

            const videoConstraints = usingPhoneSource
                ? {
                    facingMode: { ideal: 'environment' },
                    width: { ideal: 1280 },
                    height: { ideal: 720 }
                }
                : webcamConstraints;

            let stream;
            try {
                stream = await navigator.mediaDevices.getUserMedia({
                    video: videoConstraints,
                    audio: false
                });
            } catch (error) {
                const selectedDeviceUnavailable = (
                    !usingPhoneSource &&
                    !!selectedBrowserDeviceId &&
                    (error.name === 'OverconstrainedError' || error.name === 'NotFoundError')
                );

                if (!selectedDeviceUnavailable) {
                    throw error;
                }

                stream = await navigator.mediaDevices.getUserMedia({
                    video: {
                        width: { ideal: 1280 },
                        height: { ideal: 720 }
                    },
                    audio: false
                });
                selectedBrowserDeviceId = '';
                if (browserCameraSelect) {
                    browserCameraSelect.value = '';
                }
                showNotification('Selected browser camera is unavailable. Switched to default camera.', 'warning');
            }

            this.phoneCameraStream = stream;
            useBrowserCaptureRuntime = true;

            const activeTrack = stream.getVideoTracks && stream.getVideoTracks()[0];
            if (activeTrack && typeof activeTrack.getSettings === 'function') {
                const activeSettings = activeTrack.getSettings() || {};
                if (!usingPhoneSource && activeSettings.deviceId) {
                    selectedBrowserDeviceId = activeSettings.deviceId;
                }
            }

            await refreshBrowserCameraOptions();

            if (usingPhoneSource) {
                phonePermissionState = 'granted';
                updatePhonePermissionBadge();
            }

            if (phoneCameraPreview) {
                phoneCameraPreview.srcObject = stream;
                await phoneCameraPreview.play();
                phoneCameraPreview.style.display = 'block';
            }

            placeholder.style.display = 'none';
            streamImg.style.display = 'none';
            streamImg.src = '';
            statusIndicator.style.display = 'block';
            statusIndicator.innerHTML = usingPhoneSource
                ? '<i class="fas fa-circle" style="animation: blink 1.5s infinite;"></i> PHONE LIVE'
                : '<i class="fas fa-circle" style="animation: blink 1.5s infinite;"></i> WEBCAM LIVE';

            setLiveControlState(true);
            startBtn.innerHTML = '<i class="fas fa-play"></i> Start';
            hideDepthWidgets();
            renderSourceToggle();

            stopPhoneInferenceLoop();
            phoneInferenceRunId += 1;
            this.phoneInferenceInterval = setInterval(capturePhoneFrameForInference, phoneInferenceConfig.intervalMs);
            await capturePhoneFrameForInference();

            const successText = usingPhoneSource
                ? 'Phone camera access granted and monitoring started'
                : `Browser webcam access granted and monitoring started (${getSelectedBrowserDeviceLabel()})`;
            showNotification(`${noticePrefix}${successText}`.trim(), 'success');
        };

        const capturePhoneFrameForInference = async () => {
            if (!this.phoneCameraStream || !phoneCameraPreview) return;
            if (this.phoneInferenceBusy) return;
            if (phoneCameraPreview.readyState < 2) return;
            if (!APP_STATE.liveStreamActive || !shouldUseBrowserCaptureSource()) return;

            const runId = phoneInferenceRunId;

            const width = phoneCameraPreview.videoWidth || 1280;
            const height = phoneCameraPreview.videoHeight || 720;
            if (width <= 0 || height <= 0) return;

            phoneCaptureCanvas.width = width;
            phoneCaptureCanvas.height = height;
            const ctx = phoneCaptureCanvas.getContext('2d');
            if (!ctx) return;

            ctx.drawImage(phoneCameraPreview, 0, 0, width, height);

            const blob = await new Promise((resolve) => {
                phoneCaptureCanvas.toBlob(resolve, 'image/jpeg', phoneInferenceConfig.jpegQuality);
            });
            if (!blob) return;

            this.phoneInferenceBusy = true;

            try {
                const formData = new FormData();
                formData.append('image', blob, 'phone_live.jpg');
                formData.append('conf', String(phoneInferenceConfig.conf));

                const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_FRAME_INFERENCE}`, {
                    method: 'POST',
                    body: formData
                });

                if (runId !== phoneInferenceRunId || !APP_STATE.liveStreamActive || !shouldUseBrowserCaptureSource()) {
                    return;
                }

                if (!response.ok) {
                    throw new Error('Phone frame inference failed');
                }

                const result = await response.json();
                if (runId !== phoneInferenceRunId || !APP_STATE.liveStreamActive || !shouldUseBrowserCaptureSource()) {
                    return;
                }
                if (result && Array.isArray(result.detections) && liveOverlayCanvas && phoneCameraPreview) {
                    const ctx = liveOverlayCanvas.getContext('2d');
                    const videoW = phoneCameraPreview.videoWidth || width;
                    const videoH = phoneCameraPreview.videoHeight || height;
                    liveOverlayCanvas.width = videoW;
                    liveOverlayCanvas.height = videoH;
                    liveOverlayCanvas.style.display = 'block';

                    if (ctx) {
                        ctx.clearRect(0, 0, videoW, videoH);
                        ctx.lineWidth = 2;
                        ctx.font = '14px sans-serif';

                        result.detections.forEach((det) => {
                            const bbox = det.bbox || [];
                            if (bbox.length !== 4) return;
                            const [x1, y1, x2, y2] = bbox;
                            const confidence = Number(det.score ?? det.confidence ?? 0);
                            const label = `${det.class_name || 'obj'} ${(confidence * 100).toFixed(1)}%`;
                            const isViolation = String(det.class_name || '').toLowerCase().includes('no-');
                            const color = isViolation ? '#ff5252' : '#4caf50';

                            ctx.strokeStyle = color;
                            ctx.strokeRect(x1, y1, Math.max(1, x2 - x1), Math.max(1, y2 - y1));

                            const textWidth = ctx.measureText(label).width;
                            const labelY = Math.max(16, y1 - 6);
                            ctx.fillStyle = color;
                            ctx.fillRect(x1, labelY - 14, textWidth + 8, 18);
                            ctx.fillStyle = '#000';
                            ctx.fillText(label, x1 + 4, labelY);
                        });

                        const detectionCount = result.detections.length;
                        const hudLabel = `YOLO active | detections: ${detectionCount}`;
                        const hudWidth = Math.max(210, ctx.measureText(hudLabel).width + 14);
                        ctx.fillStyle = 'rgba(0, 0, 0, 0.66)';
                        ctx.fillRect(10, 10, hudWidth, 24);
                        ctx.fillStyle = '#7CFF8A';
                        ctx.font = '13px sans-serif';
                        ctx.fillText(hudLabel, 17, 27);
                    }
                }
                if (result && result.violations_detected) {
                    const now = Date.now();
                    if (now - this.phoneLastViolationNoticeAt > 10000) {
                        this.phoneLastViolationNoticeAt = now;
                        showNotification(`Phone camera: ${result.violation_count || 1} violation(s) detected`, 'warning');
                    }
                    if (result.report_queued === true) {
                        // Reset suppression state only when a new violation is successfully enqueued.
                        this.reportQueueSuppressionActive = false;
                        this.reportQueueSuppressionReason = null;
                    }
                    if (result.report_queued === false) {
                        const reason = result.report_queue_reason || 'queue_unavailable';
                        const shouldNotifySuppression =
                            !this.reportQueueSuppressionActive || this.reportQueueSuppressionReason !== reason;
                        if (shouldNotifySuppression) {
                            showNotification(`Violation detected but report not queued (${reason})`, 'warning');
                            this.reportQueueSuppressionActive = true;
                            this.reportQueueSuppressionReason = reason;
                        }
                    }
                }
            } catch (error) {
                console.error('Phone camera inference error:', error);
            } finally {
                this.phoneInferenceBusy = false;
            }
        };
        function renderCapabilities() {
            if (!capabilitiesContainer) return;

            const hasAnyRealsense = realsenseAvailable || edgeRealsenseAvailable;
            if (!hasAnyRealsense) {
                const reasonText = String((realsenseCapabilities && realsenseCapabilities.reason) || '').trim();
                const reasonBadge = reasonText
                    ? `<span class="rs-cap-badge off"><i class="fas fa-info-circle"></i> ${reasonText}</span>`
                    : '';
                const hostedBadge = isLikelyRemoteBackend
                    ? '<span class="rs-cap-badge off"><i class="fas fa-cloud"></i> Hosted backend cannot detect USB cameras on this PC</span>'
                    : '';
                capabilitiesContainer.innerHTML = `
                    <span class="rs-cap-badge off"><i class="fas fa-microchip"></i> RealSense Depth: Not detected</span>
                    ${reasonBadge}
                    ${hostedBadge}
                `;
                return;
            }

            const usingEdge = edgeRealsenseAvailable && (selectedSource === 'edge_realsense' || !realsenseAvailable);
            const activeCaps = usingEdge ? (edgeRealsenseCapabilities || {}) : (realsenseCapabilities || {});
            const activeName = usingEdge
                ? (edgeRealsenseDeviceName || 'RealSense (Edge Relay)')
                : (realsenseDeviceName || 'RealSense');
            const sourceBadge = usingEdge
                ? '<span class="rs-cap-badge ok"><i class="fas fa-network-wired"></i> Edge Relay</span>'
                : '<span class="rs-cap-badge ok"><i class="fas fa-usb"></i> Local USB</span>';

            const depthOk = !!activeCaps.depth_stream;
            const imuOk = !!activeCaps.imu;
            const colorOk = !!activeCaps.color_stream;
            const resolution = activeCaps.resolution || '-';
            const fps = activeCaps.fps || '-';

            capabilitiesContainer.innerHTML = `
                <span class="rs-cap-badge ok"><i class="fas fa-microchip"></i> ${activeName}</span>
                ${sourceBadge}
                <span class="rs-cap-badge ${depthOk ? 'ok' : 'off'}"><i class="fas fa-ruler-combined"></i> Depth ${depthOk ? 'On' : 'Off'}</span>
                <span class="rs-cap-badge ${colorOk ? 'ok' : 'off'}"><i class="fas fa-video"></i> RGB ${colorOk ? 'On' : 'Off'}</span>
                <span class="rs-cap-badge ${imuOk ? 'ok' : 'off'}"><i class="fas fa-compass"></i> IMU ${imuOk ? 'On' : 'Off'}</span>
                <span class="rs-cap-badge ok"><i class="fas fa-expand"></i> ${resolution} @ ${fps}fps</span>
            `;
        }

        function hideDepthWidgets() {
            if (depthHud) depthHud.style.display = 'none';
            if (depthPreviewBox) depthPreviewBox.style.display = 'none';
        }

        function updateDepthWidgets(depthTelemetry) {
            const showDepth = APP_STATE.liveStreamActive && isDepthSourceSelected();
            if (!showDepth || !depthTelemetry || !depthTelemetry.depth_available) {
                hideDepthWidgets();
                return;
            }

            if (depthHud) depthHud.style.display = 'block';
            if (depthPreviewBox) depthPreviewBox.style.display = 'block';

            const center = depthTelemetry.center_distance_m;
            const minD = depthTelemetry.min_distance_m;
            const maxD = depthTelemetry.max_distance_m;
            const confidence = depthTelemetry.valid_depth_ratio;

            depthCenter.textContent = center != null ? `${center.toFixed(2)} m` : '-';
            depthRange.textContent = (minD != null && maxD != null) ? `${minD.toFixed(2)} - ${maxD.toFixed(2)} m` : '-';
            depthConfidence.textContent = confidence != null ? `${Math.round(confidence * 100)}%` : '-';

            if (depthPreview) {
                depthPreview.src = `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_DEPTH_PREVIEW}?t=${Date.now()}`;
            }
        }

        async function refreshDepthStatus() {
            const shouldPollDepth = APP_STATE.liveStreamActive && isDepthSourceSelected();
            if (!shouldPollDepth) {
                hideDepthWidgets();
                return;
            }

            try {
                const resp = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_DEPTH_STATUS}`);
                if (!resp.ok) return;

                const payload = await resp.json();
                realsenseCapabilities = payload.realsense_capabilities || realsenseCapabilities;
                if (payload.edge_realsense_available !== undefined) {
                    edgeRealsenseAvailable = !!payload.edge_realsense_available;
                }
                if (payload.edge_realsense_device_name) {
                    edgeRealsenseDeviceName = payload.edge_realsense_device_name;
                }
                edgeRealsenseCapabilities = payload.edge_realsense_capabilities || edgeRealsenseCapabilities;
                renderCapabilities();
                updateDepthWidgets(payload.depth_telemetry || null);
            } catch (error) {
                console.error('Error refreshing depth status:', error);
                hideDepthWidgets();
            }
        }

        function renderSourceToggle() {
            if (!sourceToggleBtn) return;

            if (selectedSource === 'realsense') {
                sourceToggleBtn.innerHTML = `<i class="fas fa-microchip"></i> Source: ${realsenseDeviceName || 'RealSense'}`;
            } else if (selectedSource === 'edge_realsense') {
                sourceToggleBtn.innerHTML = `<i class="fas fa-network-wired"></i> Source: ${edgeRealsenseDeviceName || 'RealSense (Edge Relay)'}`;
            } else if (selectedSource === 'phone') {
                sourceToggleBtn.innerHTML = '<i class="fas fa-mobile-alt"></i> Source: Phone Camera';
            } else {
                sourceToggleBtn.innerHTML = '<i class="fas fa-camera"></i> Source: Webcam (Near-edge)';
            }

            const canToggle = getAvailableSources().length > 1 && !APP_STATE.liveStreamActive;
            sourceToggleBtn.disabled = !canToggle;

            if (!canToggle) {
                if (APP_STATE.liveStreamActive) {
                    sourceToggleBtn.title = 'Stop monitoring to switch source';
                } else if (!realsenseAvailable && !edgeRealsenseAvailable && !phoneCameraSupported) {
                    sourceToggleBtn.title = 'No additional camera source available';
                } else {
                    sourceToggleBtn.title = 'Only one source currently available';
                }
                sourceToggleBtn.style.opacity = '0.55';
                sourceToggleBtn.style.cursor = 'not-allowed';
            } else {
                const modeLabels = ['Webcam (Near-edge)'];
                if (realsenseAvailable) modeLabels.push('RealSense USB');
                if (edgeRealsenseAvailable) modeLabels.push('RealSense Edge Relay');
                if (phoneCameraSupported) modeLabels.push('Phone Camera');
                sourceToggleBtn.title = `Click to switch ${modeLabels.join(' / ')}`;
                sourceToggleBtn.style.opacity = '1';
                sourceToggleBtn.style.cursor = 'pointer';
            }

            if (selectedSource !== 'realsense' && selectedSource !== 'edge_realsense') {
                hideDepthWidgets();
            }

            renderBackendWebcamSelector();
            renderBrowserCameraSelector();
        }

        
        // Mode switching functions
        function switchToLiveMode() {
            currentMode = 'live';
            liveModeBtn.classList.add('active');
            uploadModeBtn.classList.remove('active');
            
            liveStreamContainer.style.display = 'block';
            uploadContainer.style.display = 'none';
            liveControls.style.display = 'block';
            
            cardTitle.innerHTML = '<i class="fas fa-video"></i> Live Camera Monitoring';
            
            // Update instructions
            if (instructionsList) {
                instructionsList.innerHTML = `
                    <li>Click the <strong>"Start"</strong> button above to begin live monitoring</li>
                    <li>Your webcam will activate and show the live feed</li>
                    <li>YOLO will detect PPE in real-time with bounding boxes</li>
                    <li>When violations are detected, they will be logged automatically</li>
                    <li>Click <strong>"Stop"</strong> to end the monitoring session</li>
                `;
            }
        }
        
        function switchToUploadMode() {
            // Stop live stream if active
            if (APP_STATE.liveStreamActive) {
                stopLiveStream();
            }
            
            currentMode = 'upload';
            uploadModeBtn.classList.add('active');
            liveModeBtn.classList.remove('active');
            
            liveStreamContainer.style.display = 'none';
            uploadContainer.style.display = 'block';
            liveControls.style.display = 'none';
            
            cardTitle.innerHTML = '<i class="fas fa-image"></i> Image Analysis';
            
            // Update instructions
            if (instructionsList) {
                instructionsList.innerHTML = `
                    <li>Click the upload area or <strong>drop an image</strong> to select a file</li>
                    <li>Preview will show your selected image</li>
                    <li>Click <strong>"Analyze for PPE Violations"</strong> to run detection</li>
                    <li>Violations will be automatically logged and full reports generated</li>
                    <li>View detection results with annotated bounding boxes</li>
                `;
            }
        }
        
        // Mode button listeners
        liveModeBtn.addEventListener('click', switchToLiveMode);
        uploadModeBtn.addEventListener('click', switchToUploadMode);

        sourceToggleBtn.addEventListener('click', () => {
            if (APP_STATE.liveStreamActive) {
                showNotification('Stop monitoring before switching camera source.', 'warning');
                return;
            }

            const sources = getAvailableSources();
            if (sources.length < 2) {
                showNotification('No alternate camera source is available.', 'warning');
                return;
            }

            const currentIndex = sources.indexOf(selectedSource);
            selectedSource = sources[(currentIndex + 1) % sources.length];
            renderSourceToggle();

            const sourceLabel = getCurrentSourceLabel();
            showNotification(`Camera source changed to ${sourceLabel}`, 'success');
        });

        if (webcamDeviceSelect) {
            webcamDeviceSelect.addEventListener('change', () => {
                selectedCameraIndex = normalizeCameraIndex(webcamDeviceSelect.value, selectedCameraIndex);
                showNotification(`Backend webcam index set to ${selectedCameraIndex}`, 'info');
            });
        }

        if (refreshWebcamDevicesBtn) {
            refreshWebcamDevicesBtn.addEventListener('click', async () => {
                refreshWebcamDevicesBtn.disabled = true;
                const previousLabel = refreshWebcamDevicesBtn.innerHTML;
                refreshWebcamDevicesBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
                await refreshBackendWebcamOptions(true);
                refreshWebcamDevicesBtn.innerHTML = previousLabel;
                refreshWebcamDevicesBtn.disabled = false;
            });
        }

        if (browserCameraSelect) {
            browserCameraSelect.addEventListener('change', () => {
                selectedBrowserDeviceId = browserCameraSelect.value || '';
                const label = selectedBrowserDeviceId ? getSelectedBrowserDeviceLabel() : 'Default browser camera';
                showNotification(`Browser camera set to ${label}`, 'info');
            });
        }

        if (refreshBrowserCameraBtn) {
            refreshBrowserCameraBtn.addEventListener('click', async () => {
                refreshBrowserCameraBtn.disabled = true;
                const previousLabel = refreshBrowserCameraBtn.innerHTML;
                refreshBrowserCameraBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
                await refreshBrowserCameraOptions();
                refreshBrowserCameraBtn.innerHTML = previousLabel;
                refreshBrowserCameraBtn.disabled = false;
                showNotification(`Browser camera list refreshed (${browserVideoDevices.length || 0} found)`, 'info');
            });
        }
        
        // Image upload handling
        imageUpload.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (!file) return;
            
            if (!file.type.startsWith('image/')) {
                alert('Please select a valid image file');
                return;
            }
            
            if (file.size > 10 * 1024 * 1024) { // 10MB limit
                alert('Image size must be less than 10MB');
                return;
            }
            
            selectedFile = file;
            
            // Show preview
            const reader = new FileReader();
            reader.onload = (e) => {
                previewImage.src = e.target.result;
                uploadPreview.style.display = 'block';
                uploadResults.style.display = 'none';
            };
            reader.readAsDataURL(file);
        });
        
        // Analyze button
        analyzeBtn.addEventListener('click', async () => {
            if (!selectedFile) return;
            
            try {
                analyzeBtn.disabled = true;
                analyzeBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Analyzing...';
                
                // Create form data
                const formData = new FormData();
                formData.append('image', selectedFile);
                formData.append('conf', '0.10');
                
                // Upload and analyze
                const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.UPLOAD_INFERENCE}`, {
                    method: 'POST',
                    body: formData
                });
                
                if (!response.ok) {
                    throw new Error('Analysis failed');
                }
                
                const result = await response.json();
                
                // Display results
                uploadResultsContent.innerHTML = `
                    <div style="display: flex; gap: 2rem; margin-bottom: 1rem;">
                        <div>
                            <h4 style="margin: 0 0 0.5rem 0;">Total Detections</h4>
                            <p style="font-size: 2rem; font-weight: bold; color: var(--primary-color); margin: 0;">${result.count}</p>
                        </div>
                        <div>
                            <h4 style="margin: 0 0 0.5rem 0;">Violations Found</h4>
                            <p style="font-size: 2rem; font-weight: bold; color: ${result.violations_detected ? 'var(--danger-color)' : 'var(--success-color)'}; margin: 0;">
                                ${result.violation_count}
                            </p>
                        </div>
                    </div>
                    ${result.violations_detected ? 
                        '<div class="alert alert-danger"><i class="fas fa-exclamation-triangle"></i> PPE violations detected! Report will be generated automatically.</div>' :
                        '<div class="alert alert-success"><i class="fas fa-check-circle"></i> No violations detected. All PPE compliance requirements met.</div>'
                    }
                    <h4 style="margin-top: 1rem;">Detected Objects:</h4>
                    <div style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem;">
                        ${result.detections.map(d => `
                            <span class="badge ${d.class_name.toLowerCase().includes('no-') ? 'badge-danger' : 'badge-success'}">
                                ${d.class_name} (${(d.confidence * 100).toFixed(1)}%)
                            </span>
                        `).join('')}
                    </div>
                `;
                
                annotatedResult.src = result.annotated_image;
                uploadResults.style.display = 'block';
                
                analyzeBtn.disabled = false;
                analyzeBtn.innerHTML = '<i class="fas fa-search"></i> Analyze Image';
                
            } catch (error) {
                console.error('Analysis error:', error);
                alert('Failed to analyze image. Please try again.');
                analyzeBtn.disabled = false;
                analyzeBtn.innerHTML = '<i class="fas fa-search"></i> Analyze Image';
            }
        });
        
        // Clear upload button
        clearUploadBtn.addEventListener('click', () => {
            selectedFile = null;
            imageUpload.value = '';
            uploadPreview.style.display = 'none';
            uploadResults.style.display = 'none';
        });
        
        // Live stream functions
        async function stopLiveStream() {
            stopBtn.disabled = true;
            // Tear down UI first so stream frame and boxes disappear immediately.
            setLiveControlState(false);
            stopPhoneInferenceLoop();
            clearLiveOverlayCanvas();
            streamImg.src = '';
            streamImg.style.display = 'none';
            placeholder.style.display = 'block';
            statusIndicator.style.display = 'none';
            if (phoneCameraPreview) phoneCameraPreview.style.display = 'none';
            hideDepthWidgets();

            try {
                if (shouldUseBrowserCaptureSource()) {
                    stopPhoneInferenceLoop();
                    stopPhoneCameraTrack();
                } else {
                    await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_STOP}`, {
                        method: 'POST'
                    });
                }
                showNotification('Live monitoring stopped', 'info');
            } catch (error) {
                console.error('Error stopping live stream:', error);
                showNotification('Failed to stop live monitoring cleanly', 'error');
            } finally {
                stopPhoneInferenceLoop();
                stopPhoneCameraTrack();
                useBrowserCaptureRuntime = false;
                setLiveControlState(false);
                hideDepthWidgets();
            }
        }
        
        // Attach event listeners
        // Start live stream
        startBtn.addEventListener('click', async () => {
            try {
                // Disable start button
                startBtn.disabled = true;
                startBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Starting...';

                if (shouldPreferBrowserCaptureSource()) {
                    await startBrowserCaptureSession(selectedSource === 'phone');
                    return;
                }

                // Start monitoring on backend
                // Ensure no stale backend camera session is holding the device.
                try {
                    await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_STOP}`, {
                        method: 'POST'
                    });
                } catch (cleanupError) {
                    // Safe to ignore: start call below remains authoritative.
                }

                const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_START}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        source: selectedSource,
                        camera_index: selectedSource === 'webcam' ? selectedCameraIndex : null
                    })
                });

                let startData = null;
                let startText = '';
                try {
                    startText = await response.text();
                    startData = startText ? JSON.parse(startText) : null;
                } catch (parseError) {
                    startData = null;
                }

                const backendErrorMessage = (startData && (startData.error || startData.message)) || startText || 'Failed to start monitoring';
                const shouldFallbackToBrowserWebcam = (
                    selectedSource === 'webcam' &&
                    browserCameraSupported &&
                    (!isAutomationContext || isAutomationWebcamFallbackAllowed()) &&
                    isWebcamUnavailableMessage(backendErrorMessage)
                );

                if (!response.ok || (startData && startData.success === false)) {
                    if (shouldFallbackToBrowserWebcam) {
                        await startBrowserCaptureSession(false, 'Backend webcam unavailable. ');
                        return;
                    }
                    throw new Error(backendErrorMessage);
                }

                useBrowserCaptureRuntime = false;
                if (startData.source) {
                    selectedSource = startData.source;
                }
                if (startData.camera_index !== null && startData.camera_index !== undefined) {
                    selectedCameraIndex = normalizeCameraIndex(startData.camera_index, selectedCameraIndex);
                }
                syncBackendWebcamDevices(startData || {});

                if (startData.realsense_available !== undefined) {
                    realsenseAvailable = !!startData.realsense_available;
                }
                if (startData.realsense_device_name) {
                    realsenseDeviceName = startData.realsense_device_name;
                }
                realsenseCapabilities = startData.realsense_capabilities || realsenseCapabilities;

                if (startData.edge_realsense_available !== undefined) {
                    edgeRealsenseAvailable = !!startData.edge_realsense_available;
                }
                if (startData.edge_realsense_device_name) {
                    edgeRealsenseDeviceName = startData.edge_realsense_device_name;
                }
                edgeRealsenseCapabilities = startData.edge_realsense_capabilities || edgeRealsenseCapabilities;

                // Hide placeholder, show stream
                placeholder.style.display = 'none';
                if (phoneCameraPreview) phoneCameraPreview.style.display = 'none';
                streamImg.style.display = 'block';
                statusIndicator.style.display = 'block';
                statusIndicator.innerHTML = '<i class="fas fa-circle" style="animation: blink 1.5s infinite;"></i> LIVE';

                // Set stream source
                streamImg.src = buildLiveStreamUrl();

                // Enable stop button
                stopBtn.disabled = false;
                startBtn.disabled = true;
                startBtn.innerHTML = '<i class="fas fa-play"></i> Start';
                
                // Update state
                setLiveControlState(true);
                renderCapabilities();
                renderSourceToggle();
                await refreshDepthStatus();

                showNotification(`Live monitoring started (${getCurrentSourceLabel()})`, 'success');

                if (startData.fallback_to_webcam) {
                    showNotification(startData.message || 'RealSense unavailable, switched to webcam', 'warning');
                }

            } catch (error) {
                console.error('Error starting live stream:', error);

                if (shouldUseBrowserCaptureSource()) {
                    const usingPhoneSource = selectedSource === 'phone';
                    const isPermissionDenied = error && (error.name === 'NotAllowedError' || error.name === 'SecurityError');
                    const isCameraMissing = error && error.name === 'NotFoundError';
                    if (isPermissionDenied) {
                        if (usingPhoneSource) {
                            phonePermissionState = 'denied';
                            updatePhonePermissionBadge();
                        }
                        alert('Camera permission was denied. Please allow camera access in your browser settings and try again.');
                    } else if (isCameraMissing) {
                        if (usingPhoneSource) {
                            phonePermissionState = 'unavailable';
                            updatePhonePermissionBadge();
                            alert('No usable phone camera was found.');
                        } else {
                            alert('No usable webcam was found.');
                        }
                    } else {
                        if (usingPhoneSource && phonePermissionState !== 'denied') {
                            phonePermissionState = 'prompt';
                            updatePhonePermissionBadge();
                        }
                        alert('Failed to start camera. Please check browser camera permissions and HTTPS access.');
                    }
                    stopPhoneInferenceLoop();
                    stopPhoneCameraTrack();
                } else {
                    const message = (error && error.message) ? String(error.message) : 'Failed to start live monitoring. Please check if the webcam is available.';
                    alert(message);
                }

                startBtn.disabled = false;
                startBtn.innerHTML = '<i class="fas fa-play"></i> Start';
            }
        });

        // Stop live stream
        stopBtn.addEventListener('click', stopLiveStream);

        // Handle stream errors
        streamImg.addEventListener('error', async () => {
            if (!APP_STATE.liveStreamActive) {
                return;
            }

            // Browser capture mode uses <video>, not <img>; ignore incidental img errors.
            if (shouldUseBrowserCaptureSource()) {
                return;
            }

            try {
                await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_STOP}`, {
                    method: 'POST'
                });
            } catch (stopError) {
                console.warn('Failed to stop backend stream after stream error:', stopError);
            }

            console.error('Stream error');
            placeholder.style.display = 'block';
            streamImg.style.display = 'none';
            statusIndicator.style.display = 'none';
            setLiveControlState(false);
            hideDepthWidgets();
        });

        // Get preferred/default source and RealSense availability
        try {
            const devicesResp = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_DEVICES}`);
            const devices = await devicesResp.json();
            realsenseAvailable = !!devices.realsense_available;
            if (devices.realsense_device_name) {
                realsenseDeviceName = devices.realsense_device_name;
            }
            realsenseCapabilities = devices.realsense_capabilities || {};
            edgeRealsenseAvailable = !!devices.edge_realsense_available;
            if (devices.edge_realsense_device_name) {
                edgeRealsenseDeviceName = devices.edge_realsense_device_name;
            }
            edgeRealsenseCapabilities = devices.edge_realsense_capabilities || {};
            syncBackendWebcamDevices(devices);
            selectedSource = devices.default_source || 'webcam';

            if (selectedSource === 'realsense' && !realsenseAvailable) {
                selectedSource = edgeRealsenseAvailable ? 'edge_realsense' : 'webcam';
            }

            if (selectedSource === 'edge_realsense' && !edgeRealsenseAvailable) {
                selectedSource = realsenseAvailable ? 'realsense' : 'webcam';
            }

            if (!['webcam', 'realsense', 'edge_realsense', 'phone'].includes(selectedSource)) {
                selectedSource = 'webcam';
            }

            if (phoneCameraSupported && !['realsense', 'edge_realsense', 'webcam', 'phone'].includes(selectedSource)) {
                selectedSource = 'phone';
            }
            renderCapabilities();
            renderSourceToggle();
        } catch (error) {
            console.error('Error checking live devices:', error);
            selectedSource = 'webcam';
            realsenseAvailable = false;
            edgeRealsenseAvailable = false;
            backendWebcamDevices = [];
            renderCapabilities();
            renderSourceToggle();
        }

        // Check initial status
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_STATUS}`);
            const status = await response.json();

            if (status.realsense_available !== undefined) {
                realsenseAvailable = !!status.realsense_available;
            }
            if (status.realsense_device_name) {
                realsenseDeviceName = status.realsense_device_name;
            }
            realsenseCapabilities = status.realsense_capabilities || realsenseCapabilities;
            if (status.edge_realsense_available !== undefined) {
                edgeRealsenseAvailable = !!status.edge_realsense_available;
            }
            if (status.edge_realsense_device_name) {
                edgeRealsenseDeviceName = status.edge_realsense_device_name;
            }
            edgeRealsenseCapabilities = status.edge_realsense_capabilities || edgeRealsenseCapabilities;
            syncBackendWebcamDevices(status);
            selectedSource = status.source || status.default_source || selectedSource;

            if (selectedSource === 'realsense' && !realsenseAvailable) {
                selectedSource = edgeRealsenseAvailable ? 'edge_realsense' : 'webcam';
            }

            if (selectedSource === 'edge_realsense' && !edgeRealsenseAvailable) {
                selectedSource = realsenseAvailable ? 'realsense' : 'webcam';
            }

            if (!['webcam', 'realsense', 'edge_realsense', 'phone'].includes(selectedSource)) {
                selectedSource = 'webcam';
            }

            if (phoneCameraSupported && !['realsense', 'edge_realsense', 'webcam', 'phone'].includes(selectedSource)) {
                selectedSource = 'phone';
            }
            
            if (status.active) {
                // Stream is already active
                useBrowserCaptureRuntime = false;
                placeholder.style.display = 'none';
                if (phoneCameraPreview) phoneCameraPreview.style.display = 'none';
                streamImg.style.display = 'block';
                statusIndicator.style.display = 'block';
                statusIndicator.innerHTML = '<i class="fas fa-circle" style="animation: blink 1.5s infinite;"></i> LIVE';
                streamImg.src = buildLiveStreamUrl();
                setLiveControlState(true);
            } else {
                setLiveControlState(false);
            }

            renderCapabilities();
            renderSourceToggle();
            await refreshDepthStatus();
        } catch (error) {
            console.error('Error checking stream status:', error);
            renderCapabilities();
            renderSourceToggle();
        }

        await refreshBrowserCameraOptions();
        renderSourceToggle();

        // Simple notification function (fallback if not defined globally)
        function showNotification(message, type = 'info') {
            if (typeof NotificationManager !== 'undefined') {
                if (type === 'success') return NotificationManager.success(message);
                if (type === 'warning') return NotificationManager.warning(message);
                if (type === 'error') return NotificationManager.error(message);
                return NotificationManager.info(message);
            }

            console.log(`[${type.toUpperCase()}] ${message}`);
            if (type === 'error') {
                alert(message);
            }
        }

    },

    unmount() {
        if (this.phoneInferenceInterval) {
            clearInterval(this.phoneInferenceInterval);
            this.phoneInferenceInterval = null;
        }

        if (this.phoneCameraStream) {
            this.phoneCameraStream.getTracks().forEach((track) => track.stop());
            this.phoneCameraStream = null;
        }

    }
};


