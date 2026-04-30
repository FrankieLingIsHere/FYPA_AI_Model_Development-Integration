/**
 * Batch Docs Page
 * ----------------------------------------------------------------------------
 * Replaces the per-report NCR / JKKP-7 buttons that used to live inside every
 * generated report. Officers pick a date range / status / severity / violation
 * type, multi-select reports, then export one or both official documents in
 * a single batch via /api/reports/batch-docs.
 */
const BatchDocsPage = (function () {
    const STATUS_OPTIONS = [
        { value: 'all', label: 'All statuses' },
        { value: 'success', label: 'Success only (completed reports)' },
        { value: 'pending', label: 'Pending / generating' },
        { value: 'failed', label: 'Failed / skipped' }
    ];

    const FORMAT_OPTIONS = [
        { value: 'ncr', label: 'Non-Conformance Report (NCR)' },
        { value: 'jkkp7', label: 'JKKP-7 Incident Form' },
        { value: 'both', label: 'Both NCR + JKKP-7' }
    ];

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function defaultDateRange() {
        const today = new Date();
        const start = new Date(today);
        start.setDate(today.getDate() - 30);
        const fmt = (d) => d.toISOString().slice(0, 10);
        return { start: fmt(start), end: fmt(today) };
    }

    function isCompletedStatus(status) {
        const s = String(status || '').toLowerCase();
        return s === 'completed' || s === 'success' || s === 'partial';
    }

    function isPendingStatus(status) {
        const s = String(status || '').toLowerCase();
        return ['pending', 'queued', 'processing', 'generating'].includes(s);
    }

    function isFailedStatus(status) {
        const s = String(status || '').toLowerCase();
        return ['failed', 'error', 'skipped'].includes(s);
    }

    function unique(values) {
        const seen = new Set();
        const out = [];
        for (const v of values) {
            const key = String(v || '').trim();
            if (!key || seen.has(key.toLowerCase())) continue;
            seen.add(key.toLowerCase());
            out.push(key);
        }
        return out;
    }

    return {
        violations: [],
        loading: false,
        selected: new Set(),

        filters: {
            search: '',
            status: 'success',
            severity: 'all',
            ppeType: 'all',
            dateRange: defaultDateRange()
        },

        format: 'both',

        async init() {
            this.render();
            await this.loadReports();
        },

        render() {
            const root = document.getElementById('app');
            if (!root) return;
            const range = this.filters.dateRange;
            root.innerHTML = `
                <div class="page-container batch-docs-page" style="padding: 1.5rem; max-width: 1400px; margin: 0 auto;">
                    <header style="margin-bottom: 1.25rem;">
                        <h1 style="margin: 0 0 0.35rem; display: flex; align-items: center; gap: 0.5rem;">
                            <i class="fas fa-file-export" style="color:#0d6efd;"></i>
                            Batch Documentation
                        </h1>
                        <p style="margin: 0; color: #5f6b7a; font-size: 0.95rem;">
                            Generate official Non-Conformance Reports (NCR) and JKKP-7 incident forms in one go.
                            Filter by timeline, status, severity and PPE type, then select the reports you want to export.
                        </p>
                    </header>

                    <section class="card" style="padding: 1rem 1.25rem; margin-bottom: 1rem;">
                        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.75rem;">
                            <label>
                                <span style="font-size:0.8rem; color:#5f6b7a;">From</span>
                                <input id="bdFrom" type="date" value="${escapeHtml(range.start)}" style="width:100%; padding:0.4rem; border:1px solid #ced4da; border-radius:4px;">
                            </label>
                            <label>
                                <span style="font-size:0.8rem; color:#5f6b7a;">To</span>
                                <input id="bdTo" type="date" value="${escapeHtml(range.end)}" style="width:100%; padding:0.4rem; border:1px solid #ced4da; border-radius:4px;">
                            </label>
                            <label>
                                <span style="font-size:0.8rem; color:#5f6b7a;">Status</span>
                                <select id="bdStatus" style="width:100%; padding:0.4rem; border:1px solid #ced4da; border-radius:4px;">
                                    ${STATUS_OPTIONS.map(o => `<option value="${o.value}" ${o.value === this.filters.status ? 'selected' : ''}>${escapeHtml(o.label)}</option>`).join('')}
                                </select>
                            </label>
                            <label>
                                <span style="font-size:0.8rem; color:#5f6b7a;">Severity</span>
                                <select id="bdSeverity" style="width:100%; padding:0.4rem; border:1px solid #ced4da; border-radius:4px;">
                                    <option value="all">All</option>
                                    <option value="CRITICAL">Critical</option>
                                    <option value="HIGH">High</option>
                                    <option value="MEDIUM">Medium</option>
                                    <option value="LOW">Low</option>
                                </select>
                            </label>
                            <label>
                                <span style="font-size:0.8rem; color:#5f6b7a;">PPE / violation type</span>
                                <select id="bdPpe" style="width:100%; padding:0.4rem; border:1px solid #ced4da; border-radius:4px;">
                                    <option value="all">All types</option>
                                </select>
                            </label>
                            <label>
                                <span style="font-size:0.8rem; color:#5f6b7a;">Search</span>
                                <input id="bdSearch" type="text" placeholder="Report ID or summary…" style="width:100%; padding:0.4rem; border:1px solid #ced4da; border-radius:4px;">
                            </label>
                        </div>
                    </section>

                    <section class="card" style="padding: 1rem 1.25rem; margin-bottom: 1rem; display:flex; flex-wrap:wrap; gap:0.75rem; align-items:center;">
                        <div style="display:flex; gap:0.5rem; align-items:center;">
                            <label style="display:flex; align-items:center; gap:0.4rem; font-size:0.9rem;">
                                <input id="bdSelectAll" type="checkbox"> Select all on screen
                            </label>
                            <span id="bdSelectedCount" style="font-size:0.85rem; color:#5f6b7a;">0 selected</span>
                        </div>
                        <div style="margin-left:auto; display:flex; gap:0.5rem; align-items:center;">
                            <label style="font-size:0.85rem; color:#5f6b7a;">Format</label>
                            <select id="bdFormat" style="padding:0.4rem; border:1px solid #ced4da; border-radius:4px;">
                                ${FORMAT_OPTIONS.map(o => `<option value="${o.value}" ${o.value === this.format ? 'selected' : ''}>${escapeHtml(o.label)}</option>`).join('')}
                            </select>
                            <button id="bdGenerate" class="btn btn-primary" style="padding:0.5rem 1rem;">
                                <i class="fas fa-file-download"></i> Generate Selected
                            </button>
                        </div>
                    </section>

                    <section id="bdResults" class="card" style="padding: 0; overflow:hidden;">
                        <div style="padding:1.25rem; text-align:center; color:#5f6b7a;">Loading reports…</div>
                    </section>
                </div>
            `;
            this._bindEvents();
        },

        _bindEvents() {
            const on = (id, ev, fn) => {
                const el = document.getElementById(id);
                if (el) el.addEventListener(ev, fn);
            };
            on('bdFrom', 'change', (e) => { this.filters.dateRange.start = e.target.value; this.renderResults(); });
            on('bdTo', 'change', (e) => { this.filters.dateRange.end = e.target.value; this.renderResults(); });
            on('bdStatus', 'change', (e) => { this.filters.status = e.target.value; this.renderResults(); });
            on('bdSeverity', 'change', (e) => { this.filters.severity = e.target.value; this.renderResults(); });
            on('bdPpe', 'change', (e) => { this.filters.ppeType = e.target.value; this.renderResults(); });
            on('bdSearch', 'input', (e) => { this.filters.search = e.target.value; this.renderResults(); });
            on('bdFormat', 'change', (e) => { this.format = e.target.value; });
            on('bdSelectAll', 'change', (e) => this._toggleSelectAll(e.target.checked));
            on('bdGenerate', 'click', () => this.generateSelected());
        },

        async loadReports() {
            this.loading = true;
            try {
                const violations = await API.getViolations({ limit: 1000, noCache: true });
                this.violations = Array.isArray(violations) ? violations : [];
            } catch (err) {
                console.error('BatchDocsPage.loadReports failed', err);
                this.violations = [];
            } finally {
                this.loading = false;
                this._populatePpeOptions();
                this.renderResults();
            }
        },

        _populatePpeOptions() {
            const select = document.getElementById('bdPpe');
            if (!select) return;
            const types = unique(
                this.violations.flatMap(v => Array.isArray(v.missing_ppe) ? v.missing_ppe : [])
            );
            const current = select.value || 'all';
            select.innerHTML = '<option value="all">All types</option>'
                + types.map(t => `<option value="${escapeHtml(t)}" ${t === current ? 'selected' : ''}>${escapeHtml(t)}</option>`).join('');
        },

        getFiltered() {
            const { search, status, severity, ppeType, dateRange } = this.filters;
            const term = String(search || '').trim().toLowerCase();
            const startTs = dateRange.start ? Date.parse(dateRange.start + 'T00:00:00') : null;
            const endTs = dateRange.end ? Date.parse(dateRange.end + 'T23:59:59') : null;

            return this.violations.filter((v) => {
                if (!v) return false;
                const ts = Date.parse(v.timestamp || '') || 0;
                if (startTs && ts && ts < startTs) return false;
                if (endTs && ts && ts > endTs) return false;

                const st = String(v.status || '').toLowerCase();
                if (status === 'success' && !isCompletedStatus(st)) return false;
                if (status === 'pending' && !isPendingStatus(st)) return false;
                if (status === 'failed' && !isFailedStatus(st)) return false;

                if (severity !== 'all' && String(v.severity || '').toUpperCase() !== severity) return false;

                if (ppeType !== 'all') {
                    const list = Array.isArray(v.missing_ppe) ? v.missing_ppe.map(x => String(x).toLowerCase()) : [];
                    if (!list.includes(String(ppeType).toLowerCase())) return false;
                }

                if (term) {
                    const haystack = `${v.report_id || ''} ${v.violation_summary || ''} ${(v.missing_ppe || []).join(' ')}`.toLowerCase();
                    if (!haystack.includes(term)) return false;
                }
                return true;
            });
        },

        renderResults() {
            const host = document.getElementById('bdResults');
            if (!host) return;
            if (this.loading) {
                host.innerHTML = '<div style="padding:1.25rem; text-align:center; color:#5f6b7a;">Loading reports…</div>';
                return;
            }
            const rows = this.getFiltered();
            if (rows.length === 0) {
                host.innerHTML = '<div style="padding:1.25rem; text-align:center; color:#5f6b7a;">No reports match the current filters.</div>';
                this._refreshSelectedCount();
                return;
            }

            const head = `
                <tr style="background:#f8f9fa;">
                    <th style="padding:0.55rem; width:36px;"></th>
                    <th style="padding:0.55rem; text-align:left;">Report ID</th>
                    <th style="padding:0.55rem; text-align:left;">When</th>
                    <th style="padding:0.55rem; text-align:left;">Status</th>
                    <th style="padding:0.55rem; text-align:left;">Severity</th>
                    <th style="padding:0.55rem; text-align:left;">Missing PPE</th>
                    <th style="padding:0.55rem; text-align:left;">Summary</th>
                </tr>`;
            const body = rows.map(v => {
                const id = String(v.report_id || '');
                const checked = this.selected.has(id) ? 'checked' : '';
                const ppe = Array.isArray(v.missing_ppe) ? v.missing_ppe.join(', ') : '';
                const summary = String(v.violation_summary || '').slice(0, 140);
                const ts = v.timestamp ? new Date(v.timestamp).toLocaleString() : '—';
                return `
                    <tr data-rid="${escapeHtml(id)}" style="border-top:1px solid #e9ecef;">
                        <td style="padding:0.5rem; text-align:center;">
                            <input type="checkbox" class="bd-row-check" data-rid="${escapeHtml(id)}" ${checked}>
                        </td>
                        <td style="padding:0.5rem; font-family: monospace; font-size:0.85rem;">${escapeHtml(id)}</td>
                        <td style="padding:0.5rem; font-size:0.85rem;">${escapeHtml(ts)}</td>
                        <td style="padding:0.5rem; font-size:0.85rem;">${escapeHtml(v.status || 'unknown')}</td>
                        <td style="padding:0.5rem; font-size:0.85rem;">${escapeHtml(v.severity || '—')}</td>
                        <td style="padding:0.5rem; font-size:0.85rem;">${escapeHtml(ppe || '—')}</td>
                        <td style="padding:0.5rem; font-size:0.85rem;">${escapeHtml(summary)}</td>
                    </tr>`;
            }).join('');

            host.innerHTML = `
                <div style="overflow-x:auto;">
                    <table style="width:100%; border-collapse:collapse;">
                        <thead>${head}</thead>
                        <tbody>${body}</tbody>
                    </table>
                </div>
                <div style="padding:0.75rem 1.25rem; color:#5f6b7a; font-size:0.85rem; border-top:1px solid #e9ecef;">
                    Showing ${rows.length} report${rows.length === 1 ? '' : 's'}.
                </div>
            `;
            host.querySelectorAll('.bd-row-check').forEach((cb) => {
                cb.addEventListener('change', (e) => {
                    const rid = e.target.dataset.rid;
                    if (e.target.checked) this.selected.add(rid); else this.selected.delete(rid);
                    this._refreshSelectedCount();
                });
            });
            this._refreshSelectedCount();
        },

        _toggleSelectAll(checked) {
            const rows = this.getFiltered();
            if (checked) {
                rows.forEach(r => this.selected.add(String(r.report_id || '')));
            } else {
                rows.forEach(r => this.selected.delete(String(r.report_id || '')));
            }
            this.renderResults();
        },

        _refreshSelectedCount() {
            const el = document.getElementById('bdSelectedCount');
            if (el) el.textContent = `${this.selected.size} selected`;
        },

        async generateSelected() {
            const ids = Array.from(this.selected).filter(Boolean);
            if (ids.length === 0) {
                alert('Pick at least one report to generate documentation for.');
                return;
            }
            const btn = document.getElementById('bdGenerate');
            const originalText = btn ? btn.innerHTML : '';
            try {
                if (btn) {
                    btn.disabled = true;
                    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating…';
                }
                const url = `${API_CONFIG.BASE_URL}/api/reports/batch-docs`;
                const resp = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ report_ids: ids, format: this.format })
                });
                if (!resp.ok) {
                    const text = await resp.text();
                    throw new Error(`Batch docs request failed (${resp.status}): ${text.slice(0, 200)}`);
                }
                const html = await resp.text();
                const w = window.open('', '_blank');
                if (!w) {
                    alert('Popup blocked. Please allow popups for this site to view the batch document.');
                    return;
                }
                w.document.open();
                w.document.write(html);
                w.document.close();
            } catch (err) {
                console.error('BatchDocsPage.generateSelected failed', err);
                alert(`Failed to generate batch documentation: ${err.message || err}`);
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = originalText || '<i class="fas fa-file-download"></i> Generate Selected';
                }
            }
        }
    };
})();

if (typeof window !== 'undefined') {
    window.BatchDocsPage = BatchDocsPage;
}
