// Live Monitoring Page Component
const LivePage = {
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
                            <button id="startLiveBtn" class="btn btn-success" style="margin-right: 10px;">
                                <i class="fas fa-play"></i> Start
                            </button>
                            <button id="stopLiveBtn" class="btn btn-danger" disabled>
                                <i class="fas fa-stop"></i> Stop
                            </button>
                        </div>
                    </div>
                    <div class="card-content">
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
                            <div id="streamStatus" style="position: absolute; top: 10px; right: 10px; background: rgba(0,0,0,0.7); color: #4CAF50; padding: 8px 16px; border-radius: 20px; font-weight: bold; display: none;">
                                <i class="fas fa-circle" style="animation: blink 1.5s infinite;"></i> LIVE
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

                        <h3 style="margin-bottom: 1rem;">Instructions:</h3>
                        <ol id="instructionsList" style="margin-left: 1.5rem; line-height: 2;">
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
        const startBtn = document.getElementById('startLiveBtn');
        const stopBtn = document.getElementById('stopLiveBtn');
        const streamImg = document.getElementById('liveStream');
        const placeholder = document.getElementById('streamPlaceholder');
        const statusIndicator = document.getElementById('streamStatus');
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
            instructionsList.innerHTML = `
                <li>Click the <strong>"Start"</strong> button above to begin live monitoring</li>
                <li>Your webcam will activate and show the live feed</li>
                <li>YOLO will detect PPE in real-time with bounding boxes</li>
                <li>When violations are detected, they will be logged automatically</li>
                <li>Click <strong>"Stop"</strong> to end the monitoring session</li>
            `;
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
            instructionsList.innerHTML = `
                <li>Click the upload area or <strong>drop an image</strong> to select a file</li>
                <li>Preview will show your selected image</li>
                <li>Click <strong>"Analyze for PPE Violations"</strong> to run detection</li>
                <li>Violations will be automatically logged and full reports generated</li>
                <li>View detection results with annotated bounding boxes</li>
            `;
        }
        
        // Mode button listeners
        liveModeBtn.addEventListener('click', switchToLiveMode);
        uploadModeBtn.addEventListener('click', switchToUploadMode);
        
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
            try {
                await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.LIVE_STOP}`, {
                    method: 'POST'
                });
                streamImg.src = '';
                streamImg.style.display = 'none';
                placeholder.style.display = 'block';
                statusIndicator.style.display = 'none';
                stopBtn.disabled = true;
                startBtn.disabled = false;
                APP_STATE.liveStreamActive = false;
            } catch (error) {
                console.error('Error stopping live stream:', error);
            }
        }
        
        // Attach event listeners
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
        stopBtn.addEventListener('click', stopLiveStream);

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
            }
        } catch (error) {
            console.error('Error checking stream status:', error);
        }
    }
};
