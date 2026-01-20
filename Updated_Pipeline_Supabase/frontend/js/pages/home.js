// Home Page Component
const HomePage = {
    render() {
        return `
            <div class="page">
                <!-- Hero Section -->
                <div class="card mb-4">
                    <div class="card-content text-center">
                        <i class="fas fa-hard-hat" style="font-size: 4rem; color: var(--secondary-color); margin-bottom: 1rem;"></i>
                        <h1 style="font-size: 2.5rem; color: var(--primary-color); margin-bottom: 1rem;">
                            PPE Safety Monitor
                        </h1>
                        <p style="font-size: 1.2rem; color: var(--text-color); max-width: 800px; margin: 0 auto;">
                            AI-powered real-time workplace safety monitoring system using computer vision 
                            and natural language processing to detect PPE violations and generate comprehensive safety reports.
                        </p>
                    </div>
                </div>

                <!-- Statistics Dashboard -->
                <div id="stats-grid" class="grid grid-4 mb-4">
                    <div class="spinner"></div>
                </div>

                <!-- Quick Actions -->
                <div class="card mb-4">
                    <div class="card-header">
                        <span><i class="fas fa-bolt"></i> Quick Actions</span>
                    </div>
                    <div class="card-content">
                        <div class="grid grid-3">
                            <button class="btn btn-primary" onclick="Router.navigate('live')">
                                <i class="fas fa-video"></i> Start Live Monitoring
                            </button>
                            <button class="btn btn-primary" onclick="Router.navigate('reports')">
                                <i class="fas fa-file-alt"></i> View All Reports
                            </button>
                            <button class="btn btn-primary" onclick="Router.navigate('analytics')">
                                <i class="fas fa-chart-line"></i> View Analytics
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Recent Violations -->
                <div class="card">
                    <div class="card-header">
                        <span><i class="fas fa-exclamation-triangle"></i> Recent Violations</span>
                        <button class="btn btn-secondary" onclick="Router.navigate('reports')" style="padding: 0.5rem 1rem;">
                            View All
                        </button>
                    </div>
                    <div class="card-content" id="recent-violations">
                        <div class="spinner"></div>
                    </div>
                </div>

                <!-- System Features -->
                <div class="grid grid-3 mt-4">
                    <div class="card">
                        <div class="card-content text-center">
                            <i class="fas fa-brain" style="font-size: 3rem; color: var(--secondary-color); margin-bottom: 1rem;"></i>
                            <h3 style="margin-bottom: 0.5rem;">AI Detection</h3>
                            <p>YOLOv8 custom model trained on 14 PPE classes for accurate real-time detection</p>
                        </div>
                    </div>
                    <div class="card">
                        <div class="card-content text-center">
                            <i class="fas fa-camera" style="font-size: 3rem; color: var(--success-color); margin-bottom: 1rem;"></i>
                            <h3 style="margin-bottom: 0.5rem;">High-Res Capture</h3>
                            <p>1920x1080 Full HD image capture for detailed documentation and AI analysis</p>
                        </div>
                    </div>
                    <div class="card">
                        <div class="card-content text-center">
                            <i class="fas fa-file-pdf" style="font-size: 3rem; color: var(--error-color); margin-bottom: 1rem;"></i>
                            <h3 style="margin-bottom: 0.5rem;">Smart Reports</h3>
                            <p>AI-generated safety reports with NLP analysis and actionable recommendations</p>
                        </div>
                    </div>
                </div>
            </div>
        `;
    },

    async mount() {
        // Load statistics
        const stats = await API.getStats();
        this.renderStats(stats);
        this.renderRecentViolations(stats.recentViolations);
    },

    renderStats(stats) {
        const statsGrid = document.getElementById('stats-grid');
        statsGrid.innerHTML = `
            <div class="stat-card">
                <h3>${stats.total}</h3>
                <p>Total Violations</p>
            </div>
            <div class="stat-card ${stats.today > 0 ? 'danger' : 'success'}">
                <h3>${stats.today}</h3>
                <p>Violations Today</p>
            </div>
            <div class="stat-card warning">
                <h3>${stats.thisWeek}</h3>
                <p>This Week</p>
            </div>
            <div class="stat-card danger">
                <h3>${stats.severity.high}</h3>
                <p>High Severity</p>
            </div>
        `;
    },

    renderRecentViolations(violations) {
        const container = document.getElementById('recent-violations');
        
        if (violations.length === 0) {
            container.innerHTML = `
                <div class="alert alert-success">
                    <i class="fas fa-check-circle"></i>
                    <span>No violations detected! Workplace is compliant.</span>
                </div>
            `;
            return;
        }

        container.innerHTML = `
            <div class="grid">
                ${violations.map(v => `
                    <div class="card" style="cursor: pointer;" onclick="window.open('${API.getReportUrl(v.report_id)}', '_blank')">
                        <div class="card-content">
                            <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 1rem;">
                                <div>
                                    <h3 style="color: var(--primary-color); margin-bottom: 0.5rem;">
                                        Report #${v.report_id}
                                    </h3>
                                    <p style="color: #7f8c8d; font-size: 0.9rem;">
                                        ${new Date(v.timestamp).toLocaleString()}
                                    </p>
                                </div>
                                <span class="badge badge-danger">High</span>
                            </div>
                            <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                                ${v.has_original ? '<span class="badge badge-success">Original Image</span>' : ''}
                                ${v.has_annotated ? '<span class="badge badge-success">Annotated</span>' : ''}
                                ${v.has_report ? '<span class="badge badge-success">Full Report</span>' : '<span class="badge badge-warning">Processing</span>'}
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    }
};
