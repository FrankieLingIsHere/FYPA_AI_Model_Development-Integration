// Home Page Component
const HomePage = {
    render() {
        return `
        <div class="home-dashboard">
            <div class="home-grid">

                <!-- OVERVIEW -->
                <div class="card home-summary-card">
                    <div class="card-header">
                        <span><i class="fas fa-chart-line"></i> Violations Overview</span>
                    </div>
                    <div class="card-content">
                        <div class="summary-grid">

                            <div class="summary-block">
                                <span class="label">Today</span>
                                <span class="value" id="todayCount">0</span>
                                <span class="delta" id="todayDelta"></span>
                            </div>

                            <div class="summary-block">
                                <span class="label">This Week</span>
                                <span class="value" id="weekCount">0</span>
                                <span class="delta" id="weekDelta"></span>
                            </div>

                            <div class="summary-block">
                                <span class="label">High Severity</span>
                                <span class="value" id="highSeverityCount">0</span>
                            </div>

                        </div>
                    </div>
                </div>

                <!-- VIOLATION TYPES -->
                <div class="card">
                    <div class="card-header">
                        <span><i class="fas fa-pie-chart"></i> Violation Types</span>
                    </div>
                    <div class="card-content" id="violation-types">
                        <div class="spinner"></div>
                    </div>
                </div>

                <!-- SAFETY SCORE -->
                <div class="card">
                    <div class="card-header">
                        <span><i class="fas fa-trophy"></i> Safety Compliance Score</span>
                    </div>
                    <div class="card-content" style="text-align:center;">
                        <div id="safety-score"
                             style="font-size:4rem;font-weight:700;margin-bottom:1rem;">
                            --
                        </div>

                        <p style="font-size:1.2rem;margin-bottom:1rem;">
                            Overall Safety Compliance
                        </p>

                        <div style="
                            max-width:600px;
                            height:20px;
                            background:var(--background-color);
                            border-radius:10px;
                            margin:0 auto;
                            overflow:hidden;">
                            <div id="safety-bar"
                                 style="height:100%;width:0%;transition:width 0.5s ease;">
                            </div>
                        </div>

                        <p style="color:#7f8c8d;margin-top:1rem;font-size:0.9rem;">
                            Based on violation frequency and severity
                        </p>
                    </div>
                </div>

                <!-- RECENT VIOLATIONS -->
                <div class="card">
                    <div class="recent-header">
                        <span><i class="fas fa-exclamation-triangle"></i> Recent Violations</span>
                        <button class="btn btn-secondary"
                                onclick="Router.navigate('reports')">
                            View All
                        </button>
                    </div>
                    <div id="recent-violations" class="recent-content">
                        <div class="spinner"></div>
                    </div>
                </div>

            </div>
        </div>
        `;
    },

    async mount() {
        const stats = await API.getStats();

        this.renderHomeSummary(stats);
        this.renderViolationTypes(stats);
        this.renderRecentViolations(stats.recentViolations || []);
        this.calculateSafetyScore(stats);
    },

    /* ================= SUMMARY ================= */

    renderHomeSummary(stats) {
        // Use real deltas from backend (defaults to 0 if undefined)
        const todayDelta = stats.todayDelta !== undefined ? stats.todayDelta : 0;
        const weekDelta = stats.weekDelta !== undefined ? stats.weekDelta : 0;

        document.getElementById("todayCount").textContent = stats.today;
        document.getElementById("weekCount").textContent = stats.thisWeek;
        document.getElementById("highSeverityCount").textContent =
            stats.severity?.high ?? 0;

        const todayDeltaEl = document.getElementById("todayDelta");
        const weekDeltaEl = document.getElementById("weekDelta");

        todayDeltaEl.textContent =
            todayDelta > 0 ? `+${todayDelta}` : `${todayDelta}`;
        todayDeltaEl.style.color =
            todayDelta > 0 ? 'var(--error-color)' : 'var(--success-color)';

        weekDeltaEl.textContent =
            weekDelta > 0 ? `+${weekDelta}` : `${weekDelta}`;
        weekDeltaEl.style.color =
            weekDelta > 0 ? 'var(--error-color)' : 'var(--success-color)';
    },

    /* ================= SAFETY SCORE ================= */

    calculateSafetyScore(stats) {
        const score = Math.max(0, Math.min(100, 100 - stats.today * 10));

        const scoreEl = document.getElementById("safety-score");
        const barEl = document.getElementById("safety-bar");

        scoreEl.textContent = `${score}%`;
        barEl.style.width = `${score}%`;

        if (score >= 80) {
            scoreEl.style.color = 'var(--success-color)';
            barEl.style.background =
                'linear-gradient(90deg, var(--success-color), #27ae60)';
        } else if (score >= 60) {
            scoreEl.style.color = 'var(--warning-color)';
            barEl.style.background =
                'linear-gradient(90deg, var(--warning-color), #e67e22)';
        } else {
            scoreEl.style.color = 'var(--error-color)';
            barEl.style.background =
                'linear-gradient(90deg, var(--error-color), #c0392b)';
        }
    },

    /* ================= VIOLATION TYPES ================= */

    renderViolationTypes(stats) {
        const container = document.getElementById("violation-types");

        const types = [
            { name: "Missing Hardhat", count: stats.total, color: "var(--error-color)" },
            { name: "Missing Vest", count: 0, color: "var(--warning-color)" },
            { name: "Missing Gloves", count: 0, color: "var(--info-color)" },
            { name: "Other PPE", count: 0, color: "var(--text-color)" }
        ];

        container.innerHTML = `
            <div style="display:flex;flex-direction:column;gap:1rem;">
                ${types.map(t => `
                    <div>
                        <div style="display:flex;justify-content:space-between;">
                            <span>${t.name}</span>
                            <strong style="color:${t.color}">${t.count}</strong>
                        </div>
                        <div style="height:8px;background:var(--background-color);border-radius:4px;">
                            <div style="
                                height:100%;
                                width:${stats.total ? (t.count / stats.total * 100) : 0}%;
                                background:${t.color};
                                transition:width 0.5s ease;">
                            </div>
                        </div>
                    </div>
                `).join("")}
            </div>
        `;
    },

    /* ================= RECENT ================= */

    renderRecentViolations(violations) {
        const container = document.getElementById("recent-violations");

        if (!violations.length) {
            container.innerHTML = `
                <div class="alert alert-success">
                    <i class="fas fa-check-circle"></i>
                    No violations detected
                </div>`;
            return;
        }

        container.innerHTML = `
            <div class="grid">
                ${violations.map(v => `
                    <div class="card"
                         onclick="window.open('${API.getReportUrl(v.report_id)}','_blank')"
                         style="cursor:pointer;">
                        <div class="card-content">
                            <h4>Report #${v.report_id}</h4>
                            <p style="font-size:0.85rem;color:#7f8c8d;">
                                ${typeof TimezoneManager !== 'undefined' ? TimezoneManager.formatDateTime(v.timestamp) : new Date(v.timestamp).toLocaleString()}
                            </p>
                        </div>
                    </div>
                `).join("")}
            </div>
        `;
    }
};
