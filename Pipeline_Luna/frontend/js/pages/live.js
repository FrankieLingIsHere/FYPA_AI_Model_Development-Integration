// Live Monitoring Page Component
const LivePage = {
    render() {
        return `
            <div class="page">
                <div class="card mb-4">
                    <div class="card-header">
                        <span><i class="fas fa-video"></i> Live PPE Monitoring</span>
                    </div>
                    <div class="card-content">
                        <div class="alert alert-info mb-3">
                            <i class="fas fa-info-circle"></i>
                            <span>To start live monitoring, run the Python script: <code>python run_live_demo.py</code></span>
                        </div>

                        <div style="background: #000; border-radius: 8px; padding: 2rem; text-align: center; margin-bottom: 1.5rem;">
                            <i class="fas fa-video" style="font-size: 4rem; color: #fff; opacity: 0.3; margin-bottom: 1rem;"></i>
                            <p style="color: #fff; margin: 0;">Live video stream will appear here</p>
                            <p style="color: #aaa; font-size: 0.9rem; margin-top: 0.5rem;">
                                (Feature coming soon - currently runs in separate window)
                            </p>
                        </div>

                        <h3 style="margin-bottom: 1rem;">How to Use Live Monitoring:</h3>
                        <ol style="margin-left: 1.5rem; line-height: 2;">
                            <li>Open a terminal in the project directory</li>
                            <li>Run: <code>python run_live_demo.py</code></li>
                            <li>A window will open showing the live webcam feed</li>
                            <li>YOLO will detect PPE in real-time</li>
                            <li>When NO-Hardhat is detected, a violation is triggered</li>
                            <li>System automatically captures high-res images and generates report</li>
                        </ol>

                        <h3 style="margin-top: 2rem; margin-bottom: 1rem;">Controls:</h3>
                        <div class="grid grid-3">
                            <div class="card" style="background: var(--background-color);">
                                <div class="card-content text-center">
                                    <kbd style="background: var(--primary-color); color: white; padding: 0.5rem 1rem; border-radius: 4px; font-size: 1.2rem;">Q</kbd>
                                    <p style="margin-top: 0.5rem;">Quit monitoring</p>
                                </div>
                            </div>
                            <div class="card" style="background: var(--background-color);">
                                <div class="card-content text-center">
                                    <kbd style="background: var(--primary-color); color: white; padding: 0.5rem 1rem; border-radius: 4px; font-size: 1.2rem;">P</kbd>
                                    <p style="margin-top: 0.5rem;">Pause/Resume</p>
                                </div>
                            </div>
                            <div class="card" style="background: var(--background-color);">
                                <div class="card-content text-center">
                                    <kbd style="background: var(--primary-color); color: white; padding: 0.5rem 1rem; border-radius: 4px; font-size: 1.2rem;">S</kbd>
                                    <p style="margin-top: 0.5rem;">Show status</p>
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
                                    <li>Image quality: 1920x1080 Full HD</li>
                                    <li>Cooldown: 30 seconds between violations</li>
                                </ul>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    },

    mount() {
        // No dynamic content to load
    }
};
