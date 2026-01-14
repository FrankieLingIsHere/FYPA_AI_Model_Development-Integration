// Home Page Component
const HomePage = {
    render() {
    return `
        <div class="home-dashboard">

            <!-- Top Bar -->
            <div class="hero-bar">
                <i class="fas fa-hard-hat hero-icon"></i>
                <div class="hero-text">
                    <h1>CASM</h1>
                    <p>AI-powered workplace safety monitoring</p>
                </div>
            </div>

            <!-- Middle Stats -->
            <div class="stats-row" id="stats-grid">
                <div class="spinner"></div>
            </div>

            <!-- Safety Score -->
            <div class="card mt-4">
                <div class="card-header">
                    <span><i class="fas fa-trophy"></i> Safety Compliance Score</span>
                </div>
                <div class="card-content">
                    <div style="text-align: center; padding: 2rem;">
                        <div id="safety-score" style="font-size: 4rem; font-weight: 700; color: var(--success-color); margin-bottom: 1rem;">
                            --
                        </div>
                        <p style="font-size: 1.2rem; color: var(--text-color); margin-bottom: 1rem;">
                            Overall Safety Compliance
                        </p>
                        <div style="max-width: 600px; height: 20px; background: var(--background-color); border-radius: 10px; margin: 0 auto; overflow: hidden;">
                            <div id="safety-bar" style="height: 100%; background: linear-gradient(90deg, var(--success-color), var(--secondary-color)); transition: width 0.5s ease; width: 0%;"></div>
                        </div>
                        <p style="color: #7f8c8d; margin-top: 1rem; font-size: 0.9rem;">
                            Based on violation frequency and severity
                        </p>
                    </div>
                </div>
            </div>

            <div class="grid grid-2">
                <!-- Violation Types Breakdown -->
                <div class="card">
                    <div class="card-header">
                        <span><i class="fas fa-pie-chart"></i> Violation Types</span>
                    </div>
                    <div class="card-content" id="violation-types">
                        <div class="spinner"></div>
                    </div>
                </div>

                <!-- Time Distribution -->
                <div class="card">
                    <div class="card-header">
                        <span><i class="fas fa-clock"></i> Time Distribution</span>
                    </div>
                    <div class="card-content" id="time-distribution">
                        <div class="spinner"></div>
                    </div>
                </div>
            </div>

            <!-- Main Bottom Layout -->
            <div class="main-lower">

                <!-- Quick Actions -->
                <div class="quick-card card">
                    <h2 class="section-title"><i class="fas fa-bolt"></i> Quick Actions</h2>
                    <div class="qa-buttons">
                        <button class="btn btn-primary" onclick="Router.navigate('live')">
                            <i class="fas fa-video"></i> Live
                        </button>
                        <button class="btn btn-primary" onclick="Router.navigate('reports')">
                            <i class="fas fa-file-alt"></i> Reports
                        </button>
                        <button class="btn btn-primary" onclick="Router.navigate('analytics')">
                            <i class="fas fa-chart-line"></i> Analytics
                        </button>

                    </div>
                </div>

                <!-- Recent Violations -->
                <div class="recent-card card">
                    <div class="recent-header">
                        <span><i class="fas fa-exclamation-triangle"></i> Recent Violations</span>
                        <button class="btn btn-secondary" onclick="Router.navigate('reports')">View All</button>
                    </div>

                    <!-- scrollable content -->
                    <div id="recent-violations" class="recent-content">
                        <div class="spinner"></div>
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
        this.renderViolationTypes(stats);
        this.renderTimeDistribution(stats);
        this.calculateSafetyScore(stats);
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
    },

    renderViolationTypes(stats) {
        const container = document.getElementById('violation-types');
        
        // For now, all violations are NO-Hardhat
        const types = [
            { name: 'Missing Hardhat', count: stats.total, color: 'var(--error-color)' },
            { name: 'Missing Safety Vest', count: 0, color: 'var(--warning-color)' },
            { name: 'Missing Gloves', count: 0, color: 'var(--info-color)' },
            { name: 'Other PPE', count: 0, color: 'var(--text-color)' }
        ];

        container.innerHTML = `
            <div style="display: flex; flex-direction: column; gap: 1rem;">
                ${types.map(type => `
                    <div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                            <span style="font-weight: 500;">${type.name}</span>
                            <span style="font-weight: 600; color: ${type.color};">${type.count}</span>
                        </div>
                        <div style="height: 8px; background: var(--background-color); border-radius: 4px; overflow: hidden;">
                            <div style="height: 100%; background: ${type.color}; width: ${stats.total > 0 ? (type.count / stats.total * 100) : 0}%; transition: width 0.5s ease;"></div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    },

    renderTimeDistribution(stats) {
        const container = document.getElementById('time-distribution');
        
        // Calculate time distribution
        const distribution = {
            'Morning (6AM-12PM)': 0,
            'Afternoon (12PM-6PM)': 0,
            'Evening (6PM-12AM)': 0,
            'Night (12AM-6AM)': 0
        };

        // Analyze violations (placeholder - would need actual time data)
        const violations = stats.recentViolations || [];
        violations.forEach(v => {
            const hour = new Date(v.timestamp).getHours();
            if (hour >= 6 && hour < 12) distribution['Morning (6AM-12PM)']++;
            else if (hour >= 12 && hour < 18) distribution['Afternoon (12PM-6PM)']++;
            else if (hour >= 18 && hour < 24) distribution['Evening (6PM-12AM)']++;
            else distribution['Night (12AM-6AM)']++;
        });

        const maxCount = Math.max(...Object.values(distribution), 1);

        container.innerHTML = `
            <div style="display: flex; flex-direction: column; gap: 1rem;">
                ${Object.entries(distribution).map(([period, count]) => `
                    <div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                            <span style="font-weight: 500;">${period}</span>
                            <span style="font-weight: 600;">${count}</span>
                        </div>
                        <div style="height: 8px; background: var(--background-color); border-radius: 4px; overflow: hidden;">
                            <div style="height: 100%; background: var(--secondary-color); width: ${(count / maxCount * 100)}%; transition: width 0.5s ease;"></div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    },

    calculateSafetyScore(stats) {
        // Simple safety score calculation
        // 100% - (violations_today * 10)
        const score = Math.max(0, Math.min(100, 100 - (stats.today * 10)));
        
        const scoreElement = document.getElementById('safety-score');
        const barElement = document.getElementById('safety-bar');
        
        scoreElement.textContent = `${score}%`;
        barElement.style.width = `${score}%`;
        
        // Change color based on score
        if (score >= 80) {
            scoreElement.style.color = 'var(--success-color)';
            barElement.style.background = 'linear-gradient(90deg, var(--success-color), #27ae60)';
        } else if (score >= 60) {
            scoreElement.style.color = 'var(--warning-color)';
            barElement.style.background = 'linear-gradient(90deg, var(--warning-color), #e67e22)';
        } else {
            scoreElement.style.color = 'var(--error-color)';
            barElement.style.background = 'linear-gradient(90deg, var(--error-color), #c0392b)';
        }
    }

};
