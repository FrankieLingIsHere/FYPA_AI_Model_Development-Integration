// Home Page Component
const HomePage = {
    render() {
    return `
        <div class="home-dashboard">

            <div class="home-grid">

            <!-- Top-left: Violations summary -->
            <div class="card home-summary-card">
                <h3>Violations Overview</h3>
                <div class="summary-grid">
                    <!-- Today -->
                    <div class="summary-block">
                        <span class="label">Today</span>
                        <span class="value" id="todayCount">0</span>
                        <span class="delta" id="todayDelta"></span>
                    </div>

                    <!-- This Week -->
                    <div class="summary-block">
                        <span class="label">This Week</span>
                        <span class="value" id="weekCount">0</span>
                        <span class="delta" id="weekDelta"></span>
                    </div>

                    <!-- High Severity (optional third block) -->
                    <div class="summary-block">
                        <span class="label">High Severity</span>
                        <span class="value" id="highSeverityCount">0</span>
                    </div>
                </div>

                <div class="card-header">
                    <span><i class="fas fa-trophy"></i> Safety Compliance Score</span>
                </div>
                <div class="card-content" style="text-align: center; padding: 2rem;">
                    <div id="safety-score" style="font-size: 4rem; font-weight: 700; color: var(--success-color); margin-bottom: 1rem;">--</div>
                    <p style="font-size: 1.2rem; color: var(--text-color); margin-bottom: 1rem;">Overall Safety Compliance</p>
                    <div style="max-width: 600px; height: 20px; background: var(--background-color); border-radius: 10px; margin: 0 auto; overflow: hidden;">
                        <div id="safety-bar" style="height: 100%; background: linear-gradient(90deg, var(--success-color), var(--secondary-color)); transition: width 0.5s ease; width: 0%;"></div>
                    </div>
                    <p style="color: #7f8c8d; margin-top: 1rem; font-size: 0.9rem;">Based on violation frequency and severity</p>
                </div>
            </div>


            <!-- placeholders for later -->
            <div class="card">
                <div class="card">
                    <div class="card-header">
                        <span><i class="fas fa-pie-chart"></i> Violation Types</span>
                    </div>
                    <div class="card-content" id="violation-types">
                        <div class="spinner"></div>
                    </div>
                </div>


            </div>


            <div class="card">
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

        </div>
    `;
},





    async mount() {
        const stats = await API.getStats();

        this.renderHomeSummary(stats);
        this.renderStats(stats);
        this.renderRecentViolations(stats.recentViolations || []);
        this.renderViolationTypes(stats);
        this.renderTimeDistribution(stats);
        this.calculateSafetyScore(stats);
    },


    renderStats(stats) {
        let statsGrid = document.getElementById('stats-grid');
        // If the middle stats row was removed, create a safe fallback so rendering doesn't throw
        if (!statsGrid) {
            const container = document.querySelector('.home-grid') || document.body;
            statsGrid = document.createElement('div');
            statsGrid.className = 'stats-row';
            statsGrid.id = 'stats-grid';
            // insert before the safety card if present to keep layout reasonable
            const safetyCard = document.querySelector('.card.mt-4');
            if (safetyCard && safetyCard.parentNode) safetyCard.parentNode.insertBefore(statsGrid, safetyCard);
            else container.appendChild(statsGrid);
        }
    },
    

    renderRecentViolations(violations) {
        let container = document.getElementById('recent-violations');
        if (!container) {
            const parent = document.querySelector('.home-grid') || document.body;
            container = document.createElement('div');
            container.id = 'recent-violations';
            parent.appendChild(container);
        }

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
        let container = document.getElementById('violation-types');
        if (!container) {
            const parent = document.querySelector('.home-grid') || document.body;
            container = document.createElement('div');
            container.id = 'violation-types';
            parent.appendChild(container);
        }

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


    calculateSafetyScore(stats) {
    const score = Math.max(0, Math.min(100, 100 - (stats.today * 10)));

    const scoreElement = document.getElementById('safety-score');
    const barElement = document.getElementById('safety-bar');

    if (!scoreElement || !barElement) return; // safely exit if elements missing

    scoreElement.textContent = `${score}%`;
    barElement.style.width = `${score}%`;

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
},


    renderHomeSummary(stats) {
        // MOCK previous values for now
        const yesterday = stats.today + 5;
        const lastWeek = stats.thisWeek - 3;

        const todayDelta = stats.today - yesterday;
        const weekDelta = stats.thisWeek - lastWeek;

        // Numbers
        const todayEl = document.getElementById("todayCount"); if (todayEl) todayEl.innerText = stats.today;
        const weekEl = document.getElementById("weekCount"); if (weekEl) weekEl.innerText = stats.thisWeek;

        // Deltas
        this.setDelta("todayDelta", todayDelta, "yesterday");
        this.setDelta("weekDelta", weekDelta, "last week");
    },


    setDelta(id, value, label) {
        const el = document.getElementById(id);
        if (!el) return;

        const sign = value > 0 ? "+" : "";
        const arrow = value > 0 ? "▲" : "▼";

        el.innerText = `${arrow} ${sign}${value} vs ${label}`;
        el.className = "delta " + (value > 0 ? "positive" : "negative");
    },


};
