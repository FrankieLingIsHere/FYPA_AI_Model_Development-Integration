// Analytics Page Component
const AnalyticsPage = {
    _realtimeHandler: null,
    _connectionHandler: null,
    _timezoneChangeHandler: null,
    _realtimeRefreshTimer: null,
    _fallbackInterval: null,

    render() {
        return `
            <div class="page analytics-dashboard">
                <div class="card mb-4">
                    <div class="card-header">
                        <span><i class="fas fa-chart-line"></i> Safety Analytics Dashboard</span>
                    </div>
                    <div class="card-content">
                        <div id="analytics-stats" class="grid grid-4 mb-4">
                            <div class="spinner"></div>
                        </div>
                        <div id="analytics-insights" class="analytics-insights-grid">
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
                        <div style="height: 300px; position: relative;">
                            <canvas id="trendChart"></canvas>
                        </div>
                    </div>
                </div>

                <div class="grid grid-2">
                    <!-- Violation Types Breakdown -->
                    <div class="card">
                        <div class="card-header">
                            <span><i class="fas fa-pie-chart"></i> Violation Types</span>
                        </div>
                        <div class="card-content" id="analytics-violation-types">
                            <div class="spinner"></div>
                        </div>
                    </div>

                    <!-- Time Distribution -->
                    <div class="card">
                        <div class="card-header">
                            <span><i class="fas fa-clock"></i> Time Distribution</span>
                        </div>
                        <div class="card-content" id="analytics-time-distribution">
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
                            <p id="analytics-safety-benchmark-note" style="color:#6b7280; margin-top: 0.35rem; font-size: 0.82rem;"></p>
                        </div>
                    </div>
                </div>
            </div>
        `;
    },

    async mount() {
        await this.refreshData();

        this._realtimeHandler = () => {
            if (this._realtimeRefreshTimer) return;
            this._realtimeRefreshTimer = setTimeout(async () => {
                this._realtimeRefreshTimer = null;
                await this.refreshData();
            }, 1200);
        };
        window.addEventListener('ppe-realtime:update', this._realtimeHandler);

        this._connectionHandler = () => this.syncFallbackPolling();
        window.addEventListener('ppe-realtime:connection', this._connectionHandler);

        this._timezoneChangeHandler = () => this.refreshData();
        window.addEventListener('ppe-timezone:changed', this._timezoneChangeHandler);
        this.syncFallbackPolling();
    },

    unmount() {
        if (this._realtimeHandler) {
            window.removeEventListener('ppe-realtime:update', this._realtimeHandler);
            this._realtimeHandler = null;
        }
        if (this._realtimeRefreshTimer) {
            clearTimeout(this._realtimeRefreshTimer);
            this._realtimeRefreshTimer = null;
        }
        if (this._connectionHandler) {
            window.removeEventListener('ppe-realtime:connection', this._connectionHandler);
            this._connectionHandler = null;
        }
        if (this._timezoneChangeHandler) {
            window.removeEventListener('ppe-timezone:changed', this._timezoneChangeHandler);
            this._timezoneChangeHandler = null;
        }
        if (this._fallbackInterval) {
            clearInterval(this._fallbackInterval);
            this._fallbackInterval = null;
        }
        if (window.analyticsChart) {
            window.analyticsChart.destroy();
            window.analyticsChart = null;
        }
    },

    syncFallbackPolling() {
        const connected = typeof RealtimeSync !== 'undefined' && RealtimeSync.isConnected;
        if (connected) {
            if (this._fallbackInterval) {
                clearInterval(this._fallbackInterval);
                this._fallbackInterval = null;
            }
            return;
        }

        if (!this._fallbackInterval) {
            this._fallbackInterval = setInterval(() => this.refreshData(), 12000);
        }
    },

    async refreshData() {
        try {
            const [stats, violations] = await Promise.all([
                API.getStats(),
                API.getViolations()
            ]);

            this.renderStats(stats);
            this.renderInsights(stats, violations);
            this.renderTrendsChart(violations);
            this.renderViolationTypes(stats);
            this.renderTimeDistribution(violations);
            this.calculateSafetyScore(stats);
        } catch (e) {
            console.error('Error loading analytics:', e);
            const statsEl = document.getElementById('analytics-stats');
            if (statsEl) {
                statsEl.innerHTML = '<div class="alert alert-danger">Failed to load analytics data.</div>';
            }
        }
    },

    renderStats(stats) {
        const container = document.getElementById('analytics-stats');
        if (!container) return;
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

    renderInsights(stats, violations) {
        const container = document.getElementById('analytics-insights');
        if (!container) return;

        const breakdown = stats.breakdown || {};
        const sorted = Object.entries(breakdown).sort((a, b) => Number(b[1]) - Number(a[1]));
        const topType = sorted.length > 0 ? `${sorted[0][0]} (${sorted[0][1]})` : 'No violations yet';

        const lastViolation = (violations || [])
            .map((v) => new Date(v.timestamp || 0))
            .filter((d) => !Number.isNaN(d.getTime()))
            .sort((a, b) => b.getTime() - a.getTime())[0];

        const lastViolationDisplay = lastViolation
            ? (typeof TimezoneManager !== 'undefined' && typeof TimezoneManager.formatDateTime === 'function'
                ? TimezoneManager.formatDateTime(lastViolation.toISOString())
                : lastViolation.toLocaleString())
            : 'No data';

        container.innerHTML = `
            <div class="analytics-insight-card">
                <div class="label">Top Violation Type</div>
                <div class="value">${topType}</div>
            </div>
            <div class="analytics-insight-card">
                <div class="label">Pending Reports</div>
                <div class="value">${stats.pending || 0}</div>
            </div>
            <div class="analytics-insight-card">
                <div class="label">Last Violation Seen</div>
                <div class="value">${lastViolationDisplay}</div>
            </div>
        `;
    },

    renderTrendsChart(violations) {
        const canvas = document.getElementById('trendChart');
        if (!canvas) return;

        if (typeof Chart === 'undefined') {
            canvas.parentElement.innerHTML = '<div class="alert alert-warning">Trend chart is unavailable because Chart.js failed to load.</div>';
            return;
        }

        const ctx = canvas.getContext('2d');

        // Destroy existing chart if any
        if (window.analyticsChart) {
            window.analyticsChart.destroy();
        }

        // Build 7-day trend from violations
        const today = new Date();
        const dayBuckets = new Map();
        for (let i = 6; i >= 0; i -= 1) {
            const d = new Date(today);
            d.setHours(0, 0, 0, 0);
            d.setDate(d.getDate() - i);
            const key = d.toISOString().slice(0, 10);
            dayBuckets.set(key, 0);
        }

        (violations || []).forEach((v) => {
            if (!v?.timestamp) return;
            const ts = new Date(v.timestamp);
            if (Number.isNaN(ts.getTime())) return;
            ts.setHours(0, 0, 0, 0);
            const key = ts.toISOString().slice(0, 10);
            if (dayBuckets.has(key)) {
                dayBuckets.set(key, dayBuckets.get(key) + 1);
            }
        });

        const isoDates = Array.from(dayBuckets.keys());
        const labels = isoDates.map((isoDate) => {
            const date = new Date(`${isoDate}T00:00:00`);
            return `${date.getDate()}/${date.getMonth() + 1}`;
        });
        const counts = Array.from(dayBuckets.values());

        window.analyticsChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Daily Violations',
                    data: counts,
                    borderColor: '#3498db',
                    backgroundColor: 'rgba(52, 152, 219, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 4,
                    pointHoverRadius: 7,
                    pointHitRadius: 18
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        enabled: true,
                        mode: 'nearest',
                        intersect: false,
                        callbacks: {
                            title(context) {
                                if (!context || context.length === 0) return '';
                                const idx = context[0].dataIndex;
                                const isoDate = isoDates[idx];
                                if (!isoDate) return '';
                                const date = new Date(`${isoDate}T00:00:00`);
                                return date.toLocaleDateString(undefined, {
                                    year: 'numeric',
                                    month: 'short',
                                    day: 'numeric'
                                });
                            },
                            label(context) {
                                const value = Number(context.raw || 0);
                                return `Violations: ${value}`;
                            }
                        }
                    }
                },
                interaction: {
                    mode: 'nearest',
                    intersect: false
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            precision: 0
                        }
                    }
                }
            }
        });
    },

    renderViolationTypes(stats) {
        const container = document.getElementById('analytics-violation-types');
        if (!container) return;
        const breakdown = stats.breakdown || {};
        const types = [
            { name: 'Missing Hardhat', count: breakdown['NO-Hardhat'] || 0, color: 'var(--error-color)' },
            { name: 'Missing Safety Vest', count: breakdown['NO-Safety Vest'] || 0, color: 'var(--warning-color)' },
            { name: 'Missing Gloves', count: breakdown['NO-Gloves'] || 0, color: 'var(--info-color)' },
            { name: 'Missing Mask', count: breakdown['NO-Mask'] || 0, color: '#9b59b6' },
            { name: 'Missing Goggles', count: breakdown['NO-Goggles'] || 0, color: '#e67e22' },
            { name: 'Missing Safety Shoes', count: breakdown['NO-Safety Shoes'] || 0, color: '#16a085' }
        ];

        const total = types.reduce((sum, type) => sum + type.count, 0);

        container.innerHTML = `
            <div style="display: flex; flex-direction: column; gap: 1rem;">
                ${types.map(type => `
                    <div>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                            <span style="font-weight: 500;">${type.name}</span>
                            <span style="font-weight: 600; color: ${type.color};">${type.count}</span>
                        </div>
                        <div style="height: 8px; background: var(--background-color); border-radius: 4px; overflow: hidden;">
                            <div style="height: 100%; background: ${type.color}; width: ${total > 0 ? (type.count / total * 100) : 0}%; transition: width 0.5s ease;"></div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    },

    renderTimeDistribution(violations) {
        const container = document.getElementById('analytics-time-distribution');
        if (!container) return;

        // Calculate time distribution
        const distribution = {
            'Morning (6AM-12PM)': 0,
            'Afternoon (12PM-6PM)': 0,
            'Evening (6PM-12AM)': 0,
            'Night (12AM-6AM)': 0
        };

        (violations || []).forEach(v => {
            if (!v?.timestamp) return;
            const hour = new Date(v.timestamp).getHours();
            if (Number.isNaN(hour)) return;
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
        const safety = API.computeSafetyCompliance(stats || {});
        const score = safety.score;

        const scoreElement = document.getElementById('safety-score');
        const barElement = document.getElementById('safety-bar');
        const benchmarkEl = document.getElementById('analytics-safety-benchmark-note');

        if (!scoreElement || !barElement) return;

        scoreElement.textContent = `${score}%`;
        barElement.style.width = `${score}%`;
        if (benchmarkEl) {
            benchmarkEl.textContent = safety.benchmarkNote;
        }

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
