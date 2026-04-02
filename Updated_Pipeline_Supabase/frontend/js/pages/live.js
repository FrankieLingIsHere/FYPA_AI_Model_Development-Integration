// Live Monitoring Page Component
const LivePage = {
    queueRefreshInterval: null,
    reliabilityRefreshInterval: null,
    depthStatusInterval: null,
    providerRuntimeInterval: null,
    settingsKeydownHandler: null,
    realtimeHandler: null,
    realtimeConnectionHandler: null,
    phoneCameraStream: null,
    phoneInferenceInterval: null,
    phoneInferenceBusy: false,
    phoneLastViolationNoticeAt: 0,

    render() {
        return `
            <div class="page">
                <!-- Mode Tabs -->
                <div style="margin-bottom: 1rem; border-bottom: 2px solid var(--border-color);">
                    <div style="display: flex; gap: 0.5rem;">
                        <button id="liveModeBtn" class="mode-tab active">
                            <i class="fas fa-video"></i> Camera Stream
                        </button>
                        <button id="uploadModeBtn" class="mode-tab">
                            <i class="fas fa-image"></i> Analyze Image
                        </button>
                    </div>
                </div>

                <div class="card mb-4">
                    <div class="card-header">
                        <span id="cardTitle"><i class="fas fa-video"></i> Live Camera Monitoring</span>
                        <div id="liveControls" style="float: right;">
                            <span id="phoneCameraPermissionBadge" style="display: none; margin-right: 10px; font-size: 0.78rem; font-weight: 700; padding: 6px 10px; border-radius: 999px; border: 1px solid transparent; vertical-align: middle;"></span>
                            <button id="openSettingsWindowBtn" class="btn btn-secondary" style="margin-right: 10px;" title="Open monitoring settings">
                                <i class="fas fa-cog"></i> Settings
                            </button>
                            <button id="sourceToggleBtn" class="btn btn-secondary" style="margin-right: 10px;" title="Toggle camera source">
                                <i class="fas fa-camera"></i> Source: Webcam
                            </button>
                            <button id="startLiveBtn" class="btn btn-success" style="margin-right: 10px;">
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
                                        Supports JPG, PNG • Max 10MB
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

                        <div style="padding: 1rem; border: 1px dashed var(--border-color); border-radius: 8px; background: #fafafa; margin-top: 1rem;">
                            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.75rem;">
                                <div>
                                    <h3 style="margin: 0 0 0.4rem 0;"><i class="fas fa-sliders-h"></i> Monitoring Settings</h3>
                                    <p style="margin: 0; color: var(--text-secondary); font-size: 0.92rem;">
                                        Use the Settings button near Start/Stop to open the full configuration window.
                                    </p>
                                </div>
                                <button id="quickRecommendedSettingsBtn" class="btn btn-primary">
                                    <i class="fas fa-magic"></i> Use Recommended Settings
                                </button>
                            </div>
                        </div>

                        <div id="settingsModal" class="settings-modal" aria-hidden="true">
                            <div id="settingsWindow" class="settings-window">
                                <div class="settings-window-header">
                                    <h3 style="margin: 0;"><i class="fas fa-cogs"></i> Monitoring Settings</h3>
                                    <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; justify-content: flex-end;">
                                        <button id="recommendedSettingsBtn" class="btn btn-primary">
                                            <i class="fas fa-magic"></i> Use Recommended Settings
                                        </button>
                                        <button id="toggleSettingsWindowSizeBtn" class="btn btn-secondary" title="Enlarge settings window">
                                            <i class="fas fa-expand"></i> Enlarge
                                        </button>
                                        <button id="closeSettingsWindowBtn" class="btn btn-danger" title="Close settings window">
                                            <i class="fas fa-times"></i> Close
                                        </button>
                                    </div>
                                </div>

                                <div class="settings-window-content">
                                    <div class="settings-tabs">
                                        <button class="settings-tab active" data-settings-tab="Dsettings">Detection Settings</button>
                                        <button class="settings-tab" data-settings-tab="Psettings">Processing Settings</button>
                                    </div>

                                    <div class="settings-section active" id="settings-tab-Dsettings">
                            <h3 style="margin-bottom: 1rem;">Detection Settings</h3>
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

                                    <div class="settings-section" id="settings-tab-Psettings">  
                            <h3 style="margin-bottom: 1rem;">Processing Settings</h3>
                            <div class="grid grid-2">
                                <!-- Environment Validation Toggle -->
                                <div style="padding: 1rem; background: var(--background-color); border-radius: 8px;">
                                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                                        <h4 style="margin: 0;">
                                            <i class="fas fa-building" style="color: var(--primary-color);"></i>
                                            Environment Validation
                                        </h4>
                                        <label class="toggle-switch">
                                            <input type="checkbox" id="envValidationToggle">
                                            <span class="toggle-slider"></span>
                                        </label>
                                    </div>
                                    <p style="color: var(--text-secondary); font-size: 0.9rem; margin-bottom: 0.5rem;">
                                        When <strong>ON</strong>: Only process violations in work environments (construction, factory, warehouse)
                                    </p>
                                    <p style="color: var(--text-secondary); font-size: 0.9rem; margin-bottom: 0;">
                                        When <strong>OFF</strong>: Process ALL detected violations (recommended for testing)
                                    </p>
                                    <div id="envValidationStatus" style="margin-top: 0.75rem; padding: 0.5rem; border-radius: 4px; font-size: 0.85rem;">
                                        <!-- Status will be updated by JS -->
                                    </div>
                                </div>

                                <!-- Cooldown Setting -->
                                <div style="padding: 1rem; background: var(--background-color); border-radius: 8px;">
                                    <h4 style="margin-bottom: 0.5rem;">
                                        <i class="fas fa-clock" style="color: var(--warning-color);"></i>
                                        Capture Cooldown
                                    </h4>
                                    <p style="color: var(--text-secondary); font-size: 0.9rem; margin-bottom: 1rem;">
                                        Minimum time between capturing violations (prevents duplicates)
                                    </p>
                                    <div style="display: flex; align-items: center; gap: 1rem;">
                                        <input type="range" id="cooldownSlider" min="1" max="30" value="3" 
                                            style="flex: 1; cursor: pointer;">
                                        <span id="cooldownValue" style="font-weight: bold; min-width: 60px; text-align: center; 
                                                                        background: var(--primary-color); color: white; 
                                                                        padding: 4px 12px; border-radius: 20px;">3s</span>
                                    </div>
                                    <button id="applyCooldownBtn" class="btn btn-primary" style="margin-top: 1rem; width: 100%;">
                                        <i class="fas fa-save"></i> Apply Cooldown
                                    </button>
                                </div>
                            </div>

                            <!-- Queue Status -->
                            <div style="margin-top: 1rem; padding: 1rem; background: var(--background-color); border-radius: 8px;">
                                <h4 style="margin-bottom: 0.75rem;">
                                    <i class="fas fa-tasks" style="color: var(--success-color);"></i>
                                    Processing Queue Status
                                </h4>
                                <div id="queueStatus" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem;">
                                    <div style="text-align: center; padding: 0.5rem;">
                                        <div style="font-size: 1.5rem; font-weight: bold; color: var(--primary-color);" id="queueSize">-</div>
                                        <div style="font-size: 0.8rem; color: #7f8c8d;">In Queue</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.5rem;">
                                        <div style="font-size: 1.5rem; font-weight: bold; color: var(--success-color);" id="queueProcessed">-</div>
                                        <div style="font-size: 0.8rem; color: #7f8c8d;">Processed</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.5rem;">
                                        <div style="font-size: 1.5rem; font-weight: bold; color: var(--error-color);" id="queueFailed">-</div>
                                        <div style="font-size: 0.8rem; color: #7f8c8d;">Failed</div>
                                    </div>
                                    <div style="text-align: center; padding: 0.5rem;">
                                        <div style="font-size: 1.5rem; font-weight: bold;" id="workerStatus">-</div>
                                        <div style="font-size: 0.8rem; color: #7f8c8d;">Worker</div>
                                    </div>
                                </div>
                                <button id="refreshQueueBtn" class="btn btn-secondary" style="margin-top: 0.75rem;">
                                    <i class="fas fa-sync-alt"></i> Refresh Status
                                </button>
                            </div>

                            <div style="margin-top: 1rem; padding: 1rem; background: var(--background-color); border-radius: 8px; border: 1px solid var(--border-color);">
                                <h4 style="margin-bottom: 0.5rem; display: flex; align-items: center; gap: 0.45rem;">
                                    <i class="fas fa-gauge-high" style="color: var(--primary-color);"></i>
                                    Live Performance Profile
                                </h4>
                                <p style="color: var(--text-secondary); font-size: 0.9rem; margin-bottom: 0.75rem;">
                                    Applies to laptop and phone live monitoring. You can switch while streaming.
                                </p>
                                <div style="display: flex; gap: 0.6rem; flex-wrap: wrap; align-items: center;">
                                    <select id="livePerformanceProfile" class="provider-input" style="width: 220px; margin-bottom: 0;">
                                        <option value="smooth">Smooth (lowest latency)</option>
                                        <option value="balanced" selected>Balanced (recommended)</option>
                                        <option value="detail">High Detail (best quality)</option>
                                    </select>
                                    <button id="applyLivePerformanceProfileBtn" class="btn btn-primary">
                                        <i class="fas fa-sliders-h"></i> Apply Profile
                                    </button>
                                    <span id="livePerformanceProfileStatus" style="font-size: 0.84rem; color: var(--text-secondary);">Profile: balanced</span>
                                </div>
                            </div>

                            <div style="margin-top: 1rem; padding: 1rem; background: var(--background-color); border-radius: 8px;">
                                <h4 style="margin-bottom: 0.75rem; display: flex; align-items: center; gap: 0.45rem;">
                                    <i id="reliabilityHeadingIcon" class="fas fa-shield-alt" style="color: var(--success-color);"></i>
                                    Reliability (Real vs Fallback)
                                </h4>
                                <p style="color: var(--text-secondary); font-size: 0.9rem; margin-bottom: 0.8rem;">
                                    Tracks true report quality from backend strict metrics. "Real Success" means completed with non-fallback report content.
                                </p>

                                <div style="display: flex; gap: 0.6rem; flex-wrap: wrap; align-items: center; margin-bottom: 0.8rem;">
                                    <label for="reliabilityWindowSelect" style="font-size: 0.85rem; color: var(--text-secondary);">Window</label>
                                    <select id="reliabilityWindowSelect" class="provider-input" style="width: 100px; margin-bottom: 0;">
                                        <option value="25">25</option>
                                        <option value="50" selected>50</option>
                                        <option value="100">100</option>
                                    </select>
                                    <button id="refreshReliabilityBtn" class="btn btn-secondary">
                                        <i class="fas fa-sync-alt"></i> Refresh Reliability
                                    </button>
                                    <span id="reliabilityLastUpdated" style="font-size: 0.82rem; color: var(--text-secondary);">Last updated: -</span>
                                </div>

                                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.75rem;">
                                    <div style="text-align: center; background: #fff; border: 1px solid var(--border-color); border-radius: 8px; padding: 0.7rem;">
                                        <div id="reliabilityRealSuccess" style="font-size: 1.4rem; font-weight: bold; color: var(--success-color);">-</div>
                                        <div style="font-size: 0.8rem; color: #7f8c8d;">Real Success Rate</div>
                                    </div>
                                    <div style="text-align: center; background: #fff; border: 1px solid var(--border-color); border-radius: 8px; padding: 0.7rem;">
                                        <div id="reliabilityFallbackRate" style="font-size: 1.4rem; font-weight: bold; color: var(--warning-color);">-</div>
                                        <div style="font-size: 0.8rem; color: #7f8c8d;">Fallback Needed Rate</div>
                                    </div>
                                    <div style="text-align: center; background: #fff; border: 1px solid var(--border-color); border-radius: 8px; padding: 0.7rem;">
                                        <div id="reliabilityHardFailed" style="font-size: 1.4rem; font-weight: bold; color: var(--error-color);">-</div>
                                        <div style="font-size: 0.8rem; color: #7f8c8d;">Hard Failed</div>
                                    </div>
                                    <div style="text-align: center; background: #fff; border: 1px solid var(--border-color); border-radius: 8px; padding: 0.7rem;">
                                        <div id="reliabilityConsidered" style="font-size: 1.4rem; font-weight: bold; color: var(--primary-color);">-</div>
                                        <div style="font-size: 0.8rem; color: #7f8c8d;">Reports Considered</div>
                                    </div>
                                </div>

                                <div style="margin-top: 0.8rem; background: #fff; border: 1px solid var(--border-color); border-radius: 8px; padding: 0.7rem;">
                                    <div style="font-size: 0.84rem; color: var(--text-secondary); margin-bottom: 0.35rem;">Failure causes</div>
                                    <div id="reliabilityFailureCauses" style="font-size: 0.88rem; color: var(--text-color);">-</div>
                                </div>
                            </div>

                            <div style="margin-top: 1rem; padding: 1rem; background: var(--background-color); border-radius: 8px;">
                                <h4 style="margin-bottom: 0.75rem;">
                                    <i class="fas fa-network-wired" style="color: var(--secondary-color);"></i>
                                    AI Provider Routing
                                </h4>
                                <p style="color: var(--text-secondary); font-size: 0.9rem; margin-bottom: 1rem;">
                                    Configure runtime provider switches and fallback order for Vision, NLP, and Embeddings.
                                </p>

                                <div class="grid grid-2" style="gap: 1rem;">
                                    <div style="padding: 0.9rem; background: #fff; border-radius: 8px; border: 1px solid var(--border-color);">
                                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                                            <label style="font-weight: 600;">Model API Enabled</label>
                                            <label class="toggle-switch">
                                                <input type="checkbox" id="modelApiToggle">
                                                <span class="toggle-slider"></span>
                                            </label>
                                        </div>
                                        <small style="color: var(--text-secondary);">Use provider-specific cloud APIs first.</small>
                                    </div>

                                    <div style="padding: 0.9rem; background: #fff; border-radius: 8px; border: 1px solid var(--border-color);">
                                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                                            <label style="font-weight: 600;">Gemini Fallback Enabled</label>
                                            <label class="toggle-switch">
                                                <input type="checkbox" id="geminiToggle">
                                                <span class="toggle-slider"></span>
                                            </label>
                                        </div>
                                        <small style="color: var(--text-secondary);">If cloud API fails, route to Google Gemini.</small>
                                    </div>

                                    <div style="padding: 0.9rem; background: #fff; border-radius: 8px; border: 1px solid var(--border-color);">
                                        <label style="font-weight: 600; display: block; margin-bottom: 0.5rem;">NLP Provider Order</label>
                                        <input id="nlpProviderOrderInput" class="provider-input" type="text" value="model_api,gemini,ollama,local" />
                                        <small style="color: var(--text-secondary);">Comma-separated: model_api, gemini, ollama, local</small>
                                    </div>

                                    <div style="padding: 0.9rem; background: #fff; border-radius: 8px; border: 1px solid var(--border-color);">
                                        <label style="font-weight: 600; display: block; margin-bottom: 0.5rem;">Vision Provider Order</label>
                                        <input id="visionProviderOrderInput" class="provider-input" type="text" value="model_api,gemini,ollama" />
                                        <small style="color: var(--text-secondary);">Comma-separated: model_api, gemini, ollama</small>
                                    </div>

                                    <div style="padding: 0.9rem; background: #fff; border-radius: 8px; border: 1px solid var(--border-color);">
                                        <label style="font-weight: 600; display: block; margin-bottom: 0.5rem;">Embedding Provider Order</label>
                                        <input id="embeddingProviderOrderInput" class="provider-input" type="text" value="model_api,ollama" />
                                        <small style="color: var(--text-secondary);">Comma-separated: model_api, ollama</small>
                                    </div>

                                    <div style="padding: 0.9rem; background: #fff; border-radius: 8px; border: 1px solid var(--border-color);">
                                        <label style="font-weight: 600; display: block; margin-bottom: 0.5rem;">NLP Model</label>
                                        <input id="nlpModelInput" class="provider-input" type="text" placeholder="meta-llama/Meta-Llama-3-8B-Instruct" />
                                        <small style="color: var(--text-secondary);">Cloud NLP model identifier</small>
                                    </div>

                                    <div style="padding: 0.9rem; background: #fff; border-radius: 8px; border: 1px solid var(--border-color);">
                                        <label style="font-weight: 600; display: block; margin-bottom: 0.5rem;">Vision Model</label>
                                        <input id="visionModelInput" class="provider-input" type="text" placeholder="Qwen/Qwen2.5-VL-7B-Instruct" />
                                        <small style="color: var(--text-secondary);">Cloud vision model identifier</small>
                                    </div>

                                    <div style="padding: 0.9rem; background: #fff; border-radius: 8px; border: 1px solid var(--border-color);">
                                        <label style="font-weight: 600; display: block; margin-bottom: 0.5rem;">Embedding Model</label>
                                        <input id="embeddingModelInput" class="provider-input" type="text" placeholder="nomic-ai/nomic-embed-text-v1.5" />
                                        <small style="color: var(--text-secondary);">Cloud embedding model identifier</small>
                                    </div>

                                    <div style="padding: 0.9rem; background: #fff; border-radius: 8px; border: 1px solid var(--border-color);">
                                        <label style="font-weight: 600; display: block; margin-bottom: 0.5rem;">Gemini Model</label>
                                        <input id="geminiModelInput" class="provider-input" type="text" placeholder="gemini-2.5-flash" />
                                        <small style="color: var(--text-secondary);">Fallback Gemini text model</small>
                                    </div>
                                </div>

                                <div style="display: flex; gap: 0.75rem; margin-top: 1rem; flex-wrap: wrap;">
                                    <button id="applyProviderRoutingBtn" class="btn btn-primary">
                                        <i class="fas fa-save"></i> Apply Provider Routing
                                    </button>
                                    <button id="reloadProviderRoutingBtn" class="btn btn-secondary">
                                        <i class="fas fa-sync-alt"></i> Reload Provider Settings
                                    </button>
                                </div>
                                <div id="providerRoutingStatus" style="margin-top: 0.75rem; font-size: 0.9rem; color: var(--text-secondary);"></div>
                                <div id="providerRuntimePanel" style="margin-top: 0.7rem; border: 1px solid var(--border-color); border-radius: 8px; background: #fff; padding: 0.65rem 0.75rem;">
                                    <div style="font-size: 0.84rem; color: var(--text-secondary); margin-bottom: 0.35rem;">Runtime Provider Status</div>
                                    <div id="providerRuntimeActive" style="font-size: 0.9rem; color: var(--text-color);">Active provider: -</div>
                                    <div id="providerRuntimeCapacity" style="font-size: 0.85rem; color: var(--text-secondary); margin-top: 0.2rem;">Estimated remaining reports: -</div>
                                </div>
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

                /* Toggle Switch Styles */
                .toggle-switch {
                    position: relative;
                    display: inline-block;
                    width: 60px;
                    height: 30px;
                }

                .toggle-switch input {
                    opacity: 0;
                    width: 0;
                    height: 0;
                }

                .toggle-slider {
                    position: absolute;
                    cursor: pointer;
                    top: 0;
                    left: 0;
                    right: 0;
                    bottom: 0;
                    background-color: #ccc;
                    transition: 0.3s;
                    border-radius: 30px;
                }

                .toggle-slider:before {
                    position: absolute;
                    content: "";
                    height: 22px;
                    width: 22px;
                    left: 4px;
                    bottom: 4px;
                    background-color: white;
                    transition: 0.3s;
                    border-radius: 50%;
                }

                .toggle-switch input:checked + .toggle-slider {
                    background-color: var(--success-color, #4CAF50);
                }

                .toggle-switch input:checked + .toggle-slider:before {
                    transform: translateX(30px);
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

                .provider-input {
                    width: 100%;
                    border: 1px solid var(--border-color);
                    border-radius: 6px;
                    padding: 0.5rem 0.65rem;
                    font-size: 0.92rem;
                    background: #fff;
                    color: var(--text-color);
                    margin-bottom: 0.4rem;
                }

                .provider-input:focus {
                    outline: none;
                    border-color: var(--secondary-color);
                    box-shadow: 0 0 0 2px rgba(52, 152, 219, 0.15);
                }

                .settings-modal {
                    position: fixed;
                    inset: 0;
                    background: rgba(0, 0, 0, 0.45);
                    display: none;
                    align-items: center;
                    justify-content: center;
                    z-index: 1400;
                    padding: 1rem;
                }

                .settings-modal.open {
                    display: flex;
                }

                .settings-window {
                    width: min(1080px, 94vw);
                    max-height: 88vh;
                    background: #ffffff;
                    border-radius: 12px;
                    border: 1px solid var(--border-color);
                    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.25);
                    overflow: hidden;
                    display: flex;
                    flex-direction: column;
                }

                .settings-window.expanded {
                    width: min(1320px, 98vw);
                    max-height: 94vh;
                }

                .settings-window-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 0.75rem;
                    padding: 0.9rem 1rem;
                    background: linear-gradient(180deg, #fff, #f8f9fb);
                    border-bottom: 1px solid var(--border-color);
                }

                .settings-window-content {
                    padding: 1rem;
                    overflow: auto;
                }

                .settings-tabs {
                    display: flex;
                    gap: 0.5rem;
                    border-bottom: 2px solid var(--border-color);
                    margin-bottom: 1rem;
                    flex-wrap: wrap;
                }

                .settings-tab {
                    padding: 10px 16px;
                    background: transparent;
                    border: none;
                    border-bottom: 3px solid transparent;
                    color: var(--text-secondary);
                    font-size: 0.95rem;
                    font-weight: 600;
                    cursor: pointer;
                }

                .settings-tab.active {
                    color: var(--primary-color);
                    border-bottom-color: var(--primary-color);
                }

                .settings-section {
                    display: none;
                }

                .settings-section.active {
                    display: block;
                }

                @media (max-width: 768px) {
                    .settings-window,
                    .settings-window.expanded {
                        width: 100vw;
                        max-height: 100vh;
                        height: 100vh;
                        border-radius: 0;
                    }

                    .settings-window-header {
                        flex-direction: column;
                        align-items: flex-start;
                    }
                }
            </style>
        `;
    },

    async mount() {
        // Get UI elements
        const liveModeBtn = document.getElementById('liveModeBtn');
        const uploadModeBtn = document.getElementById('uploadModeBtn');
        const liveStreamContainer = document.getElementById('liveStreamContainer');
        const uploadContainer = document.getElementById('uploadContainer');
        const liveControls = document.getElementById('liveControls');
        const cardTitle = document.getElementById('cardTitle');
        const sourceToggleBtn = document.getElementById('sourceToggleBtn');
        const openSettingsWindowBtn = document.getElementById('openSettingsWindowBtn');
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
        const settingsModal = document.getElementById('settingsModal');
        const settingsWindow = document.getElementById('settingsWindow');
        const settingsTabs = document.querySelectorAll('.settings-tab');
        const settingsSections = document.querySelectorAll('.settings-section');
        const closeSettingsWindowBtn = document.getElementById('closeSettingsWindowBtn');
        const toggleSettingsWindowSizeBtn = document.getElementById('toggleSettingsWindowSizeBtn');
        const quickRecommendedSettingsBtn = document.getElementById('quickRecommendedSettingsBtn');
        const recommendedSettingsBtn = document.getElementById('recommendedSettingsBtn');
        
        let currentMode = 'live';
        let selectedFile = null;
        let selectedSource = 'webcam';
        let realsenseAvailable = false;
        let realsenseDeviceName = 'Intel RealSense';
        let realsenseCapabilities = {};
        const isPhoneDevice = document.body.classList.contains('is-phone-device');
        const browserCameraSupported = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
        const phoneCameraSupported = !!(isPhoneDevice && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
        const permissionsApiSupported = !!(navigator.permissions && navigator.permissions.query);
        let phonePermissionState = phoneCameraSupported ? 'prompt' : 'unavailable';
        const phoneCaptureCanvas = document.createElement('canvas');
        const laptopLiveStreamConfig = {
            conf: 0.10,
            fps: 14,
            quality: 72
        };
        const phoneInferenceConfig = {
            intervalMs: 320,
            conf: 0.08,
            jpegQuality: 0.72
        };
        const LIVE_PROFILE_STORAGE_KEY = 'live_performance_profile_v1';
        const LIVE_PERFORMANCE_PROFILES = {
            smooth: {
                laptop: { conf: 0.12, fps: 16, quality: 64 },
                phone: { intervalMs: 240, conf: 0.10, jpegQuality: 0.65 }
            },
            balanced: {
                laptop: { conf: 0.10, fps: 14, quality: 72 },
                phone: { intervalMs: 320, conf: 0.08, jpegQuality: 0.72 }
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

            if (liveOverlayCanvas) {
                const ctx = liveOverlayCanvas.getContext('2d');
                if (ctx) {
                    ctx.clearRect(0, 0, liveOverlayCanvas.width || 0, liveOverlayCanvas.height || 0);
                }
                liveOverlayCanvas.style.display = 'none';
            }
        };

        const getAvailableSources = () => {
            const sources = ['webcam'];
            if (realsenseAvailable) {
                sources.push('realsense');
            }
            if (phoneCameraSupported) {
                sources.push('phone');
            }
            return sources;
        };

        const shouldUseBrowserCaptureSource = () => {
            if (!browserCameraSupported) return false;
            return selectedSource === 'phone' && phoneCameraSupported;
        };

        const capturePhoneFrameForInference = async () => {
            if (!this.phoneCameraStream || !phoneCameraPreview) return;
            if (this.phoneInferenceBusy) return;
            if (phoneCameraPreview.readyState < 2) return;

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

                const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.UPLOAD_INFERENCE}`, {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    throw new Error('Phone frame inference failed');
                }

                const result = await response.json();
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
                    if (result.report_queued === false) {
                        const reason = result.report_queue_reason || 'queue_unavailable';
                        showNotification(`Violation detected but report not queued (${reason})`, 'warning');
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

            if (!realsenseAvailable) {
                capabilitiesContainer.innerHTML = '<span class="rs-cap-badge off"><i class="fas fa-microchip"></i> RealSense Depth: Not detected</span>';
                return;
            }

            const depthOk = !!realsenseCapabilities.depth_stream;
            const imuOk = !!realsenseCapabilities.imu;
            const colorOk = !!realsenseCapabilities.color_stream;
            const resolution = realsenseCapabilities.resolution || '-';
            const fps = realsenseCapabilities.fps || '-';

            capabilitiesContainer.innerHTML = `
                <span class="rs-cap-badge ok"><i class="fas fa-microchip"></i> ${realsenseDeviceName || 'RealSense'}</span>
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
            const showDepth = APP_STATE.liveStreamActive && selectedSource === 'realsense' && realsenseAvailable;
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
            try {
                const resp = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_DEPTH_STATUS}`);
                if (!resp.ok) return;

                const payload = await resp.json();
                realsenseCapabilities = payload.realsense_capabilities || realsenseCapabilities;
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
            } else if (selectedSource === 'phone') {
                sourceToggleBtn.innerHTML = '<i class="fas fa-mobile-alt"></i> Source: Phone Camera';
            } else {
                sourceToggleBtn.innerHTML = '<i class="fas fa-camera"></i> Source: Webcam';
            }

            const canToggle = getAvailableSources().length > 1 && !APP_STATE.liveStreamActive;
            sourceToggleBtn.disabled = !canToggle;

            if (!canToggle) {
                if (APP_STATE.liveStreamActive) {
                    sourceToggleBtn.title = 'Stop monitoring to switch source';
                } else if (!realsenseAvailable && !phoneCameraSupported) {
                    sourceToggleBtn.title = 'No additional camera source available';
                } else {
                    sourceToggleBtn.title = 'Only one source currently available';
                }
                sourceToggleBtn.style.opacity = '0.55';
                sourceToggleBtn.style.cursor = 'not-allowed';
            } else {
                sourceToggleBtn.title = phoneCameraSupported
                    ? 'Click to switch Webcam / RealSense / Phone Camera'
                    : 'Click to switch webcam/RealSense';
                sourceToggleBtn.style.opacity = '1';
                sourceToggleBtn.style.cursor = 'pointer';
            }

            if (selectedSource !== 'realsense') {
                hideDepthWidgets();
            }
        }

        function openSettingsWindow() {
            if (!settingsModal) return;
            settingsModal.classList.add('open');
            settingsModal.setAttribute('aria-hidden', 'false');
            document.body.style.overflow = 'hidden';
            showNotification('Settings window opened', 'info');
        }

        function closeSettingsWindow() {
            if (!settingsModal) return;
            settingsModal.classList.remove('open');
            settingsModal.setAttribute('aria-hidden', 'true');
            document.body.style.overflow = '';
        }

        function toggleSettingsWindowSize() {
            if (!settingsWindow || !toggleSettingsWindowSizeBtn) return;
            const expanded = settingsWindow.classList.toggle('expanded');
            toggleSettingsWindowSizeBtn.innerHTML = expanded
                ? '<i class="fas fa-compress"></i> Compact'
                : '<i class="fas fa-expand"></i> Enlarge';
            toggleSettingsWindowSizeBtn.title = expanded
                ? 'Return to compact size'
                : 'Enlarge settings window';
            showNotification(expanded ? 'Settings window enlarged' : 'Settings window set to compact size', 'info');
        }

        settingsTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                settingsTabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                const target = tab.dataset.settingsTab;
                settingsSections.forEach(sec => {
                    sec.classList.toggle('active', sec.id === `settings-tab-${target}`);
                });
            });
        });
        
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

            const sourceLabel = selectedSource === 'realsense'
                ? (realsenseDeviceName || 'RealSense')
                : (selectedSource === 'phone' ? 'Phone Camera' : 'Webcam');
            showNotification(`Camera source changed to ${sourceLabel}`, 'success');
        });
        
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
            try {
                if (shouldUseBrowserCaptureSource()) {
                    stopPhoneInferenceLoop();
                    stopPhoneCameraTrack();
                } else {
                    await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_STOP}`, {
                        method: 'POST'
                    });
                }

                streamImg.src = '';
                streamImg.style.display = 'none';
                placeholder.style.display = 'block';
                statusIndicator.style.display = 'none';
                if (phoneCameraPreview) phoneCameraPreview.style.display = 'none';
                setLiveControlState(false);
                hideDepthWidgets();
                showNotification('Live monitoring stopped', 'info');
            } catch (error) {
                console.error('Error stopping live stream:', error);
                showNotification('Failed to stop live monitoring cleanly', 'error');
            } finally {
                stopPhoneInferenceLoop();
                stopPhoneCameraTrack();
                streamImg.src = '';
                streamImg.style.display = 'none';
                placeholder.style.display = 'block';
                statusIndicator.style.display = 'none';
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

                if (shouldUseBrowserCaptureSource()) {
                    if (APP_STATE.liveStreamActive) {
                        startBtn.innerHTML = '<i class="fas fa-play"></i> Start';
                        return;
                    }

                    const usingPhoneSource = selectedSource === 'phone';
                    if (usingPhoneSource) {
                        phonePermissionState = 'prompt';
                        updatePhonePermissionBadge();
                    }

                    const videoConstraints = usingPhoneSource
                        ? {
                            facingMode: { ideal: 'environment' },
                            width: { ideal: 1280 },
                            height: { ideal: 720 }
                        }
                        : {
                            width: { ideal: 1280 },
                            height: { ideal: 720 }
                        };

                    const stream = await navigator.mediaDevices.getUserMedia({
                        video: videoConstraints,
                        audio: false
                    });

                    this.phoneCameraStream = stream;
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
                        : '<i class="fas fa-circle" style="animation: blink 1.5s infinite;"></i> CAMERA LIVE';

                    setLiveControlState(true);
                    startBtn.innerHTML = '<i class="fas fa-play"></i> Start';
                    hideDepthWidgets();
                    renderSourceToggle();

                    stopPhoneInferenceLoop();
                    this.phoneInferenceInterval = setInterval(capturePhoneFrameForInference, phoneInferenceConfig.intervalMs);
                    await capturePhoneFrameForInference();

                    showNotification(
                        usingPhoneSource
                            ? 'Phone camera access granted and monitoring started'
                            : 'Webcam access granted and monitoring started',
                        'success'
                    );
                    return;
                }

                // Start monitoring on backend
                const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_START}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ source: selectedSource })
                });

                if (!response.ok) {
                    throw new Error('Failed to start monitoring');
                }

                const startData = await response.json();
                if (startData.source) {
                    selectedSource = startData.source;
                }

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
                APP_STATE.liveStreamActive = true;
                renderSourceToggle();
                await refreshDepthStatus();

                showNotification(`Live monitoring started (${selectedSource === 'realsense' ? (realsenseDeviceName || 'RealSense') : 'Webcam'})`, 'success');

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
                    alert('Failed to start live monitoring. Please check if the webcam is available.');
                }

                startBtn.disabled = false;
                startBtn.innerHTML = '<i class="fas fa-play"></i> Start';
            }
        });

        // Stop live stream
        stopBtn.addEventListener('click', stopLiveStream);

        // Handle stream errors
        streamImg.addEventListener('error', () => {
            if (!APP_STATE.liveStreamActive) {
                return;
            }

            // Browser capture mode uses <video>, not <img>; ignore incidental img errors.
            if (shouldUseBrowserCaptureSource()) {
                return;
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
            selectedSource = devices.default_source || 'webcam';
            if (!realsenseAvailable) {
                selectedSource = 'webcam';
            }

            if (phoneCameraSupported && selectedSource !== 'realsense' && selectedSource !== 'webcam' && selectedSource !== 'phone') {
                selectedSource = 'phone';
            }
            renderCapabilities();
            renderSourceToggle();
        } catch (error) {
            console.error('Error checking live devices:', error);
            selectedSource = 'webcam';
            realsenseAvailable = false;
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
            selectedSource = status.source || status.default_source || selectedSource;
            if (!realsenseAvailable) {
                selectedSource = 'webcam';
            }

            if (phoneCameraSupported && selectedSource !== 'realsense' && selectedSource !== 'webcam' && selectedSource !== 'phone') {
                selectedSource = 'phone';
            }
            
            if (status.active) {
                // Stream is already active
                placeholder.style.display = 'none';
                if (phoneCameraPreview) phoneCameraPreview.style.display = 'none';
                streamImg.style.display = 'block';
                statusIndicator.style.display = 'block';
                statusIndicator.innerHTML = '<i class="fas fa-circle" style="animation: blink 1.5s infinite;"></i> LIVE';
                streamImg.src = buildLiveStreamUrl();
                setLiveControlState(true);
            }

            renderCapabilities();
            renderSourceToggle();
            await refreshDepthStatus();
        } catch (error) {
            console.error('Error checking stream status:', error);
            renderCapabilities();
            renderSourceToggle();
        }

        // =========================================
        // PROCESSING SETTINGS HANDLERS
        // =========================================

        const envValidationToggle = document.getElementById('envValidationToggle');
        const envValidationStatus = document.getElementById('envValidationStatus');
        const cooldownSlider = document.getElementById('cooldownSlider');
        const cooldownValue = document.getElementById('cooldownValue');
        const applyCooldownBtn = document.getElementById('applyCooldownBtn');
        const refreshQueueBtn = document.getElementById('refreshQueueBtn');
        const modelApiToggle = document.getElementById('modelApiToggle');
        const geminiToggle = document.getElementById('geminiToggle');
        const nlpProviderOrderInput = document.getElementById('nlpProviderOrderInput');
        const visionProviderOrderInput = document.getElementById('visionProviderOrderInput');
        const embeddingProviderOrderInput = document.getElementById('embeddingProviderOrderInput');
        const nlpModelInput = document.getElementById('nlpModelInput');
        const visionModelInput = document.getElementById('visionModelInput');
        const embeddingModelInput = document.getElementById('embeddingModelInput');
        const geminiModelInput = document.getElementById('geminiModelInput');
        const applyProviderRoutingBtn = document.getElementById('applyProviderRoutingBtn');
        const reloadProviderRoutingBtn = document.getElementById('reloadProviderRoutingBtn');
        const providerRoutingStatus = document.getElementById('providerRoutingStatus');
        const reliabilityHeadingIcon = document.getElementById('reliabilityHeadingIcon');
        const reliabilityWindowSelect = document.getElementById('reliabilityWindowSelect');
        const refreshReliabilityBtn = document.getElementById('refreshReliabilityBtn');
        const reliabilityLastUpdated = document.getElementById('reliabilityLastUpdated');
        const reliabilityRealSuccess = document.getElementById('reliabilityRealSuccess');
        const reliabilityFallbackRate = document.getElementById('reliabilityFallbackRate');
        const reliabilityHardFailed = document.getElementById('reliabilityHardFailed');
        const reliabilityConsidered = document.getElementById('reliabilityConsidered');
        const reliabilityFailureCauses = document.getElementById('reliabilityFailureCauses');
        const livePerformanceProfile = document.getElementById('livePerformanceProfile');
        const applyLivePerformanceProfileBtn = document.getElementById('applyLivePerformanceProfileBtn');
        const livePerformanceProfileStatus = document.getElementById('livePerformanceProfileStatus');
        const RECOMMENDED_SETTINGS = {
            environment_validation_enabled: true,
            cooldown_seconds: 3,
            provider_routing: {
                model_api_enabled: false,
                gemini_enabled: false,
                nlp_provider_order: 'ollama,local,model_api,gemini',
                vision_provider_order: 'ollama,model_api,gemini',
                embedding_provider_order: 'ollama,model_api',
                nlp_model: 'meta-llama/Meta-Llama-3-8B-Instruct',
                vision_model: 'Qwen/Qwen2.5-VL-7B-Instruct',
                embedding_model: 'nomic-ai/nomic-embed-text-v1.5',
                gemini_model: 'gemini-2.5-flash'
            }
        };
        const API_MODE_SETTINGS = {
            model_api_enabled: true,
            gemini_enabled: true,
            nlp_provider_order: 'model_api,gemini,ollama,local',
            vision_provider_order: 'model_api,gemini,ollama',
            embedding_provider_order: 'model_api,ollama',
            nlp_model: 'meta-llama/Meta-Llama-3-8B-Instruct',
            vision_model: 'Qwen/Qwen2.5-VL-7B-Instruct',
            embedding_model: 'nomic-ai/nomic-embed-text-v1.5',
            gemini_model: 'gemini-2.5-flash'
        };

        const updateLiveProfileStatusText = (profileKey) => {
            if (!livePerformanceProfileStatus) return;
            const key = LIVE_PERFORMANCE_PROFILES[profileKey] ? profileKey : 'balanced';
            const phoneMs = phoneInferenceConfig.intervalMs;
            livePerformanceProfileStatus.textContent = `Profile: ${key} | laptop ${laptopLiveStreamConfig.fps}fps @ q${laptopLiveStreamConfig.quality} | phone ${phoneMs}ms`;
        };

        const applyLivePerformanceProfile = async (profileKey, options = {}) => {
            const silent = !!options.silent;
            const selected = LIVE_PERFORMANCE_PROFILES[profileKey] || LIVE_PERFORMANCE_PROFILES.balanced;
            const key = LIVE_PERFORMANCE_PROFILES[profileKey] ? profileKey : 'balanced';

            Object.assign(laptopLiveStreamConfig, selected.laptop);
            Object.assign(phoneInferenceConfig, selected.phone);

            if (livePerformanceProfile) {
                livePerformanceProfile.value = key;
            }

            updateLiveProfileStatusText(key);

            try {
                localStorage.setItem(LIVE_PROFILE_STORAGE_KEY, key);
            } catch (error) {
                console.warn('Could not persist live profile selection:', error);
            }

            if (APP_STATE.liveStreamActive) {
                if (shouldUseBrowserCaptureSource()) {
                    stopPhoneInferenceLoop();
                    this.phoneInferenceInterval = setInterval(capturePhoneFrameForInference, phoneInferenceConfig.intervalMs);
                    await capturePhoneFrameForInference();
                } else if (streamImg && streamImg.style.display !== 'none') {
                    streamImg.src = buildLiveStreamUrl();
                }
            }

            if (!silent) {
                showNotification(`Applied ${key} live profile`, 'success');
            }
        };

        const restoreLivePerformanceProfile = async () => {
            let storedProfile = 'balanced';
            try {
                storedProfile = localStorage.getItem(LIVE_PROFILE_STORAGE_KEY) || 'balanced';
            } catch (error) {
                storedProfile = 'balanced';
            }

            await applyLivePerformanceProfile(storedProfile, { silent: true });
        };

        // Function to update environment validation status display
        function updateEnvValidationStatus(enabled) {
            if (enabled) {
                envValidationStatus.innerHTML = `
                    <i class="fas fa-check-circle" style="color: var(--success-color);"></i>
                    <strong style="color: var(--success-color);">ENABLED</strong> - 
                    Only work environments will be processed (construction, factory, warehouse)
                `;
                envValidationStatus.style.background = 'rgba(76, 175, 80, 0.1)';
                envValidationStatus.style.border = '1px solid var(--success-color)';
            } else {
                envValidationStatus.innerHTML = `
                    <i class="fas fa-times-circle" style="color: var(--warning-color);"></i>
                    <strong style="color: var(--warning-color);">DISABLED</strong> - 
                    ALL violations will be processed (testing mode)
                `;
                envValidationStatus.style.background = 'rgba(255, 152, 0, 0.1)';
                envValidationStatus.style.border = '1px solid var(--warning-color)';
            }
        }

        if (applyLivePerformanceProfileBtn) {
            applyLivePerformanceProfileBtn.addEventListener('click', async () => {
                const selectedProfile = livePerformanceProfile ? livePerformanceProfile.value : 'balanced';
                await applyLivePerformanceProfile(selectedProfile);
            });
        }

        if (livePerformanceProfile) {
            livePerformanceProfile.addEventListener('change', async () => {
                await applyLivePerformanceProfile(livePerformanceProfile.value);
            });
        }

        await restoreLivePerformanceProfile();

        // Function to fetch and update queue status
        async function updateQueueStatus() {
            try {
                const response = await fetch(`${API_CONFIG.BASE_URL}/api/queue/status`);
                const data = await response.json();
                
                // Safely update elements with null checks
                const queueSizeEl = document.getElementById('queueSize');
                const queueProcessedEl = document.getElementById('queueProcessed');
                const queueFailedEl = document.getElementById('queueFailed');
                const workerStatusEl = document.getElementById('workerStatus');
                
                if (queueSizeEl) queueSizeEl.textContent = data.queue_size || 0;
                if (queueProcessedEl) queueProcessedEl.textContent = data.total_processed || 0;
                if (queueFailedEl) queueFailedEl.textContent = data.total_failed || 0;
                
                if (workerStatusEl) {
                    if (data.worker_running) {
                        workerStatusEl.textContent = 'Running';
                        workerStatusEl.style.color = 'var(--success-color)';
                    } else {
                        workerStatusEl.textContent = 'Stopped';
                        workerStatusEl.style.color = 'var(--danger-color)';
                    }
                }

                // Also update environment validation toggle from server state
                if (data.environment_validation_enabled !== undefined && envValidationToggle) {
                    envValidationToggle.checked = data.environment_validation_enabled;
                    updateEnvValidationStatus(data.environment_validation_enabled);
                }
            } catch (error) {
                console.error('Error fetching queue status:', error);
            }
        }

        function updateReliabilityHeadingVisual(realSuccessRate) {
            if (!reliabilityHeadingIcon) return;

            if (realSuccessRate >= 0.85) {
                reliabilityHeadingIcon.className = 'fas fa-shield-alt';
                reliabilityHeadingIcon.style.color = 'var(--success-color)';
            } else if (realSuccessRate >= 0.6) {
                reliabilityHeadingIcon.className = 'fas fa-exclamation-triangle';
                reliabilityHeadingIcon.style.color = 'var(--warning-color)';
            } else {
                reliabilityHeadingIcon.className = 'fas fa-exclamation-circle';
                reliabilityHeadingIcon.style.color = 'var(--error-color)';
            }
        }

        function humanizeFailureCauses(causes) {
            if (!causes || typeof causes !== 'object') {
                return 'No failure cause data';
            }

            const pairs = Object.entries(causes)
                .filter(([, value]) => Number(value) > 0)
                .sort((a, b) => Number(b[1]) - Number(a[1]));

            if (pairs.length === 0) {
                return 'No failures in selected window';
            }

            return pairs.map(([key, value]) => `${key.replace(/_/g, ' ')}: ${value}`).join(' • ');
        }

        async function updateReliabilityStatus() {
            try {
                const windowSize = reliabilityWindowSelect ? Number(reliabilityWindowSelect.value || 50) : 50;
                const data = await API.getReliabilityStats(windowSize);

                if (!data || data.success === false) {
                    throw new Error((data && data.error) || 'Unable to load reliability stats');
                }

                const realSuccessRate = Number(data.real_success_rate || 0);
                const fallbackNeededRate = Number(data.fallback_needed_rate || 0);
                const hardFailed = Number(data.hard_failed_count || 0);
                const considered = Number(data.considered_count || 0);

                if (reliabilityRealSuccess) reliabilityRealSuccess.textContent = `${(realSuccessRate * 100).toFixed(1)}%`;
                if (reliabilityFallbackRate) reliabilityFallbackRate.textContent = `${(fallbackNeededRate * 100).toFixed(1)}%`;
                if (reliabilityHardFailed) reliabilityHardFailed.textContent = String(hardFailed);
                if (reliabilityConsidered) reliabilityConsidered.textContent = String(considered);
                if (reliabilityFailureCauses) reliabilityFailureCauses.textContent = humanizeFailureCauses(data.failure_causes || {});

                updateReliabilityHeadingVisual(realSuccessRate);

                if (reliabilityLastUpdated) {
                    reliabilityLastUpdated.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
                }
            } catch (error) {
                console.error('Error fetching reliability status:', error);
                if (reliabilityLastUpdated) {
                    reliabilityLastUpdated.textContent = 'Last updated: failed to fetch';
                }
                if (reliabilityFailureCauses) {
                    reliabilityFailureCauses.textContent = 'Unable to load reliability stats';
                }
                updateReliabilityHeadingVisual(0);
            }
        }

        function renderProviderRuntimeStatus(data) {
            if (!providerRuntimeActive || !providerRuntimeCapacity) return;

            const runtime = (data && data.runtime) || {};
            const nlp = runtime.nlp || {};
            const capacity = (data && data.capacity) || {};

            const provider = nlp.last_provider || 'unknown';
            const model = nlp.last_model || '-';
            const fallbackReason = nlp.last_fallback_reason ? ` (reason: ${nlp.last_fallback_reason})` : '';
            providerRuntimeActive.textContent = `Active provider: ${provider} | model: ${model}${fallbackReason}`;

            const estimate = capacity.estimate_reports_remaining;
            const estimateText = estimate == null ? 'unbounded/unknown' : String(estimate);
            const confidence = capacity.confidence || 'low';
            const message = capacity.message || 'No capacity telemetry available.';
            providerRuntimeCapacity.textContent = `Estimated remaining reports: ${estimateText} (confidence: ${confidence}) - ${message}`;

            if ((capacity.status || '') === 'depleted') {
                providerRuntimeCapacity.style.color = 'var(--error-color)';
            } else if ((capacity.status || '') === 'limited') {
                providerRuntimeCapacity.style.color = 'var(--warning-color)';
            } else {
                providerRuntimeCapacity.style.color = 'var(--text-secondary)';
            }
        }

        async function updateProviderRuntimeStatus() {
            try {
                const data = await API.getProviderRuntimeStatus();
                if (!data || data.success === false) {
                    throw new Error((data && data.error) || 'Failed to load provider runtime');
                }
                renderProviderRuntimeStatus(data);
            } catch (error) {
                console.error('Error loading provider runtime status:', error);
                if (providerRuntimeActive) providerRuntimeActive.textContent = 'Active provider: unavailable';
                if (providerRuntimeCapacity) {
                    providerRuntimeCapacity.textContent = 'Estimated remaining reports: unavailable';
                    providerRuntimeCapacity.style.color = 'var(--error-color)';
                }
            }
        }

        // Function to fetch current settings
        async function loadCurrentSettings() {
            try {
                // Get environment validation setting
                const envResponse = await fetch(`${API_CONFIG.BASE_URL}/api/settings/environment-validation`);
                const envData = await envResponse.json();
                envValidationToggle.checked = envData.enabled;
                updateEnvValidationStatus(envData.enabled);

                // Get cooldown setting
                const cooldownResponse = await fetch(`${API_CONFIG.BASE_URL}/api/settings/cooldown`);
                const cooldownData = await cooldownResponse.json();
                cooldownSlider.value = cooldownData.cooldown_seconds;
                cooldownValue.textContent = cooldownData.cooldown_seconds + 's';
            } catch (error) {
                console.error('Error loading settings:', error);
            }

            // Also update queue status
            await updateQueueStatus();
            await updateReliabilityStatus();
            await updateProviderRuntimeStatus();
            await loadProviderRoutingSettings();
        }

        function setProviderStatus(message, type = 'info') {
            if (!providerRoutingStatus) return;

            providerRoutingStatus.textContent = message;
            if (type === 'success') {
                providerRoutingStatus.style.color = 'var(--success-color)';
            } else if (type === 'error') {
                providerRoutingStatus.style.color = 'var(--error-color)';
            } else if (type === 'warning') {
                providerRoutingStatus.style.color = 'var(--warning-color)';
            } else {
                providerRoutingStatus.style.color = 'var(--text-secondary)';
            }
        }

        async function loadProviderRoutingSettings() {
            try {
                setProviderStatus('Loading provider settings...');

                const settings = await API.getProviderRoutingSettings();
                if (!settings) {
                    setProviderStatus('Unable to load provider settings', 'warning');
                    return;
                }

                if (modelApiToggle) modelApiToggle.checked = !!settings.model_api_enabled;
                if (geminiToggle) geminiToggle.checked = !!settings.gemini_enabled;
                if (nlpProviderOrderInput) nlpProviderOrderInput.value = (settings.nlp_provider_order || []).join(',');
                if (visionProviderOrderInput) visionProviderOrderInput.value = (settings.vision_provider_order || []).join(',');
                if (embeddingProviderOrderInput) embeddingProviderOrderInput.value = (settings.embedding_provider_order || []).join(',');
                if (nlpModelInput) nlpModelInput.value = settings.nlp_model || '';
                if (visionModelInput) visionModelInput.value = settings.vision_model || '';
                if (embeddingModelInput) embeddingModelInput.value = settings.embedding_model || '';
                if (geminiModelInput) geminiModelInput.value = settings.gemini_model || '';

                setProviderStatus('Provider settings loaded');
            } catch (error) {
                console.error('Error loading provider settings:', error);
                setProviderStatus('Failed to load provider settings', 'error');
            }
        }

        async function applyProviderRoutingSettings() {
            try {
                applyProviderRoutingBtn.disabled = true;
                applyProviderRoutingBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Applying...';

                const payload = {
                    model_api_enabled: !!modelApiToggle.checked,
                    gemini_enabled: !!geminiToggle.checked,
                    nlp_provider_order: (nlpProviderOrderInput.value || '').trim(),
                    vision_provider_order: (visionProviderOrderInput.value || '').trim(),
                    embedding_provider_order: (embeddingProviderOrderInput.value || '').trim(),
                    nlp_model: (nlpModelInput.value || '').trim(),
                    vision_model: (visionModelInput.value || '').trim(),
                    embedding_model: (embeddingModelInput.value || '').trim(),
                    gemini_model: (geminiModelInput.value || '').trim()
                };

                const result = await API.updateProviderRoutingSettings(payload);
                if (result && result.success) {
                    setProviderStatus('Provider routing updated successfully', 'success');
                    showNotification('Provider routing updated', 'success');
                    await loadProviderRoutingSettings();
                    await updateProviderRuntimeStatus();
                } else {
                    const errorMessage = (result && result.error) ? result.error : 'Failed to update provider settings';
                    setProviderStatus(errorMessage, 'error');
                    showNotification(errorMessage, 'error');
                }
            } catch (error) {
                console.error('Error applying provider settings:', error);
                setProviderStatus('Failed to update provider settings', 'error');
                showNotification('Failed to update provider settings', 'error');
            } finally {
                applyProviderRoutingBtn.disabled = false;
                applyProviderRoutingBtn.innerHTML = '<i class="fas fa-save"></i> Apply Provider Routing';
            }
        }

        function applyRecommendedValuesToForm() {
            if (envValidationToggle) envValidationToggle.checked = !!RECOMMENDED_SETTINGS.environment_validation_enabled;
            if (cooldownSlider) cooldownSlider.value = RECOMMENDED_SETTINGS.cooldown_seconds;
            if (cooldownValue) cooldownValue.textContent = RECOMMENDED_SETTINGS.cooldown_seconds + 's';

            const routing = RECOMMENDED_SETTINGS.provider_routing;
            if (modelApiToggle) modelApiToggle.checked = !!routing.model_api_enabled;
            if (geminiToggle) geminiToggle.checked = !!routing.gemini_enabled;
            if (nlpProviderOrderInput) nlpProviderOrderInput.value = routing.nlp_provider_order;
            if (visionProviderOrderInput) visionProviderOrderInput.value = routing.vision_provider_order;
            if (embeddingProviderOrderInput) embeddingProviderOrderInput.value = routing.embedding_provider_order;
            if (nlpModelInput) nlpModelInput.value = routing.nlp_model;
            if (visionModelInput) visionModelInput.value = routing.vision_model;
            if (embeddingModelInput) embeddingModelInput.value = routing.embedding_model;
            if (geminiModelInput) geminiModelInput.value = routing.gemini_model;

            updateEnvValidationStatus(!!RECOMMENDED_SETTINGS.environment_validation_enabled);
            setProviderStatus('Recommended values loaded. Click apply buttons or use the recommended action again to save.', 'info');
        }

        function applyApiModeValuesToForm() {
            if (modelApiToggle) modelApiToggle.checked = !!API_MODE_SETTINGS.model_api_enabled;
            if (geminiToggle) geminiToggle.checked = !!API_MODE_SETTINGS.gemini_enabled;
            if (nlpProviderOrderInput) nlpProviderOrderInput.value = API_MODE_SETTINGS.nlp_provider_order;
            if (visionProviderOrderInput) visionProviderOrderInput.value = API_MODE_SETTINGS.vision_provider_order;
            if (embeddingProviderOrderInput) embeddingProviderOrderInput.value = API_MODE_SETTINGS.embedding_provider_order;
            if (nlpModelInput) nlpModelInput.value = API_MODE_SETTINGS.nlp_model;
            if (visionModelInput) visionModelInput.value = API_MODE_SETTINGS.vision_model;
            if (embeddingModelInput) embeddingModelInput.value = API_MODE_SETTINGS.embedding_model;
            if (geminiModelInput) geminiModelInput.value = API_MODE_SETTINGS.gemini_model;
        }

        async function applyApiModeSettings() {
            const providerResult = await API.updateProviderRoutingSettings({
                ...API_MODE_SETTINGS
            });

            if (!providerResult || !providerResult.success) {
                throw new Error((providerResult && providerResult.error) || 'Failed to switch to API mode');
            }

            applyApiModeValuesToForm();
            setProviderStatus('API mode enabled for optimized cloud inference', 'success');
            showNotification('Switched to API mode', 'success');
        }

        async function setEnvironmentValidation(enabled) {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/settings/environment-validation`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled })
            });

            const data = await response.json();
            if (!data.success) {
                throw new Error(data.error || 'Failed to update environment validation');
            }

            return data;
        }

        async function setCooldown(seconds) {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/settings/cooldown`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cooldown_seconds: seconds })
            });

            const data = await response.json();
            if (!data.success) {
                throw new Error(data.error || 'Failed to update cooldown');
            }

            return data;
        }

        async function applyRecommendedSettings() {
            try {
                const targets = [quickRecommendedSettingsBtn, recommendedSettingsBtn].filter(Boolean);
                targets.forEach(btn => {
                    btn.disabled = true;
                    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Applying recommended...';
                });

                applyRecommendedValuesToForm();

                await setEnvironmentValidation(!!RECOMMENDED_SETTINGS.environment_validation_enabled);
                await setCooldown(RECOMMENDED_SETTINGS.cooldown_seconds);

                const providerResult = await API.updateProviderRoutingSettings({
                    ...RECOMMENDED_SETTINGS.provider_routing
                });

                if (!providerResult || !providerResult.success) {
                    throw new Error((providerResult && providerResult.error) || 'Failed to apply provider routing');
                }

                const diskStatus = await API.getDiskSpaceStatus();
                if (diskStatus && diskStatus.success && diskStatus.sufficient === false) {
                    const warningText = [
                        'Local-first mode may not run well because available disk space is below the model requirement.',
                        `Required: ${diskStatus.required_gb} GB`,
                        `Available: ${diskStatus.free_gb} GB`,
                        'Switch to API mode now for optimized experience?'
                    ].join('\n');

                    const shouldSwitchToApi = confirm(warningText);
                    if (shouldSwitchToApi) {
                        await applyApiModeSettings();
                    } else {
                        alert('You can switch to API mode later from Provider Routing settings.');
                        showNotification('Low disk space detected. API mode is recommended.', 'warning');
                    }
                }

                await loadCurrentSettings();
                showNotification('Recommended monitoring settings applied', 'success');
                setProviderStatus('Recommended provider settings applied', 'success');
            } catch (error) {
                console.error('Error applying recommended settings:', error);
                showNotification(error.message || 'Failed to apply recommended settings', 'error');
                setProviderStatus('Failed to apply recommended provider settings', 'error');
            } finally {
                const targets = [quickRecommendedSettingsBtn, recommendedSettingsBtn].filter(Boolean);
                targets.forEach(btn => {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fas fa-magic"></i> Use Recommended Settings';
                });
            }
        }

        // Environment validation toggle handler
        envValidationToggle.addEventListener('change', async () => {
            const enabled = envValidationToggle.checked;
            
            try {
                const data = await setEnvironmentValidation(enabled);
                
                if (data.success) {
                    updateEnvValidationStatus(data.enabled);
                    showNotification(data.message, 'success');
                } else {
                    // Revert toggle on failure
                    envValidationToggle.checked = !enabled;
                    showNotification('Failed to update setting', 'error');
                }
            } catch (error) {
                console.error('Error updating environment validation:', error);
                envValidationToggle.checked = !enabled;
                showNotification('Failed to update setting', 'error');
            }
        });

        // Cooldown slider handler
        cooldownSlider.addEventListener('input', () => {
            cooldownValue.textContent = cooldownSlider.value + 's';
        });

        // Apply cooldown button handler
        applyCooldownBtn.addEventListener('click', async () => {
            const newCooldown = parseInt(cooldownSlider.value);
            
            try {
                applyCooldownBtn.disabled = true;
                applyCooldownBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Applying...';

                await setCooldown(newCooldown);
                
                showNotification(`Cooldown set to ${newCooldown} seconds`, 'success');
            } catch (error) {
                console.error('Error updating cooldown:', error);
                showNotification('Failed to update cooldown', 'error');
            } finally {
                applyCooldownBtn.disabled = false;
                applyCooldownBtn.innerHTML = '<i class="fas fa-save"></i> Apply Cooldown';
            }
        });

        // Refresh queue status button handler
        refreshQueueBtn.addEventListener('click', async () => {
            refreshQueueBtn.disabled = true;
            refreshQueueBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Refreshing...';
            
            await updateQueueStatus();
            await updateReliabilityStatus();
            await updateProviderRuntimeStatus();
            
            refreshQueueBtn.disabled = false;
            refreshQueueBtn.innerHTML = '<i class="fas fa-sync-alt"></i> Refresh Status';
            showNotification('Queue, reliability, and provider status refreshed', 'info');
        });

        if (refreshReliabilityBtn) {
            refreshReliabilityBtn.addEventListener('click', async () => {
                refreshReliabilityBtn.disabled = true;
                refreshReliabilityBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Refreshing...';
                await updateReliabilityStatus();
                refreshReliabilityBtn.disabled = false;
                refreshReliabilityBtn.innerHTML = '<i class="fas fa-sync-alt"></i> Refresh Reliability';
            });
        }

        if (reliabilityWindowSelect) {
            reliabilityWindowSelect.addEventListener('change', updateReliabilityStatus);
        }

        if (applyProviderRoutingBtn) {
            applyProviderRoutingBtn.addEventListener('click', applyProviderRoutingSettings);
        }

        if (reloadProviderRoutingBtn) {
            reloadProviderRoutingBtn.addEventListener('click', async () => {
                reloadProviderRoutingBtn.disabled = true;
                reloadProviderRoutingBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Reloading...';
                await loadProviderRoutingSettings();
                await updateProviderRuntimeStatus();
                reloadProviderRoutingBtn.disabled = false;
                reloadProviderRoutingBtn.innerHTML = '<i class="fas fa-sync-alt"></i> Reload Provider Settings';
                showNotification('Provider routing settings reloaded', 'info');
            });
        }

        if (openSettingsWindowBtn) {
            openSettingsWindowBtn.addEventListener('click', openSettingsWindow);
        }

        if (closeSettingsWindowBtn) {
            closeSettingsWindowBtn.addEventListener('click', closeSettingsWindow);
        }

        if (toggleSettingsWindowSizeBtn) {
            toggleSettingsWindowSizeBtn.addEventListener('click', toggleSettingsWindowSize);
        }

        if (settingsModal) {
            settingsModal.addEventListener('click', (event) => {
                if (event.target === settingsModal) {
                    closeSettingsWindow();
                }
            });
        }

        const onSettingsKeydown = (event) => {
            if (event.key === 'Escape' && settingsModal && settingsModal.classList.contains('open')) {
                closeSettingsWindow();
            }
        };
        document.addEventListener('keydown', onSettingsKeydown);
        this.settingsKeydownHandler = onSettingsKeydown;

        if (quickRecommendedSettingsBtn) {
            quickRecommendedSettingsBtn.addEventListener('click', applyRecommendedSettings);
        }

        if (recommendedSettingsBtn) {
            recommendedSettingsBtn.addEventListener('click', applyRecommendedSettings);
        }

        this.realtimeHandler = () => {
            updateQueueStatus();
            updateReliabilityStatus();
        };
        window.addEventListener('ppe-realtime:update', this.realtimeHandler);

        this.realtimeConnectionHandler = () => {
            const connected = typeof RealtimeSync !== 'undefined' && RealtimeSync.isConnected;
            if (connected) {
                if (this.queueRefreshInterval) {
                    clearInterval(this.queueRefreshInterval);
                    this.queueRefreshInterval = null;
                }
                if (this.reliabilityRefreshInterval) {
                    clearInterval(this.reliabilityRefreshInterval);
                    this.reliabilityRefreshInterval = null;
                }
            } else {
                if (!this.queueRefreshInterval) {
                    this.queueRefreshInterval = setInterval(updateQueueStatus, 5000);
                }
                if (!this.reliabilityRefreshInterval) {
                    this.reliabilityRefreshInterval = setInterval(updateReliabilityStatus, 10000);
                }
            }
        };
        window.addEventListener('ppe-realtime:connection', this.realtimeConnectionHandler);

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

        // Load settings on mount
        updatePhonePermissionBadge();
        await initPhonePermissionWatcher();
        await loadCurrentSettings();
        await updateProviderRuntimeStatus();

        const depthStatusInterval = setInterval(refreshDepthStatus, 1500);
        this.depthStatusInterval = depthStatusInterval;
        this.providerRuntimeInterval = setInterval(updateProviderRuntimeStatus, 15000);

        // Realtime-first: only use polling if realtime stream is unavailable.
        this.realtimeConnectionHandler();

        // Clean up interval when leaving page (store for cleanup)
        window._livePageQueueInterval = this.queueRefreshInterval;
        window._livePageReliabilityInterval = this.reliabilityRefreshInterval;
        window._liveDepthStatusInterval = depthStatusInterval;
        window._liveProviderRuntimeInterval = this.providerRuntimeInterval;
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

        if (this.queueRefreshInterval) {
            clearInterval(this.queueRefreshInterval);
            this.queueRefreshInterval = null;
        }

        if (this.reliabilityRefreshInterval) {
            clearInterval(this.reliabilityRefreshInterval);
            this.reliabilityRefreshInterval = null;
        }

        if (this.depthStatusInterval) {
            clearInterval(this.depthStatusInterval);
            this.depthStatusInterval = null;
        }

        if (this.providerRuntimeInterval) {
            clearInterval(this.providerRuntimeInterval);
            this.providerRuntimeInterval = null;
        }

        if (this.settingsKeydownHandler) {
            document.removeEventListener('keydown', this.settingsKeydownHandler);
            this.settingsKeydownHandler = null;
        }

        if (this.realtimeHandler) {
            window.removeEventListener('ppe-realtime:update', this.realtimeHandler);
            this.realtimeHandler = null;
        }

        if (this.realtimeConnectionHandler) {
            window.removeEventListener('ppe-realtime:connection', this.realtimeConnectionHandler);
            this.realtimeConnectionHandler = null;
        }

        if (window._livePageQueueInterval) {
            clearInterval(window._livePageQueueInterval);
            window._livePageQueueInterval = null;
        }
        if (window._livePageReliabilityInterval) {
            clearInterval(window._livePageReliabilityInterval);
            window._livePageReliabilityInterval = null;
        }
        if (window._liveDepthStatusInterval) {
            clearInterval(window._liveDepthStatusInterval);
            window._liveDepthStatusInterval = null;
        }
        if (window._liveProviderRuntimeInterval) {
            clearInterval(window._liveProviderRuntimeInterval);
            window._liveProviderRuntimeInterval = null;
        }
    }
};
