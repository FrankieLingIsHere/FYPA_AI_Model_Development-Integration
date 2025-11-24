// About Page Component
const AboutPage = {
    render() {
        return `
            <div class="page">
                <!-- Project Overview -->
                <div class="card mb-4">
                    <div class="card-content text-center">
                        <i class="fas fa-hard-hat" style="font-size: 4rem; color: var(--secondary-color); margin-bottom: 1rem;"></i>
                        <h1 style="font-size: 2.5rem; color: var(--primary-color); margin-bottom: 1rem;">
                            PPE Safety Monitor
                        </h1>
                        <p style="font-size: 1.2rem; color: var(--text-color); max-width: 800px; margin: 0 auto 1rem auto;">
                            An AI-powered real-time workplace safety monitoring system that uses advanced computer vision 
                            and natural language processing to detect PPE violations and generate comprehensive safety reports.
                        </p>
                        <div style="display: flex; gap: 1rem; justify-content: center; flex-wrap: wrap; margin-top: 1.5rem;">
                            <span class="badge badge-info" style="font-size: 1rem; padding: 0.5rem 1rem;">Computer Vision</span>
                            <span class="badge badge-info" style="font-size: 1rem; padding: 0.5rem 1rem;">Deep Learning</span>
                            <span class="badge badge-info" style="font-size: 1rem; padding: 0.5rem 1rem;">NLP</span>
                            <span class="badge badge-info" style="font-size: 1rem; padding: 0.5rem 1rem;">Real-time Detection</span>
                        </div>
                    </div>
                </div>

                <!-- Technology Stack -->
                <div class="card mb-4">
                    <div class="card-header">
                        <span><i class="fas fa-microchip"></i> Technology Stack</span>
                    </div>
                    <div class="card-content">
                        <div class="grid grid-2">
                            <div>
                                <h3 style="color: var(--primary-color); margin-bottom: 1rem;">
                                    <i class="fas fa-eye"></i> Computer Vision
                                </h3>
                                <ul style="line-height: 2; margin-left: 1.5rem;">
                                    <li><strong>YOLOv8</strong> - Custom trained model on 14 PPE classes</li>
                                    <li><strong>OpenCV</strong> - High-resolution image capture (1920x1080)</li>
                                    <li><strong>Real-time Detection</strong> - 30 FPS processing</li>
                                    <li><strong>Dual Processing</strong> - Fast inference + high-quality capture</li>
                                </ul>
                            </div>
                            <div>
                                <h3 style="color: var(--primary-color); margin-bottom: 1rem;">
                                    <i class="fas fa-brain"></i> AI & NLP
                                </h3>
                                <ul style="line-height: 2; margin-left: 1.5rem;">
                                    <li><strong>LLaVA 1.5-7b</strong> - Image captioning (4-bit quantization)</li>
                                    <li><strong>Llama3.2</strong> - NLP analysis via Ollama</li>
                                    <li><strong>RAG System</strong> - 551 historical incidents database</li>
                                    <li><strong>Smart Reports</strong> - AI-generated recommendations</li>
                                </ul>
                            </div>
                        </div>
                        <div class="grid grid-2 mt-3">
                            <div>
                                <h3 style="color: var(--primary-color); margin-bottom: 1rem;">
                                    <i class="fas fa-server"></i> Backend
                                </h3>
                                <ul style="line-height: 2; margin-left: 1.5rem;">
                                    <li><strong>Python</strong> - Core system implementation</li>
                                    <li><strong>Flask</strong> - Web server and API</li>
                                    <li><strong>SQLite</strong> - Development database</li>
                                    <li><strong>Threading</strong> - Concurrent processing pipeline</li>
                                </ul>
                            </div>
                            <div>
                                <h3 style="color: var(--primary-color); margin-bottom: 1rem;">
                                    <i class="fas fa-desktop"></i> Frontend
                                </h3>
                                <ul style="line-height: 2; margin-left: 1.5rem;">
                                    <li><strong>HTML5/CSS3</strong> - Modern responsive design</li>
                                    <li><strong>Vanilla JavaScript</strong> - SPA with custom router</li>
                                    <li><strong>REST API</strong> - Backend integration</li>
                                    <li><strong>FontAwesome</strong> - Icon library</li>
                                </ul>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Features -->
                <div class="card mb-4">
                    <div class="card-header">
                        <span><i class="fas fa-star"></i> Key Features</span>
                    </div>
                    <div class="card-content">
                        <div class="grid grid-3">
                            <div class="card" style="background: var(--background-color);">
                                <div class="card-content text-center">
                                    <i class="fas fa-video" style="font-size: 2.5rem; color: var(--secondary-color); margin-bottom: 1rem;"></i>
                                    <h4 style="margin-bottom: 0.5rem;">Real-time Monitoring</h4>
                                    <p>Continuous webcam feed analysis with instant violation detection</p>
                                </div>
                            </div>
                            <div class="card" style="background: var(--background-color);">
                                <div class="card-content text-center">
                                    <i class="fas fa-camera" style="font-size: 2.5rem; color: var(--success-color); margin-bottom: 1rem;"></i>
                                    <h4 style="margin-bottom: 0.5rem;">High-Res Capture</h4>
                                    <p>1920x1080 Full HD images for detailed evidence and AI analysis</p>
                                </div>
                            </div>
                            <div class="card" style="background: var(--background-color);">
                                <div class="card-content text-center">
                                    <i class="fas fa-comments" style="font-size: 2.5rem; color: var(--warning-color); margin-bottom: 1rem;"></i>
                                    <h4 style="margin-bottom: 0.5rem;">AI Descriptions</h4>
                                    <p>Natural language scene descriptions using LLaVA vision model</p>
                                </div>
                            </div>
                            <div class="card" style="background: var(--background-color);">
                                <div class="card-content text-center">
                                    <i class="fas fa-file-alt" style="font-size: 2.5rem; color: var(--error-color); margin-bottom: 1rem;"></i>
                                    <h4 style="margin-bottom: 0.5rem;">Smart Reports</h4>
                                    <p>NLP-powered safety analysis with actionable recommendations</p>
                                </div>
                            </div>
                            <div class="card" style="background: var(--background-color);">
                                <div class="card-content text-center">
                                    <i class="fas fa-database" style="font-size: 2.5rem; color: var(--info-color); margin-bottom: 1rem;"></i>
                                    <h4 style="margin-bottom: 0.5rem;">RAG Knowledge</h4>
                                    <p>Learn from 551 historical incidents for better recommendations</p>
                                </div>
                            </div>
                            <div class="card" style="background: var(--background-color);">
                                <div class="card-content text-center">
                                    <i class="fas fa-chart-line" style="font-size: 2.5rem; color: var(--primary-color); margin-bottom: 1rem;"></i>
                                    <h4 style="margin-bottom: 0.5rem;">Analytics</h4>
                                    <p>Comprehensive safety metrics and trend analysis</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- PPE Classes -->
                <div class="card mb-4">
                    <div class="card-header">
                        <span><i class="fas fa-list"></i> Detected PPE Classes (14 Total)</span>
                    </div>
                    <div class="card-content">
                        <div class="grid grid-2">
                            <div>
                                <h4 style="margin-bottom: 1rem; color: var(--success-color);">
                                    <i class="fas fa-check-circle"></i> Positive Classes (Compliant)
                                </h4>
                                <div style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
                                    <span class="badge badge-success">Hardhat</span>
                                    <span class="badge badge-success">Safety Vest</span>
                                    <span class="badge badge-success">Mask</span>
                                    <span class="badge badge-success">Gloves</span>
                                    <span class="badge badge-success">Safety Shoes</span>
                                    <span class="badge badge-success">Goggles</span>
                                    <span class="badge badge-info">Person</span>
                                    <span class="badge badge-info">Machinery</span>
                                </div>
                            </div>
                            <div>
                                <h4 style="margin-bottom: 1rem; color: var(--error-color);">
                                    <i class="fas fa-exclamation-triangle"></i> Negative Classes (Violations)
                                </h4>
                                <div style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
                                    <span class="badge badge-danger">NO-Hardhat</span>
                                    <span class="badge badge-danger">NO-Safety Vest</span>
                                    <span class="badge badge-danger">NO-Mask</span>
                                    <span class="badge badge-danger">NO-Gloves</span>
                                    <span class="badge badge-danger">NO-Safety Shoes</span>
                                    <span class="badge badge-danger">NO-Goggles</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- System Architecture -->
                <div class="card mb-4">
                    <div class="card-header">
                        <span><i class="fas fa-project-diagram"></i> System Pipeline</span>
                    </div>
                    <div class="card-content">
                        <div style="background: var(--background-color); padding: 2rem; border-radius: 8px; font-family: monospace; line-height: 2;">
                            <div style="text-align: center; margin-bottom: 1rem;">
                                <strong>Live Video (1920x1080 Full HD)</strong>
                            </div>
                            <div style="text-align: center;">↓</div>
                            <div style="text-align: center; margin: 1rem 0;">
                                <strong>Resize to 1280x720 → YOLO Detection (Fast)</strong>
                            </div>
                            <div style="text-align: center;">↓</div>
                            <div style="text-align: center; margin: 1rem 0;">
                                <strong>Violation Detected? (NO-Hardhat)</strong>
                            </div>
                            <div style="text-align: center;">↓ YES</div>
                            <div style="text-align: center; margin: 1rem 0;">
                                <strong>Save High-Res Images (1920x1080)</strong><br>
                                <small>Original.jpg + Annotated.jpg</small>
                            </div>
                            <div style="text-align: center;">↓</div>
                            <div style="text-align: center; margin: 1rem 0;">
                                <strong>AI Caption (LLaVA) + NLP Analysis (Llama3)</strong>
                            </div>
                            <div style="text-align: center;">↓</div>
                            <div style="text-align: center; margin: 1rem 0;">
                                <strong>Generate Report (HTML + PDF)</strong>
                            </div>
                            <div style="text-align: center;">↓</div>
                            <div style="text-align: center; margin-top: 1rem;">
                                <strong>View in Web Interface 🎉</strong>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Credits -->
                <div class="card">
                    <div class="card-header">
                        <span><i class="fas fa-users"></i> Credits & Acknowledgments</span>
                    </div>
                    <div class="card-content">
                        <div style="text-align: center;">
                            <p style="font-size: 1.1rem; margin-bottom: 1rem;">
                                Final Year Project - AI-Powered Workplace Safety Monitoring
                            </p>
                            <p style="color: #7f8c8d; margin-bottom: 2rem;">
                                Developed as part of academic research in Computer Vision and AI Safety Systems
                            </p>
                            
                            <h4 style="margin: 2rem 0 1rem 0;">Technologies & Frameworks:</h4>
                            <div style="display: flex; flex-wrap: wrap; gap: 0.75rem; justify-content: center; margin-bottom: 2rem;">
                                <span class="badge badge-info" style="font-size: 0.95rem; padding: 0.5rem 1rem;">YOLOv8 (Ultralytics)</span>
                                <span class="badge badge-info" style="font-size: 0.95rem; padding: 0.5rem 1rem;">LLaVA (Haotian Liu et al.)</span>
                                <span class="badge badge-info" style="font-size: 0.95rem; padding: 0.5rem 1rem;">Llama3.2 (Meta AI)</span>
                                <span class="badge badge-info" style="font-size: 0.95rem; padding: 0.5rem 1rem;">Ollama</span>
                                <span class="badge badge-info" style="font-size: 0.95rem; padding: 0.5rem 1rem;">OpenCV</span>
                                <span class="badge badge-info" style="font-size: 0.95rem; padding: 0.5rem 1rem;">Flask</span>
                                <span class="badge badge-info" style="font-size: 0.95rem; padding: 0.5rem 1rem;">PyTorch</span>
                            </div>

                            <p style="color: #95a5a6; font-size: 0.9rem; margin-top: 2rem;">
                                © 2025 PPE Safety Monitor. Built with ❤️ for workplace safety.
                            </p>
                        </div>
                    </div>
                </div>
            </div>
        `;
    },

    mount() {
        // Static page, no dynamic content
    }
};
