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
        const breakdown = stats.breakdown || {};

        // Data mapping
        const types = [
            { name: "Missing Hardhat", count: breakdown['NO-Hardhat'] || 0, color: "var(--error-color)" },
            { name: "Missing Vest", count: breakdown['NO-Safety Vest'] || 0, color: "var(--warning-color)" },
            { name: "Missing Gloves", count: breakdown['NO-Gloves'] || 0, color: "var(--info-color)" },
            { name: "Missing Mask", count: breakdown['NO-Mask'] || 0, color: "#9b59b6" }, // Added Mask styling
            { name: "Missing Goggles", count: breakdown['NO-Goggles'] || 0, color: "#e67e22" }
        ];

        // Calculate total for percentages
        const totalViolations = types.reduce((sum, t) => sum + t.count, 0);

        container.innerHTML = `
            <div style="display:flex;flex-direction:column;gap:1rem;">
                ${types.map(t => `
                    <div class="violation-stat-row">
                        <div style="display:flex;justify-content:space-between;margin-bottom:0.25rem;">
                            <span style="font-size:0.9rem;">${t.name}</span>
                            <strong style="color:${t.color}">${t.count}</strong>
                        </div>
                        <div style="height:8px;background:var(--background-color);border-radius:4px;overflow:hidden;">
                            <div style="
                                height:100%;
                                width:${totalViolations ? (t.count / totalViolations * 100) : 0}%;
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
                <div class="alert alert-success" style="padding:1.5rem;text-align:center;">
                    <i class="fas fa-check-circle" style="font-size:2rem;display:block;margin-bottom:0.5rem;"></i>
                    No recent violations detected
                </div>`;
            return;
        }

        container.innerHTML = `
            <div class="recent-list" style="display:flex; flex-direction:column; gap:0.5rem;">
                ${violations.map(v => `
                    <div class="recent-item" 
                         onclick="window.open('${API.getReportUrl(v.report_id)}','_blank')"
                         style="
                            display:flex; 
                            justify-content:space-between; 
                            align-items:center;
                            padding:1rem;
                            background:var(--background-color);
                            border-radius:8px;
                            cursor:pointer;
                            border-left: 4px solid ${v.severity === 'HIGH' ? 'var(--error-color)' : 'var(--warning-color)'};
                            transition: transform 0.2s;
                         "
                         onmouseover="this.style.transform='translateX(4px)'"
                         onmouseout="this.style.transform='translateX(0)'">
                        
                        <div>
                            <h5 style="margin:0 0 0.25rem 0;color:var(--text-color);">#${v.report_id}</h5>
                            <span style="font-size:0.8rem;color:#7f8c8d;">
                                ${typeof TimezoneManager !== 'undefined' ? TimezoneManager.formatDateTime(v.timestamp) : new Date(v.timestamp).toLocaleString()}
                            </span>
                        </div>
                        
                        <div style="text-align:right;">
                            <span class="badge ${v.severity === 'HIGH' ? 'badge-danger' : 'badge-warning'}" 
                                  style="font-size:0.75rem;padding:0.25rem 0.5rem;">
                                ${v.severity || 'MEDIUM'}
                            </span>
                        </div>
                    </div>
                `).join("")}
            </div>
        `;
    }
};
