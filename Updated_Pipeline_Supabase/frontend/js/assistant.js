const CASMAssistant = {
    STORAGE_KEY: 'casm.assistant.sessions.v1',
    PANEL_STATE_KEY: 'casm.assistant.panelState.v1',
    CLIENT_ID_KEY: 'casm.assistant.clientId.v1',
    SYNC_SECRET_KEY: 'casm.assistant.syncSecret.v1',
    MAX_SESSIONS: 14,
    MAX_MESSAGES: 80,
    sessions: [],
    activeSessionId: '',
    docsIndex: [],
    panelOpen: false,
    railOpen: false,
    clientIdentity: null,
    syncTimer: null,
    syncInFlight: false,
    syncQueued: false,
    ui: {},

    init() {
        this.cacheDom();
        if (!this.ui.launcher || !this.ui.panel) return;
        if (this.ui.input) {
            this.ui.input.setAttribute(
                'placeholder',
                'Type a question or request, like "show local tutorial" or "export cloud reports csv"'
            );
        }
        this.clientIdentity = this.ensureClientIdentity();
        this.docsIndex = this.buildDocsIndex();
        this.loadState();
        this.ensureActiveSession();
        this.bindEvents();
        this.renderSessionRail();
        this.renderShortcutStrip();
        this.renderPromptDeck();
        this.renderMessages();
        this.syncPanelState(false);
        this.trackRoute(APP_STATE.currentPage || 'home');
    },

    cacheDom() {
        this.ui = {
            dock: document.getElementById('assistantDock'),
            launcher: document.getElementById('assistantLauncher'),
            panel: document.getElementById('assistantPanel'),
            close: document.getElementById('assistantClose'),
            sessionsToggle: document.getElementById('assistantSessionsToggle'),
            newSession: document.getElementById('assistantNewSession'),
            sessionRail: document.getElementById('assistantSessionRail'),
            sessionList: document.getElementById('assistantSessionList'),
            shortcutStrip: document.getElementById('assistantShortcutStrip'),
            promptDeck: document.getElementById('assistantPromptDeck'),
            messages: document.getElementById('assistantMessages'),
            composer: document.getElementById('assistantComposer'),
            input: document.getElementById('assistantInput')
        };
    },

    bindEvents() {
        this.ui.launcher.addEventListener('click', () => this.togglePanel());
        this.ui.close.addEventListener('click', () => this.togglePanel(false));
        this.ui.newSession.addEventListener('click', () => this.createSession({ focusInput: true }));
        this.ui.sessionsToggle.addEventListener('click', () => this.toggleRail());
        this.ui.composer.addEventListener('submit', (event) => {
            event.preventDefault();
            this.handleSubmit();
        });
        this.ui.input.addEventListener('input', () => this.autosizeInput());
        this.ui.input.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                this.handleSubmit();
            }
        });
        this.ui.messages.addEventListener('click', (event) => this.handleActionClick(event));
        this.ui.shortcutStrip.addEventListener('click', (event) => this.handleActionClick(event));
        if (this.ui.promptDeck) {
            this.ui.promptDeck.addEventListener('click', (event) => this.handleActionClick(event));
        }
        this.ui.sessionList.addEventListener('click', (event) => this.handleSessionRailClick(event));
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && this.panelOpen) {
                this.togglePanel(false);
            }
        });
        window.addEventListener('resize', () => this.handleResize());
        window.addEventListener('ppe-route:changed', (event) => {
            const page = String(event?.detail?.page || APP_STATE.currentPage || 'home');
            this.trackRoute(page);
        });
    },

    handleResize() {
        if (window.innerWidth > 900) {
            this.railOpen = true;
        } else if (!this.panelOpen) {
            this.railOpen = false;
        }
        this.syncPanelState(false);
        this.autosizeInput();
    },

    loadState() {
        try {
            const rawSessions = localStorage.getItem(this.STORAGE_KEY);
            if (rawSessions) {
                const parsed = JSON.parse(rawSessions);
                if (Array.isArray(parsed)) {
                    this.sessions = parsed
                        .filter((session) => session && session.id)
                        .map((session) => this.normalizeSession(session))
                        .filter(Boolean);
                }
            }
        } catch (_) {
            this.sessions = [];
        }

        try {
            const rawPanelState = localStorage.getItem(this.PANEL_STATE_KEY);
            const parsedPanelState = rawPanelState ? JSON.parse(rawPanelState) : null;
            if (parsedPanelState && typeof parsedPanelState === 'object') {
                this.activeSessionId = String(parsedPanelState.activeSessionId || '').trim();
                this.railOpen = parsedPanelState.railOpen !== false;
            }
        } catch (_) {
            this.activeSessionId = '';
        }
    },

    saveState() {
        try {
            localStorage.setItem(this.STORAGE_KEY, JSON.stringify(this.sessions.slice(0, this.MAX_SESSIONS)));
        } catch (_) {
            // Ignore storage failures.
        }
        try {
            localStorage.setItem(this.PANEL_STATE_KEY, JSON.stringify({
                activeSessionId: this.activeSessionId,
                railOpen: this.railOpen,
                panelOpen: this.panelOpen,
                measuredAt: Date.now()
            }));
        } catch (_) {
            // Ignore storage failures.
        }
        this.queueAdminSync();
    },

    normalizeSession(session) {
        const id = String(session?.id || '').trim();
        if (!id) return null;
        const messages = Array.isArray(session.messages) ? session.messages.slice(-this.MAX_MESSAGES) : [];
        return {
            id,
            title: String(session.title || 'New session').trim() || 'New session',
            createdAt: Number(session.createdAt || Date.now()),
            updatedAt: Number(session.updatedAt || Date.now()),
            context: {
                tutorialFlow: String(session?.context?.tutorialFlow || 'cloud') === 'local' ? 'local' : 'cloud',
                tutorialIndex: Math.max(0, Number(session?.context?.tutorialIndex || 0)),
                recentPages: Array.isArray(session?.context?.recentPages) ? session.context.recentPages.slice(0, 8) : [],
                lastDocsQuery: String(session?.context?.lastDocsQuery || ''),
                lastDocsResults: Array.isArray(session?.context?.lastDocsResults) ? session.context.lastDocsResults.slice(0, 6) : [],
                lastExportKind: String(session?.context?.lastExportKind || ''),
                lastUserPrompt: String(session?.context?.lastUserPrompt || '')
            },
            messages: messages.map((message) => this.normalizeMessage(message)).filter(Boolean)
        };
    },

    normalizeMessage(message) {
        if (!message || !message.id || !message.role) return null;
        return {
            id: String(message.id),
            role: message.role === 'assistant' ? 'assistant' : 'user',
            text: String(message.text || ''),
            createdAt: Number(message.createdAt || Date.now()),
            bullets: Array.isArray(message.bullets) ? message.bullets.slice(0, 8) : [],
            actions: Array.isArray(message.actions) ? message.actions.slice(0, 8) : [],
            docs: Array.isArray(message.docs) ? message.docs.slice(0, 4) : [],
            tutorial: message.tutorial && typeof message.tutorial === 'object' ? message.tutorial : null,
            metrics: Array.isArray(message.metrics) ? message.metrics.slice(0, 6) : []
        };
    },

    ensureActiveSession() {
        if (!this.sessions.length) {
            this.sessions = [this.createSessionRecord({
                title: 'Getting started',
                welcome: true
            })];
        }

        const active = this.sessions.find((session) => session.id === this.activeSessionId);
        if (!active) {
            this.activeSessionId = this.sessions[0].id;
        }

        if (window.innerWidth > 900) {
            this.railOpen = true;
        }
        this.saveState();
    },

    createSessionRecord({ title = 'New session', welcome = false } = {}) {
        const session = {
            id: `assistant-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            title,
            createdAt: Date.now(),
            updatedAt: Date.now(),
            context: {
                tutorialFlow: 'cloud',
                tutorialIndex: 0,
                recentPages: [],
                lastDocsQuery: '',
                lastDocsResults: [],
                lastExportKind: '',
                lastUserPrompt: ''
            },
            messages: []
        };
        if (welcome) {
            session.messages.push({
                id: `msg-${Date.now()}-welcome`,
                role: 'assistant',
                text: 'Hi, I can guide tutorials, explain the system, open pages or handbook sections, and export filtered CSV files from natural-language requests.',
                createdAt: Date.now(),
                bullets: [
                    'Explain report tags, local mode checkup, cloud/local behavior, and caption flow.',
                    'Show cloud or local tutorial steps directly in chat and jump into the handbook.',
                    'Open pages like Live, Reports, Analytics, Settings, or a specific handbook section.',
                    'Export analytics or report CSV files from prompts like "export cloud reports csv month".',
                    'Session memory stays on this browser, and only admins can review synced copies.'
                ],
                actions: [
                    { type: 'tutorial', label: 'Cloud tutorial', flow: 'cloud', stepIndex: 0 },
                    { type: 'tutorial', label: 'Local tutorial', flow: 'local', stepIndex: 0 },
                    { type: 'overview', label: 'System overview' },
                    { type: 'export', label: 'Export reports CSV', exportKind: 'reports' }
                ]
            });
        }
        return session;
    },

    createSession(options = {}) {
        const session = this.createSessionRecord({
            title: 'New session',
            welcome: true
        });
        this.sessions.unshift(session);
        this.sessions = this.sessions.slice(0, this.MAX_SESSIONS);
        this.activeSessionId = session.id;
        this.renderSessionRail();
        this.renderMessages();
        this.saveState();
        if (options.focusInput) {
            this.togglePanel(true);
            this.ui.input.focus();
        }
    },

    getActiveSession() {
        return this.sessions.find((session) => session.id === this.activeSessionId) || this.sessions[0] || null;
    },

    setActiveSession(sessionId) {
        const target = this.sessions.find((session) => session.id === sessionId);
        if (!target) return;
        this.activeSessionId = target.id;
        target.updatedAt = Date.now();
        this.renderSessionRail();
        this.renderMessages();
        this.saveState();
        this.toggleRail(window.innerWidth > 900);
    },

    togglePanel(force) {
        const next = typeof force === 'boolean' ? force : !this.panelOpen;
        this.panelOpen = next;
        if (next && window.innerWidth > 900) {
            this.railOpen = true;
        }
        this.syncPanelState(true);
        if (this.panelOpen) {
            this.autosizeInput();
            window.setTimeout(() => {
                this.scrollMessagesToBottom();
                this.ui.input.focus();
            }, 60);
        }
        this.saveState();
    },

    toggleRail(force) {
        this.railOpen = typeof force === 'boolean' ? force : !this.railOpen;
        this.syncPanelState(false);
        this.saveState();
    },

    syncPanelState(updateLauncher = false) {
        this.ui.panel.classList.toggle('hidden', !this.panelOpen);
        this.ui.panel.classList.toggle('is-open', this.panelOpen);
        this.ui.sessionRail.classList.toggle('is-open', this.railOpen);
        document.body.classList.toggle('assistant-open', this.panelOpen);
        document.body.classList.toggle('assistant-rail-open', this.panelOpen && this.railOpen);
        if (updateLauncher) {
            this.ui.launcher.setAttribute('aria-expanded', this.panelOpen ? 'true' : 'false');
        }
        this.ui.sessionsToggle.setAttribute('aria-expanded', this.railOpen ? 'true' : 'false');
    },

    renderShortcutStrip() {
        const actions = [
            { type: 'route', label: 'Home', icon: 'fa-home', page: 'home' },
            { type: 'route', label: 'Live', icon: 'fa-video', page: 'live' },
            { type: 'route', label: 'Reports', icon: 'fa-file-alt', page: 'reports' },
            { type: 'route', label: 'Analytics', icon: 'fa-chart-line', page: 'analytics' },
            { type: 'handbook', label: 'Manual', icon: 'fa-book-open', pageKey: 'intro' },
            { type: 'tutorial', label: 'Cloud demo', icon: 'fa-cloud', flow: 'cloud', stepIndex: 0 },
            { type: 'tutorial', label: 'Local demo', icon: 'fa-laptop-code', flow: 'local', stepIndex: 0 },
            { type: 'export', label: 'Reports CSV', icon: 'fa-file-csv', exportKind: 'reports' },
            { type: 'overview', label: 'Overview', icon: 'fa-signal', exportKind: '' }
        ];
        this.ui.shortcutStrip.innerHTML = actions.map((action, index) => `
            <button class="assistant-shortcut-btn" type="button" data-shortcut-index="${index}">
                <i class="fas ${action.icon}" aria-hidden="true"></i>
                <span>${this.escapeHtml(action.label)}</span>
            </button>
        `).join('');
        this.shortcutActions = actions;
    },

    buildPromptSuggestion(label, prompt) {
        return {
            type: 'prompt',
            label: String(label || '').trim(),
            prompt: String(prompt || '').trim()
        };
    },

    buildPromptDeckModel() {
        const session = this.getActiveSession();
        const currentPage = String((APP_STATE && APP_STATE.currentPage) || session?.context?.recentPages?.[0] || 'home');
        const lastUserPrompt = this.normalizeText(session?.context?.lastUserPrompt || '');
        const messages = Array.isArray(session?.messages) ? session.messages : [];
        const userMessages = messages.filter((message) => message.role === 'user');
        const lastAssistantMessage = [...messages].reverse().find((message) => message.role === 'assistant') || null;
        const tutorialFlow = String(session?.context?.tutorialFlow || 'cloud') === 'local' ? 'local' : 'cloud';
        const tutorialSteps = (window.CASM_TUTORIAL_FLOWS && window.CASM_TUTORIAL_FLOWS[tutorialFlow]) || [];
        const tutorialIndex = Math.max(0, Math.min(
            Number(session?.context?.tutorialIndex || 0),
            Math.max(0, tutorialSteps.length - 1)
        ));
        const promptModel = {
            headline: 'Try one of these',
            subline: 'New here? These are safe starter prompts. Synced history is admin-only.',
            compact: userMessages.length > 0,
            mode: 'starter',
            actions: []
        };

        if (!userMessages.length) {
            promptModel.actions = [
                this.buildPromptSuggestion('Show local tutorial', 'show local tutorial'),
                this.buildPromptSuggestion('Explain Local Tag', 'what does local synced mean'),
                this.buildPromptSuggestion('Find sync docs', 'find docs about wifi reconnect local sync'),
                this.buildPromptSuggestion('Export cloud CSV', 'export cloud reports csv month'),
                this.buildPromptSuggestion('Open checkup', 'open settings checkup')
            ];
            return promptModel;
        }

        if (lastAssistantMessage && lastAssistantMessage.tutorial) {
            const nextStepIndex = Math.min(Math.max(0, tutorialSteps.length - 1), tutorialIndex + 1);
            const previousStepIndex = Math.max(0, tutorialIndex - 1);
            promptModel.headline = 'Suggested next steps';
            promptModel.subline = tutorialFlow === 'local'
                ? 'You are in the local tutorial flow. These prompts keep that path moving.'
                : 'You are in the cloud tutorial flow. These prompts continue the happy path.';
            promptModel.mode = `tutorial-${tutorialFlow}`;
            promptModel.actions = tutorialFlow === 'local'
                ? [
                    this.buildPromptSuggestion('Next tutorial step', 'next step'),
                    this.buildPromptSuggestion('Previous step', 'previous step'),
                    this.buildPromptSuggestion('Open checkup', 'open settings checkup'),
                    this.buildPromptSuggestion('Find sync docs', 'find docs about wifi reconnect local sync'),
                    this.buildPromptSuggestion('Explain Local Tag', 'what does local synced mean')
                ]
                : [
                    this.buildPromptSuggestion('Next tutorial step', 'next step'),
                    this.buildPromptSuggestion('Previous step', 'previous step'),
                    this.buildPromptSuggestion('Open reports', 'open reports'),
                    this.buildPromptSuggestion('Explain Cloud Tag', 'what should cloud tag mean'),
                    this.buildPromptSuggestion('Export cloud CSV', 'export cloud reports csv month')
                ];
            if (!tutorialSteps.length || nextStepIndex === tutorialIndex && previousStepIndex === tutorialIndex) {
                promptModel.actions = promptModel.actions.filter((action) => action.prompt !== 'previous step');
            }
            return promptModel;
        }

        if (this.isDocsIntent(lastUserPrompt) || (lastAssistantMessage && Array.isArray(lastAssistantMessage.docs) && lastAssistantMessage.docs.length)) {
            promptModel.headline = 'Keep exploring';
            promptModel.subline = 'You just searched the handbook. These prompts keep the explanation and follow-up close by.';
            promptModel.mode = 'docs';
            promptModel.actions = [
                this.buildPromptSuggestion('Open handbook', 'open handbook'),
                this.buildPromptSuggestion('Export docs CSV', 'export docs csv about wifi reconnect local sync'),
                this.buildPromptSuggestion('Show local tutorial', 'show local tutorial'),
                this.buildPromptSuggestion('Explain Local Tag', 'what does local synced mean'),
                this.buildPromptSuggestion('Open checkup', 'open settings checkup')
            ];
            return promptModel;
        }

        if (String(session?.context?.lastExportKind || '') === 'reports') {
            promptModel.headline = 'After report export';
            promptModel.subline = 'You exported report rows. These are the usual next questions people ask.';
            promptModel.mode = 'reports-export';
            promptModel.actions = [
                this.buildPromptSuggestion('Open reports', 'open reports'),
                this.buildPromptSuggestion('Explain Cloud Tag', 'what should cloud tag mean'),
                this.buildPromptSuggestion('Explain Local Tag', 'what does local synced mean'),
                this.buildPromptSuggestion('Export cloud CSV', 'export cloud reports csv month'),
                this.buildPromptSuggestion('Open analytics', 'open analytics')
            ];
            return promptModel;
        }

        if (String(session?.context?.lastExportKind || '') === 'analytics') {
            promptModel.headline = 'After analytics export';
            promptModel.subline = 'You just exported metrics. These prompts help connect the numbers back to operations.';
            promptModel.mode = 'analytics-export';
            promptModel.actions = [
                this.buildPromptSuggestion('Open analytics', 'open analytics'),
                this.buildPromptSuggestion('System overview', 'system overview'),
                this.buildPromptSuggestion('Export reports CSV', 'export reports csv'),
                this.buildPromptSuggestion('Explain Cloud Tag', 'what should cloud tag mean'),
                this.buildPromptSuggestion('Show cloud tutorial', 'show cloud tutorial')
            ];
            return promptModel;
        }

        if (/wifi|reconnect|sync|offline|checkup|provision/i.test(lastUserPrompt) || currentPage === 'settings') {
            promptModel.headline = 'Local readiness follow-up';
            promptModel.subline = 'These prompts usually help once someone is checking local mode health or reconnect behavior.';
            promptModel.mode = 'local-readiness';
            promptModel.actions = [
                this.buildPromptSuggestion('Open checkup', 'open settings checkup'),
                this.buildPromptSuggestion('Show local tutorial', 'show local tutorial'),
                this.buildPromptSuggestion('Find sync docs', 'find docs about wifi reconnect local sync'),
                this.buildPromptSuggestion('Explain Local Tag', 'what does local synced mean'),
                this.buildPromptSuggestion('Export local reports CSV', 'export local reports csv')
            ];
            return promptModel;
        }

        if (/caption|gemini|gemma|cloud|report tag|reports?/i.test(lastUserPrompt) || currentPage === 'reports') {
            promptModel.headline = 'Report follow-up';
            promptModel.subline = 'These prompts keep the report-review flow moving without making the user restate the context.';
            promptModel.mode = 'reports';
            promptModel.actions = [
                this.buildPromptSuggestion('Open reports', 'open reports'),
                this.buildPromptSuggestion('Explain Cloud Tag', 'what should cloud tag mean'),
                this.buildPromptSuggestion('Export cloud CSV', 'export cloud reports csv month'),
                this.buildPromptSuggestion('Show cloud tutorial', 'show cloud tutorial'),
                this.buildPromptSuggestion('Find report tag docs', 'find docs about cloud local synced tags')
            ];
            return promptModel;
        }

        if (/overview|metric|analytics|trend|ready rate/i.test(lastUserPrompt) || currentPage === 'analytics') {
            promptModel.headline = 'Analytics follow-up';
            promptModel.subline = 'The user is in metrics mode, so these prompts stay close to summary and export tasks.';
            promptModel.mode = 'analytics';
            promptModel.actions = [
                this.buildPromptSuggestion('System overview', 'system overview'),
                this.buildPromptSuggestion('Export analytics CSV', 'export analytics csv'),
                this.buildPromptSuggestion('Open reports', 'open reports'),
                this.buildPromptSuggestion('Explain Local Tag', 'what does local synced mean'),
                this.buildPromptSuggestion('Show cloud tutorial', 'show cloud tutorial')
            ];
            return promptModel;
        }

        if (currentPage === 'live') {
            promptModel.headline = 'Live monitoring follow-up';
            promptModel.subline = 'These prompts help after a monitoring run or before closing a live session.';
            promptModel.mode = 'live';
            promptModel.actions = [
                this.buildPromptSuggestion('Show cloud tutorial', 'show cloud tutorial'),
                this.buildPromptSuggestion('Show local tutorial', 'show local tutorial'),
                this.buildPromptSuggestion('Open reports', 'open reports'),
                this.buildPromptSuggestion('Explain caption flow', 'how does caption flow work'),
                this.buildPromptSuggestion('Open checkup', 'open settings checkup')
            ];
            return promptModel;
        }

        promptModel.headline = 'Suggested next steps';
        promptModel.subline = 'I am keeping the prompts near your recent context so you can keep moving with one click.';
        promptModel.mode = 'general-followup';
        promptModel.actions = [
            this.buildPromptSuggestion('System overview', 'system overview'),
            this.buildPromptSuggestion('Open reports', 'open reports'),
            this.buildPromptSuggestion('Show local tutorial', 'show local tutorial'),
            this.buildPromptSuggestion('Find handbook docs', 'find docs about report tags'),
            this.buildPromptSuggestion('Export analytics CSV', 'export analytics csv')
        ];
        return promptModel;
    },

    renderPromptDeck() {
        if (!this.ui.promptDeck) return;
        const promptModel = this.buildPromptDeckModel();
        const promptActions = Array.isArray(promptModel.actions) ? promptModel.actions.slice(0, 5) : [];
        this.ui.promptDeck.innerHTML = `
            <div class="assistant-prompt-deck-copy" data-prompt-mode="${this.escapeHtml(promptModel.mode || 'general')}">
                <strong>${this.escapeHtml(promptModel.headline || 'Suggested next steps')}</strong>
                <span>${this.escapeHtml(promptModel.subline || '')}</span>
            </div>
            <div class="assistant-prompt-chip-row">
                ${promptActions.map((action, index) => `
                    <button class="assistant-prompt-chip" type="button" data-prompt-index="${index}">
                        ${this.escapeHtml(action.label)}
                    </button>
                `).join('')}
            </div>
        `;
        this.promptActions = promptActions;
        this.ui.promptDeck.classList.toggle('is-compact', !!promptModel.compact);
    },

    renderSessionRail() {
        const sessions = [...this.sessions].sort((a, b) => b.updatedAt - a.updatedAt);
        this.ui.sessionList.innerHTML = sessions.map((session) => `
            <button class="assistant-session-chip ${session.id === this.activeSessionId ? 'active' : ''}" type="button" data-session-id="${this.escapeHtml(session.id)}">
                <span class="assistant-session-chip-title">${this.escapeHtml(session.title)}</span>
                <span class="assistant-session-chip-meta">${this.formatRelativeTime(session.updatedAt)}</span>
            </button>
        `).join('');
    },

    renderMessages() {
        const session = this.getActiveSession();
        if (!session) return;
        this.renderPromptDeck();
        this.ui.messages.innerHTML = session.messages.map((message) => this.renderMessage(message)).join('');
        this.scrollMessagesToBottom();
    },

    renderMessage(message) {
        const actionsHtml = Array.isArray(message.actions) && message.actions.length
            ? `<div class="assistant-action-row">${message.actions.map((action, index) => `
                <button class="assistant-action-btn" type="button" data-message-id="${this.escapeHtml(message.id)}" data-action-index="${index}">
                    ${this.escapeHtml(action.label || 'Open')}
                </button>
            `).join('')}</div>`
            : '';

        const bulletsHtml = Array.isArray(message.bullets) && message.bullets.length
            ? `<ul class="assistant-bullet-list">${message.bullets.map((item) => `<li>${this.escapeHtml(item)}</li>`).join('')}</ul>`
            : '';

        const docsHtml = Array.isArray(message.docs) && message.docs.length
            ? `<div class="assistant-doc-grid">${message.docs.map((doc, index) => `
                <article class="assistant-doc-card">
                    <span class="assistant-doc-kicker">${this.escapeHtml(doc.label || 'Manual')}</span>
                    <h4>${this.escapeHtml(doc.title || 'Section')}</h4>
                    <p>${this.escapeHtml(doc.snippet || '')}</p>
                    <button class="assistant-inline-link" type="button" data-message-id="${this.escapeHtml(message.id)}" data-action-index="${Number(doc.actionIndex || index)}">
                        Open section
                    </button>
                </article>
            `).join('')}</div>`
            : '';

        const tutorialHtml = message.tutorial
            ? `
                <div class="assistant-tutorial-card">
                    <div class="assistant-tutorial-topline">
                        <span class="assistant-flow-badge">${this.escapeHtml(message.tutorial.flowLabel || '')}</span>
                        <span class="assistant-step-badge">Step ${Number(message.tutorial.stepNumber || 1)} of ${Number(message.tutorial.totalSteps || 1)}</span>
                    </div>
                    <h4>${this.escapeHtml(message.tutorial.title || '')}</h4>
                    <p>${this.escapeHtml(message.tutorial.summary || '')}</p>
                    <ul class="assistant-bullet-list">${(message.tutorial.bullets || []).map((item) => `<li>${this.escapeHtml(item)}</li>`).join('')}</ul>
                    <div class="assistant-caution">${this.escapeHtml(message.tutorial.caution || '')}</div>
                </div>
            `
            : '';

        const metricsHtml = Array.isArray(message.metrics) && message.metrics.length
            ? `<div class="assistant-metric-grid">${message.metrics.map((metric) => `
                <article class="assistant-metric-card">
                    <span class="assistant-metric-label">${this.escapeHtml(metric.label || '')}</span>
                    <strong>${this.escapeHtml(metric.value || '')}</strong>
                    <span class="assistant-metric-note">${this.escapeHtml(metric.note || '')}</span>
                </article>
            `).join('')}</div>`
            : '';

        return `
            <article class="assistant-message assistant-message-${message.role}">
                <div class="assistant-bubble">
                    <p>${this.escapeHtml(message.text)}</p>
                    ${tutorialHtml}
                    ${metricsHtml}
                    ${bulletsHtml}
                    ${docsHtml}
                    ${actionsHtml}
                </div>
            </article>
        `;
    },

    async handleSubmit() {
        const raw = String(this.ui.input.value || '').trim();
        if (!raw) return;
        this.ui.input.value = '';
        this.autosizeInput();
        this.pushMessage({
            role: 'user',
            text: raw
        });
        const session = this.getActiveSession();
        if (session) {
            session.context.lastUserPrompt = raw;
            if (session.title === 'New session' || session.title === 'Getting started') {
                session.title = this.deriveSessionTitle(raw);
            }
        }
        this.renderSessionRail();
        this.saveState();
        await this.answer(raw);
    },

    async answer(raw) {
        const query = this.normalizeText(raw);
        const session = this.getActiveSession();
        if (!session) return;
        const exportIntent = this.isExportIntent(query);
        const docsIntent = this.isDocsIntent(query);

        if (!docsIntent) {
            session.context.lastDocsQuery = '';
            session.context.lastDocsResults = [];
        }
        if (!exportIntent) {
            session.context.lastExportKind = '';
        }

        if (exportIntent) {
            await this.handleExportIntent(raw, query);
            return;
        }

        if (this.isOverviewIntent(query)) {
            await this.handleOverviewIntent();
            return;
        }

        if (this.isTutorialIntent(query)) {
            this.handleTutorialIntent(query);
            return;
        }

        if (docsIntent) {
            this.handleDocsSearch(raw);
            return;
        }

        const destination = this.resolveDestination(query);
        if (destination) {
            this.handleDestination(destination);
            return;
        }

        const explanation = this.resolveExplanation(query);
        if (explanation) {
            this.pushMessage({
                role: 'assistant',
                text: explanation.text,
                actions: explanation.actions || []
            });
            return;
        }

        this.handleDocsSearch(raw);
    },

    isDocsIntent(query) {
        return /\b(docs|documentation|manual|handbook|faq|guide)\b/.test(query)
            || query.startsWith('find ')
            || query.startsWith('search ');
    },

    handleDocsSearch(raw) {
        const session = this.getActiveSession();
        if (!session) return;
        const docs = this.searchDocs(raw);
        session.context.lastDocsQuery = raw;
        session.context.lastDocsResults = docs.map((doc) => ({
            id: doc.id,
            title: doc.title,
            pageKey: doc.pageKey || '',
            stageKey: doc.stageKey || '',
            tutorialFlow: doc.tutorialFlow || '',
            tutorialStep: Number(doc.tutorialStep || 0)
        }));

        if (!docs.length) {
            this.pushMessage({
                role: 'assistant',
                text: 'I could not find a close handbook match for that yet. Try asking about tags, local mode checkup, reports, exports, voice alerts, or cloud/local tutorials.',
                actions: [
                    { type: 'handbook', label: 'Open handbook', pageKey: 'intro' },
                    { type: 'tutorial', label: 'Show cloud tutorial', flow: 'cloud', stepIndex: 0 }
                ]
            });
            return;
        }

        const actions = docs.map((doc) => ({
            type: 'doc-result',
            label: doc.title,
            pageKey: doc.pageKey || 'intro',
            stageKey: doc.stageKey || '',
            tutorialFlow: doc.tutorialFlow || '',
            tutorialStep: Number(doc.tutorialStep || 0)
        }));

        this.pushMessage({
            role: 'assistant',
            text: docs.length === 1
                ? 'I found the closest handbook match for that request.'
                : `I found ${docs.length} handbook matches for that request.`,
            docs: docs.map((doc, index) => ({
                label: doc.label,
                title: doc.title,
                snippet: doc.snippet,
                actionIndex: index
            })),
            actions
        });
    },

    isExportIntent(query) {
        return /\b(export|download|csv)\b/.test(query);
    },

    isOverviewIntent(query) {
        return /\b(overview|summary|metrics|status|health|analytics snapshot)\b/.test(query);
    },

    isTutorialIntent(query) {
        return /\b(tutorial|walkthrough|demo|guide|next step|previous step|prev step|continue tutorial|cloud mode|local mode)\b/.test(query);
    },

    async handleExportIntent(raw, query) {
        if (/\b(analytics|metrics|overview)\b/.test(query)) {
            const outcome = await this.exportAnalyticsCsv();
            this.pushMessage({
                role: 'assistant',
                text: outcome.success
                    ? `Analytics CSV is ready. I exported ${outcome.rowCount} rows of summary metrics.`
                    : outcome.message,
                actions: [
                    { type: 'route', label: 'Open Analytics', page: 'analytics' }
                ]
            });
            return;
        }

        if (/\b(docs|manual|handbook|documentation)\b/.test(query)) {
            const outcome = await this.exportDocsCsv(raw);
            this.pushMessage({
                role: 'assistant',
                text: outcome.success
                    ? `Documentation CSV is ready. I exported ${outcome.rowCount} handbook matches.`
                    : outcome.message,
                actions: [
                    { type: 'handbook', label: 'Open handbook', pageKey: 'intro' }
                ]
            });
            return;
        }

        const outcome = await this.exportReportsCsv(raw);
        this.pushMessage({
            role: 'assistant',
            text: outcome.success
                ? `Reports CSV is ready. I exported ${outcome.rowCount} report rows${outcome.filterSummary ? ` using ${outcome.filterSummary}` : ''}.`
                : outcome.message,
            actions: [
                { type: 'route', label: 'Open Reports', page: 'reports' },
                { type: 'overview', label: 'System overview' }
            ]
        });
    },

    async handleOverviewIntent() {
        const payload = await this.fetchOverview();
        if (!payload.success) {
            this.pushMessage({
                role: 'assistant',
                text: payload.message
            });
            return;
        }
        this.pushMessage({
            role: 'assistant',
            text: 'Here is the current pipeline snapshot I pulled from the app data.',
            metrics: payload.metrics,
            actions: [
                { type: 'route', label: 'Open Analytics', page: 'analytics' },
                { type: 'export', label: 'Export analytics CSV', exportKind: 'analytics' }
            ]
        });
    },

    handleTutorialIntent(query) {
        const session = this.getActiveSession();
        if (!session) return;
        const flow = /\blocal\b/.test(query)
            ? 'local'
            : /\bcloud\b/.test(query)
                ? 'cloud'
                : session.context.tutorialFlow || 'cloud';
        const steps = (window.CASM_TUTORIAL_FLOWS && window.CASM_TUTORIAL_FLOWS[flow]) || [];
        if (!steps.length) {
            this.pushMessage({
                role: 'assistant',
                text: 'Tutorial data is unavailable right now.'
            });
            return;
        }

        let index = Number(session.context.tutorialIndex || 0);
        if (/\b(start over|restart|first step)\b/.test(query)) {
            index = 0;
        } else if (/\b(previous step|prev step|back)\b/.test(query)) {
            index = Math.max(0, index - 1);
        } else if (/\b(next step|continue|next)\b/.test(query)) {
            index = Math.min(steps.length - 1, index + 1);
        } else if (flow !== session.context.tutorialFlow) {
            index = 0;
        }

        session.context.tutorialFlow = flow;
        session.context.tutorialIndex = index;
        const step = steps[index];

        this.pushMessage({
            role: 'assistant',
            text: `${flow === 'local' ? 'Local' : 'Cloud'} tutorial loaded.`,
            tutorial: {
                flowLabel: flow === 'local' ? 'Local Pipeline' : 'Cloud Pipeline',
                stepNumber: index + 1,
                totalSteps: steps.length,
                title: step.title,
                summary: step.summary,
                bullets: step.bullets || [],
                caution: step.caution
            },
            actions: [
                { type: 'tutorial', label: 'Previous step', flow, stepIndex: Math.max(0, index - 1) },
                { type: 'tutorial', label: 'Next step', flow, stepIndex: Math.min(steps.length - 1, index + 1) },
                { type: 'handbook', label: 'Open in handbook', pageKey: 'workflow', tutorialFlow: flow, tutorialStep: index }
            ]
        });
    },

    resolveDestination(query) {
        const destinations = [
            { match: /\b(settings|checkup|local mode checkup|provisioning)\b/, type: 'route', page: 'settings', label: 'Settings', focusLocalCheckup: /\bcheckup|provisioning\b/.test(query) },
            { match: /\b(report|reports)\b/, type: 'route', page: 'reports', label: 'Reports' },
            { match: /\b(analytics|stats|metrics dashboard)\b/, type: 'route', page: 'analytics', label: 'Analytics' },
            { match: /\b(live|monitor|camera)\b/, type: 'route', page: 'live', label: 'Live Monitor' },
            { match: /\b(about page|system architecture|architecture)\b/, type: 'route', page: 'about', label: 'About' },
            { match: /\b(home|dashboard)\b/, type: 'route', page: 'home', label: 'Home' },
            { match: /\b(handbook|manual|documentation)\b/, type: 'handbook', pageKey: 'intro', label: 'Manual Handbook' },
            { match: /\b(notification|alert history)\b/, type: 'handbook', pageKey: 'notifications', label: 'Notification handbook' },
            { match: /\b(voice|audio)\b/, type: 'handbook', pageKey: 'alerts', label: 'Voice alerts handbook' },
            { match: /\b(admin|device|approve|provision)\b/, type: 'handbook', pageKey: 'admin', label: 'Admin and devices' }
        ];
        return destinations.find((item) => item.match.test(query)) || null;
    },

    handleDestination(destination) {
        if (destination.type === 'route') {
            const targetPage = destination.focusLocalCheckup ? 'settings-checkup' : destination.page;
            Router.navigate(targetPage);
        } else if (destination.type === 'handbook' && window.CASMHandbook && typeof window.CASMHandbook.open === 'function') {
            window.CASMHandbook.open(destination.pageKey || 'intro', {
                stage: destination.stageKey || '',
                tutorialFlow: destination.tutorialFlow || '',
                tutorialStep: Number(destination.tutorialStep || 0)
            });
        }
        this.pushMessage({
            role: 'assistant',
            text: `${destination.label} is open now.`,
            actions: destination.type === 'route'
                ? [{
                    type: 'route',
                    label: `Go to ${destination.label}`,
                    page: destination.page,
                    focusLocalCheckup: !!destination.focusLocalCheckup
                }]
                : [{ type: 'handbook', label: 'Open handbook', pageKey: destination.pageKey || 'intro' }]
        });
    },

    resolveExplanation(query) {
        const explanations = [
            {
                match: /\b(local synced|synced local)\b/,
                text: 'Local Synced means the report was generated from a local-origin run and only changed to synced after connectivity returned and upload evidence was confirmed.',
                actions: [
                    { type: 'handbook', label: 'Open report tags section', pageKey: 'workflow', stageKey: 'reports' },
                    { type: 'tutorial', label: 'Show local recovery steps', flow: 'local', stepIndex: 3 }
                ]
            },
            {
                match: /\bcloud tag|cloud report|cloud mode\b/,
                text: 'Cloud mode should keep a Cloud source tag end to end. It uses the remote report path and should not flip to Local Synced unless the report actually began as a local-origin run.',
                actions: [
                    { type: 'tutorial', label: 'Show cloud tutorial', flow: 'cloud', stepIndex: 2 },
                    { type: 'route', label: 'Open Reports', page: 'reports' }
                ]
            },
            {
                match: /\blocal mode\b/,
                text: 'Local mode runs the approved host pipeline directly on the machine. While Wi-Fi is down, locally generated reports stay Local. Only after reconnect and verified upload should they become Local Synced.',
                actions: [
                    { type: 'tutorial', label: 'Show local tutorial', flow: 'local', stepIndex: 0 },
                    { type: 'route', label: 'Open settings checkup', page: 'settings', focusLocalCheckup: true }
                ]
            },
            {
                match: /\bcaption|gemini|gemma\b/,
                text: 'Cloud captioning uses the cloud vision path for fast remote report generation. Local captioning stays on the host path, so it avoids Supabase egress for caption work but can take longer on a cold model.',
                actions: [
                    { type: 'tutorial', label: 'Cloud generation step', flow: 'cloud', stepIndex: 2 },
                    { type: 'tutorial', label: 'Local generation step', flow: 'local', stepIndex: 2 }
                ]
            },
            {
                match: /\bcheckup|readiness|provisioning\b/,
                text: 'Local Mode Checkup verifies machine approval, local backend health, camera readiness, and model availability before you rely on local generation.',
                actions: [
                    { type: 'route', label: 'Open settings checkup', page: 'settings', focusLocalCheckup: true },
                    { type: 'handbook', label: 'Open local mode guide', pageKey: 'workflow', stageKey: 'local' }
                ]
            }
        ];
        return explanations.find((item) => item.match.test(query)) || null;
    },

    async performAction(action) {
        if (!action || !action.type) return;
        switch (action.type) {
            case 'route': {
                const page = action.focusLocalCheckup ? 'settings-checkup' : action.page;
                Router.navigate(page || 'home');
                return;
            }
            case 'handbook': {
                if (window.CASMHandbook && typeof window.CASMHandbook.open === 'function') {
                    window.CASMHandbook.open(action.pageKey || 'intro', {
                        stage: action.stageKey || '',
                        tutorialFlow: action.tutorialFlow || '',
                        tutorialStep: Number(action.tutorialStep || 0)
                    });
                }
                return;
            }
            case 'tutorial': {
                const session = this.getActiveSession();
                if (session) {
                    session.context.tutorialFlow = action.flow === 'local' ? 'local' : 'cloud';
                    session.context.tutorialIndex = Math.max(0, Number(action.stepIndex || 0));
                    this.saveState();
                }
                this.handleTutorialIntent(`${action.flow || 'cloud'} tutorial`);
                return;
            }
            case 'export': {
                if (action.exportKind === 'analytics') {
                    await this.handleExportIntent('export analytics csv', 'export analytics csv');
                } else {
                    await this.handleExportIntent('export reports csv', 'export reports csv');
                }
                return;
            }
            case 'overview': {
                await this.handleOverviewIntent();
                return;
            }
            case 'doc-result': {
                if (window.CASMHandbook && typeof window.CASMHandbook.open === 'function') {
                    window.CASMHandbook.open(action.pageKey || 'intro', {
                        stage: action.stageKey || '',
                        tutorialFlow: action.tutorialFlow || '',
                        tutorialStep: Number(action.tutorialStep || 0)
                    });
                }
                return;
            }
            default:
                return;
        }
    },

    handleActionClick(event) {
        const promptButton = event.target.closest('[data-prompt-index]');
        if (promptButton) {
            const index = Number(promptButton.dataset.promptIndex || -1);
            if (Number.isFinite(index) && this.promptActions && this.promptActions[index]) {
                this.runSuggestedPrompt(this.promptActions[index].prompt || '');
            }
            return;
        }

        const shortcutButton = event.target.closest('[data-shortcut-index]');
        if (shortcutButton) {
            const index = Number(shortcutButton.dataset.shortcutIndex || -1);
            if (Number.isFinite(index) && this.shortcutActions && this.shortcutActions[index]) {
                this.performAction(this.shortcutActions[index]);
            }
            return;
        }

        const actionButton = event.target.closest('[data-message-id][data-action-index]');
        if (!actionButton) return;
        const messageId = String(actionButton.dataset.messageId || '');
        const actionIndex = Number(actionButton.dataset.actionIndex || -1);
        const session = this.getActiveSession();
        if (!session) return;
        const message = session.messages.find((item) => item.id === messageId);
        if (!message || !Array.isArray(message.actions) || !message.actions[actionIndex]) return;
        this.performAction(message.actions[actionIndex]);
    },

    handleSessionRailClick(event) {
        const button = event.target.closest('[data-session-id]');
        if (!button) return;
        this.setActiveSession(button.dataset.sessionId || '');
    },

    async runSuggestedPrompt(prompt) {
        const text = String(prompt || '').trim();
        if (!text) return;
        this.ui.input.value = text;
        this.autosizeInput();
        await this.handleSubmit();
    },

    pushMessage(message) {
        const session = this.getActiveSession();
        if (!session) return;
        const normalized = this.normalizeMessage({
            ...message,
            id: message.id || `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            createdAt: message.createdAt || Date.now()
        });
        session.messages.push(normalized);
        session.messages = session.messages.slice(-this.MAX_MESSAGES);
        session.updatedAt = Date.now();
        this.renderMessages();
        this.renderSessionRail();
        this.saveState();
    },

    buildDocsIndex() {
        const entries = [];
        const pages = Array.from(document.querySelectorAll('#handbookModal .handbook-page'));
        pages.forEach((page) => {
            const pageKey = String(page.id || '').replace('handbook-', '');
            const titleNode = page.querySelector('h3');
            const title = String(titleNode?.textContent || pageKey || 'Handbook').trim();
            const text = this.compactText(page.innerText || page.textContent || '');
            if (text) {
                entries.push({
                    id: `page-${pageKey}`,
                    label: 'Handbook',
                    title,
                    text,
                    pageKey,
                    keywords: [pageKey, title]
                });
            }
        });

        Array.from(document.querySelectorAll('#handbook-workflow [data-stage-panel]')).forEach((panel) => {
            const stageKey = String(panel.dataset.stagePanel || '').trim();
            const title = String(panel.querySelector('h4')?.textContent || stageKey || 'Workflow').trim();
            const text = this.compactText(panel.innerText || panel.textContent || '');
            if (text) {
                entries.push({
                    id: `workflow-${stageKey}`,
                    label: 'Workflow stage',
                    title,
                    text,
                    pageKey: 'workflow',
                    stageKey,
                    keywords: ['workflow', 'tutorial', stageKey]
                });
            }
        });

        const tutorialFlows = window.CASM_TUTORIAL_FLOWS || {};
        Object.keys(tutorialFlows).forEach((flowKey) => {
            const steps = tutorialFlows[flowKey] || [];
            steps.forEach((step, index) => {
                entries.push({
                    id: `tutorial-${flowKey}-${index}`,
                    label: flowKey === 'local' ? 'Local tutorial' : 'Cloud tutorial',
                    title: step.title,
                    text: this.compactText([step.summary, step.caution, ...(step.bullets || [])].join(' ')),
                    pageKey: 'workflow',
                    tutorialFlow: flowKey,
                    tutorialStep: index,
                    keywords: [flowKey, step.tag, 'tutorial', 'walkthrough']
                });
            });
        });

        const glossary = [
            {
                id: 'glossary-tags',
                label: 'Glossary',
                title: 'Report source tags',
                text: 'Cloud reports stay Cloud. Local reports stay Local while connectivity is absent. After verified reconnect upload, a local-origin report becomes Local Synced.',
                pageKey: 'workflow',
                stageKey: 'reports',
                keywords: ['tag', 'cloud', 'local', 'local synced', 'source']
            },
            {
                id: 'glossary-checkup',
                label: 'Glossary',
                title: 'Local mode checkup',
                text: 'The local readiness check verifies provider routing, machine approval, local backend health, camera readiness, and model availability before a local run starts.',
                pageKey: 'workflow',
                stageKey: 'local',
                keywords: ['checkup', 'local mode', 'readiness', 'provisioning']
            },
            {
                id: 'glossary-assistant',
                label: 'Assistant',
                title: 'Assistant shortcuts and exports',
                text: 'The assistant can open app pages, jump into handbook sections, guide tutorial steps in chat, export reports CSV, export analytics CSV, and remember previous sessions locally in the browser.',
                pageKey: 'intro',
                keywords: ['assistant', 'export', 'csv', 'session', 'shortcut']
            }
        ];

        return entries.concat(glossary);
    },

    searchDocs(rawQuery) {
        const query = this.normalizeText(rawQuery);
        const tokens = this.expandTokens(this.tokenize(query));
        return this.docsIndex
            .map((entry) => {
                const haystack = this.normalizeText(`${entry.title} ${entry.text} ${(entry.keywords || []).join(' ')}`);
                let score = 0;
                tokens.forEach((token) => {
                    if (this.normalizeText(entry.title).includes(token)) score += 7;
                    if ((entry.keywords || []).some((keyword) => this.normalizeText(keyword).includes(token))) score += 4;
                    if (haystack.includes(token)) score += 2;
                });
                if (query && haystack.includes(query)) score += 10;
                return {
                    ...entry,
                    score,
                    snippet: this.buildSnippet(entry.text, tokens)
                };
            })
            .filter((entry) => entry.score > 0)
            .sort((a, b) => b.score - a.score)
            .slice(0, 4);
    },

    expandTokens(tokens) {
        const synonyms = {
            wifi: ['network', 'reconnect', 'offline'],
            cloud: ['remote', 'supabase'],
            local: ['offline', 'host'],
            report: ['reports', 'badge', 'tag'],
            caption: ['gemini', 'gemma'],
            tutorial: ['guide', 'walkthrough', 'demo'],
            export: ['csv', 'download']
        };
        const expanded = new Set(tokens);
        tokens.forEach((token) => {
            (synonyms[token] || []).forEach((value) => expanded.add(value));
        });
        return Array.from(expanded);
    },

    buildSnippet(text, tokens) {
        const source = String(text || '').trim();
        if (!source) return '';
        if (!tokens.length) return source.slice(0, 180);
        const normalized = this.normalizeText(source);
        const match = tokens.find((token) => normalized.includes(token));
        if (!match) return source.slice(0, 180);
        const start = Math.max(0, normalized.indexOf(match) - 56);
        const snippet = source.slice(start, start + 180).trim();
        return snippet.length < source.length ? `${snippet}...` : snippet;
    },

    async fetchOverview() {
        try {
            const [stats, violations] = await Promise.all([
                API.getStats(),
                API.getViolations()
            ]);
            const normalizedStats = AnalyticsPage.normalizeStats(stats, violations);
            const derived = AnalyticsPage.buildDerivedMetrics(normalizedStats, violations);
            return {
                success: true,
                metrics: [
                    { label: 'Ready rate', value: `${derived.readyRate}%`, note: `${normalizedStats.reportsGenerated} reports ready` },
                    { label: 'Pending', value: String(derived.pending), note: 'Queued or generating now' },
                    { label: 'Local-origin', value: String(derived.localOriginCount), note: `${derived.sourceMix.synced_local} already synced` },
                    { label: 'Cloud-origin', value: String(derived.cloudOriginCount), note: `${derived.dominantSource.replace(/_/g, ' ')} currently leads` },
                    { label: 'Top type', value: derived.topType, note: `Peak window: ${derived.peakWindow}` },
                    { label: 'Last violation', value: derived.lastViolationDisplay, note: `${derived.recentWeekCount} in the last 7 days` }
                ]
            };
        } catch (error) {
            console.error('Assistant overview fetch failed:', error);
            return {
                success: false,
                message: 'I could not fetch the current pipeline metrics right now.'
            };
        }
    },

    async exportReportsCsv(rawQuery = '') {
        try {
            const rows = await API.getViolations({ limit: 1000 });
            const filters = this.buildReportFilters(rawQuery);
            const filtered = (rows || []).filter((row) => this.matchesReportFilters(row, filters));
            if (!filtered.length) {
                return {
                    success: false,
                    message: 'No report rows matched that export request.'
                };
            }
            const headers = [
                'report_id',
                'timestamp',
                'status',
                'severity',
                'device_id',
                'violation_count',
                'missing_ppe',
                'source_scope',
                'source_label',
                'violation_summary'
            ];
            const lines = [headers.join(',')];
            filtered.forEach((row) => {
                const missing = Array.isArray(row.missing_ppe) ? row.missing_ppe.join('; ') : '';
                const values = [
                    row.report_id,
                    row.timestamp,
                    row.status,
                    row.severity,
                    row.device_id,
                    row.violation_count,
                    missing,
                    row.source_scope,
                    row.source_label,
                    row.violation_summary
                ];
                lines.push(values.map((value) => this.escapeCsv(value)).join(','));
            });
            this.downloadCsv(`casm-assistant-reports-${this.buildTimestampToken()}.csv`, '\uFEFF' + lines.join('\r\n'));
            const summary = this.describeReportFilters(filters);
            const session = this.getActiveSession();
            if (session) session.context.lastExportKind = 'reports';
            return {
                success: true,
                rowCount: filtered.length,
                filterSummary: summary
            };
        } catch (error) {
            console.error('Assistant reports CSV export failed:', error);
            return {
                success: false,
                message: 'Reports CSV export failed.'
            };
        }
    },

    buildReportFilters(rawQuery = '') {
        const query = this.normalizeText(rawQuery);
        return {
            source: /\blocal synced\b/.test(query)
                ? 'synced_local'
                : /\blocal\b/.test(query) && !/\blocal synced\b/.test(query)
                    ? 'local'
                    : /\bcloud\b/.test(query)
                        ? 'cloud'
                        : '',
            severity: /\bhigh\b/.test(query)
                ? 'high'
                : /\bmedium\b/.test(query)
                    ? 'medium'
                    : /\blow\b/.test(query)
                        ? 'low'
                        : '',
            dateRange: /\btoday\b/.test(query)
                ? 'today'
                : /\bweek\b/.test(query)
                    ? 'week'
                    : /\bmonth\b/.test(query)
                        ? 'month'
                        : '',
            searchTokens: this.tokenize(query)
                .filter((token) => ![
                    'export', 'download', 'csv', 'reports', 'report', 'analytics', 'local', 'cloud', 'synced',
                    'today', 'week', 'month', 'high', 'medium', 'low'
                ].includes(token))
        };
    },

    matchesReportFilters(row, filters) {
        if (filters.source) {
            const scope = String(row?.source_scope || '').trim().toLowerCase() || String(row?.source_label || '').trim().toLowerCase().replace(/\s+/g, '_');
            if (filters.source === 'cloud' && scope !== 'cloud') return false;
            if (filters.source === 'local' && scope !== 'local') return false;
            if (filters.source === 'synced_local' && scope !== 'synced_local') return false;
        }

        if (filters.severity) {
            const severity = String(row?.severity || '').trim().toLowerCase();
            if (severity !== filters.severity) return false;
        }

        if (filters.dateRange) {
            const rowDate = new Date(row?.timestamp || 0);
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            if (filters.dateRange === 'today' && rowDate < today) return false;
            if (filters.dateRange === 'week') {
                const weekAgo = new Date(today);
                weekAgo.setDate(weekAgo.getDate() - 7);
                if (rowDate < weekAgo) return false;
            }
            if (filters.dateRange === 'month') {
                const monthAgo = new Date(today);
                monthAgo.setMonth(monthAgo.getMonth() - 1);
                if (rowDate < monthAgo) return false;
            }
        }

        if (Array.isArray(filters.searchTokens) && filters.searchTokens.length) {
            const haystack = this.normalizeText([
                row?.report_id,
                row?.device_id,
                row?.timestamp,
                row?.violation_summary,
                Array.isArray(row?.missing_ppe) ? row.missing_ppe.join(' ') : ''
            ].join(' '));
            if (!filters.searchTokens.every((token) => haystack.includes(token))) return false;
        }

        return true;
    },

    describeReportFilters(filters) {
        const parts = [];
        if (filters.source === 'cloud') parts.push('cloud rows');
        if (filters.source === 'local') parts.push('local rows');
        if (filters.source === 'synced_local') parts.push('local-synced rows');
        if (filters.severity) parts.push(`${filters.severity} severity`);
        if (filters.dateRange) parts.push(filters.dateRange);
        return parts.join(', ');
    },

    async exportAnalyticsCsv() {
        try {
            const [stats, violations] = await Promise.all([
                API.getStats(),
                API.getViolations()
            ]);
            const normalizedStats = AnalyticsPage.normalizeStats(stats, violations);
            const derived = AnalyticsPage.buildDerivedMetrics(normalizedStats, violations);
            const lines = [
                'metric,value,note',
                ['total_violations', normalizedStats.total, 'Current total rows'],
                ['reports_ready', normalizedStats.reportsGenerated, 'Completed or ready reports'],
                ['pending_reports', derived.pending, 'Queued, pending, or generating'],
                ['ready_rate_percent', `${derived.readyRate}%`, 'Ready rows share'],
                ['high_severity_share_percent', `${derived.highShare}%`, 'High severity share'],
                ['local_origin_runs', derived.localOriginCount, 'Local plus synced-local'],
                ['cloud_origin_runs', derived.cloudOriginCount, 'Cloud plus shared'],
                ['peak_window', derived.peakWindow, `${derived.peakWindowCount} rows`],
                ['top_violation_type', derived.topType, 'Most frequent breakdown item'],
                ['last_violation_seen', derived.lastViolationDisplay, 'Most recent timestamp'],
                ['seven_day_daily_average', derived.dailyAverage.toFixed(1), `${derived.recentWeekCount} last-week rows`]
            ].map((row, index) => index === 0 ? row : row.map((cell) => this.escapeCsv(cell)).join(','));
            this.downloadCsv(`casm-assistant-analytics-${this.buildTimestampToken()}.csv`, '\uFEFF' + lines.join('\r\n'));
            const session = this.getActiveSession();
            if (session) session.context.lastExportKind = 'analytics';
            return {
                success: true,
                rowCount: lines.length - 1
            };
        } catch (error) {
            console.error('Assistant analytics CSV export failed:', error);
            return {
                success: false,
                message: 'Analytics CSV export failed.'
            };
        }
    },

    async exportDocsCsv(rawQuery = '') {
        const results = this.searchDocs(rawQuery);
        if (!results.length) {
            return {
                success: false,
                message: 'No handbook results matched that documentation export request.'
            };
        }
        const lines = [
            'label,title,page,section,snippet',
            ...results.map((entry) => [
                entry.label,
                entry.title,
                entry.pageKey || '',
                entry.stageKey || entry.tutorialFlow || '',
                entry.snippet || entry.text || ''
            ].map((cell) => this.escapeCsv(cell)).join(','))
        ];
        this.downloadCsv(`casm-assistant-docs-${this.buildTimestampToken()}.csv`, '\uFEFF' + lines.join('\r\n'));
        return {
            success: true,
            rowCount: results.length
        };
    },

    downloadCsv(filename, content) {
        const blob = new Blob([String(content || '')], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        if (typeof notifyApp === 'function') {
            notifyApp(`Downloaded ${filename}.`, 'success');
        }
    },

    ensureClientIdentity() {
        const randomToken = (size = 16) => {
            try {
                if (window.crypto && typeof window.crypto.getRandomValues === 'function') {
                    const bytes = new Uint8Array(size);
                    window.crypto.getRandomValues(bytes);
                    return Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
                }
            } catch (_) {
                // Fall through to Math.random.
            }
            return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 2 + size)}`;
        };

        let clientId = '';
        let syncSecret = '';
        try { clientId = String(localStorage.getItem(this.CLIENT_ID_KEY) || '').trim(); } catch (_) {}
        try { syncSecret = String(localStorage.getItem(this.SYNC_SECRET_KEY) || '').trim(); } catch (_) {}

        if (!clientId) {
            clientId = `assistant-${randomToken(12)}`;
            try { localStorage.setItem(this.CLIENT_ID_KEY, clientId); } catch (_) {}
        }
        if (!syncSecret) {
            syncSecret = randomToken(24);
            try { localStorage.setItem(this.SYNC_SECRET_KEY, syncSecret); } catch (_) {}
        }

        let machineId = '';
        try {
            if (typeof getOrCreateDeviceMachineId === 'function') {
                machineId = String(getOrCreateDeviceMachineId() || '').trim();
            } else {
                machineId = String(localStorage.getItem('ppe.localMode.deviceMachineId.v1') || '').trim();
            }
        } catch (_) {
            machineId = '';
        }

        return {
            clientId,
            syncSecret,
            machineId,
            browserLabel: String((navigator && navigator.userAgent) || '').slice(0, 180)
        };
    },

    queueAdminSync() {
        if (this.syncTimer) {
            window.clearTimeout(this.syncTimer);
        }
        this.syncTimer = window.setTimeout(() => {
            this.syncTimer = null;
            this.syncSessionsToAdminLog();
        }, 900);
    },

    buildSyncPayload() {
        const identity = this.clientIdentity || this.ensureClientIdentity();
        const sessions = this.sessions.slice(0, this.MAX_SESSIONS).map((session) => ({
            id: String(session.id || ''),
            title: String(session.title || '').slice(0, 120),
            created_at: Number(session.createdAt || Date.now()),
            updated_at: Number(session.updatedAt || Date.now()),
            context: {
                tutorial_flow: String(session?.context?.tutorialFlow || 'cloud'),
                tutorial_index: Math.max(0, Number(session?.context?.tutorialIndex || 0)),
                recent_pages: Array.isArray(session?.context?.recentPages) ? session.context.recentPages.slice(0, 8) : [],
                last_docs_query: String(session?.context?.lastDocsQuery || '').slice(0, 200),
                last_export_kind: String(session?.context?.lastExportKind || '').slice(0, 40)
            },
            messages: (Array.isArray(session.messages) ? session.messages : []).slice(-this.MAX_MESSAGES).map((message) => ({
                id: String(message.id || ''),
                role: String(message.role || 'assistant'),
                text: String(message.text || '').slice(0, 1600),
                created_at: Number(message.createdAt || Date.now())
            }))
        }));

        return {
            client_id: identity.clientId,
            machine_id: identity.machineId,
            sync_secret: identity.syncSecret,
            browser_label: identity.browserLabel,
            active_session_id: this.activeSessionId,
            current_page: String((APP_STATE && APP_STATE.currentPage) || 'home'),
            sessions
        };
    },

    async syncSessionsToAdminLog() {
        if (this.syncInFlight) {
            this.syncQueued = true;
            return;
        }
        this.syncInFlight = true;
        try {
            const payload = this.buildSyncPayload();
            const baseUrl = (typeof API_CONFIG !== 'undefined' && API_CONFIG && API_CONFIG.BASE_URL) ? API_CONFIG.BASE_URL : '';
            const response = await fetch(`${baseUrl}/api/assistant/sessions/sync`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
                cache: 'no-store'
            });
            if (!response.ok) {
                console.debug('Assistant session sync skipped:', response.status);
            }
        } catch (error) {
            console.debug('Assistant session sync failed:', error);
        } finally {
            this.syncInFlight = false;
            if (this.syncQueued) {
                this.syncQueued = false;
                this.queueAdminSync();
            }
        }
    },

    trackRoute(page) {
        const session = this.getActiveSession();
        if (!session) return;
        const recentPages = Array.isArray(session.context.recentPages) ? session.context.recentPages : [];
        const nextPages = [page, ...recentPages.filter((entry) => entry !== page)].slice(0, 8);
        session.context.recentPages = nextPages;
        session.updatedAt = Date.now();
        this.saveState();
        this.renderPromptDeck();
    },

    deriveSessionTitle(prompt) {
        const compact = String(prompt || '').replace(/\s+/g, ' ').trim();
        if (!compact) return 'New session';
        const words = compact.split(' ').slice(0, 6).join(' ');
        return words.length > 42 ? `${words.slice(0, 39)}...` : words;
    },

    autosizeInput() {
        if (!this.ui.input) return;
        this.ui.input.style.height = 'auto';
        const next = Math.min(this.ui.input.scrollHeight, 132);
        this.ui.input.style.height = `${Math.max(46, next)}px`;
    },

    scrollMessagesToBottom() {
        if (!this.ui.messages) return;
        this.ui.messages.scrollTop = this.ui.messages.scrollHeight;
    },

    buildTimestampToken() {
        return new Date().toISOString().replace(/[:.]/g, '-');
    },

    formatRelativeTime(epochMs) {
        const delta = Math.max(0, Date.now() - Number(epochMs || 0));
        if (delta < 60 * 1000) return 'Just now';
        if (delta < 60 * 60 * 1000) return `${Math.round(delta / 60000)} min ago`;
        if (delta < 24 * 60 * 60 * 1000) return `${Math.round(delta / 3600000)} hr ago`;
        return `${Math.round(delta / 86400000)} day ago`;
    },

    normalizeText(value) {
        return String(value || '')
            .toLowerCase()
            .replace(/[^a-z0-9\s-]/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    },

    compactText(value) {
        return String(value || '').replace(/\s+/g, ' ').trim();
    },

    tokenize(value) {
        const stopWords = new Set(['the', 'and', 'for', 'with', 'that', 'this', 'from', 'into', 'what', 'when', 'where', 'which', 'show', 'open', 'give', 'tell', 'about', 'please', 'help']);
        return this.normalizeText(value)
            .split(' ')
            .map((token) => token.trim())
            .filter((token) => token.length > 1 && !stopWords.has(token));
    },

    escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },

    escapeCsv(value) {
        const normalized = String(value === null || value === undefined ? '' : value).replace(/\r?\n/g, ' ');
        return /[",]/.test(normalized)
            ? `"${normalized.replace(/"/g, '""')}"`
            : normalized;
    }
};

document.addEventListener('DOMContentLoaded', () => {
    CASMAssistant.init();
    window.CASMAssistant = CASMAssistant;
});
