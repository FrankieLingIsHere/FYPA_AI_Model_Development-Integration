// About Page Component
const AboutPage = {
    render() {
        return `
            <div class="page about-page">
                <section class="page-command-bar about-command-bar">
                    <div>
                        <span class="ops-kicker"><i class="fas fa-hard-hat"></i> CASM safety platform</span>
                        <h1>PPE Safety Monitor</h1>
                        <p>AI-assisted construction safety monitoring for live PPE detection, evidence capture, and report generation.</p>
                    </div>
                    <div class="command-bar-pills" aria-label="Platform capabilities">
                        <span><i class="fas fa-eye"></i> Vision</span>
                        <span><i class="fas fa-file-signature"></i> Reports</span>
                        <span><i class="fas fa-plug-circle-check"></i> Local mode</span>
                    </div>
                </section>

                <section class="about-showcase-grid">
                    <article class="card about-mission-card">
                        <div class="card-content">
                            <span class="ops-kicker"><i class="fas fa-shield"></i> Mission</span>
                            <h2>Keep every site visibly safer.</h2>
                            <p>
                                CASM connects live camera monitoring, PPE violation evidence, AI summaries, and report workflows
                                into a compact dashboard built for construction safety operations.
                            </p>
                            <div class="about-chip-row">
                                <span class="badge badge-info">YOLO PPE detection</span>
                                <span class="badge badge-success">Cloud + local routing</span>
                                <span class="badge badge-warning">Realtime alerts</span>
                            </div>
                        </div>
                    </article>

                    <article class="card about-standards-card">
                        <div class="card-header">
                            <span><i class="fas fa-helmet-safety"></i> PPE References</span>
                        </div>
                        <div class="card-content ppe-reference-grid">
                            <figure>
                                <img src="/static/images/standards/ms183_helmet.jpg" alt="Helmet PPE reference" loading="lazy" decoding="async">
                                <figcaption>Helmet</figcaption>
                            </figure>
                            <figure>
                                <img src="/static/images/standards/ms1731_vest.jpg" alt="Vest PPE reference" loading="lazy" decoding="async">
                                <figcaption>Vest</figcaption>
                            </figure>
                            <figure>
                                <img src="/static/images/standards/iso20345_boots.jpg" alt="Boot PPE reference" loading="lazy" decoding="async">
                                <figcaption>Boots</figcaption>
                            </figure>
                            <figure>
                                <img src="/static/images/standards/bowec_harness.jpg" alt="Harness PPE reference" loading="lazy" decoding="async">
                                <figcaption>Harness</figcaption>
                            </figure>
                        </div>
                    </article>
                </section>

                <section class="grid grid-3 about-feature-grid">
                    <article class="card feature-tile">
                        <div class="card-content">
                            <i class="fas fa-video"></i>
                            <h3>Live Monitoring</h3>
                            <p>Camera stream and browser camera capture for real-time PPE checks.</p>
                        </div>
                    </article>
                    <article class="card feature-tile">
                        <div class="card-content">
                            <i class="fas fa-clipboard-check"></i>
                            <h3>Evidence Reports</h3>
                            <p>Annotated images, violation summaries, AI notes, and generated report files.</p>
                        </div>
                    </article>
                    <article class="card feature-tile">
                        <div class="card-content">
                            <i class="fas fa-chart-line"></i>
                            <h3>Safety Trends</h3>
                            <p>Severity breakdowns, top violation types, and recent site activity signals.</p>
                        </div>
                    </article>
                </section>

                <section class="card pipeline-card">
                    <div class="card-header">
                        <span><i class="fas fa-route"></i> Detection Pipeline</span>
                    </div>
                    <div class="card-content pipeline-steps">
                        <div><span>01</span><strong>Capture</strong><p>Camera or uploaded image enters the monitoring workflow.</p></div>
                        <div><span>02</span><strong>Detect</strong><p>YOLO identifies PPE classes and missing PPE conditions.</p></div>
                        <div><span>03</span><strong>Record</strong><p>Original and annotated evidence is saved for the report trail.</p></div>
                        <div><span>04</span><strong>Analyze</strong><p>Vision and language providers generate safety context.</p></div>
                        <div><span>05</span><strong>Review</strong><p>Reports and analytics support follow-up action.</p></div>
                    </div>
                </section>

                <section class="card credits-card">
                    <div class="card-content">
                        <span class="ops-kicker"><i class="fas fa-graduation-cap"></i> Final Year Project</span>
                        <p>CASM PPE Safety Monitor - FYPA AI Model Development & Integration, 2026.</p>
                    </div>
                </section>
            </div>
        `;
    },

    mount() {
        // Static page, no dynamic content.
    }
};