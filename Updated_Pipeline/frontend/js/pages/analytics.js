// Analytics Page Component
const AnalyticsPage = {
    render() {
        return `
            <div class="page">
                <div class="card mb-4">
                    <div class="card-header">
                        <span><i class="fas fa-chart-line"></i> Safety Analytics Dashboard</span>
                    </div>
                    <div class="card-content">
                        <div id="analytics-stats" class="grid grid-4 mb-4">
                            <div class="spinner"></div>
                        </div>
                    </div>
                </div>

                <!-- Violation Trends -->
                <div class="card mb-4">
                    <div class="card-header">
                        <span><i class="fas fa-chart-bar"></i> Violation Trends</span>
                    </div>
                    <div class="card-content">
                        <div id="trends-chart" style="min-height: 300px; display: flex; align-items: center; justify-content: center; background: var(--background-color); border-radius: 8px; padding: 2rem;">
                            <div style="text-align: center;">
                                <i class="fas fa-chart-line" style="font-size: 3rem; color: var(--border-color); margin-bottom: 1rem;"></i>
                                <p style="color: #7f8c8d;">Interactive charts coming soon</p>
                                <p style="color: #95a5a6; font-size: 0.9rem;">Will show violation trends over time</p>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="grid grid-2">
                    <!-- Violation Types Breakdown -->
                    <div class="card">
                        <div class="card-header">
                            <span><i class="fas fa-pie-chart"></i> Violation Types</span>
                        </div>
                        <div class="card-content" id="violation-types-analytics">
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
            </div>
        `;
    },

    async mount() {
        const stats = await API.getStats();
        this.renderStats(stats);
        this.renderViolationTypes(stats);
        this.renderTimeDistribution(stats);
        this.calculateSafetyScore(stats);
    },

    renderStats(stats) {
        const container = document.getElementById('analytics-stats');
        container.innerHTML = `
            <div class="stat-card">
                <h3>${stats.total}</h3>
                <p>Total Violations</p>
            </div>
            <div class="stat-card danger">
                <h3>${stats.severity.high}</h3>
                <p>High Severity</p>
            </div>
            <div class="stat-card warning">
                <h3>${stats.severity.medium}</h3>
                <p>Medium Severity</p>
            </div>
            <div class="stat-card success">
                <h3>${stats.severity.low}</h3>
                <p>Low Severity</p>
            </div>
        `;
    },

    renderViolationTypes(stats) {
        const container = document.getElementById('violation-types-analytics');
        
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
