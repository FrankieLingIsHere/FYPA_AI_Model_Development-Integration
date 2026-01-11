// Reports Page Component
const ReportsPage = {
    violations: [],
    filters: {
        search: '',
        severity: 'all',
        dateRange: 'all'
    },
    refreshInterval: null,

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
        // Auto-refresh for pending reports
        this.startAutoRefresh();
    },

    unmount() {
        this.stopAutoRefresh();
    },

    startAutoRefresh() {
        // Check for pending reports every 10 seconds
        this.refreshInterval = setInterval(async () => {
            const hasPending = this.violations.some(v => 
                v.status === 'pending' || v.status === 'generating' || !v.has_report
            );
            if (hasPending) {
                await this.loadReports();
            }
        }, 10000);
    },

    stopAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
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
                v.timestamp.toLowerCase().includes(this.filters.search) ||
                (v.device_id && v.device_id.toLowerCase().includes(this.filters.search))
            );
        }

        // Severity filter
        if (this.filters.severity !== 'all') {
            filtered = filtered.filter(v => {
                const severity = (v.severity || 'HIGH').toLowerCase();
                return severity === this.filters.severity;
            });
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

        // Show ALL reports including in-progress ones (Pipeline_Luna behavior)
        list.innerHTML = `
            <div class="grid">
                ${filtered.map(v => this.renderReportCard(v)).join('')}
            </div>
        `;
    },

    // Check if report is ready to view
    isReportReady(violation) {
        const status = violation.status || 'unknown';
        return violation.has_report && 
               (status === 'completed' || status === 'partial' || status === 'unknown');
    },

    // Get status display info
    getStatusInfo(violation) {
        const status = violation.status || (violation.has_report ? 'completed' : 'pending');
        
        switch(status) {
            case 'completed':
                return { icon: 'fa-check-circle', color: 'success', text: 'Ready' };
            case 'generating':
                return { icon: 'fa-spinner fa-spin', color: 'warning', text: 'Generating...' };
            case 'pending':
                return { icon: 'fa-clock', color: 'warning', text: 'Queued' };
            case 'failed':
                return { icon: 'fa-exclamation-triangle', color: 'danger', text: 'Failed' };
            case 'partial':
                return { icon: 'fa-exclamation-circle', color: 'warning', text: 'Partial' };
            default:
                return violation.has_report 
                    ? { icon: 'fa-check-circle', color: 'success', text: 'Ready' }
                    : { icon: 'fa-spinner fa-spin', color: 'warning', text: 'Processing' };
        }
    },

    // Handle report click with fallback for generating reports
    handleReportClick(violation) {
        if (this.isReportReady(violation)) {
            window.open(API.getReportUrl(violation.report_id), '_blank');
        } else {
            this.showGeneratingModal(violation);
        }
    },

    // Show modal for reports still generating
    showGeneratingModal(violation) {
        const statusInfo = this.getStatusInfo(violation);
        
        // Create modal overlay
        const modal = document.createElement('div');
        modal.id = 'report-status-modal';
        modal.style.cssText = `
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.5); display: flex; align-items: center;
            justify-content: center; z-index: 1000;
        `;
        
        modal.innerHTML = `
            <div style="background: white; padding: 2rem; border-radius: 12px; max-width: 500px; width: 90%; text-align: center;">
                <div style="font-size: 4rem; color: var(--${statusInfo.color}-color); margin-bottom: 1rem;">
                    <i class="fas ${statusInfo.icon}"></i>
                </div>
                <h2 style="color: var(--text-color); margin-bottom: 0.5rem;">
                    Report ${statusInfo.text}
                </h2>
                <p style="color: #7f8c8d; margin-bottom: 1.5rem;">
                    ${this.getStatusMessage(violation)}
                </p>
                <div style="display: flex; gap: 1rem; justify-content: center;">
                    <button onclick="ReportsPage.closeModal()" class="btn" style="background: #95a5a6;">
                        <i class="fas fa-times"></i> Close
                    </button>
                    ${violation.status !== 'failed' ? `
                        <button onclick="ReportsPage.checkAndRefresh('${violation.report_id}')" class="btn btn-primary">
                            <i class="fas fa-sync"></i> Check Status
                        </button>
                    ` : `
                        <button onclick="ReportsPage.viewPartialReport('${violation.report_id}')" class="btn btn-warning">
                            <i class="fas fa-eye"></i> View Available Data
                        </button>
                    `}
                </div>
            </div>
        `;
        
        modal.onclick = (e) => {
            if (e.target === modal) this.closeModal();
        };
        
        document.body.appendChild(modal);
    },

    getStatusMessage(violation) {
        const status = violation.status || 'pending';
        
        switch(status) {
            case 'generating':
                return 'The AI is analyzing the violation and generating a detailed report. This usually takes 30-60 seconds.';
            case 'pending':
                return 'This report is queued for processing. It will be generated shortly.';
            case 'failed':
                return `Report generation failed. ${violation.error_message || 'Please try again or contact support.'}`;
            default:
                return 'The report is being processed. Please wait a moment.';
        }
    },

    closeModal() {
        const modal = document.getElementById('report-status-modal');
        if (modal) modal.remove();
    },

    async checkAndRefresh(reportId) {
        this.closeModal();
        await this.refreshReports();
        
        // Find the updated violation
        const violation = this.violations.find(v => v.report_id === reportId);
        if (violation && this.isReportReady(violation)) {
            window.open(API.getReportUrl(reportId), '_blank');
        } else if (violation) {
            this.showGeneratingModal(violation);
        }
    },

    viewPartialReport(reportId) {
        this.closeModal();
        // Navigate to violation detail page with available images
        window.location.hash = `#/violation/${reportId}`;
    },

    renderReportCard(violation) {
        const date = new Date(violation.timestamp);
        const imageUrl = API.getImageUrl(violation.report_id, 'annotated.jpg');
        const statusInfo = this.getStatusInfo(violation);
        const isReady = this.isReportReady(violation);
        const severityClass = (violation.severity === 'HIGH' || violation.severity === 'CRITICAL') ? 'danger' : 
                             (violation.severity === 'MEDIUM' ? 'warning' : 'info');
        
        return `
            <div class="card" id="report-${violation.report_id}" 
                 style="cursor: pointer; ${!isReady ? 'opacity: 0.9;' : ''}" 
                 onclick="ReportsPage.handleReportClick(${JSON.stringify(violation).replace(/"/g, '&quot;')})">
                <div style="height: 200px; overflow: hidden; background: #000; position: relative;">
                    ${violation.has_annotated ? 
                        `<img src="${imageUrl}" alt="Violation" style="width: 100%; height: 100%; object-fit: cover;">` :
                        `<div style="display: flex; align-items: center; justify-content: center; height: 100%;">
                            <i class="fas fa-image" style="font-size: 3rem; color: #fff; opacity: 0.3;"></i>
                         </div>`
                    }
                    ${!isReady ? `
                        <div style="position: absolute; top: 0; left: 0; right: 0; bottom: 0; 
                                    background: rgba(0,0,0,0.4); display: flex; align-items: center; 
                                    justify-content: center;">
                            <div style="color: white; text-align: center;">
                                <i class="fas ${statusInfo.icon}" style="font-size: 2rem;"></i>
                                <p style="margin: 0.5rem 0 0 0;">${statusInfo.text}</p>
                            </div>
                        </div>
                    ` : ''}
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
                        <span class="badge badge-${severityClass}">
                            ${violation.severity || 'High'}
                        </span>
                    </div>
                    
                    <div style="display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem;">
                        ${violation.has_original ? '<span class="badge badge-success"><i class="fas fa-image"></i> Original</span>' : ''}
                        ${violation.has_annotated ? '<span class="badge badge-success"><i class="fas fa-draw-polygon"></i> Annotated</span>' : ''}
                        <span class="badge badge-${statusInfo.color}">
                            <i class="fas ${statusInfo.icon}"></i> ${statusInfo.text}
                        </span>
                    </div>
                    
                    <div style="padding-top: 1rem; border-top: 1px solid var(--border-color);">
                        <p style="margin: 0; color: var(--text-color); font-size: 0.9rem;">
                            <i class="fas fa-exclamation-triangle" style="color: var(--error-color);"></i>
                            <strong>${violation.violation_count || 0} Violation${violation.violation_count !== 1 ? 's' : ''}</strong>
                        </p>
                        ${violation.missing_ppe && violation.missing_ppe.length > 0 ? `
                            <div style="margin-top: 0.75rem; display: flex; gap: 0.5rem; flex-wrap: wrap;">
                                ${violation.missing_ppe.map(ppe => `
                                    <span class="badge badge-danger" style="font-size: 0.75rem;">
                                        <i class="fas fa-times-circle"></i> No ${ppe}
                                    </span>
                                `).join('')}
                            </div>
                        ` : `
                            <p style="margin: 0.5rem 0 0 0; color: #7f8c8d; font-size: 0.85rem;">
                                ${violation.violation_summary || 'PPE Violation'}
                            </p>
                        `}
                        ${violation.device_id ? `
                            <p style="margin: 0.5rem 0 0 0; color: #95a5a6; font-size: 0.8rem;">
                                <i class="fas fa-desktop"></i> Device: ${violation.device_id}
                            </p>
                        ` : ''}
                    </div>
                </div>
            </div>
        `;
    }
};
