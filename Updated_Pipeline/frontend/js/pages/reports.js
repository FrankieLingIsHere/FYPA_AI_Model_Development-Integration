// Reports Page Component
const ReportsPage = {
    violations: [],
    filters: {
        search: '',
        severity: 'all',
        dateRange: 'all'
    },

    render() {
        return `
            <div class="page">
                <div class="card mb-4">
                    <div class="card-header">
                        <span><i class="fas fa-file-alt"></i> Violation Reports</span>
                        <button class="btn btn-primary" onclick="ReportsPage.refreshReports()" style="padding: 0.5rem 1rem;">
                            <i class="fas fa-sync"></i> Refresh
                        </button>
                    </div>
                    <div class="card-content">
                        <!-- Filters -->
                        <div class="grid grid-3 mb-3">
                            <input 
                                type="text" 
                                id="search-reports" 
                                placeholder="Search reports..." 
                                style="padding: 0.75rem; border: 1px solid var(--border-color); border-radius: var(--radius-md);"
                                onkeyup="ReportsPage.handleSearch(event)"
                            >
                            <select 
                                id="filter-severity" 
                                style="padding: 0.75rem; border: 1px solid var(--border-color); border-radius: var(--radius-md);"
                                onchange="ReportsPage.handleFilter()"
                            >
                                <option value="all">All Severities</option>
                                <option value="high">High Severity</option>
                                <option value="medium">Medium Severity</option>
                                <option value="low">Low Severity</option>
                            </select>
                            <select 
                                id="filter-date" 
                                style="padding: 0.75rem; border: 1px solid var(--border-color); border-radius: var(--radius-md);"
                                onchange="ReportsPage.handleFilter()"
                            >
                                <option value="all">All Time</option>
                                <option value="today">Today</option>
                                <option value="week">This Week</option>
                                <option value="month">This Month</option>
                            </select>
                        </div>

                        <!-- Reports List -->
                        <div id="reports-list">
                            <div class="spinner"></div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    },

    async mount() {
        await this.loadReports();
    },

    async loadReports() {
        this.violations = await API.getViolations();
        this.renderReports();
    },

    async refreshReports() {
        const list = document.getElementById('reports-list');
        list.innerHTML = '<div class="spinner"></div>';
        await this.loadReports();
    },

    handleSearch(event) {
        this.filters.search = event.target.value.toLowerCase();
        this.renderReports();
    },

    handleFilter() {
        this.filters.severity = document.getElementById('filter-severity').value;
        this.filters.dateRange = document.getElementById('filter-date').value;
        this.renderReports();
    },

    getFilteredViolations() {
        let filtered = [...this.violations];

        // Search filter
        if (this.filters.search) {
            filtered = filtered.filter(v => 
                v.report_id.toLowerCase().includes(this.filters.search) ||
                v.timestamp.toLowerCase().includes(this.filters.search)
            );
        }

        // Date range filter
        if (this.filters.dateRange !== 'all') {
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            
            filtered = filtered.filter(v => {
                const vDate = new Date(v.timestamp);
                
                switch(this.filters.dateRange) {
                    case 'today':
                        return vDate >= today;
                    case 'week':
                        const weekAgo = new Date(today);
                        weekAgo.setDate(weekAgo.getDate() - 7);
                        return vDate >= weekAgo;
                    case 'month':
                        const monthAgo = new Date(today);
                        monthAgo.setMonth(monthAgo.getMonth() - 1);
                        return vDate >= monthAgo;
                    default:
                        return true;
                }
            });
        }

        return filtered;
    },

    renderReports() {
        const list = document.getElementById('reports-list');
        const filtered = this.getFilteredViolations();

        if (filtered.length === 0) {
            list.innerHTML = `
                <div class="alert alert-info">
                    <i class="fas fa-info-circle"></i>
                    <span>No reports found. Try adjusting your filters or run the live demo to generate violations.</span>
                </div>
            `;
            return;
        }

        list.innerHTML = `
            <div class="grid">
                ${filtered.map(v => this.renderReportCard(v)).join('')}
            </div>
        `;
    },

    renderReportCard(violation) {
        const date = new Date(violation.timestamp);
        const imageUrl = API.getImageUrl(violation.report_id, 'annotated.jpg');
        
        return `
            <div class="card" style="cursor: pointer;" onclick="window.open('${API.getReportUrl(violation.report_id)}', '_blank')">
                <div style="height: 200px; overflow: hidden; background: #000;">
                    ${violation.has_annotated ? 
                        `<img src="${imageUrl}" alt="Violation" style="width: 100%; height: 100%; object-fit: cover;">` :
                        `<div style="display: flex; align-items: center; justify-content: center; height: 100%;">
                            <i class="fas fa-image" style="font-size: 3rem; color: #fff; opacity: 0.3;"></i>
                         </div>`
                    }
                </div>
                <div class="card-content">
                    <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 1rem;">
                        <div style="flex: 1;">
                            <h3 style="color: var(--primary-color); margin-bottom: 0.5rem; font-size: 1.1rem;">
                                Report #${violation.report_id}
                            </h3>
                            <p style="color: #7f8c8d; font-size: 0.9rem; margin: 0;">
                                <i class="fas fa-clock"></i> ${date.toLocaleString()}
                            </p>
                        </div>
                        <span class="badge badge-danger">High</span>
                    </div>
                    
                    <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem;">
                        ${violation.has_original ? '<span class="badge badge-success"><i class="fas fa-image"></i> Original</span>' : ''}
                        ${violation.has_annotated ? '<span class="badge badge-success"><i class="fas fa-draw-polygon"></i> Annotated</span>' : ''}
                        ${violation.has_report ? '<span class="badge badge-success"><i class="fas fa-file-pdf"></i> Report</span>' : '<span class="badge badge-warning"><i class="fas fa-spinner"></i> Processing</span>'}
                    </div>
                    
                    <div style="padding-top: 1rem; border-top: 1px solid var(--border-color);">
                        <p style="margin: 0; color: var(--text-color); font-size: 0.9rem;">
                            <i class="fas fa-exclamation-triangle" style="color: var(--error-color);"></i>
                            <strong>Violation Type:</strong> Missing Hardhat (PPE)
                        </p>
                    </div>
                </div>
            </div>
        `;
    }
};
