const CASMAssistant = {
    ASSISTANT_NAME: 'Mira',
    ASSISTANT_ROLE: 'CASM Safety Copilot',
    ASSISTANT_SUBTITLE: 'Chat for tutorials, camera help, image checks, exports, settings, and system questions.',
    STORAGE_KEY: 'casm.assistant.sessions.v1',
    PANEL_STATE_KEY: 'casm.assistant.panelState.v1',
    CLIENT_ID_KEY: 'casm.assistant.clientId.v1',
    SYNC_SECRET_KEY: 'casm.assistant.syncSecret.v1',
    UNMATCHED_PROMPTS_KEY: 'casm.assistant.unmatchedPrompts.v1',
    MAX_SESSIONS: 14,
    MAX_MESSAGES: 80,
    MAX_UNMATCHED_PROMPTS: 60,
    sessions: [],
    activeSessionId: '',
    docsIndex: [],
    panelOpen: false,
    railOpen: false,
    clientIdentity: null,
    syncTimer: null,
    syncInFlight: false,
    syncQueued: false,
    isResponding: false,
    activeResponseJobId: 0,
    responseFeedbackText: 'Thinking...',
    preparedCsvDownloads: {},
    ui: {},

    init() {
        this.cacheDom();
        if (!this.ui.launcher || !this.ui.panel) return;
        this.applyBranding();
        if (this.ui.input) {
            this.ui.input.setAttribute(
                'placeholder',
                `Ask ${this.ASSISTANT_NAME} something like "show local tutorial" or "export cloud reports csv"`
            );
            this.ui.input.setAttribute('aria-label', `Ask ${this.ASSISTANT_NAME}`);
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
            input: document.getElementById('assistantInput'),
            send: document.getElementById('assistantSend'),
            title: document.getElementById('assistantTitle'),
            kicker: document.getElementById('assistantKicker'),
            subtitle: document.getElementById('assistantSubtitle')
        };
    },

    applyBranding() {
        if (this.ui.launcher) {
            const label = `Open ${this.ASSISTANT_NAME} chat`;
            this.ui.launcher.setAttribute('aria-label', label);
            this.ui.launcher.setAttribute('title', label);
        }
        if (this.ui.title) {
            this.ui.title.textContent = this.ASSISTANT_NAME;
        }
        if (this.ui.kicker) {
            this.ui.kicker.textContent = this.ASSISTANT_ROLE;
        }
        if (this.ui.subtitle) {
            this.ui.subtitle.textContent = this.ASSISTANT_SUBTITLE;
        }
        if (this.ui.sessionsToggle) {
            this.ui.sessionsToggle.setAttribute('aria-label', 'Toggle assistant sessions');
        }
        if (this.ui.newSession) {
            this.ui.newSession.setAttribute('aria-label', 'Start a new assistant session');
        }
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
        this.ui.panel.addEventListener('wheel', (event) => this.handlePanelWheel(event), { passive: false });
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

    handlePanelWheel(event) {
        if (!this.panelOpen || !this.ui.messages) return;
        if (window.innerWidth <= 900) return;
        const messages = this.ui.messages;
        if (messages.scrollHeight <= messages.clientHeight + 8) return;
        const target = event.target;
        if (!(target instanceof Element)) return;
        if (
            target.closest('#assistantMessages') ||
            target.closest('#assistantInput') ||
            target.closest('.assistant-session-list') ||
            target.closest('.assistant-shortcut-strip') ||
            target.closest('.assistant-prompt-chip-row')
        ) {
            return;
        }
        messages.scrollTop += event.deltaY;
        event.preventDefault();
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
                lastUserPrompt: String(session?.context?.lastUserPrompt || ''),
                guidedFlow: session?.context?.guidedFlow && typeof session.context.guidedFlow === 'object'
                    ? {
                        kind: ['reports', 'analytics'].includes(String(session.context.guidedFlow.kind || '').trim())
                            ? String(session.context.guidedFlow.kind || '').trim()
                            : 'analytics',
                        step: String(session.context.guidedFlow.step || '').trim(),
                        awaiting: String(session.context.guidedFlow.awaiting || '').trim(),
                        filters: session.context.guidedFlow.filters && typeof session.context.guidedFlow.filters === 'object'
                            ? { ...session.context.guidedFlow.filters }
                            : {}
                    }
                    : null,
                reportReview: session?.context?.reportReview && typeof session.context.reportReview === 'object'
                    ? {
                        ...session.context.reportReview,
                        reports: Array.isArray(session.context.reportReview.reports)
                            ? session.context.reportReview.reports.slice(0, 50)
                            : []
                    }
                    : null
            },
            messages: messages.map((message) => this.normalizeMessage(message)).filter(Boolean)
        };
    },

    normalizeMessage(message) {
        if (!message || !message.id || !message.role) return null;
        return {
            id: String(message.id),
            role: this.normalizeMessageRole(message.role),
            text: String(message.text || ''),
            createdAt: Number(message.createdAt || Date.now()),
            bullets: Array.isArray(message.bullets) ? message.bullets.slice(0, 8) : [],
            actions: Array.isArray(message.actions) ? message.actions.slice(0, 8) : [],
            docs: Array.isArray(message.docs) ? message.docs.slice(0, 4) : [],
            tutorial: message.tutorial && typeof message.tutorial === 'object' ? message.tutorial : null,
            guided: message.guided && typeof message.guided === 'object' ? message.guided : null,
            reportCarousel: message.reportCarousel && typeof message.reportCarousel === 'object' ? message.reportCarousel : null,
            metrics: Array.isArray(message.metrics) ? message.metrics.slice(0, 6) : [],
            sections: Array.isArray(message.sections) ? message.sections.slice(0, 6) : []
        };
    },

    normalizeMessageRole(role) {
        const normalized = String(role || '').trim().toLowerCase();
        if (!normalized) return 'assistant';
        if (['assistant', 'mira', 'moira', 'bot', 'copilot', 'system'].includes(normalized)) {
            return 'assistant';
        }
        if (['user', 'human', 'me', 'you'].includes(normalized)) {
            return 'user';
        }
        if (normalized.includes('user') || normalized.includes('human')) {
            return 'user';
        }
        return 'assistant';
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
                lastUserPrompt: '',
                guidedFlow: null
            },
            messages: []
        };
        if (welcome) {
            session.messages.push({
                id: `msg-${Date.now()}-welcome`,
                role: 'assistant',
                text: `Hi, I'm ${this.ASSISTANT_NAME}. I can guide tutorials, explain the system, open pages or handbook sections, and export filtered CSV files from natural-language requests.`,
                createdAt: Date.now(),
                bullets: [
                    'Explain report tags, local mode checkup, cloud/local behavior, and caption flow.',
                    'Show cloud or local tutorial steps in one guided card and jump into the handbook.',
                    'Open Camera Stream or Image Analysis, then collapse so the page stays usable.',
                    'Export analytics or report CSV files from prompts like "export cloud reports csv month".',
                    'Use Guided Reports or Guided Analytics when you want step-by-step filter choices.',
                    'Session memory stays on this browser, and only admins can review synced copies.'
                ],
                actions: [
                    { type: 'guided-start', label: 'Guided Reports', guidedKind: 'reports' },
                    { type: 'guided-start', label: 'Guided Analytics', guidedKind: 'analytics' },
                    { type: 'tutorial', label: 'Cloud tutorial', flow: 'cloud', stepIndex: 0 },
                    { type: 'tutorial', label: 'Local tutorial', flow: 'local', stepIndex: 0 },
                    { type: 'route', label: 'Open camera', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true },
                    { type: 'settings-profile', label: 'Use recommended settings', profile: 'recommended' }
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
            { type: 'route', label: 'Home', icon: 'fa-home', page: 'home', prompt: 'open home' },
            { type: 'route', label: 'Camera', icon: 'fa-video', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true, prompt: 'open camera' },
            { type: 'route', label: 'Image Check', icon: 'fa-image', page: 'live', liveMode: 'upload', liveFocus: 'upload', collapsePanel: true, prompt: 'open image analysis' },
            { type: 'route', label: 'Reports', icon: 'fa-file-alt', page: 'reports', prompt: 'open reports' },
            { type: 'route', label: 'Analytics', icon: 'fa-chart-line', page: 'analytics', prompt: 'open analytics' },
            { type: 'route', label: 'Settings', icon: 'fa-sliders-h', page: 'settings', collapsePanel: true, prompt: 'open settings' },
            { type: 'tutorial', label: 'Cloud demo', icon: 'fa-cloud', flow: 'cloud', stepIndex: 0, prompt: 'show cloud tutorial' },
            { type: 'tutorial', label: 'Local demo', icon: 'fa-laptop-code', flow: 'local', stepIndex: 0, prompt: 'show local tutorial' },
            { type: 'guided-start', label: 'Report Guide', icon: 'fa-list-check', guidedKind: 'reports', prompt: 'guided reports' },
            { type: 'guided-start', label: 'Analytics Guide', icon: 'fa-chart-pie', guidedKind: 'analytics', prompt: 'guided analytics' },
            { type: 'export', label: 'Reports CSV', icon: 'fa-file-csv', exportKind: 'reports', prompt: 'export reports csv' },
            { type: 'overview', label: 'Overview', icon: 'fa-signal', exportKind: '', prompt: 'system overview' }
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
                this.buildPromptSuggestion('What is CASM?', 'what is this system for'),
                this.buildPromptSuggestion("I'm new here", 'i dont know what should i do first'),
                this.buildPromptSuggestion('Open camera', 'help me start live monitoring'),
                this.buildPromptSuggestion('Check image', 'can you check if this image has violations'),
                { type: 'guided-start', label: 'Guided Analytics', guidedKind: 'analytics' }
            ];
            return promptModel;
        }

        if (this.isOnboardingIntent(lastUserPrompt)) {
            promptModel.headline = 'Start here';
            promptModel.subline = 'If the system is new to you, these prompts walk through the safest first actions without assuming prior context.';
            promptModel.mode = 'onboarding';
            promptModel.actions = [
                this.buildPromptSuggestion('Start live monitoring', 'help me start live monitoring'),
                this.buildPromptSuggestion('Check one image', 'can you check if this image has violations'),
                this.buildPromptSuggestion('Show analytics', 'show analytics overview'),
                this.buildPromptSuggestion('Recommend settings', 'recommend settings'),
                this.buildPromptSuggestion('Open handbook', 'open handbook')
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
                { type: 'guided-start', label: 'Guided Reports', guidedKind: 'reports' },
                this.buildPromptSuggestion('Explain Cloud Tag', 'what should cloud tag mean'),
                this.buildPromptSuggestion('Export cloud CSV', 'export cloud reports csv month'),
                this.buildPromptSuggestion('Show cloud tutorial', 'show cloud tutorial')
            ];
            return promptModel;
        }

        if (/overview|metric|analytics|trend|ready rate/i.test(lastUserPrompt) || currentPage === 'analytics') {
            promptModel.headline = 'Analytics follow-up';
            promptModel.subline = 'The user is in metrics mode, so these prompts stay close to summary and export tasks.';
            promptModel.mode = 'analytics';
            promptModel.actions = [
                this.buildPromptSuggestion('System overview', 'system overview'),
                { type: 'guided-start', label: 'Guided Analytics', guidedKind: 'analytics' },
                this.buildPromptSuggestion('Export analytics CSV', 'export analytics csv'),
                this.buildPromptSuggestion('Open reports', 'open reports'),
                this.buildPromptSuggestion('Explain Local Tag', 'what does local synced mean')
            ];
            return promptModel;
        }

        if (currentPage === 'live') {
            promptModel.headline = 'Live monitoring follow-up';
            promptModel.subline = 'These prompts help after a monitoring run or before closing a live session.';
            promptModel.mode = 'live';
            promptModel.actions = [
                this.buildPromptSuggestion('Open camera', 'help me start live monitoring'),
                this.buildPromptSuggestion('Check image', 'can you check if this image has violations'),
                this.buildPromptSuggestion('Recommend settings', 'recommend settings'),
                this.buildPromptSuggestion('Show cloud tutorial', 'show cloud tutorial'),
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
        const messageHtml = session.messages.map((message) => this.renderMessage(message)).join('');
        const feedbackHtml = this.isResponding ? this.renderResponseFeedback() : '';
        this.ui.messages.innerHTML = `${messageHtml}${feedbackHtml}`;
        this.scrollMessagesToBottom();
    },

    renderResponseFeedback() {
        return `
            <article class="assistant-message assistant-message-assistant assistant-message-thinking">
                <div class="assistant-avatar" aria-hidden="true">
                    <i class="fas fa-sparkles"></i>
                </div>
                <div class="assistant-message-stack">
                    <div class="assistant-message-meta">${this.escapeHtml(this.ASSISTANT_NAME)}</div>
                    <div class="assistant-bubble assistant-thinking-bubble" role="status" aria-live="polite">
                        <span class="assistant-thinking-dots" aria-hidden="true">
                            <span></span><span></span><span></span>
                        </span>
                        <p>${this.escapeHtml(this.responseFeedbackText || 'Thinking...')}</p>
                    </div>
                </div>
            </article>
        `;
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

        const sectionsHtml = Array.isArray(message.sections) && message.sections.length
            ? `<div class="assistant-detail-sections">${message.sections.map((section) => {
                const items = Array.isArray(section.items) ? section.items : [];
                if (!items.length) return '';
                return `
                    <section class="assistant-detail-section">
                        <h4>${this.escapeHtml(section.title || 'Detail')}</h4>
                        <ul>${items.map((item) => `<li>${this.escapeHtml(item)}</li>`).join('')}</ul>
                    </section>
                `;
            }).join('')}</div>`
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
                    <div class="assistant-tutorial-progress" aria-hidden="true">
                        <div class="assistant-tutorial-progress-track">
                            <span class="assistant-tutorial-progress-fill" style="width: ${Math.max(8, Math.min(100, Math.round((Number(message.tutorial.stepNumber || 1) / Math.max(1, Number(message.tutorial.totalSteps || 1))) * 100)))}%;"></span>
                        </div>
                    </div>
                    <h4>${this.escapeHtml(message.tutorial.title || '')}</h4>
                    <p>${this.escapeHtml(message.tutorial.summary || '')}</p>
                    <ul class="assistant-bullet-list">${(message.tutorial.bullets || []).map((item) => `<li>${this.escapeHtml(item)}</li>`).join('')}</ul>
                    <div class="assistant-caution">${this.escapeHtml(message.tutorial.caution || '')}</div>
                    <div class="assistant-tutorial-footnote">Use Previous step and Next step to move this guide without stacking extra tutorial cards.</div>
                </div>
            `
            : '';

        const reportCarouselHtml = message.reportCarousel
            ? this.renderReportCarousel(message.reportCarousel)
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

        const speakerName = message.role === 'assistant' ? this.ASSISTANT_NAME : 'You';
        const speakerIcon = message.role === 'assistant' ? 'fa-sparkles' : 'fa-user';

        return `
            <article class="assistant-message assistant-message-${message.role}" data-role="${this.escapeHtml(message.role)}">
                <div class="assistant-avatar" aria-hidden="true">
                    <i class="fas ${speakerIcon}"></i>
                </div>
                <div class="assistant-message-stack">
                    <div class="assistant-message-meta">${this.escapeHtml(speakerName)}</div>
                    <div class="assistant-bubble">
                        <p>${this.escapeHtml(message.text)}</p>
                        ${tutorialHtml}
                        ${reportCarouselHtml}
                        ${metricsHtml}
                        ${sectionsHtml}
                        ${bulletsHtml}
                        ${docsHtml}
                        ${actionsHtml}
                    </div>
                </div>
            </article>
        `;
    },

    renderReportCarousel(carousel = {}) {
        const report = carousel.report || {};
        const thumbnailHtml = report.thumbnailUrl
            ? `<img src="${this.escapeHtml(report.thumbnailUrl)}" alt="Report ${this.escapeHtml(report.reportId || '')} thumbnail" loading="lazy">`
            : `<div class="assistant-report-thumb-empty"><i class="fas fa-image" aria-hidden="true"></i><span>No thumbnail</span></div>`;
        const missing = Array.isArray(report.missingPpe) && report.missingPpe.length
            ? report.missingPpe.join(', ')
            : 'No PPE labels';
        return `
            <article class="assistant-report-card">
                <div class="assistant-report-card-topline">
                    <span class="assistant-report-index">${this.escapeHtml(carousel.positionLabel || '')}</span>
                    <span class="assistant-report-tag">${this.escapeHtml(report.sourceLabel || report.sourceScope || 'Unknown source')}</span>
                </div>
                <div class="assistant-report-card-body">
                    <div class="assistant-report-thumb">${thumbnailHtml}</div>
                    <div class="assistant-report-copy">
                        <h4>${this.escapeHtml(report.reportId || 'Unknown report')}</h4>
                        <div class="assistant-report-meta">
                            <span>${this.escapeHtml(report.status || 'unknown')}</span>
                            <span>${this.escapeHtml(report.severity || 'unknown')} severity</span>
                            <span>${this.escapeHtml(report.timestampLabel || 'time unknown')}</span>
                        </div>
                        <p>${this.escapeHtml(report.summary || 'No report summary available yet.')}</p>
                        <div class="assistant-report-ppe">${this.escapeHtml(missing)}</div>
                    </div>
                </div>
            </article>
        `;
    },

    async handleSubmit() {
        const raw = String(this.ui.input.value || '').trim();
        if (!raw) return;
        if (this.handleBusyInteraction()) return;
        this.ui.input.value = '';
        this.autosizeInput();
        this.recordUserPrompt(raw);
        const responseJobId = this.beginResponseFeedback(this.pickResponseFeedback(raw));
        try {
            await this.waitForFeedbackFrame();
            await this.answer(raw);
        } finally {
            this.finishResponseFeedback(responseJobId);
        }
    },

    pickResponseFeedback(raw) {
        const query = this.normalizeText(raw);
        if (/\b(export|download|csv)\b/.test(query)) return 'Preparing the export...';
        if (/\b(reports?|report id|violation records?|case records?|evidence|latest reports?|recent reports?|local synced|synced local)\b/.test(query)) return 'Reading reports...';
        if (/\b(analytics|metric|metrics|trend|filter|severity|week|month|today)\b/.test(query)) return 'Checking the analytics view...';
        if (/\b(camera|live|monitor|monitoring|supervision|supervise|image|upload)\b/.test(query)) return 'Mapping that to the right workflow...';
        if (/\b(tutorial|guide|handbook|manual|docs)\b/.test(query)) return 'Looking through the guide...';
        return 'Thinking...';
    },

    pickActionFeedback(action = {}) {
        const type = String(action.type || '').trim();
        if (type === 'route') return `Opening ${action.label || 'the page'}...`;
        if (type === 'handbook' || type === 'doc-result') return 'Opening the handbook...';
        if (type === 'tutorial') return 'Loading the tutorial...';
        if (type === 'export') return 'Preparing the export preview...';
        if (type === 'overview') return 'Checking current metrics...';
        if (type === 'guided-start') return `Starting guided ${this.getGuidedKind(action.guidedKind)}...`;
        if (type === 'guided-finish') {
            return this.getGuidedKind(action.guidedKind) === 'reports'
                ? 'Reading reports...'
                : 'Building the guided result...';
        }
        if (type === 'settings-profile') return 'Applying the selected settings...';
        if (type === 'report-review-explain') return 'Reading the selected report...';
        if (type === 'open-report') return 'Opening the selected report...';
        return '';
    },

    waitForFeedbackFrame() {
        return new Promise((resolve) => {
            const finish = () => window.setTimeout(resolve, 140);
            if (typeof window.requestAnimationFrame === 'function') {
                window.requestAnimationFrame(finish);
            } else {
                finish();
            }
        });
    },

    setResponseFeedback(active, label = '') {
        const next = !!active;
        this.isResponding = next;
        if (label) {
            this.responseFeedbackText = label;
        }
        this.syncResponseControls();
        this.renderMessages();
    },

    beginResponseFeedback(label = '') {
        this.activeResponseJobId += 1;
        const jobId = this.activeResponseJobId;
        this.setResponseFeedback(true, label || 'Thinking...');
        return jobId;
    },

    finishResponseFeedback(jobId) {
        if (!jobId || jobId === this.activeResponseJobId) {
            this.setResponseFeedback(false);
        }
    },

    updateResponseFeedback(label = '') {
        const nextLabel = String(label || '').trim();
        if (!this.isResponding || !nextLabel) return;
        this.responseFeedbackText = nextLabel;
        this.renderMessages();
    },

    handleBusyInteraction() {
        if (!this.isResponding) return false;
        const current = String(this.responseFeedbackText || '').trim();
        this.updateResponseFeedback(current && current !== 'Thinking...'
            ? current
            : 'Still working on your last request...');
        return true;
    },

    syncResponseControls() {
        if (this.ui.composer) {
            this.ui.composer.classList.toggle('is-responding', this.isResponding);
        }
        if (this.ui.input) {
            this.ui.input.disabled = this.isResponding;
            this.ui.input.setAttribute('aria-busy', this.isResponding ? 'true' : 'false');
        }
        if (this.ui.send) {
            this.ui.send.disabled = this.isResponding;
            this.ui.send.setAttribute('aria-busy', this.isResponding ? 'true' : 'false');
        }
    },

    async answer(raw) {
        const query = this.normalizeText(raw);
        const session = this.getActiveSession();
        if (!session) return;
        if (await this.handlePendingGuidedDateInput(raw)) {
            return;
        }
        const localIntent = this.resolveLocalIntent(raw);
        const exportIntent = this.isExportIntent(query) || (localIntent && /^export-/.test(localIntent.id));
        const docsIntent = this.isDocsIntent(query) || (localIntent && localIntent.id === 'docs-search' && localIntent.confidence >= 0.64);
        const safetyGuardrail = this.resolveSafetyGuardrail(raw, query);
        const languageGuardrail = this.resolveLanguageGuardrail(raw, query);
        const negativePreference = this.resolveNegativePreference(raw, query);

        if (!docsIntent) {
            session.context.lastDocsQuery = '';
            session.context.lastDocsResults = [];
        }
        if (!exportIntent) {
            session.context.lastExportKind = '';
        }

        if (safetyGuardrail) {
            this.handleSafetyGuardrail(safetyGuardrail);
            return;
        }

        if (languageGuardrail) {
            this.handleLanguageGuardrail(languageGuardrail);
            return;
        }

        if (negativePreference) {
            this.handleNegativePreference(negativePreference);
            return;
        }

        const reportReviewIntent = !exportIntent ? this.resolveReportReviewIntent(raw, query) : null;
        if (reportReviewIntent) {
            await this.handleReportReviewIntent(reportReviewIntent);
            return;
        }

        const explanation = this.resolveExplanation(query);
        if (this.isExplanationQuestion(query) && explanation) {
            this.pushMessage({
                role: 'assistant',
                text: explanation.text,
                actions: explanation.actions || []
            });
            return;
        }

        if (docsIntent && !exportIntent) {
            this.handleDocsSearch(raw);
            return;
        }

        const semanticAnswer = this.resolveSemanticAnswer(raw, query);
        if (semanticAnswer) {
            this.handleSemanticAnswer(semanticAnswer);
            return;
        }

        const compoundIntent = !exportIntent ? this.resolveCompoundIntent(raw, query, localIntent) : null;
        if (compoundIntent) {
            this.handleCompoundIntent(compoundIntent);
            return;
        }

        if (localIntent && localIntent.confidence >= localIntent.directThreshold) {
            const handled = await this.handleLocalIntent(localIntent, raw, query);
            if (handled) return;
        }

        if (exportIntent) {
            await this.handleExportIntent(raw, query);
            return;
        }

        if (this.isOverviewIntent(query) && !this.isTargetedStatusIntent(query)) {
            await this.handleOverviewIntent();
            return;
        }

        if (docsIntent) {
            this.handleDocsSearch(raw);
            return;
        }

        if (this.isOnboardingIntent(query)) {
            this.handleOnboardingIntent();
            return;
        }

        if (this.isCapabilityIntent(query)) {
            this.handleCapabilityIntent();
            return;
        }

        if (this.isTutorialIntent(query)) {
            this.handleTutorialIntent(query);
            return;
        }

        const workflowIntent = this.resolveWorkflowIntent(query);
        if (workflowIntent) {
            this.handleWorkflowIntent(workflowIntent);
            return;
        }

        const settingsIntent = this.resolveSettingsIntent(query);
        if (settingsIntent) {
            await this.handleSettingsIntent(settingsIntent);
            return;
        }

        const analyticsIntent = this.resolveAnalyticsIntent(raw, query);
        if (analyticsIntent) {
            await this.handleAnalyticsIntent(analyticsIntent);
            return;
        }

        const destination = this.resolveDestination(query);
        if (destination) {
            this.handleDestination(destination);
            return;
        }

        if (explanation) {
            this.pushMessage({
                role: 'assistant',
                text: explanation.text,
                actions: explanation.actions || []
            });
            return;
        }

        if (localIntent && localIntent.confidence >= localIntent.clarifyThreshold) {
            this.handleIntentClarification(raw, localIntent);
            return;
        }

        this.recordUnmatchedPrompt(raw, query, localIntent);
        this.handleUnknownPrompt(raw, query);
    },

    getLocalIntentModels() {
        return [
            {
                id: 'start-live',
                label: 'start live monitoring',
                directThreshold: 0.58,
                clarifyThreshold: 0.38,
                examples: [
                    'start live monitoring',
                    'start supervision',
                    'begin site supervision',
                    'monitor the workers',
                    'watch the construction site',
                    'start camera stream',
                    'open live camera',
                    'begin safety monitoring',
                    'run real time PPE detection'
                ],
                keywords: ['start', 'begin', 'open', 'live', 'monitor', 'camera', 'stream', 'supervision', 'site', 'worker', 'watch', 'real time', 'ppe']
            },
            {
                id: 'image-analysis',
                label: 'check an image',
                directThreshold: 0.6,
                clarifyThreshold: 0.4,
                examples: [
                    'check this image',
                    'analyze image',
                    'inspect photo for PPE',
                    'scan picture for violations',
                    'review uploaded image',
                    'detect violations in this snapshot',
                    'upload image for checking'
                ],
                keywords: ['image', 'photo', 'picture', 'snapshot', 'upload', 'analyze', 'analyse', 'inspect', 'scan', 'check', 'violation']
            },
            {
                id: 'analytics-snapshot',
                label: 'show analytics',
                directThreshold: 0.55,
                clarifyThreshold: 0.4,
                examples: [
                    'show analytics',
                    'show me safety metrics',
                    'what are the violation trends',
                    'how many violations happened',
                    'any safety issues right now',
                    'did anything unsafe happen yesterday',
                    'show me the bad stuff',
                    'show dashboard stats',
                    'summarize risk this week',
                    'give me compliance score'
                ],
                keywords: ['analytics', 'metric', 'stats', 'trend', 'dashboard', 'summary', 'violation', 'incident', 'alert', 'unsafe', 'safety', 'risk', 'score', 'compliance', 'how many', 'issue', 'helmet', 'hardhat', 'vest', 'mask', 'glove', 'goggle', 'boot', 'shoe', 'today', 'yesterday', 'week', 'month', 'high', 'medium', 'low']
            },
            {
                id: 'open-analytics',
                label: 'open analytics',
                directThreshold: 0.66,
                clarifyThreshold: 0.42,
                examples: ['open analytics page', 'go to analytics', 'take me to stats', 'show dashboard page'],
                keywords: ['open', 'go', 'analytics', 'stats', 'dashboard']
            },
            {
                id: 'open-reports',
                label: 'open reports',
                directThreshold: 0.66,
                clarifyThreshold: 0.42,
                examples: ['open reports', 'review reports', 'show generated reports', 'go to report history'],
                keywords: ['open', 'review', 'report', 'reports', 'history', 'generated']
            },
            {
                id: 'export-analytics',
                label: 'export analytics CSV',
                directThreshold: 0.58,
                clarifyThreshold: 0.38,
                examples: ['export analytics csv', 'download metrics csv', 'save dashboard stats', 'download analytics'],
                keywords: ['export', 'download', 'csv', 'analytics', 'metrics', 'stats']
            },
            {
                id: 'export-reports',
                label: 'export reports CSV',
                directThreshold: 0.58,
                clarifyThreshold: 0.38,
                examples: ['export reports csv', 'download report rows', 'save violations csv', 'download reports'],
                keywords: ['export', 'download', 'csv', 'report', 'reports', 'violations']
            },
            {
                id: 'tutorial',
                label: 'show tutorial',
                directThreshold: 0.64,
                clarifyThreshold: 0.42,
                examples: ['show tutorial', 'guide me through this', 'walk me through local mode', 'show cloud walkthrough', 'next tutorial step'],
                keywords: ['tutorial', 'guide', 'walkthrough', 'demo', 'step', 'teach', 'show me how', 'cloud', 'local']
            },
            {
                id: 'settings-recommend',
                label: 'recommend settings',
                directThreshold: 0.62,
                clarifyThreshold: 0.42,
                examples: ['recommend settings', 'best settings', 'what settings should I use', 'use safe default settings'],
                keywords: ['recommend', 'best', 'settings', 'default', 'safe', 'profile']
            },
            {
                id: 'settings-local',
                label: 'apply local profile',
                directThreshold: 0.54,
                clarifyThreshold: 0.44,
                examples: ['switch to local mode', 'apply local profile', 'use local pipeline', 'prepare offline mode'],
                keywords: ['switch', 'apply', 'local', 'profile', 'pipeline', 'offline']
            },
            {
                id: 'settings-cloud',
                label: 'apply cloud/API profile',
                directThreshold: 0.58,
                clarifyThreshold: 0.44,
                examples: ['switch to cloud mode', 'apply api mode', 'use hosted mode', 'cloud profile'],
                keywords: ['switch', 'apply', 'cloud', 'api', 'hosted', 'profile']
            },
            {
                id: 'docs-search',
                label: 'search handbook',
                directThreshold: 0.68,
                clarifyThreshold: 0.44,
                examples: ['search handbook', 'open manual', 'find documentation', 'show FAQ', 'explain in guide'],
                keywords: ['handbook', 'manual', 'documentation', 'docs', 'faq', 'guide', 'find', 'search']
            },
            {
                id: 'onboarding',
                label: 'help me start',
                directThreshold: 0.6,
                clarifyThreshold: 0.38,
                examples: ['I am new here', 'what should I do first', 'I do not know how to start', 'help me use this system', 'first time using this'],
                keywords: ['new', 'start', 'first', 'help', 'not sure', 'do not know', 'dont know', 'how']
            }
        ];
    },

    resolveLocalIntent(raw) {
        const normalized = this.normalizeForNlu(raw);
        const tokens = this.tokenizeForIntent(normalized);
        if (!tokens.length) return null;
        const entities = this.extractLocalIntentEntities(raw, normalized);
        const scored = this.getLocalIntentModels()
            .map((model) => this.scoreLocalIntentModel(model, normalized, tokens, entities))
            .sort((a, b) => b.confidence - a.confidence);
        const best = scored[0] || null;
        if (!best || best.confidence <= 0.12) return null;
        return {
            ...best,
            entities,
            alternatives: scored.slice(1, 4)
        };
    },

    scoreLocalIntentModel(model, normalized, tokens, entities = {}) {
        const tokenSet = new Set(tokens);
        const expandedTokenSet = new Set(this.expandIntentTokens(tokens));
        const exampleScores = (model.examples || []).map((example) => {
            const exampleTokens = this.tokenizeForIntent(this.normalizeForNlu(example));
            if (!exampleTokens.length) return 0;
            const exampleSet = new Set(this.expandIntentTokens(exampleTokens));
            const overlap = Array.from(exampleSet).filter((token) => expandedTokenSet.has(token)).length;
            const coverage = overlap / Math.max(1, Math.min(expandedTokenSet.size, exampleSet.size));
            const jaccard = overlap / Math.max(1, new Set([...expandedTokenSet, ...exampleSet]).size);
            const phrase = normalized.includes(this.normalizeForNlu(example)) ? 0.22 : 0;
            return Math.min(1, (coverage * 0.68) + (jaccard * 0.32) + phrase);
        });
        const exampleScore = Math.max(0, ...exampleScores);
        const keywordTokens = (model.keywords || []).flatMap((keyword) => this.tokenizeForIntent(this.normalizeForNlu(keyword)));
        const keywordMatches = keywordTokens.filter((token) => expandedTokenSet.has(token) || tokenSet.has(token));
        const keywordScore = keywordTokens.length
            ? Math.min(1, keywordMatches.length / Math.min(keywordTokens.length, 5))
            : 0;
        const entityBoost = this.getIntentEntityBoost(model.id, entities, normalized);
        const actionBoost = /\b(open|go|start|begin|show|check|analy[sz]e|export|download|recommend|switch|apply|help)\b/.test(normalized) ? 0.06 : 0;
        let confidence = Math.min(0.99, (exampleScore * 0.58) + (keywordScore * 0.28) + entityBoost + actionBoost);
        const actionfulSettings = /\b(switch|apply|use|set|prepare|change|enable|turn on|move to)\b/.test(normalized);
        const explanatoryQuestion = this.isExplanationQuestion(normalized);
        if ((model.id === 'settings-local' || model.id === 'settings-cloud') && !actionfulSettings) {
            confidence *= 0.56;
        }
        if ((model.id === 'settings-local' || model.id === 'settings-cloud') && explanatoryQuestion) {
            confidence *= 0.45;
        }
        return {
            ...model,
            confidence: Number(confidence.toFixed(3)),
            evidence: {
                exampleScore: Number(exampleScore.toFixed(3)),
                keywordScore: Number(keywordScore.toFixed(3)),
                entityBoost: Number(entityBoost.toFixed(3))
            }
        };
    },

    getIntentEntityBoost(intentId, entities = {}, normalized = '') {
        const hasFilters = entities.analyticsFilters && this.hasActiveAnalyticsFilters(entities.analyticsFilters);
        const exportMention = entities.exportKind || /\b(export|download|csv)\b/.test(normalized);
        if (intentId === 'analytics-snapshot' && (hasFilters || entities.analyticsMention)) return hasFilters ? 0.24 : 0.1;
        if (intentId === 'open-analytics' && entities.page === 'analytics') return 0.16;
        if (intentId === 'open-reports' && entities.page === 'reports') return 0.16;
        if (intentId === 'start-live' && entities.liveMode === 'live') return 0.16;
        if (intentId === 'image-analysis' && entities.liveMode === 'upload') return 0.16;
        if (intentId === 'export-analytics' && exportMention && (entities.exportKind === 'analytics' || entities.analyticsMention)) return 0.2;
        if (intentId === 'export-reports' && exportMention && (entities.exportKind === 'reports' || entities.reportMention)) return 0.18;
        if (intentId === 'tutorial' && entities.tutorialMention) return 0.14;
        if (intentId === 'settings-recommend' && entities.settingsProfile === 'recommended') return 0.16;
        if (intentId === 'settings-local' && entities.settingsProfile === 'local') return 0.16;
        if (intentId === 'settings-cloud' && entities.settingsProfile === 'api') return 0.16;
        if (intentId === 'docs-search' && entities.docsMention) return 0.15;
        return 0;
    },

    extractLocalIntentEntities(raw, normalized = '') {
        const query = normalized || this.normalizeForNlu(raw);
        const analyticsFilters = this.buildAnalyticsFilters(raw);
        const page = /\b(analytics|metric|stats|dashboard|chart|graph)\b/.test(query)
            ? 'analytics'
            : /\b(reports?|history|report list)\b/.test(query)
                ? 'reports'
                : /\b(live|camera|monitor|stream|supervision|supervise|watch|feed)\b/.test(query)
                    ? 'live'
                    : /\b(settings?|checkup|profile|provision)\b/.test(query)
                        ? 'settings'
                        : '';
        const liveMode = /\b(image|photo|picture|snapshot|upload)\b/.test(query)
            ? 'upload'
            : /\b(live|camera|monitor|stream|supervision|supervise|watch|feed)\b/.test(query)
                ? 'live'
                : '';
        const actionfulSettings = /\b(switch|apply|use|set|prepare|change|enable|turn on|move to)\b/.test(query);
        const settingsProfile = /\b(recommend|recommended|best|default)\b/.test(query)
            ? 'recommended'
            : actionfulSettings && /\b(local|offline)\b/.test(query) && /\b(profile|mode|settings|pipeline|switch|apply|use|prepare|enable)\b/.test(query)
                ? 'local'
                : actionfulSettings && /\b(api|cloud|hosted)\b/.test(query) && /\b(profile|mode|settings|switch|apply|use|enable)\b/.test(query)
                    ? 'api'
                    : '';
        const exportKind = /\b(export|download|csv)\b/.test(query)
            ? (/\b(analytics|metric|stats|dashboard)\b/.test(query)
                ? 'analytics'
                : /\b(docs|manual|handbook|documentation|faq)\b/.test(query)
                    ? 'docs'
                    : 'reports')
            : '';
        return {
            analyticsFilters,
            page,
            liveMode,
            settingsProfile,
            exportKind,
            tutorialFlow: /\blocal\b/.test(query) ? 'local' : /\bcloud\b/.test(query) ? 'cloud' : '',
            analyticsMention: /\b(analytics|metric|metrics|stats|trend|dashboard|score|risk|violation|incident|alert|safety|unsafe|compliance|chart|graph)\b/.test(query),
            reportMention: /\b(reports?|history|records?|incident list)\b/.test(query),
            docsMention: /\b(docs|manual|handbook|documentation|faq|guide)\b/.test(query),
            tutorialMention: /\b(tutorial|guide|walkthrough|demo|step)\b/.test(query)
        };
    },

    async handleLocalIntent(intent, raw, query) {
        switch (intent.id) {
            case 'start-live':
                this.handleWorkflowIntent(this.buildLiveMonitoringIntent());
                return true;
            case 'image-analysis':
                this.handleWorkflowIntent(this.buildImageAnalysisIntent());
                return true;
            case 'analytics-snapshot':
                await this.handleAnalyticsIntent({
                    raw,
                    query,
                    filters: intent.entities.analyticsFilters || this.buildAnalyticsFilters(raw),
                    filterSummary: this.describeAnalyticsFilters(intent.entities.analyticsFilters || this.buildAnalyticsFilters(raw))
                });
                return true;
            case 'open-analytics': {
                const filters = intent.entities.analyticsFilters || this.buildAnalyticsFilters(raw);
                if (this.hasActiveAnalyticsFilters(filters)) {
                    await this.handleAnalyticsIntent({
                        raw,
                        query,
                        filters,
                        filterSummary: this.describeAnalyticsFilters(filters)
                    });
                } else {
                    this.handleDestination({ type: 'route', page: 'analytics', label: 'Analytics' });
                }
                return true;
            }
            case 'open-reports':
                this.handleDestination({ type: 'route', page: 'reports', label: 'Reports' });
                return true;
            case 'export-analytics':
                await this.handleExportIntent(`${raw} analytics csv`, `${query} analytics csv`);
                return true;
            case 'export-reports':
                await this.handleExportIntent(`${raw} reports csv`, `${query} reports csv`);
                return true;
            case 'tutorial':
                this.handleTutorialIntent(`${intent.entities.tutorialFlow || ''} ${query} tutorial`);
                return true;
            case 'settings-recommend':
                await this.handleSettingsIntent({ type: 'recommendation' });
                return true;
            case 'settings-local':
                await this.handleSettingsIntent({ type: 'apply-local' });
                return true;
            case 'settings-cloud':
                await this.handleSettingsIntent({ type: 'apply-api' });
                return true;
            case 'docs-search':
                this.handleDocsSearch(raw);
                return true;
            case 'onboarding':
                this.handleOnboardingIntent();
                return true;
            default:
                return false;
        }
    },

    buildLiveMonitoringIntent() {
        return {
            text: 'I read that as starting site supervision, so the Live Monitor workflow is the right place. I can take you there and collapse the chat so the camera controls stay usable.',
            bullets: [
                'I will place you on Live Monitor with the camera stream workflow ready.',
                'Use Start after the preview area is visible and the camera source looks right.',
                'Reopen Mira anytime from the launcher; this same session stays here.'
            ],
            actions: [
                { type: 'route', label: 'Open Live Monitor', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true },
                { type: 'tutorial', label: 'Show cloud tutorial', flow: 'cloud', stepIndex: 0 },
                { type: 'route', label: 'Open settings checkup', page: 'settings', focusLocalCheckup: true, collapsePanel: true }
            ]
        };
    },

    buildImageAnalysisIntent() {
        return {
            text: 'For still-image checks, use Live Monitor in Analyze Image mode. I can open that view and land you right on the upload area.',
            bullets: [
                'This path is best when you want one or several still images reviewed instead of a full live session.',
                'Use the upload area, choose the image files, then run Analyze for PPE Violations.',
                'Mira will remember this conversation when you reopen the panel.'
            ],
            actions: [
                { type: 'route', label: 'Open Image Analysis', page: 'live', liveMode: 'upload', liveFocus: 'upload', collapsePanel: true },
                { type: 'handbook', label: 'Open upload guide', pageKey: 'workflow', stageKey: 'capture', collapsePanel: true },
                { type: 'tutorial', label: 'Show cloud tutorial', flow: 'cloud', stepIndex: 0 }
            ]
        };
    },

    getGuidedKind(kind = '') {
        return String(kind || '').trim() === 'reports' ? 'reports' : 'analytics';
    },

    getGuidedKindLabel(kind = '') {
        return this.getGuidedKind(kind) === 'reports' ? 'reports' : 'analytics';
    },

    normalizeFilterValues(values, allowedValues = []) {
        const allowed = new Set(allowedValues);
        const rawValues = Array.isArray(values) ? values : [values];
        return Array.from(new Set(
            rawValues
                .map((value) => String(value || '').trim().toLowerCase().replace(/-/g, '_'))
                .filter((value) => allowed.has(value))
        ));
    },

    normalizeSourceFilterValues(filters = {}, includeShared = false) {
        const rawValues = [];
        if (Array.isArray(filters.sources)) rawValues.push(...filters.sources);
        if (filters.source) rawValues.push(filters.source);
        return this.normalizeFilterValues(
            rawValues,
            includeShared ? ['cloud', 'local', 'synced_local', 'shared'] : ['cloud', 'local', 'synced_local']
        );
    },

    normalizeSeverityFilterValues(filters = {}) {
        const rawValues = [];
        if (Array.isArray(filters.severities)) rawValues.push(...filters.severities);
        if (filters.severity) rawValues.push(filters.severity);
        return this.normalizeFilterValues(rawValues, ['high', 'medium', 'low']);
    },

    getSourceScope(row = {}) {
        const explicitScope = String(row?.source_scope || '').trim().toLowerCase().replace(/-/g, '_');
        const labelScope = String(row?.source_label || '').trim().toLowerCase();
        if (explicitScope === 'synced_local' || labelScope === 'local synced') return 'synced_local';
        return explicitScope || labelScope.replace(/\s+/g, '_');
    },

    formatSourceFilterLabel(value = '') {
        const labels = {
            cloud: 'Cloud',
            local: 'Local',
            synced_local: 'Local Synced',
            shared: 'Shared'
        };
        return labels[String(value || '').trim()] || String(value || '').replace(/_/g, ' ');
    },

    formatSeverityFilterLabel(value = '') {
        const normalized = String(value || '').trim().toLowerCase();
        return normalized ? `${normalized.slice(0, 1).toUpperCase()}${normalized.slice(1)}` : '';
    },

    buildChoiceLabel(label, selected = false) {
        return selected ? `${label} (selected)` : label;
    },

    sanitizeGuidedFilters(kind = '', filters = {}) {
        if (this.getGuidedKind(kind) === 'analytics') {
            return this.sanitizeAnalyticsFilters(filters);
        }

        const cleaned = {};
        const sources = this.normalizeSourceFilterValues(filters, true);
        if (sources.length === 1) {
            cleaned.source = sources[0];
        } else if (sources.length > 1) {
            cleaned.sources = sources;
        }

        const severities = this.normalizeSeverityFilterValues(filters);
        if (severities.length === 1) {
            cleaned.severity = severities[0];
        } else if (severities.length > 1) {
            cleaned.severities = severities;
        }

        const dateRange = String(filters.dateRange || '').trim().toLowerCase();
        if (['today', 'yesterday', 'week', 'month'].includes(dateRange)) {
            cleaned.dateRange = dateRange;
        }

        const dateExact = this.normalizeDateKey(filters.dateExact);
        const dateFrom = this.normalizeDateKey(filters.dateFrom);
        const dateTo = this.normalizeDateKey(filters.dateTo);
        if (dateExact) {
            cleaned.dateExact = dateExact;
            delete cleaned.dateRange;
        } else {
            if (dateFrom) {
                cleaned.dateFrom = dateFrom;
                delete cleaned.dateRange;
            }
            if (dateTo) {
                cleaned.dateTo = dateTo;
                delete cleaned.dateRange;
            }
        }

        const validPpe = new Set([
            'NO-Hardhat',
            'NO-Safety Vest',
            'NO-Gloves',
            'NO-Mask',
            'NO-Goggles',
            'NO-Safety Shoes'
        ]);
        const ppeTypes = Array.isArray(filters.ppeTypes) ? filters.ppeTypes : [];
        const normalizedPpe = Array.from(new Set(
            ppeTypes
                .map((label) => this.normalizePpeFilterLabel(label))
                .filter((label) => validPpe.has(label))
        ));
        if (normalizedPpe.length) {
            cleaned.ppeTypes = normalizedPpe;
        }

        return cleaned;
    },

    mergeGuidedFilters(kind = '', filters = {}, update = {}) {
        const guidedKind = this.getGuidedKind(kind);
        const next = {
            ...this.sanitizeGuidedFilters(kind, filters)
        };
        const updateKeys = Object.keys(update || {});
        if (updateKeys.some((key) => ['dateRange', 'dateExact', 'dateFrom', 'dateTo'].includes(key))) {
            delete next.dateRange;
            delete next.dateExact;
            delete next.dateFrom;
            delete next.dateTo;
        }

        if (update.resetSources) {
            delete next.source;
            delete next.sources;
        }
        if (update.toggleSource) {
            const sources = this.normalizeSourceFilterValues(next, guidedKind === 'reports');
            const value = this.normalizeFilterValues(update.toggleSource, guidedKind === 'reports'
                ? ['cloud', 'local', 'synced_local', 'shared']
                : ['cloud', 'local', 'synced_local'])[0];
            if (value) {
                const nextSources = sources.includes(value)
                    ? sources.filter((item) => item !== value)
                    : [...sources, value];
                delete next.source;
                delete next.sources;
                if (nextSources.length === 1) next.source = nextSources[0];
                if (nextSources.length > 1) next.sources = nextSources;
            }
        }

        if (update.resetSeverities) {
            delete next.severity;
            delete next.severities;
        }
        if (update.toggleSeverity) {
            const severities = this.normalizeSeverityFilterValues(next);
            const value = this.normalizeFilterValues(update.toggleSeverity, ['high', 'medium', 'low'])[0];
            if (value) {
                const nextSeverities = severities.includes(value)
                    ? severities.filter((item) => item !== value)
                    : [...severities, value];
                delete next.severity;
                delete next.severities;
                if (nextSeverities.length === 1) next.severity = nextSeverities[0];
                if (nextSeverities.length > 1) next.severities = nextSeverities;
            }
        }

        if (update.togglePpe) {
            const validPpe = new Set([
                'NO-Hardhat',
                'NO-Safety Vest',
                'NO-Gloves',
                'NO-Mask',
                'NO-Goggles',
                'NO-Safety Shoes'
            ]);
            const currentPpe = Array.isArray(next.ppeTypes) ? next.ppeTypes : [];
            const value = this.normalizePpeFilterLabel(update.togglePpe);
            if (validPpe.has(value)) {
                const nextPpe = currentPpe.includes(value)
                    ? currentPpe.filter((item) => item !== value)
                    : [...currentPpe, value];
                if (nextPpe.length) next.ppeTypes = nextPpe;
                else delete next.ppeTypes;
            }
        }

        Object.entries(update || {}).forEach(([key, value]) => {
            if (['toggleSource', 'toggleSeverity', 'togglePpe', 'resetSources', 'resetSeverities'].includes(key)) {
                return;
            }
            if (key === 'ppeTypes') {
                if (Array.isArray(value) && value.length) {
                    next.ppeTypes = value.slice(0, 6);
                } else {
                    delete next.ppeTypes;
                }
                return;
            }
            if (key === 'sources') {
                const sources = this.normalizeFilterValues(value, guidedKind === 'reports'
                    ? ['cloud', 'local', 'synced_local', 'shared']
                    : ['cloud', 'local', 'synced_local']);
                delete next.source;
                delete next.sources;
                if (sources.length === 1) next.source = sources[0];
                if (sources.length > 1) next.sources = sources;
                return;
            }
            if (key === 'severities') {
                const severities = this.normalizeFilterValues(value, ['high', 'medium', 'low']);
                delete next.severity;
                delete next.severities;
                if (severities.length === 1) next.severity = severities[0];
                if (severities.length > 1) next.severities = severities;
                return;
            }
            if (value) {
                next[key] = value;
            } else {
                delete next[key];
            }
        });
        return this.sanitizeGuidedFilters(kind, next);
    },

    describeGuidedFilters(kind = '', filters = {}) {
        const safeFilters = this.sanitizeGuidedFilters(kind, filters);
        const summary = this.getGuidedKind(kind) === 'reports'
            ? this.describeReportFilters(safeFilters)
            : this.describeAnalyticsFilters(safeFilters);
        return summary || 'all rows';
    },

    buildGuidedAction(label, kind, step, filters, update = {}, nextStep = '') {
        return {
            type: 'guided-select',
            label,
            guidedKind: this.getGuidedKind(kind),
            guidedStep: step,
            guidedFilters: this.sanitizeGuidedFilters(kind, filters),
            guidedUpdate: update,
            guidedNextStep: nextStep
        };
    },

    buildGuidedToggleAction(label, kind, step, filters, update = {}) {
        return {
            type: 'guided-toggle',
            label,
            guidedKind: this.getGuidedKind(kind),
            guidedStep: step,
            guidedFilters: this.sanitizeGuidedFilters(kind, filters),
            guidedUpdate: update
        };
    },

    buildGuidedContinueAction(label, kind, nextStep, filters) {
        return {
            type: 'guided-continue',
            label,
            guidedKind: this.getGuidedKind(kind),
            guidedNextStep: nextStep,
            guidedFilters: this.sanitizeGuidedFilters(kind, filters)
        };
    },

    buildGuidedStepMessage(kind = 'analytics', step = 'source', filters = {}) {
        const guidedKind = this.getGuidedKind(kind);
        const safeFilters = this.sanitizeGuidedFilters(guidedKind, filters);
        const kindLabel = this.getGuidedKindLabel(guidedKind);
        const summary = this.describeGuidedFilters(guidedKind, safeFilters);
        const sourceChoices = guidedKind === 'reports'
            ? ['cloud', 'local', 'synced_local', 'shared']
            : ['cloud', 'local', 'synced_local'];
        const selectedSources = this.normalizeSourceFilterValues(safeFilters, guidedKind === 'reports');
        const selectedSeverities = this.normalizeSeverityFilterValues(safeFilters);
        const selectedPpe = Array.isArray(safeFilters.ppeTypes) ? safeFilters.ppeTypes : [];
        const base = {
            role: 'assistant',
            text: `Guided ${kindLabel}: ${step === 'review' ? 'review the filter set' : `choose the ${step} filter`}.`,
            guided: {
                kind: guidedKind,
                step
            },
            bullets: [
                `Current filter: ${summary}.`,
                ['source', 'severity', 'ppe'].includes(step)
                    ? 'Pick one or more choices, then press Continue.'
                    : 'Use the buttons below; free-text prompts still work anytime.'
            ],
            actions: []
        };

        if (step === 'source') {
            base.actions = [
                this.buildGuidedToggleAction('All sources', guidedKind, step, safeFilters, { resetSources: true }),
                ...sourceChoices.map((value) => this.buildGuidedToggleAction(
                    this.buildChoiceLabel(this.formatSourceFilterLabel(value), selectedSources.includes(value)),
                    guidedKind,
                    step,
                    safeFilters,
                    { toggleSource: value }
                )),
                this.buildGuidedContinueAction('Continue', guidedKind, 'severity', safeFilters)
            ];
            return base;
        }

        if (step === 'severity') {
            base.actions = [
                this.buildGuidedToggleAction('All severities', guidedKind, step, safeFilters, { resetSeverities: true }),
                ...['high', 'medium', 'low'].map((value) => this.buildGuidedToggleAction(
                    this.buildChoiceLabel(this.formatSeverityFilterLabel(value), selectedSeverities.includes(value)),
                    guidedKind,
                    step,
                    safeFilters,
                    { toggleSeverity: value }
                )),
                this.buildGuidedContinueAction('Continue', guidedKind, 'date', safeFilters)
            ];
            return base;
        }

        if (step === 'date') {
            base.bullets.push('For a typed date, use YYYY-MM-DD or YYYY-MM-DD..YYYY-MM-DD.');
            base.actions = [
                this.buildGuidedAction('All dates', guidedKind, step, safeFilters, { dateRange: '', dateExact: '', dateFrom: '', dateTo: '' }, 'ppe'),
                this.buildGuidedAction('Today', guidedKind, step, safeFilters, { dateRange: 'today' }, 'ppe'),
                this.buildGuidedAction('Yesterday', guidedKind, step, safeFilters, { dateRange: 'yesterday' }, 'ppe'),
                this.buildGuidedAction('Last 7 days', guidedKind, step, safeFilters, { dateRange: 'week' }, 'ppe'),
                this.buildGuidedAction('Last 30 days', guidedKind, step, safeFilters, { dateRange: 'month' }, 'ppe'),
                { type: 'guided-date-request', label: 'Type strict date', guidedKind, guidedFilters: safeFilters }
            ];
            return base;
        }

        if (step === 'ppe') {
            base.actions = [
                this.buildGuidedToggleAction('All violations', guidedKind, step, safeFilters, { ppeTypes: [] }),
                ...[
                    ['Missing hardhat', 'NO-Hardhat'],
                    ['Missing vest', 'NO-Safety Vest'],
                    ['Missing mask', 'NO-Mask'],
                    ['Missing gloves', 'NO-Gloves'],
                    ['Missing goggles', 'NO-Goggles'],
                    ['Missing shoes', 'NO-Safety Shoes']
                ].map(([label, value]) => this.buildGuidedToggleAction(
                    this.buildChoiceLabel(label, selectedPpe.includes(value)),
                    guidedKind,
                    step,
                    safeFilters,
                    { togglePpe: value }
                )),
                this.buildGuidedContinueAction('Continue', guidedKind, 'review', safeFilters)
            ];
            return base;
        }

        base.text = guidedKind === 'reports'
            ? 'Guided reports: ready to fetch matching reports.'
            : 'Guided analytics: ready to compute this filtered slice.';
        base.sections = [{
            title: 'Chosen filters',
            items: [summary]
        }];
        base.actions = guidedKind === 'reports'
            ? [
                { type: 'guided-finish', label: 'Show reports', guidedKind, guidedFilters: safeFilters, guidedMode: 'browse' },
                { type: 'guided-finish', label: 'Explain first match', guidedKind, guidedFilters: safeFilters, guidedMode: 'explain' },
                { type: 'guided-start', label: 'Start over', guidedKind }
            ]
            : [
                { type: 'guided-finish', label: 'Build analytics snapshot', guidedKind, guidedFilters: safeFilters, guidedMode: 'snapshot' },
                { type: 'guided-finish', label: 'Open filtered dashboard', guidedKind, guidedFilters: safeFilters, guidedMode: 'dashboard' },
                { type: 'guided-start', label: 'Start over', guidedKind }
            ];
        return base;
    },

    setGuidedFlowState(kind = 'analytics', step = 'source', filters = {}, awaiting = '') {
        const session = this.getActiveSession();
        if (!session) return;
        const guidedKind = this.getGuidedKind(kind);
        session.context.guidedFlow = {
            kind: guidedKind,
            step: String(step || 'source'),
            awaiting: String(awaiting || ''),
            filters: this.sanitizeGuidedFilters(guidedKind, filters)
        };
        this.saveState();
    },

    clearGuidedFlowState() {
        const session = this.getActiveSession();
        if (!session) return;
        session.context.guidedFlow = null;
        this.saveState();
    },

    startGuidedFlow(kind = 'analytics') {
        const guidedKind = this.getGuidedKind(kind);
        const filters = {};
        this.setGuidedFlowState(guidedKind, 'source', filters);
        this.upsertGuidedStepMessage(guidedKind, 'source', filters);
    },

    handleGuidedSelection(action = {}) {
        const guidedKind = this.getGuidedKind(action.guidedKind);
        const filters = this.mergeGuidedFilters(guidedKind, action.guidedFilters || {}, action.guidedUpdate || {});
        const nextStep = String(action.guidedNextStep || 'source').trim() || 'source';
        this.setGuidedFlowState(guidedKind, nextStep, filters);
        this.upsertGuidedStepMessage(guidedKind, nextStep, filters);
    },

    handleGuidedToggle(action = {}) {
        const guidedKind = this.getGuidedKind(action.guidedKind);
        const step = String(action.guidedStep || 'source').trim() || 'source';
        const filters = this.mergeGuidedFilters(guidedKind, action.guidedFilters || {}, action.guidedUpdate || {});
        this.setGuidedFlowState(guidedKind, step, filters);
        this.upsertGuidedStepMessage(guidedKind, step, filters);
    },

    handleGuidedContinue(action = {}) {
        const guidedKind = this.getGuidedKind(action.guidedKind);
        const filters = this.sanitizeGuidedFilters(guidedKind, action.guidedFilters || {});
        const nextStep = String(action.guidedNextStep || 'source').trim() || 'source';
        this.setGuidedFlowState(guidedKind, nextStep, filters);
        this.upsertGuidedStepMessage(guidedKind, nextStep, filters);
    },

    getLatestGuidedMessageIndex(session, kind = '') {
        if (!session || !Array.isArray(session.messages)) return -1;
        const guidedKind = this.getGuidedKind(kind);
        for (let index = session.messages.length - 1; index >= 0; index -= 1) {
            const message = session.messages[index];
            if (message && message.role === 'assistant' && message.guided && message.guided.kind === guidedKind) {
                return index;
            }
        }
        return -1;
    },

    upsertGuidedStepMessage(kind = 'analytics', step = 'source', filters = {}) {
        const session = this.getActiveSession();
        if (!session) return;
        const guidedKind = this.getGuidedKind(kind);
        const nextMessage = this.buildGuidedStepMessage(guidedKind, step, filters);
        const existingIndex = this.getLatestGuidedMessageIndex(session, guidedKind);
        if (this.shouldUpdateInteractiveMessageInPlace(session, existingIndex)) {
            const existing = session.messages[existingIndex] || {};
            session.messages[existingIndex] = this.normalizeMessage({
                ...existing,
                ...nextMessage,
                id: existing.id,
                createdAt: existing.createdAt
            });
            session.updatedAt = Date.now();
            this.refreshSessionUi();
            return;
        }
        this.pushMessage(nextMessage);
    },

    requestGuidedDateInput(action = {}) {
        const guidedKind = this.getGuidedKind(action.guidedKind);
        const filters = this.sanitizeGuidedFilters(guidedKind, action.guidedFilters || {});
        this.setGuidedFlowState(guidedKind, 'date', filters, 'date');
        this.pushMessage({
            role: 'assistant',
            text: 'Type one strict date or date range for this guided filter.',
            bullets: [
                'Exact date format: YYYY-MM-DD, for example 2026-05-18.',
                'Range format: YYYY-MM-DD..YYYY-MM-DD, for example 2026-05-01..2026-05-18.'
            ],
            actions: [
                this.buildGuidedAction('Use all dates', guidedKind, 'date', filters, { dateRange: '', dateExact: '', dateFrom: '', dateTo: '' }, 'ppe'),
                this.buildGuidedAction('Back to date choices', guidedKind, 'date', filters, {}, 'date')
            ]
        });
    },

    parseGuidedDateInput(raw = '') {
        const source = String(raw || '').trim();
        const single = source.match(/^(20\d{2}-\d{2}-\d{2})$/);
        if (single) {
            const dateExact = this.normalizeDateKey(single[1]);
            return dateExact ? { success: true, filters: { dateExact } } : { success: false };
        }

        const range = source.match(/^(20\d{2}-\d{2}-\d{2})\s*(?:\.\.|\s+to\s+|\s+-\s+)\s*(20\d{2}-\d{2}-\d{2})$/i);
        if (range) {
            const dateFrom = this.normalizeDateKey(range[1]);
            const dateTo = this.normalizeDateKey(range[2]);
            if (dateFrom && dateTo && dateFrom <= dateTo) {
                return { success: true, filters: { dateFrom, dateTo } };
            }
        }

        return { success: false };
    },

    async handlePendingGuidedDateInput(raw = '') {
        const session = this.getActiveSession();
        const flow = session?.context?.guidedFlow;
        if (!flow || flow.awaiting !== 'date') return false;

        const guidedKind = this.getGuidedKind(flow.kind);
        const normalized = this.normalizeText(raw);
        if (/\b(cancel|skip|all dates|no date)\b/.test(normalized)) {
            const filters = this.mergeGuidedFilters(guidedKind, flow.filters || {}, { dateRange: '', dateExact: '', dateFrom: '', dateTo: '' });
            this.setGuidedFlowState(guidedKind, 'ppe', filters);
            this.upsertGuidedStepMessage(guidedKind, 'ppe', filters);
            return true;
        }

        const parsed = this.parseGuidedDateInput(raw);
        if (!parsed.success) {
            this.pushMessage({
                role: 'assistant',
                text: 'That date did not match the strict guided format.',
                bullets: [
                    'Use YYYY-MM-DD for one date.',
                    'Use YYYY-MM-DD..YYYY-MM-DD for a date range.'
                ],
                actions: [
                    this.buildGuidedAction('Use all dates', guidedKind, 'date', flow.filters || {}, { dateRange: '', dateExact: '', dateFrom: '', dateTo: '' }, 'ppe'),
                    this.buildGuidedAction('Back to date choices', guidedKind, 'date', flow.filters || {}, {}, 'date')
                ]
            });
            return true;
        }

        const filters = this.mergeGuidedFilters(guidedKind, flow.filters || {}, parsed.filters);
        this.setGuidedFlowState(guidedKind, 'ppe', filters);
        this.upsertGuidedStepMessage(guidedKind, 'ppe', filters);
        return true;
    },

    async finishGuidedFlow(action = {}) {
        const guidedKind = this.getGuidedKind(action.guidedKind);
        const filters = this.sanitizeGuidedFilters(guidedKind, action.guidedFilters || {});
        const filterSummary = this.describeGuidedFilters(guidedKind, filters);
        this.clearGuidedFlowState();

        if (guidedKind === 'reports') {
            await this.handleReportReviewIntent({
                type: 'browse',
                raw: 'guided reports',
                query: 'guided reports',
                filters,
                filterSummary: filterSummary === 'all rows' ? '' : filterSummary,
                selection: action.guidedMode === 'explain' ? 'latest' : '',
                autoExplain: action.guidedMode === 'explain'
            });
            return;
        }

        await this.handleAnalyticsIntent({
            raw: 'guided analytics',
            query: 'guided analytics',
            filters,
            filterSummary: filterSummary === 'all rows' ? '' : filterSummary
        });

        if (action.guidedMode === 'dashboard') {
            this.performRouteNavigation({
                type: 'route',
                page: 'analytics',
                analyticsFilters: filters,
                analyticsSummary: filterSummary === 'all rows' ? 'Guided analytics view' : filterSummary,
                collapsePanel: true
            });
        }
    },

    handleIntentClarification(raw, intent) {
        this.recordUnmatchedPrompt(raw, this.normalizeText(raw), intent);
        const candidates = [intent, ...(intent.alternatives || [])]
            .filter((item) => item && item.confidence >= 0.24)
            .slice(0, 3);
        const actions = candidates
            .map((item) => this.buildActionForIntentCandidate(item, raw))
            .filter(Boolean);
        this.pushMessage({
            role: 'assistant',
            text: `I have a partial read on that. I think you may mean "${intent.label}", but I want to avoid taking the wrong action.`,
            bullets: [
                `Best match confidence: ${Math.round(intent.confidence * 100)}%.`,
                'Pick one action below, or rephrase with the page/action you want.'
            ],
            actions: actions.length ? actions : [
                { type: 'route', label: 'Open camera', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true },
                { type: 'route', label: 'Open analytics', page: 'analytics', collapsePanel: true }
            ]
        });
    },

    buildActionForIntentCandidate(intent, raw) {
        if (!intent || !intent.id) return null;
        const filters = intent.entities?.analyticsFilters || this.buildAnalyticsFilters(raw);
        switch (intent.id) {
            case 'start-live':
                return { type: 'route', label: 'Start live monitoring', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true };
            case 'image-analysis':
                return { type: 'route', label: 'Check image', page: 'live', liveMode: 'upload', liveFocus: 'upload', collapsePanel: true };
            case 'analytics-snapshot':
            case 'open-analytics':
                return this.hasActiveAnalyticsFilters(filters)
                    ? { type: 'route', label: 'Open filtered analytics', page: 'analytics', analyticsFilters: filters, analyticsSummary: this.describeAnalyticsFilters(filters) || 'Filtered analytics view', collapsePanel: true }
                    : { type: 'route', label: 'Open analytics', page: 'analytics', collapsePanel: true };
            case 'open-reports':
                return { type: 'route', label: 'Open reports', page: 'reports', collapsePanel: true };
            case 'export-analytics':
                return { type: 'export', label: 'Export analytics CSV', exportKind: 'analytics' };
            case 'export-reports':
                return { type: 'export', label: 'Export reports CSV', exportKind: 'reports' };
            case 'tutorial':
                return { type: 'tutorial', label: 'Show tutorial', flow: intent.entities?.tutorialFlow || 'cloud', stepIndex: 0 };
            case 'settings-recommend':
                return { type: 'settings-profile', label: 'Recommend settings', profile: 'recommended' };
            case 'settings-local':
                return { type: 'settings-profile', label: 'Apply local profile', profile: 'local' };
            case 'settings-cloud':
                return { type: 'settings-profile', label: 'Apply API mode', profile: 'api' };
            case 'docs-search':
                return { type: 'handbook', label: 'Open handbook', pageKey: 'intro' };
            case 'onboarding':
                return { type: 'tutorial', label: 'Start guided tutorial', flow: 'cloud', stepIndex: 0 };
            default:
                return null;
        }
    },

    resolveSafetyGuardrail(raw, query = '') {
        const normalized = query || this.normalizeText(raw);
        if (!normalized) return null;
        const secretOrCredential = /\b(password|passcode|api key|secret|sync secret|token|jwt|service role|private key|database url|connection string|env|environment variable|credential|cookie|session id|auth header)\b/.test(normalized);
        const bypassRequest = /\b(bypass|skip|disable|turn off|override|remove|ignore)\b/.test(normalized)
            && /\b(auth|authentication|authorization|permission|approval|login|admin|role|security|access control)\b/.test(normalized);
        const crossUserData = /\b(other user|another user|someone else|all users|user sessions|assistant sessions|chat history|private report|personal data)\b/.test(normalized)
            && /\b(show|read|open|download|export|give|dump|list|reveal)\b/.test(normalized);
        const unsafeAdminAction = /\b(make me admin|grant admin|impersonate|login as|approve without|authorize without|delete audit|delete logs|hide audit|erase evidence)\b/.test(normalized);
        const privacyQuestion = /\b(private|public|sensitive|confidential|personal data|permission|allowed|anonymi[sz]e|redact|hide sensitive|safe version|remove names|what parts.*confidential|data should not be shared|without exposing)\b/.test(normalized);

        if (secretOrCredential || bypassRequest || crossUserData || unsafeAdminAction) {
            return {
                type: 'deny-sensitive',
                reason: secretOrCredential
                    ? 'credentials'
                    : bypassRequest || unsafeAdminAction
                        ? 'authorization'
                        : 'cross-user-data'
            };
        }
        if (privacyQuestion) {
            return { type: 'privacy-guidance' };
        }
        return null;
    },

    handleSafetyGuardrail(intent) {
        if (!intent) return;
        if (intent.type === 'deny-sensitive') {
            this.pushMessage({
                role: 'assistant',
                text: 'I cannot reveal secrets, private session data, or help bypass permissions. I can still help you reach the authorized views and prepare a safe summary.',
                bullets: [
                    'Keep passwords, API keys, sync secrets, tokens, and session identifiers out of chat and exports.',
                    'Admin/device actions should stay behind the app permission flow and audit trail.',
                    'For sharing, use a redacted summary or CSV that removes personal and credential-like fields.'
                ],
                actions: [
                    { type: 'handbook', label: 'Open privacy guidance', pageKey: 'admin', collapsePanel: true },
                    { type: 'route', label: 'Open reports safely', page: 'reports', collapsePanel: true },
                    { type: 'route', label: 'Open settings checkup', page: 'settings', focusLocalCheckup: true, collapsePanel: true }
                ]
            });
            return;
        }

        this.pushMessage({
            role: 'assistant',
            text: 'Yes. I can help keep the output permission-aware and safe to share.',
            bullets: [
                'Use summaries, counts, dates, camera/location labels, and violation categories when a broad audience only needs the safety picture.',
                'Redact names, credentials, sync secrets, tokens, private chat/session data, and anything outside the current user role.',
                'If admin details are needed, open the approved admin/settings area instead of exposing them in a general chat answer.'
            ],
            actions: [
                { type: 'route', label: 'Open analytics summary', page: 'analytics', collapsePanel: true },
                { type: 'route', label: 'Open reports', page: 'reports', collapsePanel: true },
                { type: 'handbook', label: 'Open admin guidance', pageKey: 'admin', collapsePanel: true }
            ]
        });
    },

    getAssistantTopicModels() {
        return [
            {
                id: 'reports',
                label: 'Reports',
                pattern: /\b(reports?|report history|incident records?|evidence list)\b/,
                action: { type: 'route', label: 'Open reports', page: 'reports', collapsePanel: true }
            },
            {
                id: 'analytics',
                label: 'Analytics',
                pattern: /\b(analytics|metrics?|statistics|stats|numbers?|trends?|dashboard|risk|count|counts)\b/,
                action: { type: 'route', label: 'Open analytics', page: 'analytics', collapsePanel: true }
            },
            {
                id: 'live',
                label: 'Live Monitor',
                pattern: /\b(live|camera|stream|monitor|supervision|supervise|watch)\b/,
                action: { type: 'route', label: 'Open live monitor', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true }
            },
            {
                id: 'image',
                label: 'Image Analysis',
                pattern: /\b(image|upload|photo|picture|snapshot|still image)\b/,
                action: { type: 'route', label: 'Open Image Analysis', page: 'live', liveMode: 'upload', liveFocus: 'upload', collapsePanel: true }
            },
            {
                id: 'settings',
                label: 'Settings',
                pattern: /\b(settings|checkup|local mode|cloud mode|profile|readiness)\b/,
                action: { type: 'route', label: 'Open settings checkup', page: 'settings', focusLocalCheckup: true, collapsePanel: true }
            },
            {
                id: 'tutorial',
                label: 'Tutorial',
                pattern: /\b(tutorial|guide|walkthrough|teach|steps?)\b/,
                action: { type: 'tutorial', label: 'Show cloud tutorial', flow: 'cloud', stepIndex: 0 }
            },
            {
                id: 'handbook',
                label: 'Handbook',
                pattern: /\b(handbook|manual|docs|documentation|help article)\b/,
                action: { type: 'handbook', label: 'Open handbook', pageKey: 'intro', collapsePanel: true }
            },
            {
                id: 'export',
                label: 'CSV export',
                pattern: /\b(export|download|csv|spreadsheet)\b/,
                action: { type: 'route', label: 'Open analytics', page: 'analytics', collapsePanel: true }
            }
        ];
    },

    getTopicLabel(ids = []) {
        const models = this.getAssistantTopicModels();
        const labels = ids
            .map((id) => models.find((model) => model.id === id)?.label)
            .filter(Boolean);
        if (!labels.length) return 'that area';
        if (labels.length === 1) return labels[0];
        return `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`;
    },

    buildAlternativeActions(avoidIds = [], preferredIds = []) {
        const avoid = new Set(avoidIds);
        const seen = new Set();
        const models = this.getAssistantTopicModels();
        const orderedIds = [
            ...preferredIds,
            'analytics',
            'live',
            'image',
            'settings',
            'handbook',
            'tutorial',
            'reports'
        ];
        const actions = [];
        orderedIds.forEach((id) => {
            if (avoid.has(id) || seen.has(id)) return;
            const model = models.find((item) => item.id === id);
            if (!model) return;
            seen.add(id);
            actions.push(model.action);
        });
        return actions.slice(0, 3);
    },

    resolveLanguageGuardrail(raw, query = '') {
        const rawText = String(raw || '').toLowerCase();
        const normalized = query || this.normalizeText(raw);
        const profanityPattern = /\b(f+u+c+k+|fxxk|f[\W_]*u?[\W_]*c[\W_]*k|wtf|sh+i+t+|damn|bitch|asshole|idiot|stupid)\b/i;
        if (!profanityPattern.test(rawText) && !profanityPattern.test(normalized)) return null;
        const topicIds = this.getAssistantTopicModels()
            .filter((model) => model.pattern.test(normalized))
            .map((model) => model.id);
        return {
            type: topicIds.length || this.hasCasmDomainSignal(normalized) ? 'frustrated-task' : 'abusive-only',
            topicIds
        };
    },

    handleLanguageGuardrail(intent) {
        if (!intent) return;
        if (intent.type === 'frustrated-task') {
            this.pushMessage({
                role: 'assistant',
                text: 'I can tell this is frustrating. I will keep the chat work-focused and help with the CASM task without matching that language.',
                bullets: [
                    intent.topicIds.length
                        ? `I detected the topic as ${this.getTopicLabel(intent.topicIds)}.`
                        : 'Tell me which CASM area failed: live monitoring, image analysis, reports, analytics, settings, or handbook.',
                    'Short, concrete wording works best, for example "reports not loading" or "show analytics this week".'
                ],
                actions: this.buildAlternativeActions([], intent.topicIds)
            });
            return;
        }

        this.pushMessage({
            role: 'assistant',
            text: 'I can help, but I need the wording to stay work-focused.',
            bullets: [
                'Ask about CASM monitoring, image checks, reports, analytics, settings, exports, or tutorials.',
                'If something is broken, describe the page and what you expected to happen.'
            ],
            actions: this.buildAlternativeActions([], ['handbook', 'analytics', 'live'])
        });
    },

    resolveNegativePreference(raw, query = '') {
        const normalized = this.normalizeForNlu(raw || query);
        if (!normalized) return null;
        const avoidedIds = [];
        const models = this.getAssistantTopicModels();

        const topicMatches = models
            .map((model) => {
                const match = normalized.match(model.pattern);
                return match && typeof match.index === 'number'
                    ? { id: model.id, index: match.index }
                    : null;
            })
            .filter(Boolean)
            .sort((a, b) => a.index - b.index);

        const negativeCuePattern = /\b(?:dont|do not|never)\s+(?:want|need|open|show|see|view|use|export|download|go(?: to)?|look at)\b|\b(?:avoid|skip|hide|without)\b/g;
        Array.from(normalized.matchAll(negativeCuePattern)).forEach((match) => {
            const cueIndex = Number(match.index || 0);
            const nearest = topicMatches.find((topic) => topic.index >= cueIndex && topic.index - cueIndex <= 72);
            if (nearest) avoidedIds.push(nearest.id);
        });

        models.forEach((model) => {
            const source = model.pattern.source;
            const explicitNo = new RegExp(`\\bno\\s+(?:the\\s+)?${source}`, 'i');
            const directNot = new RegExp(`\\bnot\\s+(?:the\\s+)?${source}`, 'i');
            const targetBeforeNegative = new RegExp(`${source}.{0,36}\\b(?:no need|not needed|skip it|avoid it|hide it)\\b`, 'i');
            if (explicitNo.test(normalized) || directNot.test(normalized) || targetBeforeNegative.test(normalized)) {
                avoidedIds.push(model.id);
            }
        });

        const avoidedUnique = Array.from(new Set(avoidedIds));
        if (!avoidedUnique.length) return null;
        const requestedIds = topicMatches
            .map((topic) => topic.id)
            .filter((id) => !avoidedUnique.includes(id));
        return {
            avoidedIds: avoidedUnique,
            requestedIds: Array.from(new Set(requestedIds))
        };
    },

    handleNegativePreference(intent) {
        const avoidedLabel = this.getTopicLabel(intent.avoidedIds);
        const requestedLabel = this.getTopicLabel(intent.requestedIds);
        const hasPreferredPath = Array.isArray(intent.requestedIds) && intent.requestedIds.length > 0;
        this.pushMessage({
            role: 'assistant',
            text: `Got it. I will not open ${avoidedLabel} for that request.`,
            bullets: [
                hasPreferredPath
                    ? `I read the positive part as ${requestedLabel}, so I am keeping the actions pointed there.`
                    : 'I read the negative wording as a preference, not as a command to open that page.',
                'Use "instead" or "just" when you want Mira to choose a different page.'
            ],
            actions: this.buildAlternativeActions(intent.avoidedIds, intent.requestedIds)
        });
    },

    getSemanticAnswerModels() {
        return [
            {
                id: 'system-purpose',
                label: 'system purpose',
                examples: [
                    'what is this system for',
                    'what does this system do',
                    'what does casm do',
                    'what is casm',
                    'what is ppe safety monitor',
                    'what is this app used for',
                    'what is it used for',
                    'explain this system',
                    'tell me about the system',
                    'why do we use this system'
                ],
                keywords: ['casm', 'system', 'purpose', 'used', 'ppe', 'safety', 'monitor', 'construction', 'compliance', 'violation'],
                text: 'CASM is a PPE safety monitoring system for construction or worksite supervision. It helps users watch camera feeds or uploaded images, detect missing PPE, record violations, and turn those detections into reports and analytics.',
                bullets: [
                    'Use Live Monitor for real-time camera supervision.',
                    'Use Image Analysis when you only need to check uploaded photos.',
                    'Use Reports and Analytics to review evidence, trends, severity, source tags, and compliance progress.',
                    'Mira can explain workflows and open the right page, without needing an external LLM API for these basic answers.'
                ],
                actions: [
                    { type: 'route', label: 'Open live monitor', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true },
                    { type: 'route', label: 'Open analytics', page: 'analytics', collapsePanel: true },
                    { type: 'tutorial', label: 'Show cloud tutorial', flow: 'cloud', stepIndex: 0 }
                ]
            },
            {
                id: 'how-it-works',
                label: 'how the system works',
                examples: [
                    'how does this system work',
                    'how does it work',
                    'how does the pipeline work',
                    'what is the process',
                    'what happens in the workflow',
                    'explain the detection flow',
                    'how are reports generated',
                    'how does casm detect violations',
                    'how does the app turn camera images into reports',
                    'how does detection become analytics'
                ],
                keywords: ['how', 'work', 'pipeline', 'process', 'flow', 'camera', 'image', 'detect', 'report', 'analytics', 'caption'],
                text: 'At a high level, CASM takes camera frames or uploaded images, runs PPE detection, stores violation records, then generates reports and analytics so supervisors can review what happened.',
                bullets: [
                    'Live mode watches an active camera stream and logs PPE issues as they appear.',
                    'Image mode checks selected photos as a one-off inspection workflow.',
                    'Reports preserve incident evidence and status; analytics summarizes trends, severity, sources, and readiness.',
                    'Cloud and local paths can both exist, but their source tags should stay consistent.'
                ],
                actions: [
                    { type: 'route', label: 'Open live monitor', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true },
                    { type: 'route', label: 'Open reports', page: 'reports', collapsePanel: true },
                    { type: 'handbook', label: 'Open workflow guide', pageKey: 'workflow', collapsePanel: true }
                ]
            },
            {
                id: 'ppe-detection',
                label: 'PPE detection coverage',
                examples: [
                    'what can it detect',
                    'what ppe can it detect',
                    'what equipment does it check',
                    'does it detect helmet and vest',
                    'what violations are detected',
                    'what safety gear is checked',
                    'what missing ppe does it look for',
                    'can it check uploaded images for missing ppe',
                    'can this system check whether workers are missing helmets vests gloves masks goggles or safety shoes',
                    'can image analysis detect missing ppe',
                    'what ppe can it check from uploaded photos'
                ],
                keywords: ['detect', 'check', 'ppe', 'helmet', 'hardhat', 'vest', 'gloves', 'mask', 'goggles', 'boots', 'shoes', 'equipment', 'gear', 'missing', 'worker', 'upload', 'image'],
                text: 'CASM focuses on PPE compliance. The dashboard and reports track missing hardhat or helmet, safety vest, gloves, mask or respirator, goggles, and safety shoes or boots where those classes are available in the detection result.',
                bullets: [
                    'The exact classes shown depend on what the detector reports for a frame or image.',
                    'Reports keep the missing-PPE labels so the same evidence can be reviewed later.',
                    'Analytics groups those labels into violation types for trend review.'
                ],
                actions: [
                    { type: 'route', label: 'Open Image Analysis', page: 'live', liveMode: 'upload', liveFocus: 'upload', collapsePanel: true },
                    { type: 'route', label: 'Open analytics', page: 'analytics', collapsePanel: true },
                    { type: 'handbook', label: 'Open PPE guidelines', pageKey: 'ppe', collapsePanel: true }
                ]
            },
            {
                id: 'violation-reporting',
                label: 'violation reports',
                examples: [
                    'what happens when a violation is found',
                    'what happens after detection',
                    'how are violations reported',
                    'where do reports go',
                    'what are reports for',
                    'how do i read the reports',
                    'what does report status mean'
                ],
                keywords: ['violation', 'detected', 'report', 'reports', 'status', 'queued', 'generating', 'ready', 'evidence', 'review'],
                text: 'When CASM records a PPE violation, it creates a report row that can move through states like queued, generating, ready, failed, local, or local synced. Reports are where you review the evidence and generated safety summary.',
                bullets: [
                    'Open Reports for individual incident rows and evidence.',
                    'Open Analytics for the bigger pattern across many reports.',
                    'Use source tags carefully: Cloud, Local, and Local Synced describe where the report came from.'
                ],
                actions: [
                    { type: 'route', label: 'Open reports', page: 'reports', collapsePanel: true },
                    { type: 'route', label: 'Open analytics', page: 'analytics', collapsePanel: true },
                    { type: 'handbook', label: 'Open reports guide', pageKey: 'workflow', stageKey: 'reports', collapsePanel: true }
                ]
            },
            {
                id: 'local-cloud-offline',
                label: 'local and cloud modes',
                examples: [
                    'what is local mode',
                    'what is cloud mode',
                    'local vs cloud',
                    'can it work offline',
                    'what happens when wifi drops',
                    'do i need internet',
                    'what is local synced',
                    'how does sync work',
                    'what happens when the internet connection becomes unstable',
                    'what happens when reports are created locally first and sync later',
                    'what should happen when connection comes back',
                    'how do local reports synchronize again'
                ],
                keywords: ['local', 'cloud', 'offline', 'wifi', 'network', 'connection', 'connectivity', 'sync', 'synchronize', 'synced', 'internet', 'host', 'approved', 'provision'],
                text: 'Cloud mode uses the hosted backend path. Local mode is for an approved host machine that can keep working locally when connectivity is poor. A local-origin report should only become Local Synced after reconnect and confirmed upload.',
                bullets: [
                    'Run Local Mode Checkup before relying on local mode.',
                    'During disconnection, local reports should remain Local.',
                    'After connectivity returns, synced local reports can appear as Local Synced.',
                    'Mira can explain these terms offline; checking live machine health still depends on the app data available to the browser.'
                ],
                actions: [
                    { type: 'route', label: 'Open settings checkup', page: 'settings', focusLocalCheckup: true, collapsePanel: true },
                    { type: 'tutorial', label: 'Show local tutorial', flow: 'local', stepIndex: 0 },
                    { type: 'handbook', label: 'Open local guide', pageKey: 'workflow', stageKey: 'local', collapsePanel: true }
                ]
            },
            {
                id: 'assistant-offline-nlp',
                label: 'Mira offline NLP',
                examples: [
                    'do you need api',
                    'do you use api',
                    'can you answer without api',
                    'can you work without internet',
                    'how do you understand my question',
                    'do you have nlp',
                    'are you an ai assistant',
                    'what can mira answer',
                    'what can the assistant do',
                    'are you calling an online ai model',
                    'are you using a third party api',
                    'do you call an external ai service',
                    'can you understand basic questions inside the app without third party api',
                    'can you answer casm questions without an online model'
                ],
                keywords: ['mira', 'assistant', 'api', 'offline', 'nlp', 'understand', 'question', 'answer', 'natural language', 'without internet', 'external', 'third party', 'online', 'ai', 'model', 'service', 'browser'],
                text: 'Mira has a basic offline NLP layer in the browser. It normalizes the wording, expands common synonyms, scores likely intents, answers built-in CASM questions, and only uses app APIs when you ask for live data or exports.',
                bullets: [
                    'Plain explanations like system purpose, PPE coverage, report meaning, and local/cloud behavior do not need an external API.',
                    'Navigation and tutorial requests are handled by local intent rules.',
                    'Live metrics, reports, and CSV exports still use the app data source because those answers depend on current records.',
                    'Mira is not a general open-ended LLM; it is a focused CASM assistant with safe local NLP.'
                ],
                actions: [
                    { type: 'overview', label: 'Show live overview' },
                    { type: 'handbook', label: 'Open handbook', pageKey: 'intro', collapsePanel: true },
                    { type: 'route', label: 'Open analytics', page: 'analytics', collapsePanel: true }
                ]
            },
            {
                id: 'page-map',
                label: 'where things are',
                examples: [
                    'where should i go',
                    'which page should i use',
                    'what are the pages for',
                    'where is the camera',
                    'where is analytics',
                    'where are reports',
                    'where do i start',
                    'where should i go if i want to start',
                    'which page should i open first',
                    'what page do i use first',
                    'which page should i open first if i want to monitor ppe compliance',
                    'where do i begin monitoring ppe compliance today'
                ],
                keywords: ['where', 'page', 'pages', 'home', 'live', 'camera', 'reports', 'analytics', 'settings', 'start'],
                text: 'Use Home for the overview, Live for camera or image checks, Reports for incident records, Analytics for trends and safety metrics, Settings for local readiness, and Handbook for guidance.',
                bullets: [
                    'If you want to supervise now, open Live Monitor.',
                    'If you want to review what already happened, open Reports or Analytics.',
                    'If you are preparing local/offline use, open Settings Checkup.'
                ],
                actions: [
                    { type: 'route', label: 'Open live monitor', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true },
                    { type: 'route', label: 'Open reports', page: 'reports', collapsePanel: true },
                    { type: 'route', label: 'Open settings checkup', page: 'settings', focusLocalCheckup: true, collapsePanel: true }
                ]
            }
        ];
    },

    isNaturalLanguageQuestion(query) {
        return /\b(what|how|why|where|when|which|who|can|could|does|do|is|are|explain|describe|tell me|meaning|mean|purpose|used for|about)\b/.test(query);
    },

    hasCasmDomainSignal(query) {
        return /\b(casm|system|app|assistant|mira|ppe|safety|construction|site|worker|monitor|camera|image|report|reports|analytics|violation|violations|helmet|hardhat|vest|glove|mask|goggle|boot|shoe|local|cloud|sync|settings|handbook)\b/.test(query);
    },

    resolveSemanticAnswer(raw, query = '') {
        const normalized = this.normalizeForNlu(raw || query);
        if (!normalized) return null;
        if (this.isExportIntent(normalized)) return null;

        const questionLike = this.isNaturalLanguageQuestion(normalized);
        const negatesLiveData = /\b(not asking for|not looking for|do not need|dont need|without)\b.{0,36}\b(current|live|latest|analytics|statistics|metrics|numbers|counts|snapshot|data)\b/.test(normalized)
            || /\b(just|only)\b.{0,24}\b(want|need)\b.{0,36}\b(know|understand|explain|which page|where|how to start)\b/.test(normalized);
        const liveDataQuestion = /\b(how many|count|number|latest|trend|trends|today|yesterday|week|month|high|medium|low|analytics|metric|metrics|score|rate|happened|any)\b/.test(normalized)
            && /\b(violation|violations|incident|incidents|helmet|hardhat|vest|ppe|report|reports|analytics|score|metric|metrics|compliance|risk)\b/.test(normalized);
        if (liveDataQuestion && !negatesLiveData) return null;

        const actionOnly = /\b(open|go|start|begin|export|download|switch|apply|use recommended|run checkup)\b/.test(normalized)
            && !questionLike;
        if (actionOnly) return null;

        const tokens = this.expandIntentTokens(this.tokenizeForIntent(normalized));
        const scored = this.getSemanticAnswerModels()
            .map((model) => this.scoreSemanticAnswerModel(model, normalized, tokens, questionLike))
            .sort((a, b) => b.confidence - a.confidence);
        const best = scored[0] || null;
        if (best && best.confidence >= 0.46) {
            return best;
        }

        if (questionLike && this.hasCasmDomainSignal(normalized)) {
            const docs = this.searchDocs(raw).slice(0, 3);
            if (docs.length) {
                return {
                    id: 'handbook-semantic-fallback',
                    label: 'handbook answer',
                    confidence: 0.42,
                    text: 'I can answer that from the built-in CASM guide rather than an external AI service. These are the closest local handbook matches I found.',
                    bullets: [
                        'This is an offline semantic match from the page handbook/glossary content.',
                        'Open a matched section if you want the detailed workflow view.'
                    ],
                    docs: docs.map((doc, index) => ({
                        label: doc.label,
                        title: doc.title,
                        snippet: doc.snippet,
                        actionIndex: index
                    })),
                    actions: docs.map((doc) => ({
                        type: 'doc-result',
                        label: doc.title,
                        pageKey: doc.pageKey || 'intro',
                        stageKey: doc.stageKey || '',
                        tutorialFlow: doc.tutorialFlow || '',
                        tutorialStep: Number(doc.tutorialStep || 0)
                    }))
                };
            }

            return {
                id: 'casm-domain-fallback',
                label: 'CASM domain fallback',
                confidence: 0.38,
                text: 'I can answer CASM workflow questions without an external API, but I need one more concrete clue to avoid guessing.',
                bullets: [
                    'Ask about purpose, live monitoring, image checks, PPE classes, reports, analytics, local mode, cloud mode, or settings.',
                    'For current counts or CSV files, I will use the app data source because those answers depend on live records.'
                ],
                actions: [
                    { type: 'handbook', label: 'Open handbook', pageKey: 'intro', collapsePanel: true },
                    { type: 'tutorial', label: 'Show cloud tutorial', flow: 'cloud', stepIndex: 0 }
                ]
            };
        }

        return null;
    },

    scoreSemanticAnswerModel(model, normalized, tokens, questionLike) {
        const expandedTokenSet = new Set(tokens);
        const examples = Array.isArray(model.examples) ? model.examples : [];
        const exactExample = examples.some((example) => {
            const normalizedExample = this.normalizeForNlu(example);
            return normalized === normalizedExample || normalized.includes(normalizedExample);
        });
        const exampleScores = examples.map((example) => {
            const exampleTokens = this.expandIntentTokens(this.tokenizeForIntent(this.normalizeForNlu(example)));
            if (!exampleTokens.length) return 0;
            const exampleSet = new Set(exampleTokens);
            const overlap = Array.from(exampleSet).filter((token) => expandedTokenSet.has(token)).length;
            const coverage = overlap / Math.max(1, Math.min(exampleSet.size, expandedTokenSet.size || 1));
            const jaccard = overlap / Math.max(1, new Set([...exampleSet, ...expandedTokenSet]).size);
            return (coverage * 0.72) + (jaccard * 0.28);
        });
        const keywordTokens = this.expandIntentTokens(this.tokenizeForIntent((model.keywords || []).join(' ')));
        const keywordMatches = keywordTokens.filter((token) => expandedTokenSet.has(token)).length;
        const keywordScore = keywordTokens.length
            ? Math.min(1, keywordMatches / Math.min(keywordTokens.length, 7))
            : 0;
        const questionBoost = questionLike ? 0.08 : 0;
        const exactBoost = exactExample ? 0.54 : 0;
        const modelBoost = this.getSemanticModelCueBoost(model.id, normalized);
        let confidence = Math.min(0.99, exactBoost + (Math.max(0, ...exampleScores) * 0.34) + (keywordScore * 0.28) + questionBoost + modelBoost);
        if (model.id === 'page-map'
            && !exactExample
            && !/\b(where|which page|what page|pages?|open|go|begin|start|first|navigate)\b/.test(normalized)) {
            confidence = Math.min(confidence, 0.42);
        }
        return {
            ...model,
            confidence: Number(confidence.toFixed(3))
        };
    },

    getSemanticModelCueBoost(modelId, normalized) {
        if (modelId === 'ppe-detection'
            && /\b(detect|check|missing|ppe|equipment|gear|helmet|hardhat|vest|gloves?|mask|goggles?|boots?|shoes?|worker|image|upload)\b/.test(normalized)
            && /\b(image|upload|camera|worksite|worker|helmet|hardhat|vest|gloves?|mask|goggles?|boots?|shoes?|ppe|equipment|gear)\b/.test(normalized)) {
            return 0.18;
        }
        if (modelId === 'local-cloud-offline'
            && /\b(local|offline|wifi|internet|network|connection|connectivity|sync|synchronize|synced|reconnect|cloud)\b/.test(normalized)) {
            return 0.2;
        }
        if (modelId === 'assistant-offline-nlp'
            && /\b(api|third party|external|online|ai model|llm|nlp|understand|answer|question)\b/.test(normalized)
            && /\b(assistant|mira|you|your|inside|browser|without|need|use|call|calling|model|service|api)\b/.test(normalized)) {
            return 0.2;
        }
        if (modelId === 'page-map'
            && /\b(where|which page|what page|pages?|open first|go first|start|begin|navigate)\b/.test(normalized)) {
            return 0.14;
        }
        if (modelId === 'system-purpose'
            && /\b(what|purpose|used for|supposed to|help|do|explain)\b/.test(normalized)
            && /\b(casm|system|app|project|safety|supervisor|construction|worksite)\b/.test(normalized)) {
            return 0.14;
        }
        return 0;
    },

    handleSemanticAnswer(answer) {
        this.pushMessage({
            role: 'assistant',
            text: answer.text,
            bullets: answer.bullets || [],
            docs: answer.docs || [],
            actions: answer.actions || []
        });
    },

    resolveCompoundIntent(raw, query = '', localIntent = null) {
        if (!query) return null;
        const hasCompoundCue = /\b(and|also|plus|then|after that|both|together|all together|at the same time|first|next|with)\b/.test(query)
            || /[,;]/.test(String(raw || ''));
        const longInstruction = String(raw || '').trim().length >= 90;
        if (!hasCompoundCue && !longInstruction) return null;

        const actions = [];
        const bullets = [];
        const addAction = (key, action, bullet = '') => {
            if (!action || actions.some((item) => item.key === key)) return;
            actions.push({ key, action });
            if (bullet && !bullets.includes(bullet)) bullets.push(bullet);
        };

        const wantsImage = /\b(image|photo|picture|snapshot|upload|still image|scan)\b/.test(query);
        const wantsLive = /\b(live|camera|feed|stream|monitor|supervision|supervise|watch|front gate|warehouse|entrance|perimeter)\b/.test(query) && !wantsImage;
        const wantsAnalytics = /\b(analytics|metric|metrics|chart|graph|trend|compliance|score|risk|summary|numbers|how many|violation|violations|incidents?|alerts?|helmet|hardhat|vest|ppe|unsafe|safety issue|bad stuff|top|compare|breakdown)\b/.test(query);
        const wantsReports = /\b(reports?|history|records?|audit trail|evidence|log|logs|incident list|latest incident|incidents?|raw data|table)\b/.test(query);
        const wantsAdmin = /\b(device|devices|camera list|ip address|edge|streamer|pending|approval|approve|authorize|provision|admin|offline|heartbeat|health)\b/.test(query);
        const wantsGuide = /\b(explain|simple|plain english|beginner|walk me|teach|where do i|how do i|guide|tutorial|manual|handbook)\b/.test(query);
        const wantsSettings = /\b(settings|profile|local mode|cloud mode|api mode|checkup|readiness)\b/.test(query);
        const filters = this.buildAnalyticsFilters(raw);
        const filterSummary = this.describeAnalyticsFilters(filters);

        if (wantsLive || localIntent?.id === 'start-live') {
            addAction(
                'live',
                { type: 'route', label: 'Open live monitor', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true },
                'Open Live Monitor for camera/feed checks and real-time supervision.'
            );
        }
        if (wantsImage || localIntent?.id === 'image-analysis') {
            addAction(
                'image',
                { type: 'route', label: 'Analyze images', page: 'live', liveMode: 'upload', liveFocus: 'upload', collapsePanel: true },
                'Use Analyze Image when the request is about uploaded photos or snapshots.'
            );
        }
        if (wantsAnalytics || localIntent?.id === 'analytics-snapshot') {
            addAction(
                'analytics',
                this.hasActiveAnalyticsFilters(filters)
                    ? { type: 'route', label: 'Open filtered analytics', page: 'analytics', analyticsFilters: filters, analyticsSummary: filterSummary || 'Filtered analytics view', collapsePanel: true }
                    : { type: 'route', label: 'Open analytics', page: 'analytics', collapsePanel: true },
                filterSummary ? `Apply the valid analytics filters I found: ${filterSummary}.` : 'Use Analytics for trends, counts, risk, and compliance summaries.'
            );
        }
        if (wantsReports || localIntent?.id === 'open-reports') {
            addAction(
                'reports',
                { type: 'route', label: 'Open reports', page: 'reports', collapsePanel: true },
                'Use Reports when you need the underlying incident rows, records, or evidence list.'
            );
        }
        if (wantsAdmin) {
            addAction(
                'admin',
                { type: 'handbook', label: 'Open admin/device guide', pageKey: 'admin', collapsePanel: true },
                'Device and approval questions stay in the admin/device guidance path.'
            );
        }
        if (wantsSettings || localIntent?.id === 'settings-recommend') {
            addAction(
                'settings',
                { type: 'route', label: 'Open settings checkup', page: 'settings', focusLocalCheckup: true, collapsePanel: true },
                'Use Settings Checkup for local/cloud readiness and operating profile decisions.'
            );
        }
        if (wantsGuide || localIntent?.id === 'tutorial' || localIntent?.id === 'docs-search') {
            addAction(
                'guide',
                { type: 'handbook', label: 'Open handbook', pageKey: 'intro', collapsePanel: true },
                'Use the handbook path when the request asks for explanation, training, or where to click.'
            );
        }

        if (actions.length < 2) return null;
        return {
            actions: actions.slice(0, 5).map((item) => item.action),
            bullets: bullets.slice(0, 4),
            filterSummary
        };
    },

    handleCompoundIntent(intent) {
        this.pushMessage({
            role: 'assistant',
            text: 'I read that as a combined request, so I split it into safe workspace actions instead of forcing only one interpretation.',
            bullets: [
                ...(intent.bullets || []),
                'I will not expose restricted admin, credential, or cross-user details in chat; those stay behind the approved app views.'
            ].slice(0, 5),
            actions: intent.actions || []
        });
    },

    recordUnmatchedPrompt(raw, query, intent = null) {
        const text = String(raw || '').trim();
        if (!text) return;
        try {
            const current = JSON.parse(localStorage.getItem(this.UNMATCHED_PROMPTS_KEY) || '[]');
            const rows = Array.isArray(current) ? current : [];
            rows.unshift({
                text: text.slice(0, 280),
                normalized: String(query || '').slice(0, 280),
                page: String((APP_STATE && APP_STATE.currentPage) || 'home'),
                bestIntent: intent ? {
                    id: intent.id,
                    label: intent.label,
                    confidence: intent.confidence,
                    alternatives: (intent.alternatives || []).slice(0, 3).map((item) => ({
                        id: item.id,
                        label: item.label,
                        confidence: item.confidence
                    }))
                } : null,
                createdAt: Date.now()
            });
            localStorage.setItem(this.UNMATCHED_PROMPTS_KEY, JSON.stringify(rows.slice(0, this.MAX_UNMATCHED_PROMPTS)));
        } catch (_) {
            // Ignore local review-log failures.
        }
    },

    normalizeForNlu(value) {
        let text = this.normalizeText(value);
        const replacements = [
            [/\bwanna\b/g, 'want to'],
            [/\bgonna\b/g, 'going to'],
            [/\bpls\b|\bplz\b/g, 'please'],
            [/\bthird[- ]party\b/g, 'third party'],
            [/\bstatistic(s)?\b|\bstats\b/g, 'analytics'],
            [/\banalysis dashboard\b/g, 'analytics'],
            [/\bsupervise\b|\bsupervision\b|\bsurveillance\b|\bpatrol\b|\bwatching\b/g, 'monitor'],
            [/\bphoto\b|\bpicture\b|\bsnapshot\b|\bscreenshot\b/g, 'image'],
            [/\bphotos\b|\bpictures\b|\bsnapshots\b|\bscreenshots\b/g, 'image'],
            [/\bfront gate\b|\bmain entrance\b|\bnorth gate\b|\bwest gate\b/g, 'camera location'],
            [/\bbad stuff\b|\bbad news\b|\bno good results\b|\bsafety problems?\b/g, 'violations'],
            [/\bmissing gear\b|\bforgot (their )?(helmet|hardhat|vest)\b/g, 'ppe violation'],
            [/\bhelmets\b/g, 'helmet'],
            [/\bhardhats\b/g, 'hardhat'],
            [/\bvests\b/g, 'vest'],
            [/\bmasks\b/g, 'mask'],
            [/\bboots\b/g, 'boots'],
            [/\bshoes\b/g, 'shoes'],
            [/\bworkers\b/g, 'worker'],
            [/\blocally\b/g, 'local'],
            [/\bsynchroni[sz](e|es|ed|ing|ation)?\b/g, 'sync'],
            [/\breconnect(ed|ing)?\b/g, 'sync'],
            [/\brealtime\b/g, 'real time'],
            [/\bppe check\b/g, 'ppe detection'],
            [/\btake me to\b|\bgo to\b|\bbring me to\b/g, 'open'],
            [/\badvise\b|\bsuggest\b/g, 'recommend']
        ];
        replacements.forEach(([pattern, replacement]) => {
            text = text.replace(pattern, replacement);
        });
        return text.replace(/\s+/g, ' ').trim();
    },

    tokenizeForIntent(value) {
        const stopWords = new Set([
            'the', 'and', 'for', 'with', 'that', 'this', 'from', 'into', 'what', 'when', 'where',
            'which', 'please', 'can', 'could', 'would', 'should', 'you', 'me', 'my', 'i', 'am',
            'is', 'are', 'to', 'a', 'an', 'of', 'in', 'on', 'it'
        ]);
        return this.normalizeText(value)
            .split(' ')
            .map((token) => token.trim())
            .filter((token) => token.length > 1 && !stopWords.has(token));
    },

    expandIntentTokens(tokens = []) {
        const synonyms = {
            monitor: ['supervision', 'supervise', 'watch', 'surveillance', 'stream', 'live'],
            live: ['monitor', 'camera', 'stream', 'realtime'],
            camera: ['live', 'stream', 'monitor'],
            image: ['photo', 'picture', 'snapshot', 'upload'],
            analytics: ['stats', 'metrics', 'dashboard', 'trend', 'summary'],
            report: ['reports', 'history', 'violation'],
            reports: ['report', 'history', 'violations'],
            export: ['download', 'csv', 'save'],
            download: ['export', 'csv', 'save'],
            settings: ['profile', 'configuration', 'config'],
            recommend: ['suggest', 'advise', 'best'],
            docs: ['manual', 'handbook', 'documentation', 'faq'],
            tutorial: ['guide', 'walkthrough', 'demo'],
            start: ['begin', 'run', 'open'],
            open: ['go', 'show', 'launch'],
            hardhat: ['helmet'],
            helmet: ['hardhat'],
            boots: ['shoes'],
            shoes: ['boots']
        };
        const expanded = new Set(tokens);
        tokens.forEach((token) => {
            (synonyms[token] || []).forEach((value) => expanded.add(value));
        });
        return Array.from(expanded);
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
        return /\b(overview|summary|metrics|status|health|system running|services online|online|all clear|everything fine|everything okay|site safe|safe right now|current status|analytics snapshot)\b/.test(query);
    },

    isTargetedStatusIntent(query) {
        return /\b(camera|device|edge|streamer|admin|pending|approval|warehouse|gate|entrance|zone|area|perimeter)\b/.test(query)
            && /\b(status|health|online|offline|running|working|active|failing|broken)\b/.test(query);
    },

    isOnboardingIntent(query) {
        return /\b(i m new|new here|where do i start|what should i do|dont know|do not know|not sure|what can you do|how do i use this|how do i start|first time|help me understand)\b/.test(query);
    },

    isTutorialIntent(query) {
        return /\b(tutorial|walkthrough|demo|guide|next step|previous step|prev step|continue tutorial|cloud mode|local mode)\b/.test(query);
    },

    isExplanationQuestion(query) {
        return /\b(what is|what does|explain|meaning|mean|how does|why does|tell me about|describe)\b/.test(query);
    },

    isCapabilityIntent(query) {
        return /\b(what can you do|what can you help me with|what can you help with|what kinds of things|what data do you have access to|explain your limitations|your limitations|do you understand|can you handle|how do you decide|what if i ask|use you for a beginner)\b/.test(query);
    },

    handleOnboardingIntent() {
        this.pushMessage({
            role: 'assistant',
            text: 'No problem. If you are new here, I can guide you through the easiest starting paths instead of expecting you to know the system already.',
            bullets: [
                'Start live monitoring if you want a real-time camera session with report generation.',
                'Use image analysis if you only want to check one still image for violations.',
                'Open analytics if you want a quick operational snapshot before doing anything else.',
                'Use recommended settings if you want the balanced default profile first.'
            ],
            actions: [
                { type: 'route', label: 'Open camera', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true },
                { type: 'route', label: 'Open image analysis', page: 'live', liveMode: 'upload', liveFocus: 'upload', collapsePanel: true },
                { type: 'route', label: 'Open analytics', page: 'analytics', collapsePanel: true },
                { type: 'settings-profile', label: 'Use recommended settings', profile: 'recommended' },
                { type: 'tutorial', label: 'Show local tutorial', flow: 'local', stepIndex: 0 }
            ]
        });
    },

    handleCapabilityIntent() {
        this.pushMessage({
            role: 'assistant',
            text: 'I can help with CASM workflows using local, deterministic intent rules so normal prompts stay quick and low-cost.',
            bullets: [
                'I can open Live Monitor, image analysis, reports, analytics, settings, tutorials, and handbook sections.',
                'I can understand short, messy, code-switched, or combined requests and split them into safe actions.',
                'I can export CSVs and apply valid analytics/report filters, while ignoring unsupported filters instead of breaking the page.',
                'I do not reveal credentials, sync secrets, private sessions, or cross-user/admin data in chat.'
            ],
            actions: [
                { type: 'route', label: 'Open live monitor', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true },
                { type: 'route', label: 'Open analytics', page: 'analytics', collapsePanel: true },
                { type: 'route', label: 'Analyze images', page: 'live', liveMode: 'upload', liveFocus: 'upload', collapsePanel: true },
                { type: 'handbook', label: 'Open handbook', pageKey: 'intro', collapsePanel: true }
            ]
        });
    },

    async handleExportIntent(raw, query) {
        if (/\b(analytics|metrics|overview)\b/.test(query)) {
            this.updateResponseFeedback('Preparing the analytics export...');
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
            this.updateResponseFeedback('Preparing the handbook export...');
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

        this.updateResponseFeedback('Preparing the report export preview...');
        const outcome = await this.exportReportsCsv(raw);
        const previewBullets = outcome.success
            ? [
                `Matched rows: ${outcome.rowCount}${outcome.filterSummary ? ` using ${outcome.filterSummary}` : ''}.`,
                ...(outcome.previewRows || []).map((row) => `${row.report_id || 'unknown'} | ${row.timestamp || 'time unknown'} | ${row.severity || 'unknown'} | ${row.status || 'unknown'} | ${row.source_label || row.source_scope || 'unknown source'} | ${row.missing_ppe || 'no PPE labels'}`)
            ]
            : [];
        this.pushMessage({
            role: 'assistant',
            text: outcome.success
                ? 'Reports CSV is prepared. Review the preview, then download it when you are happy with the filter.'
                : outcome.message,
            bullets: previewBullets,
            actions: [
                ...(outcome.success ? [{
                    type: 'download-prepared-csv',
                    label: 'Download CSV',
                    exportId: outcome.exportId,
                    filename: outcome.filename
                }] : []),
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
        this.upsertTutorialMessage(flow, index, steps);
    },

    buildTutorialActions(flow, index, steps) {
        const actions = [
            { type: 'tutorial', label: 'Previous step', flow, stepIndex: Math.max(0, index - 1) },
            { type: 'tutorial', label: 'Next step', flow, stepIndex: Math.min(steps.length - 1, index + 1) }
        ];

        if (flow === 'local' && index === 0) {
            actions.push({ type: 'route', label: 'Open settings checkup', page: 'settings', focusLocalCheckup: true, collapsePanel: true });
        } else if (flow === 'local' && (index === 1 || index === 2)) {
            actions.push({ type: 'route', label: 'Open live monitor', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true });
        } else if (flow === 'local' && index >= steps.length - 1) {
            actions.push({ type: 'route', label: 'Open reports', page: 'reports', collapsePanel: true });
        } else if (flow === 'cloud' && index <= 1) {
            actions.push({ type: 'route', label: 'Open live monitor', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true });
        } else if (flow === 'cloud' && index >= steps.length - 2) {
            actions.push({ type: 'route', label: 'Open reports', page: 'reports', collapsePanel: true });
        }

        actions.push({ type: 'handbook', label: 'Open in handbook', pageKey: 'workflow', tutorialFlow: flow, tutorialStep: index, collapsePanel: true });
        return actions;
    },

    buildTutorialMessage(flow, index, steps) {
        const step = steps[index] || {};
        return {
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
            actions: this.buildTutorialActions(flow, index, steps)
        };
    },

    getLatestTutorialMessageIndex(session) {
        if (!session || !Array.isArray(session.messages)) return -1;
        for (let index = session.messages.length - 1; index >= 0; index -= 1) {
            const message = session.messages[index];
            if (message && message.role === 'assistant' && message.tutorial) {
                return index;
            }
        }
        return -1;
    },

    refreshSessionUi() {
        this.renderMessages();
        this.renderSessionRail();
        this.saveState();
    },

    shouldUpdateInteractiveMessageInPlace(session, existingIndex) {
        if (!session || !Array.isArray(session.messages)) return false;
        return existingIndex >= 0 && existingIndex === session.messages.length - 1;
    },

    upsertTutorialMessage(flow, index, steps) {
        const session = this.getActiveSession();
        if (!session) return;
        const tutorialMessage = this.buildTutorialMessage(flow, index, steps);
        const existingIndex = this.getLatestTutorialMessageIndex(session);
        if (this.shouldUpdateInteractiveMessageInPlace(session, existingIndex)) {
            const existing = session.messages[existingIndex];
            session.messages[existingIndex] = this.normalizeMessage({
                ...existing,
                ...tutorialMessage,
                id: existing.id,
                createdAt: existing.createdAt
            });
            session.updatedAt = Date.now();
            this.refreshSessionUi();
            return;
        }
        this.pushMessage(tutorialMessage);
    },

    resolveWorkflowIntent(query) {
        const intents = [
            {
                match: /\b(start live|start monitoring|start camera|open camera|open live|live monitoring|use camera stream|start supervision|begin supervision|site supervision|supervise site|start supervise|begin monitoring|start site watch|watch the site)\b/,
                text: 'I read that as starting site supervision, so the Live Monitor workflow is the right place. I can take you there and collapse the chat so the camera controls stay usable.',
                bullets: [
                    'I will place you on Live Monitor with the camera stream workflow ready.',
                    'Use Start after the preview area is visible and the camera source looks right.',
                    'Reopen Mira anytime from the launcher; this same session stays here.'
                ],
                actions: [
                    { type: 'route', label: 'Open Live Monitor', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true },
                    { type: 'tutorial', label: 'Show cloud tutorial', flow: 'cloud', stepIndex: 0 },
                    { type: 'route', label: 'Open settings checkup', page: 'settings', focusLocalCheckup: true, collapsePanel: true }
                ]
            },
            {
                match: /\b(upload image|analy[sz]e image|check (if )?(this )?image|see if (this )?image|inspect image|review image|image .*violat)\b/,
                text: 'For a single-image check, use Live Monitor in Analyze Image mode. I can open that view and land you right on the upload area.',
                bullets: [
                    'This path is best when you want one still image reviewed instead of a full live session.',
                    'Use the upload area, then run Analyze for PPE Violations.',
                    'Mira will remember this conversation when you reopen the panel.'
                ],
                actions: [
                    { type: 'route', label: 'Open Image Analysis', page: 'live', liveMode: 'upload', liveFocus: 'upload', collapsePanel: true },
                    { type: 'handbook', label: 'Open upload guide', pageKey: 'workflow', stageKey: 'capture', collapsePanel: true },
                    { type: 'tutorial', label: 'Show cloud tutorial', flow: 'cloud', stepIndex: 0 }
                ]
            }
        ];
        return intents.find((intent) => intent.match.test(query)) || null;
    },

    handleWorkflowIntent(intent) {
        this.pushMessage({
            role: 'assistant',
            text: intent.text,
            bullets: intent.bullets || [],
            actions: intent.actions || []
        });
    },

    resolveSettingsIntent(query) {
        const intents = [
            { match: /\b(recommend(ed)? settings|best settings|which settings should i use)\b/, type: 'recommendation' },
            { match: /\b(apply recommended settings|use recommended settings)\b/, type: 'apply-recommended' },
            { match: /\b(switch to api mode|switch to cloud mode|apply api mode|apply cloud profile|cloud profile)\b/, type: 'apply-api' },
            { match: /\b(switch to local mode|apply local profile|local profile)\b/, type: 'apply-local' }
        ];
        return intents.find((intent) => intent.match.test(query)) || null;
    },

    async handleSettingsIntent(intent) {
        if (!intent) return;
        if (intent.type === 'recommendation') {
            this.pushMessage({
                role: 'assistant',
                text: 'I can recommend or apply the main operating profiles for you. Recommended settings are the safest balanced default, API mode favors hosted cloud smoothness, and Local profile prepares the approved host path.',
                bullets: [
                    'Recommended settings keep the general deployment balanced for everyday use.',
                    'API mode is the best pick when you want the smoothest hosted cloud workflow.',
                    'Local profile is for approved host machines that need the local pipeline.'
                ],
                actions: [
                    { type: 'settings-profile', label: 'Use recommended settings', profile: 'recommended' },
                    { type: 'settings-profile', label: 'Switch to API mode', profile: 'api' },
                    { type: 'settings-profile', label: 'Apply local profile', profile: 'local' },
                    { type: 'route', label: 'Open settings', page: 'settings', collapsePanel: true }
                ]
            });
            return;
        }

        const profile = intent.type === 'apply-api'
            ? 'api'
            : intent.type === 'apply-local'
                ? 'local'
                : 'recommended';
        await this.applySettingsProfile(profile);
    },

    resolveAnalyticsIntent(raw, query) {
        if (!query) return null;
        const offTopicOnly = /\b(weather|pizza|joke|game|capital|bored|banana|universe|homework|recipe|song|movie)\b/.test(query)
            && !/\b(camera|report|reports|analytics|metric|violation|violations|incident|alert|ppe|helmet|hardhat|vest|site|safety|safe|compliance|dashboard|system)\b/.test(query);
        if (offTopicOnly) return null;
        const directOpen = /\b(open|go to|take me to)\s+(the\s+)?analytics\b/.test(query);
        const analyticsMatch = /\b(analytics|metric|metrics|data|ready rate|high severity|severity share|trend|trends|chart|graph|peak window|safety score|compliance score|dashboard stats?|violation count|how many violations|last violation|incident|incidents|alert|alerts|risk|unsafe|safety issue|issues?|problems?|bad stuff|ppe|helmet|hardhat|vest|glove|mask|goggle|boot|shoe|site|happen|happened|going on|important|main)\b/.test(query);
        const filterMatch = /\b(cloud|local|local synced|high|medium|low|today|yesterday|last 24 hours|week|seven days|7 days|month|helmet|hardhat|vest|gloves?|mask|goggles?|boots?|shoes?)\b/.test(query);
        const queryMatch = /\b(show|give|see|summari[sz]e|snapshot|compare|compared|comparison|tell me|what is|what happened|what happen|how many|count|find|list|filter|only|just|latest|any|did|have|had|data|highlight|main|important|more|fewer|need|want)\b/.test(query);
        if (directOpen && !filterMatch) {
            return null;
        }
        if (!analyticsMatch && !(filterMatch && queryMatch)) {
            return null;
        }
        const filters = this.buildAnalyticsFilters(raw);
        return {
            raw,
            query,
            filters,
            filterSummary: this.describeAnalyticsFilters(filters)
        };
    },

    buildAnalyticsFilters(rawQuery = '') {
        const base = this.sanitizeAnalyticsFilters(this.buildReportFilters(rawQuery));
        const ppeTypes = this.extractAnalyticsPpeTypes(rawQuery);
        return this.sanitizeAnalyticsFilters({
            ...base,
            ppeTypes
        });
    },

    sanitizeAnalyticsFilters(filters = {}) {
        const cleaned = {};
        const sources = this.normalizeSourceFilterValues(filters, false);
        if (sources.length === 1) {
            cleaned.source = sources[0];
        } else if (sources.length > 1) {
            cleaned.sources = sources;
        }

        const severities = this.normalizeSeverityFilterValues(filters);
        if (severities.length === 1) {
            cleaned.severity = severities[0];
        } else if (severities.length > 1) {
            cleaned.severities = severities;
        }

        const dateRange = String(filters.dateRange || '').trim().toLowerCase();
        if (['today', 'yesterday', 'week', 'month'].includes(dateRange)) {
            cleaned.dateRange = dateRange;
        }

        const dateExact = this.normalizeDateKey(filters.dateExact);
        const dateFrom = this.normalizeDateKey(filters.dateFrom);
        const dateTo = this.normalizeDateKey(filters.dateTo);
        if (dateExact) {
            cleaned.dateExact = dateExact;
            delete cleaned.dateRange;
        } else {
            if (dateFrom) {
                cleaned.dateFrom = dateFrom;
                delete cleaned.dateRange;
            }
            if (dateTo) {
                cleaned.dateTo = dateTo;
                delete cleaned.dateRange;
            }
        }

        const validPpe = new Set([
            'NO-Hardhat',
            'NO-Safety Vest',
            'NO-Gloves',
            'NO-Mask',
            'NO-Goggles',
            'NO-Safety Shoes'
        ]);
        const ppeTypes = Array.isArray(filters.ppeTypes) ? filters.ppeTypes : [];
        const normalizedPpe = Array.from(new Set(
            ppeTypes
                .map((label) => this.normalizePpeFilterLabel(label))
                .filter((label) => validPpe.has(label))
        ));
        if (normalizedPpe.length) {
            cleaned.ppeTypes = normalizedPpe;
        }

        return cleaned;
    },

    hasActiveAnalyticsFilters(filters = {}) {
        return !!(
            filters
            && typeof filters === 'object'
            && (
                filters.source
                || (Array.isArray(filters.sources) && filters.sources.length > 0)
                || filters.severity
                || (Array.isArray(filters.severities) && filters.severities.length > 0)
                || filters.dateRange
                || filters.dateExact
                || filters.dateFrom
                || filters.dateTo
                || (Array.isArray(filters.ppeTypes) && filters.ppeTypes.length > 0)
            )
        );
    },

    normalizeDateKey(value) {
        const raw = String(value || '').trim();
        const match = raw.match(/^(20\d{2})-(0[1-9]|1[0-2])-([0-2]\d|3[01])$/);
        if (!match) return '';
        const [, year, month, day] = match;
        const parsed = new Date(Number(year), Number(month) - 1, Number(day));
        if (
            parsed.getFullYear() !== Number(year)
            || parsed.getMonth() !== Number(month) - 1
            || parsed.getDate() !== Number(day)
        ) {
            return '';
        }
        return `${year}-${month}-${day}`;
    },

    getRowDateKey(row = {}) {
        const rowDate = new Date(row?.timestamp || 0);
        if (Number.isNaN(rowDate.getTime())) return '';
        return `${rowDate.getFullYear()}-${String(rowDate.getMonth() + 1).padStart(2, '0')}-${String(rowDate.getDate()).padStart(2, '0')}`;
    },

    normalizePpeFilterLabel(label) {
        const normalized = this.normalizeText(label).replace(/-/g, ' ');
        if (/\b(no )?(hardhat|hard hat|helmet|helmets)\b/.test(normalized)) return 'NO-Hardhat';
        if (/\b(no )?(safety )?vests?\b/.test(normalized)) return 'NO-Safety Vest';
        if (/\b(no )?gloves?\b/.test(normalized)) return 'NO-Gloves';
        if (/\b(no )?(mask|masks|respirator|respirators)\b/.test(normalized)) return 'NO-Mask';
        if (/\b(no )?(goggles?|eye protection|eyewear)\b/.test(normalized)) return 'NO-Goggles';
        if (/\b(no )?(safety )?(shoe|shoes|boot|boots)\b/.test(normalized)) return 'NO-Safety Shoes';
        return String(label || '').trim();
    },

    extractAnalyticsPpeTypes(rawQuery = '') {
        const query = this.normalizeText(rawQuery);
        const labels = [];
        const add = (label) => {
            if (!labels.includes(label)) labels.push(label);
        };
        if (/\b(hardhat|hard hat|helmet|helmets)\b/.test(query)) add('NO-Hardhat');
        if (/\b(safety vest|vest|vests)\b/.test(query)) add('NO-Safety Vest');
        if (/\b(glove|gloves)\b/.test(query)) add('NO-Gloves');
        if (/\b(mask|masks|respirator|respirators)\b/.test(query)) add('NO-Mask');
        if (/\b(goggle|goggles|eye protection|eyewear)\b/.test(query)) add('NO-Goggles');
        if (/\b(safety shoe|safety shoes|shoe|shoes|boot|boots)\b/.test(query)) add('NO-Safety Shoes');
        return labels;
    },

    matchesAnalyticsFilters(row, filters = {}) {
        const safeFilters = this.sanitizeAnalyticsFilters(filters);
        if (!this.hasActiveAnalyticsFilters(safeFilters)) return true;

        const sourceValues = this.normalizeSourceFilterValues(safeFilters, false);
        if (sourceValues.length) {
            const scope = this.getSourceScope(row);
            if (!sourceValues.includes(scope)) return false;
        }

        const severityValues = this.normalizeSeverityFilterValues(safeFilters);
        if (severityValues.length) {
            const severity = String(row?.severity || '').trim().toLowerCase();
            if (!severityValues.includes(severity)) return false;
        }

        if (safeFilters.dateRange) {
            const rowDate = new Date(row?.timestamp || 0);
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            if (safeFilters.dateRange === 'today' && rowDate < today) return false;
            if (safeFilters.dateRange === 'yesterday') {
                const yesterday = new Date(today);
                yesterday.setDate(yesterday.getDate() - 1);
                if (rowDate < yesterday || rowDate >= today) return false;
            }
            if (safeFilters.dateRange === 'week') {
                const weekAgo = new Date(today);
                weekAgo.setDate(weekAgo.getDate() - 7);
                if (rowDate < weekAgo) return false;
            }
            if (safeFilters.dateRange === 'month') {
                const monthAgo = new Date(today);
                monthAgo.setMonth(monthAgo.getMonth() - 1);
                if (rowDate < monthAgo) return false;
            }
        }

        if (safeFilters.dateExact || safeFilters.dateFrom || safeFilters.dateTo) {
            const rowDateKey = this.getRowDateKey(row);
            if (!rowDateKey) return false;
            if (safeFilters.dateExact && rowDateKey !== safeFilters.dateExact) return false;
            if (safeFilters.dateFrom && rowDateKey < safeFilters.dateFrom) return false;
            if (safeFilters.dateTo && rowDateKey > safeFilters.dateTo) return false;
        }

        if (Array.isArray(safeFilters.ppeTypes) && safeFilters.ppeTypes.length) {
            const missing = Array.isArray(row?.missing_ppe) ? row.missing_ppe : [];
            const ppeTags = Array.isArray(row?.ppe_tags) ? row.ppe_tags : [];
            const breakdownLabels = row?.breakdown && typeof row.breakdown === 'object'
                ? Object.entries(row.breakdown)
                    .filter(([, value]) => Number(value) > 0)
                    .map(([label]) => label)
                : [];
            const normalizedLabels = new Set([...missing, ...ppeTags, ...breakdownLabels].map((label) => this.normalizePpeFilterLabel(label)));
            if (!safeFilters.ppeTypes.some((label) => normalizedLabels.has(this.normalizePpeFilterLabel(label)))) return false;
        }

        return true;
    },

    describeAnalyticsFilters(filters = {}) {
        const parts = [];
        const sources = this.normalizeSourceFilterValues(filters, false);
        if (sources.length) {
            parts.push(`${sources.map((value) => this.formatSourceFilterLabel(value)).join(' or ')} rows`);
        }
        const severities = this.normalizeSeverityFilterValues(filters);
        if (severities.length) {
            parts.push(`${severities.map((value) => this.formatSeverityFilterLabel(value)).join(' or ')} severity`);
        }
        if (filters.dateRange === 'today') parts.push('today');
        if (filters.dateRange === 'yesterday') parts.push('yesterday');
        if (filters.dateRange === 'week') parts.push('this week');
        if (filters.dateRange === 'month') parts.push('this month');
        if (filters.dateExact) parts.push(filters.dateExact);
        if (filters.dateFrom && filters.dateTo) parts.push(`${filters.dateFrom} to ${filters.dateTo}`);
        else if (filters.dateFrom) parts.push(`from ${filters.dateFrom}`);
        else if (filters.dateTo) parts.push(`until ${filters.dateTo}`);
        if (Array.isArray(filters.ppeTypes) && filters.ppeTypes.length) {
            const labels = filters.ppeTypes.map((label) => String(label || '')
                .replace(/^NO-/, '')
                .replace(/Safety /g, 'safety ')
                .toLowerCase());
            parts.push(`missing ${labels.join(', ')}`);
        }
        return parts.join(', ');
    },

    async fetchAnalyticsSnapshot(rawQuery = '', overrideFilters = null) {
        try {
            const filters = overrideFilters && typeof overrideFilters === 'object'
                ? this.sanitizeAnalyticsFilters(overrideFilters)
                : this.buildAnalyticsFilters(rawQuery);
            const [stats, violations] = await Promise.all([
                API.getStats(),
                API.getViolations({ limit: 1000 })
            ]);
            const hasFilters = this.hasActiveAnalyticsFilters(filters);
            const allRows = Array.isArray(violations) ? violations : [];
            const filteredRows = hasFilters
                ? allRows.filter((row) => this.matchesAnalyticsFilters(row, filters))
                : allRows;
            if (!filteredRows.length) {
                return {
                    success: false,
                    filters,
                    hasFilters,
                    filterSummary: this.describeAnalyticsFilters(filters),
                    message: hasFilters
                        ? 'No analytics rows matched the valid filters I found, so I will not open an empty filtered dashboard automatically.'
                        : 'No analytics rows are available yet.'
                };
            }

            const baseStats = hasFilters
                ? AnalyticsPage.buildStatsFromViolations(filteredRows)
                : stats;
            const normalizedStats = AnalyticsPage.normalizeStats(baseStats, filteredRows);
            const derived = AnalyticsPage.buildDerivedMetrics(normalizedStats, filteredRows);
            return {
                success: true,
                filters,
                hasFilters,
                filterSummary: this.describeAnalyticsFilters(filters),
                stats: normalizedStats,
                derived,
                rowCount: filteredRows.length,
                metrics: [
                    { label: 'Rows', value: String(filteredRows.length), note: 'Matched analytics rows' },
                    { label: 'Ready rate', value: `${derived.readyRate}%`, note: `${normalizedStats.reportsGenerated} reports ready` },
                    { label: 'Pending', value: String(derived.pending), note: 'Queued or generating' },
                    { label: 'High severity', value: `${derived.highShare}%`, note: `${normalizedStats.severity.high} high-severity rows` },
                    { label: 'Peak window', value: derived.peakWindow, note: `${derived.peakWindowCount} matching rows` },
                    { label: 'Last violation', value: derived.lastViolationDisplay, note: derived.topType }
                ],
                bullets: [
                    `Dominant source mix: ${String(derived.dominantSource || 'unknown').replace(/_/g, ' ')} (${derived.dominantSourceCount})`,
                    `Local-origin rows: ${derived.localOriginCount}; cloud-origin rows: ${derived.cloudOriginCount}`,
                    `7-day average within this slice: ${derived.dailyAverage.toFixed(1)}`
                ]
            };
        } catch (error) {
            console.error('Assistant analytics snapshot failed:', error);
            const fallbackFilters = overrideFilters && typeof overrideFilters === 'object'
                ? this.sanitizeAnalyticsFilters(overrideFilters)
                : this.buildAnalyticsFilters(rawQuery);
            return {
                success: false,
                filters: fallbackFilters,
                hasFilters: this.hasActiveAnalyticsFilters(fallbackFilters),
                filterSummary: this.describeAnalyticsFilters(fallbackFilters),
                message: 'I could not fetch the analytics snapshot right now.'
            };
        }
    },

    async handleAnalyticsIntent(intent) {
        const outcome = await this.fetchAnalyticsSnapshot(intent.raw || intent.query || '', intent.filters || null);
        const filterSummary = outcome.filterSummary || intent.filterSummary || '';
        const label = filterSummary ? ` for ${filterSummary}` : '';
        if (!outcome.success) {
            this.pushMessage({
                role: 'assistant',
                text: `${outcome.message || 'I could not fetch analytics right now.'}${label ? ` (${label.trim()})` : ''}`,
                actions: [
                    { type: 'guided-start', label: 'Choose filters', guidedKind: 'analytics' },
                    { type: 'route', label: 'Open full analytics', page: 'analytics', collapsePanel: true },
                    { type: 'export', label: 'Export analytics CSV', exportKind: 'analytics' }
                ]
            });
            return;
        }

        const analyticsRoute = this.hasActiveAnalyticsFilters(outcome.filters)
            ? { type: 'route', label: 'Open filtered analytics', page: 'analytics', analyticsFilters: outcome.filters || {}, analyticsSummary: filterSummary || 'Filtered analytics view', collapsePanel: true }
            : { type: 'route', label: 'Open analytics', page: 'analytics', collapsePanel: true };

        this.pushMessage({
            role: 'assistant',
            text: `Here is the live analytics snapshot${label}.`,
            metrics: outcome.metrics || [],
            bullets: outcome.bullets || [],
            actions: [
                { type: 'guided-start', label: 'Refine by clicking filters', guidedKind: 'analytics' },
                analyticsRoute,
                { type: 'export', label: 'Export analytics CSV', exportKind: 'analytics' },
                { type: 'route', label: 'Open reports', page: 'reports', collapsePanel: true }
            ]
        });
    },

    resolveReportReviewIntent(raw, query = '') {
        const normalized = this.normalizeText(raw || query);
        if (!normalized || this.isExportIntent(normalized)) return null;
        if (/\b(docs|documentation|manual|handbook|guide)\b/.test(normalized)) return null;
        const session = this.getActiveSession();
        const hasActiveCarousel = !!(session && session.context && session.context.reportReview);
        if (hasActiveCarousel && /\b(explain|summari[sz]e|interpret|what does this mean|tell me about)\b.{0,28}\b(this|current|selected|report|it)\b/.test(normalized)) {
            return { type: 'explain-current' };
        }
        if (hasActiveCarousel && /\b(next|previous|prev|back)\s+(report|one|item)?\b/.test(normalized)) {
            return { type: /\b(previous|prev|back)\b/.test(normalized) ? 'previous' : 'next' };
        }

        const reportCue = /\b(reports?|report id|report #|incident records?|evidence list|violation records?|cases?|case records?|main risks?|risk summary|risk summaries)\b/.test(normalized);
        if (!reportCue) return null;

        const filters = this.buildReportFilters(raw);
        const hasFilters = this.hasActiveReportFilters(filters);
        const directOpen = /\b(open|go to|take me to)\s+(the\s+)?reports?\b/.test(normalized);
        const reviewCue = /\b(show|shows|showing|see|view|review|check|browse|inspect|filter|find|list|display|slide|slideshow|carousel|walk through|look through|look|scan|know|understand|summari[sz]e|explain|interpret|latest|recent|current|so far|have a look|get|main|risk|risks|case|cases)\b/.test(normalized);
        const pluralLatestCue = /\b(latest|newest|most recent|last|recent)\s+(reports|cases|violations)\b/.test(normalized);
        const wantsLatestOnly = !pluralLatestCue && ((
            /\b(latest|newest|most recent|last)\s+(report|case|violation)\b/.test(normalized)
            && !/\b(latest|newest|most recent|last)\s+(reports|cases|violations)\b/.test(normalized)
        ) || /\b(explain|summari[sz]e|interpret|open|show|see|view)\s+(the\s+)?(latest|newest|most recent|last)\b/.test(normalized));
        const wantsExplain = /\b(explain|summari[sz]e|interpret|what happened|tell me about|walk me through|read\s+(the\s+)?report|fuller read)\b/.test(normalized);
        if (directOpen && !hasFilters && !/\b(show|review|check|browse|inspect|slide|slideshow|list|find|filter|view)\b/.test(normalized)) {
            return null;
        }
        if (!reviewCue && !hasFilters) return null;

        return {
            type: 'browse',
            raw,
            query: normalized,
            filters,
            filterSummary: this.describeReportFilters(filters),
            selection: wantsLatestOnly ? 'latest' : '',
            autoExplain: wantsExplain
        };
    },

    hasActiveReportFilters(filters = {}) {
        return !!(
            filters.source
            || (Array.isArray(filters.sources) && filters.sources.length > 0)
            || filters.severity
            || (Array.isArray(filters.severities) && filters.severities.length > 0)
            || filters.status
            || filters.dateRange
            || filters.dateExact
            || filters.dateFrom
            || filters.dateTo
            || (Array.isArray(filters.ppeTypes) && filters.ppeTypes.length)
            || (Array.isArray(filters.searchTokens) && filters.searchTokens.length)
        );
    },

    async handleReportReviewIntent(intent) {
        if (!intent) return;
        if (intent.type === 'explain-current') {
            await this.explainCurrentReportReview();
            return;
        }
        if (intent.type === 'next' || intent.type === 'previous') {
            this.moveReportReview(intent.type === 'next' ? 1 : -1);
            return;
        }

        try {
            this.updateResponseFeedback('Reading report rows...');
            const rows = await API.getViolations({ limit: 1000 });
            this.updateResponseFeedback('Filtering matching reports...');
            const filters = intent.filters || this.buildReportFilters(intent.raw || intent.query || '');
            const filtered = (rows || [])
                .filter((row) => this.matchesReportFilters(row, filters))
                .sort((a, b) => new Date(b?.timestamp || 0) - new Date(a?.timestamp || 0));
            const summary = intent.filterSummary || this.describeReportFilters(filters);
            if (!filtered.length) {
                this.pushMessage({
                    role: 'assistant',
                    text: `I could not find report rows${summary ? ` for ${summary}` : ''}.`,
                    bullets: [
                        'Try fewer filters, for example "show high reports" or "show cloud reports this week".',
                        'You can still open the Reports page to inspect all rows manually.'
                    ],
                    actions: [
                        { type: 'guided-start', label: 'Choose report filters', guidedKind: 'reports' },
                        { type: 'route', label: 'Open reports', page: 'reports', collapsePanel: true },
                        { type: 'route', label: 'Open analytics', page: 'analytics', collapsePanel: true }
                    ]
                });
                return;
            }

            const maxCarouselReports = intent.selection === 'latest' ? 1 : (filtered.length > 15 ? 12 : 50);
            const reports = filtered.slice(0, maxCarouselReports).map((row) => this.normalizeReportPreview(row));
            const session = this.getActiveSession();
            if (session) {
                session.context.reportReview = {
                    reports,
                    index: 0,
                    filters,
                    filterSummary: summary,
                    totalMatched: filtered.length,
                    shownLimit: maxCarouselReports,
                    selectionSummary: this.buildReportSelectionSummary(filtered, filters),
                    createdAt: Date.now()
                };
            }
            this.upsertReportReviewMessage();
            if (intent.autoExplain && reports.length) {
                this.updateResponseFeedback('Reading the selected report...');
                await this.waitForFeedbackFrame();
                await this.explainCurrentReportReview();
            }
        } catch (error) {
            console.error('Assistant report review failed:', error);
            this.pushMessage({
                role: 'assistant',
                text: 'I could not fetch the filtered reports right now.',
                actions: [
                    { type: 'guided-start', label: 'Choose report filters', guidedKind: 'reports' },
                    { type: 'route', label: 'Open reports', page: 'reports', collapsePanel: true }
                ]
            });
        }
    },

    buildReportSelectionSummary(rows = [], filters = {}) {
        const list = Array.isArray(rows) ? rows : [];
        const sourceCounts = { cloud: 0, local: 0, synced_local: 0, shared: 0, unknown: 0 };
        const severityCounts = { high: 0, medium: 0, low: 0, unknown: 0 };
        list.forEach((row) => {
            const source = this.getSourceScope(row);
            const sourceKey = Object.prototype.hasOwnProperty.call(sourceCounts, source) ? source : 'unknown';
            sourceCounts[sourceKey] += 1;

            const severity = String(row?.severity || '').trim().toLowerCase();
            const severityKey = Object.prototype.hasOwnProperty.call(severityCounts, severity) ? severity : 'unknown';
            severityCounts[severityKey] += 1;
        });

        const activeFilters = this.describeReportFilters(filters);
        const sourceText = Object.entries(sourceCounts)
            .filter(([, count]) => count > 0)
            .map(([key, count]) => `${count} ${key.replace(/_/g, ' ')}`)
            .join(', ');
        const severityText = Object.entries(severityCounts)
            .filter(([, count]) => count > 0)
            .map(([key, count]) => `${count} ${key}`)
            .join(', ');

        return {
            activeFilters,
            sourceText,
            severityText
        };
    },

    normalizeReportPreview(row = {}) {
        const sourceScope = String(row.source_scope || '').trim().toLowerCase();
        const sourceLabel = String(row.source_label || '').trim()
            || (sourceScope === 'synced_local'
                ? 'Local Synced'
                : sourceScope === 'local'
                    ? 'Local'
                    : 'Cloud');
        const timestamp = row.timestamp || row.created_at || row.updated_at || '';
        return {
            reportId: String(row.report_id || row.id || 'Unknown report').trim(),
            status: String(row.status || 'unknown').trim(),
            severity: String(row.severity || 'unknown').trim(),
            deviceId: String(row.device_id || row.camera_id || '').trim(),
            violationCount: Number(row.violation_count || 0),
            missingPpe: Array.isArray(row.missing_ppe) ? row.missing_ppe.map((item) => String(item || '').trim()).filter(Boolean) : [],
            ppeTags: Array.isArray(row.ppe_tags) ? row.ppe_tags.map((item) => String(item || '').trim()).filter(Boolean) : [],
            errorMessage: String(row.error_message || row.failure_reason || '').trim(),
            hasReport: !!row.has_report,
            hasOriginal: !!row.has_original,
            hasAnnotated: !!row.has_annotated,
            sourceScope,
            sourceLabel,
            timestamp,
            timestampLabel: this.formatReportTimestamp(timestamp),
            location: String(row.location || row.zone || row.area || '').trim(),
            summary: String(row.violation_summary || row.summary || 'PPE violation report').trim(),
            thumbnailUrl: this.resolveReportThumbnailUrl(row)
        };
    },

    resolveReportThumbnailUrl(row = {}) {
        if (row.local_image_url) return row.local_image_url;
        if (row.thumbnail_url) return row.thumbnail_url;
        if (row.image_url) return row.image_url;
        const reportId = String(row.report_id || row.id || '').trim();
        if (!reportId || !window.API || typeof API.getImageUrl !== 'function') return '';
        const filename = row.has_annotated ? 'annotated.jpg' : row.has_original ? 'original.jpg' : '';
        if (!filename) return '';
        try {
            return API.getImageUrl(reportId, filename, row) || '';
        } catch (_) {
            return '';
        }
    },

    formatReportTimestamp(value) {
        if (!value) return 'time unknown';
        if (typeof TimezoneManager !== 'undefined' && typeof TimezoneManager.formatDateTime === 'function') {
            try {
                return TimezoneManager.formatDateTime(value);
            } catch (_) {
                // Fall through to local formatting.
            }
        }
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
    },

    getReportReviewContext() {
        const session = this.getActiveSession();
        const context = session && session.context ? session.context.reportReview : null;
        if (!context || !Array.isArray(context.reports) || !context.reports.length) return null;
        context.index = Math.max(0, Math.min(context.reports.length - 1, Number(context.index || 0)));
        return context;
    },

    getCurrentReportReview() {
        const context = this.getReportReviewContext();
        if (!context) return null;
        return {
            context,
            report: context.reports[context.index],
            index: context.index
        };
    },

    buildReportReviewActions(context, report) {
        return [
            { type: 'report-review-prev', label: 'Previous report' },
            { type: 'report-review-next', label: 'Next report' },
            { type: 'report-review-explain', label: 'Explain this report' },
            { type: 'guided-start', label: 'Refine by clicking filters', guidedKind: 'reports' },
            { type: 'open-report', label: 'Open report', reportId: report.reportId },
            { type: 'route', label: 'Open reports page', page: 'reports', collapsePanel: true }
        ];
    },

    buildReportReviewMessage(context) {
        const report = context.reports[context.index];
        const shownTotal = context.reports.length;
        const matchedTotal = Number(context.totalMatched || shownTotal);
        const filterText = context.filterSummary ? ` for ${context.filterSummary}` : '';
        const manyMatches = matchedTotal > shownTotal;
        const selection = context.selectionSummary || {};
        const bullets = [
            manyMatches
                ? `Showing the newest ${shownTotal} matches first so the list stays usable; ${matchedTotal} rows matched overall.`
                : 'Use Previous report and Next report to move through the filtered set.',
            selection.severityText ? `Severity mix in this match set: ${selection.severityText}.` : '',
            selection.sourceText ? `Source mix in this match set: ${selection.sourceText}.` : '',
            'Select Explain this report when you want Mira to interpret the selected row.',
            'Use Refine by clicking filters if you prefer choosing report filters without typing.'
        ].filter(Boolean);
        return {
            role: 'assistant',
            text: `I found ${matchedTotal} report${matchedTotal === 1 ? '' : 's'}${filterText}. Here is the report slideshow.`,
            reportCarousel: {
                report,
                positionLabel: `Report ${context.index + 1} of ${shownTotal}${matchedTotal > shownTotal ? ` (${matchedTotal} matched)` : ''}`
            },
            bullets,
            actions: this.buildReportReviewActions(context, report)
        };
    },

    getLatestReportReviewMessageIndex(session) {
        if (!session || !Array.isArray(session.messages)) return -1;
        for (let index = session.messages.length - 1; index >= 0; index -= 1) {
            const message = session.messages[index];
            if (message && message.role === 'assistant' && message.reportCarousel) return index;
        }
        return -1;
    },

    upsertReportReviewMessage() {
        const session = this.getActiveSession();
        const context = this.getReportReviewContext();
        if (!session || !context) return;
        const baseMessage = this.buildReportReviewMessage(context);
        const existingIndex = this.getLatestReportReviewMessageIndex(session);
        if (this.shouldUpdateInteractiveMessageInPlace(session, existingIndex)) {
            const existing = session.messages[existingIndex] || {};
            session.messages[existingIndex] = {
                ...existing,
                ...baseMessage,
                id: existing.id,
                createdAt: existing.createdAt,
                updatedAt: Date.now()
            };
            session.updatedAt = Date.now();
            this.refreshSessionUi();
            return;
        }
        this.pushMessage(baseMessage);
    },

    moveReportReview(delta) {
        const session = this.getActiveSession();
        const context = this.getReportReviewContext();
        if (!session || !context) {
            this.pushMessage({
                role: 'assistant',
                text: 'There is no active report slideshow yet. Ask me to show filtered reports first.',
                actions: [{ type: 'route', label: 'Open reports', page: 'reports', collapsePanel: true }]
            });
            return;
        }
        const total = context.reports.length;
        context.index = (context.index + delta + total) % total;
        session.context.reportReview = context;
        this.upsertReportReviewMessage();
    },

    normalizeReportExtractedText(value = '') {
        return this.compactText(String(value || '')
            .replace(/\u00a0/g, ' ')
            .replace(/[•·]/g, ' • ')
            .replace(/([a-z0-9)])(Mitigation steps|Likelihood|Regulation|Legal consequence|Severity|Category|Evidence|DANGER|LAW|WHO|WHAT|WHY|WHERE|WHEN)\b/g, '$1. $2')
            .replace(/(steps)([A-Z][A-Z\s]{2,}:)/g, '$1. $2')
            .replace(/([a-z])([A-Z][a-z]+(?:\s+[a-z]+){1,4}\s+risk\b)/g, '$1. $2'));
    },

    splitReportListText(value = '', maxItems = 6) {
        const normalized = this.normalizeReportExtractedText(value);
        if (!normalized) return [];
        const prepared = normalized
            .replace(/\s*•\s*/g, '\n')
            .replace(/\s+(?=(?:Respiratory|Struck-by|Head injury|Fall|Caught|Direct exposure|Immediate Risk|Core Violation|Critical Action|WEAR|REPLACE|STOP|VERIFY|ESCALATE)\b)/g, '\n');
        return prepared
            .split(/\n+|;\s+|\.\s+(?=[A-Z])/)
            .map((item) => item.trim().replace(/^[-:]+/, '').trim())
            .filter((item) => item.length >= 3)
            .slice(0, maxItems);
    },

    uniqueReportItems(items = [], maxItems = 6) {
        const output = [];
        const seen = new Set();
        (Array.isArray(items) ? items : [items]).forEach((item) => {
            const text = this.normalizeReportExtractedText(item);
            if (!text) return;
            const key = this.normalizeText(text);
            if (seen.has(key)) return;
            seen.add(key);
            output.push(text);
        });
        return output.slice(0, maxItems);
    },

    formatPpeLabel(label = '') {
        const normalized = String(label || '')
            .replace(/^NO[-\s]+/i, '')
            .replace(/^Missing\s+/i, '')
            .replace(/[-_]+/g, ' ')
            .replace(/\s+/g, ' ')
            .trim()
            .toLowerCase();
        const map = {
            hardhat: 'Hard Hat',
            'hard hat': 'Hard Hat',
            helmet: 'Hard Hat',
            vest: 'Safety Vest',
            'safety vest': 'Safety Vest',
            mask: 'Mask',
            respirator: 'Mask',
            gloves: 'Gloves',
            glove: 'Gloves',
            goggles: 'Goggles',
            goggle: 'Goggles',
            boots: 'Safety Boots',
            boot: 'Safety Boots',
            shoes: 'Safety Shoes',
            shoe: 'Safety Shoes',
            footwear: 'Safety Footwear'
        };
        if (map[normalized]) return map[normalized];
        return normalized
            ? normalized.replace(/\b\w/g, (char) => char.toUpperCase())
            : '';
    },

    formatCountedLabels(labels = []) {
        const counts = new Map();
        (Array.isArray(labels) ? labels : [labels]).forEach((label) => {
            const formatted = this.formatPpeLabel(label);
            if (!formatted) return;
            counts.set(formatted, (counts.get(formatted) || 0) + 1);
        });
        return Array.from(counts.entries())
            .map(([label, count]) => count > 1 ? `${label} (x${count})` : label)
            .join(', ');
    },

    parseReportDocumentHtml(html = '') {
        const raw = String(html || '');
        const fallbackText = this.normalizeReportExtractedText(raw.replace(/<[^>]+>/g, ' ')).slice(0, 12000);
        const empty = {
            text: fallbackText,
            caption: '',
            executive: {},
            dangers: [],
            regulations: [],
            persons: [],
            mitigations: [],
            actions: []
        };
        if (!raw || typeof DOMParser === 'undefined') return empty;

        let doc = null;
        try {
            doc = new DOMParser().parseFromString(raw, 'text/html');
        } catch (_) {
            return empty;
        }
        if (!doc || !doc.documentElement) return empty;

        doc.querySelectorAll('script, style, noscript, svg, canvas').forEach((node) => node.remove());
        const textOf = (node) => {
            if (!node) return '';
            let clone = node;
            try {
                clone = node.cloneNode(true);
                clone.querySelectorAll('br').forEach((br) => br.replaceWith(doc.createTextNode('\n')));
                clone.querySelectorAll('li').forEach((li) => {
                    li.insertBefore(doc.createTextNode(' • '), li.firstChild);
                    li.appendChild(doc.createTextNode('\n'));
                });
                clone.querySelectorAll('p, div, tr, th, td, h1, h2, h3, h4, section, article').forEach((block) => {
                    block.appendChild(doc.createTextNode('\n'));
                });
            } catch (_) {
                clone = node;
            }
            return this.normalizeReportExtractedText(clone ? clone.textContent : '');
        };
        const listFrom = (nodes, maxItems = 6) => this.uniqueReportItems(
            Array.from(nodes || []).flatMap((node) => this.splitReportListText(textOf(node), maxItems)),
            maxItems
        );

        const evidence = {
            ...empty,
            text: textOf(doc.body || doc.documentElement).slice(0, 12000),
            executive: {},
            dangers: [],
            regulations: [],
            persons: [],
            mitigations: [],
            actions: []
        };

        const sections = Array.from(doc.querySelectorAll('.section, section, .card'));
        const sceneSection = sections.find((section) => /scene description|ai scene|caption|visual analysis/i.test(textOf(section.querySelector('h1,h2,h3,.section-title,.card-header'))));
        if (sceneSection) {
            const contentNode = sceneSection.querySelector('.card-content p, .card-content, p');
            const titleNode = sceneSection.querySelector('h1,h2,h3,.section-title,.card-header');
            const titleText = textOf(titleNode);
            const sceneText = textOf(contentNode || sceneSection).replace(titleText, '').trim();
            evidence.caption = sceneText;
        }

        Array.from(doc.querySelectorAll('table tr')).forEach((row) => {
            const cells = Array.from(row.querySelectorAll('th,td'));
            if (cells.length < 2) return;
            const key = textOf(cells[0]).toUpperCase();
            const value = textOf(cells[1]);
            if (key === 'WHO') evidence.executive.who = value;
            if (key === 'WHAT') evidence.executive.what = value;
            if (key === 'DANGER') {
                evidence.executive.danger = value;
                evidence.dangers = this.uniqueReportItems([
                    ...evidence.dangers,
                    ...this.splitReportListText(value, 8)
                ], 8);
            }
            if (key === 'LAW') {
                evidence.executive.law = value;
                evidence.regulations = this.uniqueReportItems([
                    ...evidence.regulations,
                    ...this.splitReportListText(value, 6)
                ], 6);
            }
        });

        const regulationSections = sections.filter((section) => /regulations|standards|law|compliance/i.test(textOf(section.querySelector('h1,h2,h3,.section-title,.card-header'))));
        regulationSections.forEach((section) => {
            const cards = Array.from(section.querySelectorAll('.card'));
            cards.forEach((card) => {
                const header = textOf(card.querySelector('.card-header, h3, h4'));
                const requirement = textOf(card.querySelector('.card-content p, p'));
                if (header && !/summary|executive/i.test(header)) {
                    evidence.regulations.push(requirement && requirement !== header ? `${header}: ${requirement}` : header);
                }
            });
        });
        evidence.regulations = this.uniqueReportItems(evidence.regulations, 6);

        Array.from(doc.querySelectorAll('.person-card')).forEach((card, index) => {
            const title = textOf(card.querySelector('h3')) || `Person ${index + 1}`;
            const description = textOf(card.querySelector('.person-header p, summary p, p'));
            const ppeMissing = [];
            Array.from(card.querySelectorAll('.ppe-item')).forEach((item) => {
                const label = textOf(item.querySelector('.ppe-label')).replace(/:$/, '');
                const status = textOf(item.querySelector('.ppe-status'));
                if (/missing|not worn|absent|non-compliant|no\b/i.test(status)) {
                    const formatted = this.formatPpeLabel(label);
                    if (formatted) ppeMissing.push(formatted);
                }
            });
            const hazards = listFrom(card.querySelectorAll('.hazard-chip'), 6);
            const risks = Array.from(card.querySelectorAll('.risk-item')).flatMap((riskNode) => {
                const risk = textOf(riskNode.querySelector('.risk-content')) || textOf(riskNode);
                const likelihood = textOf(riskNode.querySelector('.likelihood-value'));
                const regulation = textOf(riskNode.querySelector('.risk-meta'));
                const mitigation = listFrom(riskNode.querySelectorAll('.risk-mitigation li'), 5);
                evidence.mitigations.push(...mitigation);
                return this.uniqueReportItems([
                    likelihood ? `${risk} Likelihood: ${likelihood}` : risk,
                    regulation
                ], 4);
            });
            const actions = listFrom(card.querySelectorAll('.action-chip'), 6);
            evidence.actions.push(...actions);
            evidence.persons.push({
                title,
                description,
                ppeMissing: this.uniqueReportItems(ppeMissing, 6),
                hazards,
                risks: this.uniqueReportItems(risks, 6),
                actions
            });
        });

        evidence.mitigations = this.uniqueReportItems(evidence.mitigations, 8);
        evidence.actions = this.uniqueReportItems(evidence.actions, 8);
        if (!evidence.dangers.length) {
            evidence.dangers = listFrom(doc.querySelectorAll('.hazard-chip, .risk-content'), 8);
        }
        if (!evidence.mitigations.length) {
            evidence.mitigations = evidence.actions.slice(0, 8);
        }

        return evidence;
    },

    async fetchReportDocumentEvidence(report = {}) {
        const reportId = String(report.reportId || '').trim();
        if (!reportId || !window.API || typeof API.getReportUrl !== 'function' || typeof fetch !== 'function') {
            return this.parseReportDocumentHtml('');
        }

        try {
            const sourceHint = {
                report_id: reportId,
                source_scope: report.sourceScope,
                source_label: report.sourceLabel
            };
            const url = API.getReportUrl(reportId, sourceHint);
            if (!url) return this.parseReportDocumentHtml('');
            const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
            const timeoutId = controller ? setTimeout(() => controller.abort(), 6000) : 0;
            let response;
            try {
                response = await fetch(url, {
                    cache: 'no-store',
                    ...(controller ? { signal: controller.signal } : {})
                });
            } finally {
                if (timeoutId) clearTimeout(timeoutId);
            }
            if (!response.ok) return this.parseReportDocumentHtml('');
            const html = await response.text();
            if (!html) return this.parseReportDocumentHtml('');
            return this.parseReportDocumentHtml(html);
        } catch (error) {
            console.debug('Mira report content fetch skipped:', error);
            return this.parseReportDocumentHtml('');
        }
    },

    async fetchReportDocumentText(report = {}) {
        const evidence = await this.fetchReportDocumentEvidence(report);
        return evidence && evidence.text ? evidence.text : '';
    },

    pickReportSentences(text = '', keywords = [], maxCount = 2) {
        const normalizedKeywords = (keywords || []).map((keyword) => this.normalizeText(keyword)).filter(Boolean);
        if (!text || !normalizedKeywords.length) return [];
        const rawSentences = this.compactText(text)
            .split(/(?:\.|\?|!|\n)\s+/)
            .map((sentence) => sentence.trim())
            .filter((sentence) => sentence.length >= 24 && sentence.length <= 260);
        const picked = [];
        rawSentences.forEach((sentence) => {
            if (picked.length >= maxCount) return;
            const normalized = this.normalizeText(sentence);
            if (normalizedKeywords.some((keyword) => normalized.includes(keyword))) {
                picked.push(sentence.replace(/\s+/g, ' ').trim());
            }
        });
        return picked;
    },

    buildDetailedReportExplanation(report = {}, documentEvidence = '') {
        const evidence = documentEvidence && typeof documentEvidence === 'object'
            ? {
                text: '',
                caption: '',
                executive: {},
                dangers: [],
                regulations: [],
                persons: [],
                mitigations: [],
                actions: [],
                ...documentEvidence
            }
            : {
                text: String(documentEvidence || ''),
                caption: '',
                executive: {},
                dangers: [],
                regulations: [],
                persons: [],
                mitigations: [],
                actions: []
            };
        const documentText = String(evidence.text || '');
        const executive = evidence.executive && typeof evidence.executive === 'object' ? evidence.executive : {};
        const persons = Array.isArray(evidence.persons) ? evidence.persons : [];
        const missingPpe = Array.isArray(report.missingPpe) ? report.missingPpe : [];
        const ppeTagList = Array.isArray(report.ppeTags) ? report.ppeTags : [];
        const personMissingPpe = persons.flatMap((person) => Array.isArray(person.ppeMissing) ? person.ppeMissing : []);
        const missing = this.formatCountedLabels(personMissingPpe.length ? personMissingPpe : missingPpe) || 'no PPE labels recorded';
        const ppeTags = this.formatCountedLabels(ppeTagList) || missing;
        const status = String(report.status || 'unknown').toLowerCase();
        const ready = status === 'completed' || status === 'ready';
        const fallbackRiskSentences = this.pickReportSentences(documentText, ['risk', 'severity', 'likelihood', 'hazard', 'injury'], 3);
        const fallbackActionSentences = this.pickReportSentences(documentText, ['corrective', 'action', 'recommend', 'control', 'mitigation', 'supervisor'], 3);
        const fallbackEvidenceSentences = this.pickReportSentences(documentText, ['visual', 'evidence', 'caption', 'observed', 'detected', 'worker', 'scene'], 2);
        const fallbackComplianceSentences = this.pickReportSentences(documentText, ['regulation', 'standard', 'compliance', 'ms', 'iso', 'osha', 'requirement'], 2);

        const caption = this.normalizeReportExtractedText(evidence.caption)
            || fallbackEvidenceSentences[0]
            || '';
        const whatSummary = this.normalizeReportExtractedText(executive.what || report.summary || 'The report row does not include a generated summary yet.');
        const whoSummary = this.normalizeReportExtractedText(executive.who || (persons.length ? `Report lists ${persons.length} person${persons.length === 1 ? '' : 's'} in the scene.` : 'Person-level detail was not found in the report HTML.'));
        const whatItems = this.uniqueReportItems([
            ...this.splitReportListText(whatSummary, 4),
            ...(whatSummary && !this.splitReportListText(whatSummary, 4).length ? [whatSummary] : [])
        ], 4);
        const personItems = persons.map((person, index) => {
            const title = this.normalizeReportExtractedText(person.title || `Person ${index + 1}`);
            const description = this.normalizeReportExtractedText(person.description || 'No person description was listed.');
            const personPpe = this.formatCountedLabels(person.ppeMissing || []) || 'PPE status not clearly listed';
            const hazards = this.uniqueReportItems(person.hazards || [], 2).join('; ');
            const risks = this.uniqueReportItems(person.risks || [], 2).join('; ');
            const actions = this.uniqueReportItems(person.actions || [], 2).join('; ');
            return [
                `${title}: ${description}`,
                `Missing/concern: ${personPpe}`,
                hazards ? `Hazards: ${hazards}` : '',
                risks ? `Risk: ${risks}` : '',
                actions ? `Action: ${actions}` : ''
            ].filter(Boolean).join('. ');
        });
        const riskItems = this.uniqueReportItems([
            ...(Array.isArray(evidence.dangers) ? evidence.dangers : []),
            ...persons.flatMap((person) => Array.isArray(person.risks) ? person.risks : []),
            ...fallbackRiskSentences
        ], 8);
        const mitigationItems = this.uniqueReportItems([
            ...(Array.isArray(evidence.mitigations) ? evidence.mitigations : []),
            ...(Array.isArray(evidence.actions) ? evidence.actions : []),
            ...persons.flatMap((person) => Array.isArray(person.actions) ? person.actions : []),
            ...fallbackActionSentences
        ], 8);
        const complianceItems = this.uniqueReportItems([
            ...(Array.isArray(evidence.regulations) ? evidence.regulations : []),
            executive.law || '',
            ...fallbackComplianceSentences
        ], 6);
        const recommendedNext = mitigationItems[0]
            || 'Verify the missing PPE against the image evidence, stop the affected task if the scene is active, and record the corrective action before closing the case.';
        const riskSummary = riskItems[0]
            || `${report.severity || 'Unknown'} severity means this row should be reviewed against the site risk matrix and surrounding work environment.`;
        const evidenceDetail = caption
            || `Use the ${report.hasAnnotated ? 'annotated and original images' : report.hasOriginal ? 'original image' : 'available report evidence'} to confirm the detection before closing the case.`;
        const complianceDetail = complianceItems[0]
            || 'Check the report body for any listed Malaysian standards or site policy references before sharing it outside the team.';
        const sections = [
            caption ? { title: 'Scene / Caption', items: [caption] } : null,
            { title: 'People And PPE', items: personItems.length ? personItems.slice(0, 6) : [whoSummary, `Missing/concern: ${missing}`] },
            { title: 'What Happened', items: whatItems.length ? whatItems : [whatSummary] },
            { title: 'Main Hazards / Risk', items: riskItems.length ? riskItems : [riskSummary] },
            { title: 'Mitigation Steps', items: mitigationItems.length ? mitigationItems : [recommendedNext] },
            { title: 'Compliance / Traceability', items: complianceItems.length ? complianceItems : [complianceDetail] }
        ].filter((section) => section && Array.isArray(section.items) && section.items.length);

        return {
            role: 'assistant',
            text: `Here is a fuller read of report ${report.reportId}.`,
            bullets: [
                `What happened: ${whatSummary}`,
                `PPE concern: ${missing}. Detection labels recorded: ${ppeTags}.`,
                `Risk interpretation: ${riskSummary}`,
                `Evidence to check: ${evidenceDetail}`,
                `Recommended next step: ${recommendedNext}`,
                `Compliance note: ${complianceDetail}`,
                `Traceability: ${report.sourceLabel || 'Unknown source'} row, ${report.severity || 'unknown'} severity, ${ready ? 'ready for evidence review' : `currently ${report.status || 'not ready'}`}, timestamp ${report.timestampLabel || 'unknown'}.`
            ],
            sections,
            actions: [
                { type: 'open-report', label: 'Open report', reportId: report.reportId },
                { type: 'report-review-prev', label: 'Previous report' },
                { type: 'report-review-next', label: 'Next report' }
            ]
        };
    },

    async explainCurrentReportReview() {
        const current = this.getCurrentReportReview();
        if (!current || !current.report) {
            this.pushMessage({
                role: 'assistant',
                text: 'There is no selected report to explain yet. Ask me to show filtered reports first.',
                actions: [{ type: 'route', label: 'Open reports', page: 'reports', collapsePanel: true }]
            });
            return;
        }
        const report = current.report;
        this.updateResponseFeedback('Reading the selected report...');
        const documentEvidence = await this.fetchReportDocumentEvidence(report);
        this.pushMessage(this.buildDetailedReportExplanation(report, documentEvidence));
    },

    async openSelectedReport(reportId = '') {
        const rid = String(reportId || this.getCurrentReportReview()?.report?.reportId || '').trim();
        if (!rid) return;
        Router.navigate('reports');
        this.collapseAssistantForWorkspaceAction();
        window.setTimeout(async () => {
            let source = null;
            try {
                if (window.ReportsPage && Array.isArray(ReportsPage.violations)) {
                    source = ReportsPage.violations.find((row) => String(row.report_id || '') === rid) || null;
                }
                if (!source && window.API && typeof API.getViolations === 'function') {
                    const rows = await API.getViolations({ limit: 1000 });
                    source = (rows || []).find((row) => String(row.report_id || '') === rid) || null;
                }
                if (window.ReportsPage && typeof ReportsPage.openReport === 'function') {
                    ReportsPage.openReport(rid, source);
                }
            } catch (error) {
                console.error('Assistant open report failed:', error);
            }
        }, 420);
    },

    isLowSignalPrompt(raw, query) {
        const compactRaw = String(raw || '').trim();
        if (!compactRaw) return true;
        if (/^[^a-zA-Z0-9]+$/.test(compactRaw)) return true;
        const queryNoSpace = String(query || '').replace(/\s+/g, '');
        if (queryNoSpace.length > 0 && /^([a-z0-9])\1{2,}$/i.test(queryNoSpace)) return true;
        const tokens = this.tokenize(query);
        return tokens.length === 0;
    },

    handleUnknownPrompt(raw, query) {
        if (this.isLowSignalPrompt(raw, query)) {
            this.pushMessage({
                role: 'assistant',
                text: 'I did not get a usable request from that yet.',
                bullets: [
                    'Try a concrete ask like "show analytics for cloud this week".',
                    'You can also ask me to open camera, check an image, explain report tags, or run a tutorial.'
                ],
                actions: [
                    { type: 'route', label: 'Open camera', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true },
                    { type: 'tutorial', label: 'Show local tutorial', flow: 'local', stepIndex: 0 },
                    { type: 'route', label: 'Open analytics', page: 'analytics', collapsePanel: true }
                ]
            });
            return;
        }

        const offTopicOnly = /\b(weather|pizza|joke|game|capital|bored|banana|universe|homework|recipe|song|movie|poem)\b/.test(query)
            && !this.hasCasmDomainSignal(query);
        if (offTopicOnly) {
            this.pushMessage({
                role: 'assistant',
                text: 'I could not confidently map that to a CASM workflow because it is outside the monitoring assistant scope.',
                bullets: [
                    'I stay focused on live monitoring, image checks, reports, analytics, settings, exports, and handbook guidance.',
                    'Try a safety task like "start supervision", "check image", or "show analytics this week".'
                ],
                actions: [
                    { type: 'route', label: 'Open camera', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true },
                    { type: 'route', label: 'Open analytics', page: 'analytics', collapsePanel: true },
                    { type: 'tutorial', label: 'Show local tutorial', flow: 'local', stepIndex: 0 }
                ]
            });
            return;
        }

        this.pushMessage({
            role: 'assistant',
            text: 'I could not confidently map that wording to one workflow yet, but I can still help you get to the main safety actions quickly.',
            bullets: [
                'I stay focused on live monitoring, image checks, reports, analytics, settings, exports, and handbook guidance.',
                'Short phrases like "start supervision", "check image", or "show analytics this week" are enough.'
            ],
            actions: [
                { type: 'route', label: 'Open camera', page: 'live', liveMode: 'live', liveFocus: 'start', collapsePanel: true },
                { type: 'route', label: 'Open analytics', page: 'analytics', collapsePanel: true },
                { type: 'settings-profile', label: 'Recommend settings', profile: 'recommended' }
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
        const destinationAction = destination.type === 'route'
            ? {
                type: 'route',
                label: `Go to ${destination.label}`,
                page: destination.page,
                focusLocalCheckup: !!destination.focusLocalCheckup,
                collapsePanel: true
            }
            : {
                type: 'handbook',
                label: 'Open handbook',
                pageKey: destination.pageKey || 'intro',
                stageKey: destination.stageKey || '',
                tutorialFlow: destination.tutorialFlow || '',
                tutorialStep: Number(destination.tutorialStep || 0),
                collapsePanel: true
            };
        this.pushMessage({
            role: 'assistant',
            text: `${destination.label} is ready. I will collapse after opening it so you can use the workspace, and reopening Mira brings you back to this same chat.`,
            actions: [destinationAction]
        });
        void this.performAction(destinationAction);
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
                match: /\b(likelihood|risk likelihood|probability|chance)\b/,
                text: 'Likelihood in a report means how probable the listed harm is if the observed scene continues without correction. It is separate from severity: severity describes consequence, while likelihood describes the chance of that consequence in context.',
                actions: [
                    { type: 'handbook', label: 'Open report terminology', pageKey: 'workflow', stageKey: 'reports' },
                    { type: 'route', label: 'Open Reports', page: 'reports' }
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

    queueLiveIntent(detail = {}) {
        const payload = {
            mode: detail.mode === 'upload' ? 'upload' : 'live',
            focus: String(detail.focus || '').trim(),
            requestedAt: Date.now()
        };
        window.__CASM_LIVE_ASSISTANT_INTENT = payload;
        window.setTimeout(() => {
            window.dispatchEvent(new CustomEvent('casm-live:intent', { detail: payload }));
        }, APP_STATE.currentPage === 'live' ? 40 : 220);
    },

    queueAnalyticsIntent(detail = {}) {
        const filters = this.sanitizeAnalyticsFilters(detail && typeof detail.filters === 'object' ? detail.filters : {});
        if (!this.hasActiveAnalyticsFilters(filters)) return;
        const payload = {
            filters,
            summary: String(detail.summary || 'Filtered analytics view').trim() || 'Filtered analytics view',
            requestedAt: Date.now()
        };
        window.__CASM_ANALYTICS_ASSISTANT_INTENT = payload;
        window.setTimeout(() => {
            window.dispatchEvent(new CustomEvent('casm-analytics:intent', { detail: payload }));
        }, APP_STATE.currentPage === 'analytics' ? 40 : 220);
    },

    collapseAssistantForWorkspaceAction(delayMs = 140) {
        window.setTimeout(() => this.togglePanel(false), delayMs);
    },

    performRouteNavigation(action) {
        if (!action) return;
        const page = action.focusLocalCheckup ? 'settings-checkup' : action.page;
        if (action.page === 'live' && (action.liveMode || action.liveFocus)) {
            this.queueLiveIntent({
                mode: action.liveMode || 'live',
                focus: action.liveFocus || ''
            });
        }
        if (action.page === 'analytics' && action.analyticsFilters) {
            const filters = this.sanitizeAnalyticsFilters(action.analyticsFilters);
            if (this.hasActiveAnalyticsFilters(filters)) {
                this.queueAnalyticsIntent({
                    filters,
                    summary: action.analyticsSummary || 'Filtered analytics view'
                });
            }
        }
        Router.navigate(page || 'home');
        if (action.collapsePanel !== false) {
            this.collapseAssistantForWorkspaceAction();
        }
    },

    performHandbookNavigation(action) {
        if (window.CASMHandbook && typeof window.CASMHandbook.open === 'function') {
            window.CASMHandbook.open(action.pageKey || 'intro', {
                stage: action.stageKey || '',
                tutorialFlow: action.tutorialFlow || '',
                tutorialStep: Number(action.tutorialStep || 0)
            });
        }
        if (action.collapsePanel !== false) {
            this.collapseAssistantForWorkspaceAction();
        }
    },

    async applySettingsProfile(profile) {
        const modal = window.PPEGlobalSettingsModal;
        if (!modal) {
            this.pushMessage({
                role: 'assistant',
                text: 'I could not reach the settings controller right now.',
                actions: [{ type: 'route', label: 'Open settings', page: 'settings', collapsePanel: true }]
            });
            return;
        }

        let outcome = null;
        let successText = 'I applied the requested settings.';
        let failureText = 'I could not apply that settings profile.';

        if (profile === 'api') {
            outcome = await modal.applyApiModeProfile();
            successText = 'I switched the system to API mode for the smoother hosted cloud workflow.';
            failureText = 'I could not switch the system to API mode.';
        } else if (profile === 'local') {
            outcome = await modal.applyProviderRoutingLocalProfile();
            successText = 'I applied the local profile. Use it only on an approved host with the local pipeline ready.';
            failureText = 'I could not apply the local profile.';
        } else {
            outcome = await modal.applyRecommendedSettings();
            successText = 'I applied the recommended settings. That keeps the system in the balanced everyday profile.';
            failureText = 'I could not apply the recommended settings.';
        }

        const success = !!(outcome && outcome.success);
        this.pushMessage({
            role: 'assistant',
            text: success ? successText : `${failureText}${outcome && outcome.message ? ` ${outcome.message}` : ''}`,
            actions: [
                { type: 'route', label: 'Open settings', page: 'settings', collapsePanel: true },
                { type: 'route', label: 'Open checkup', page: 'settings', focusLocalCheckup: true, collapsePanel: true }
            ]
        });
    },

    async performAction(action) {
        if (!action || !action.type) return;
        const feedbackLabel = this.pickActionFeedback(action);
        const responseJobId = feedbackLabel && !this.isResponding
            ? this.beginResponseFeedback(feedbackLabel)
            : 0;
        if (responseJobId) {
            await this.waitForFeedbackFrame();
        }
        try {
            switch (action.type) {
            case 'route': {
                this.performRouteNavigation(action);
                return;
            }
            case 'handbook': {
                this.performHandbookNavigation(action);
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
            case 'download-prepared-csv': {
                const exportId = String(action.exportId || '').trim();
                const prepared = exportId ? this.preparedCsvDownloads[exportId] : null;
                const filename = String((prepared && prepared.filename) || action.filename || `casm-assistant-export-${this.buildTimestampToken()}.csv`);
                const content = prepared && prepared.content ? prepared.content : action.content;
                if (!content) {
                    this.pushMessage({
                        role: 'assistant',
                        text: 'That prepared CSV is no longer available in this chat session. Ask me to prepare the export again and I will rebuild it.'
                    });
                    return;
                }
                this.downloadCsv(filename, content);
                return;
            }
            case 'overview': {
                await this.handleOverviewIntent();
                return;
            }
            case 'guided-start': {
                this.startGuidedFlow(action.guidedKind || 'analytics');
                return;
            }
            case 'guided-select': {
                this.handleGuidedSelection(action);
                return;
            }
            case 'guided-toggle': {
                this.handleGuidedToggle(action);
                return;
            }
            case 'guided-continue': {
                this.handleGuidedContinue(action);
                return;
            }
            case 'guided-date-request': {
                this.requestGuidedDateInput(action);
                return;
            }
            case 'guided-finish': {
                await this.finishGuidedFlow(action);
                return;
            }
            case 'settings-profile': {
                await this.applySettingsProfile(String(action.profile || 'recommended').trim().toLowerCase());
                return;
            }
            case 'doc-result': {
                this.performHandbookNavigation(action);
                return;
            }
            case 'report-review-prev': {
                this.moveReportReview(-1);
                return;
            }
            case 'report-review-next': {
                this.moveReportReview(1);
                return;
            }
            case 'report-review-explain': {
                await this.explainCurrentReportReview();
                return;
            }
            case 'open-report': {
                await this.openSelectedReport(action.reportId || '');
                return;
            }
            default:
                return;
            }
        } finally {
            if (responseJobId) {
                this.finishResponseFeedback(responseJobId);
            }
        }
    },

    handleActionClick(event) {
        const guardedButton = event.target.closest('[data-prompt-index], [data-shortcut-index], [data-message-id][data-action-index]');
        if (guardedButton && this.handleBusyInteraction()) {
            event.preventDefault();
            return;
        }

        const promptButton = event.target.closest('[data-prompt-index]');
        if (promptButton) {
            const index = Number(promptButton.dataset.promptIndex || -1);
            if (Number.isFinite(index) && this.promptActions && this.promptActions[index]) {
                const action = this.promptActions[index];
                if (action.type && action.type !== 'prompt') {
                    this.runActionAsUserPrompt(action);
                } else {
                    this.runSuggestedPrompt(action.prompt || '');
                }
            }
            return;
        }

        const shortcutButton = event.target.closest('[data-shortcut-index]');
        if (shortcutButton) {
            const index = Number(shortcutButton.dataset.shortcutIndex || -1);
            if (Number.isFinite(index) && this.shortcutActions && this.shortcutActions[index]) {
                this.runActionAsUserPrompt(this.shortcutActions[index]);
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
        if (this.handleBusyInteraction()) return;
        this.ui.input.value = text;
        this.autosizeInput();
        await this.handleSubmit();
    },

    recordUserPrompt(raw) {
        const text = String(raw || '').trim();
        if (!text) return;
        const session = this.getActiveSession();
        if (session) {
            session.context.lastUserPrompt = text;
            if (session.title === 'New session' || session.title === 'Getting started') {
                session.title = this.deriveSessionTitle(text);
            }
        }
        this.pushMessage({
            role: 'user',
            text
        });
        this.renderSessionRail();
        this.saveState();
    },

    buildPromptForAction(action = {}) {
        const explicit = String(action.prompt || '').trim();
        if (explicit) return explicit;
        const type = String(action.type || '').trim();
        if (type === 'route') {
            if (action.focusLocalCheckup) return 'open settings checkup';
            if (action.page === 'live' && action.liveMode === 'upload') return 'open image analysis';
            if (action.page === 'live') return 'open camera';
            if (action.page) return `open ${String(action.page).replace(/-/g, ' ')}`;
        }
        if (type === 'handbook' || type === 'doc-result') return 'open handbook';
        if (type === 'tutorial') return `show ${action.flow === 'local' ? 'local' : 'cloud'} tutorial`;
        if (type === 'guided-start') return `guided ${this.getGuidedKind(action.guidedKind)}`;
        if (type === 'export') {
            return `export ${String(action.exportKind || 'reports').trim().toLowerCase() === 'analytics' ? 'analytics' : 'reports'} csv`;
        }
        if (type === 'overview') return 'system overview';
        if (type === 'settings-profile') {
            const profile = String(action.profile || 'recommended').trim().toLowerCase();
            if (profile === 'api') return 'switch to api mode';
            if (profile === 'local') return 'apply local profile';
            return 'recommend settings';
        }
        return String(action.label || '').trim();
    },

    buildActionAcknowledgement(action = {}, prompt = '') {
        const label = String(action.label || action.page || 'That action').trim();
        const preserved = prompt ? ` I also saved "${prompt}" as your prompt in this chat.` : '';
        if (action.type === 'route') {
            return `${label} is ready. I am opening it now.${preserved}`;
        }
        if (action.type === 'handbook' || action.type === 'doc-result') {
            return `${label} is ready in the handbook. I am opening it now.${preserved}`;
        }
        return '';
    },

    async runActionAsUserPrompt(action = {}) {
        if (!action || !action.type) return;
        if (this.handleBusyInteraction()) return;
        const prompt = this.buildPromptForAction(action);
        if (prompt) {
            this.recordUserPrompt(prompt);
        }
        const feedbackLabel = this.pickActionFeedback(action) || this.pickResponseFeedback(prompt) || 'Working on that...';
        const responseJobId = this.beginResponseFeedback(feedbackLabel);
        try {
            await this.waitForFeedbackFrame();
            const acknowledgement = this.buildActionAcknowledgement(action, prompt);
            if (acknowledgement) {
                this.pushMessage({
                    role: 'assistant',
                    text: acknowledgement,
                    actions: [action]
                });
            }
            await this.performAction(action);
        } finally {
            this.finishResponseFeedback(responseJobId);
        }
    },

    pushMessage(message) {
        const session = this.getActiveSession();
        if (!session) return;
        const normalized = this.normalizeMessage({
            ...message,
            id: message.id || `msg-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
            createdAt: message.createdAt || Date.now()
        });
        if (!normalized) return;
        session.messages.push(normalized);
        session.messages = session.messages.slice(-this.MAX_MESSAGES);
        session.updatedAt = Date.now();
        this.refreshSessionUi();
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
                id: 'glossary-report-risk-terms',
                label: 'Glossary',
                title: 'Report risk terminology',
                text: 'Severity describes the consequence level of the observed violation. Likelihood describes how probable the listed harm is if the scene continues without correction. Main risks summarize the highest-priority risk cells for each report card.',
                pageKey: 'workflow',
                stageKey: 'reports',
                keywords: ['severity', 'likelihood', 'probability', 'chance', 'main risks', 'risk summary', 'case']
            },
            {
                id: 'glossary-assistant',
                label: 'Assistant',
                title: 'Assistant shortcuts and exports',
                text: 'The assistant can open app pages, switch Live Monitor into camera or image-analysis mode, guide tutorial steps in a slideshow-style card, apply recommended settings profiles, export CSV files, and remember previous sessions locally in the browser.',
                pageKey: 'intro',
                keywords: ['assistant', 'export', 'csv', 'session', 'shortcut', 'camera', 'upload', 'settings']
            },
            {
                id: 'glossary-privacy-boundaries',
                label: 'Glossary',
                title: 'Privacy and permission boundaries',
                text: 'Safe assistant output should summarize allowed safety data without exposing credentials, sync secrets, private session data, or cross-user admin details. Sensitive admin actions should stay inside approved app views.',
                pageKey: 'admin',
                keywords: ['privacy', 'permission', 'sensitive', 'confidential', 'secret', 'token', 'admin', 'safe version', 'anonymize', 'redact']
            },
            {
                id: 'glossary-live-workflows',
                label: 'Glossary',
                title: 'Live monitor workflows',
                text: 'Camera Stream is for live monitoring and report capture. Analyze Image is for still image uploads where the user wants one-off PPE detection and annotated results.',
                pageKey: 'workflow',
                stageKey: 'capture',
                keywords: ['live monitor', 'camera', 'upload image', 'analyze image', 'image violations']
            },
            {
                id: 'glossary-settings-profiles',
                label: 'Glossary',
                title: 'Settings profiles',
                text: 'Recommended settings keep the system balanced. API mode favors the smooth hosted cloud workflow. Local profile is for approved machines using the local pipeline and local mode checkup.',
                pageKey: 'admin',
                keywords: ['recommended settings', 'api mode', 'cloud mode', 'local profile', 'settings']
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
            export: ['csv', 'download'],
            camera: ['live', 'monitor', 'stream'],
            image: ['upload', 'photo', 'snapshot'],
            settings: ['profile', 'recommended', 'checkup']
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
            const filename = `casm-assistant-reports-${this.buildTimestampToken()}.csv`;
            const content = '\uFEFF' + lines.join('\r\n');
            const exportId = `reports-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
            this.preparedCsvDownloads[exportId] = {
                filename,
                content,
                createdAt: Date.now()
            };
            const summary = this.describeReportFilters(filters);
            const session = this.getActiveSession();
            if (session) session.context.lastExportKind = 'reports';
            return {
                success: true,
                rowCount: filtered.length,
                filterSummary: summary,
                filename,
                exportId,
                previewRows: filtered.slice(0, 5).map((row) => ({
                    report_id: row.report_id,
                    timestamp: row.timestamp,
                    status: row.status,
                    severity: row.severity,
                    source_scope: row.source_scope,
                    source_label: row.source_label,
                    missing_ppe: Array.isArray(row.missing_ppe) ? row.missing_ppe.join('; ') : ''
                }))
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
        const ppeTypes = this.extractAnalyticsPpeTypes(rawQuery);
        const source = /\blocal synced\b|\bsynced local\b/.test(query)
            ? 'synced_local'
            : /\bshared\b/.test(query)
                ? 'shared'
                : /\blocal\b/.test(query) && !/\blocal synced\b|\bsynced local\b/.test(query)
                    ? 'local'
                    : /\bcloud\b/.test(query)
                        ? 'cloud'
                        : '';
        const status = /\b(ready|completed|complete|done|finished)\b/.test(query)
            ? 'completed'
            : /\b(generating|processing|in progress|running)\b/.test(query)
                ? 'generating'
                : /\b(queued|queue|pending|waiting)\b/.test(query)
                    ? 'pending'
                    : /\b(failed|failure|error|errored)\b/.test(query)
                        ? 'failed'
                        : /\b(skipped|cancelled|canceled)\b/.test(query)
                            ? 'skipped'
                            : /\bpartial|partially\b/.test(query)
                                ? 'partial'
                                : '';
        const dateExact = this.extractReportExactDateFilter(rawQuery);
        return {
            source,
            severity: /\bhigh\b/.test(query)
                ? 'high'
                : /\bmedium\b/.test(query)
                    ? 'medium'
                    : /\blow\b/.test(query)
                        ? 'low'
                        : '',
            status,
            dateRange: dateExact
                ? ''
                : /\btoday\b/.test(query)
                ? 'today'
                : /\byesterday\b|\blast 24 hours\b/.test(query)
                    ? 'yesterday'
                    : /\bweek\b|\bthis week\b|\blast seven days\b|\bseven days\b|\b7 days\b|\blast 7 days\b/.test(query)
                        ? 'week'
                        : /\bmonth\b|\bthis month\b|\blast 30 days\b|\b30 days\b/.test(query)
                            ? 'month'
                            : '',
            dateExact,
            ppeTypes,
            searchTokens: this.tokenize(query)
                .filter((token) => ![
                    'export', 'download', 'csv', 'reports', 'report', 'analytics', 'local', 'cloud', 'synced',
                    'show', 'shows', 'showing', 'see', 'view', 'review', 'check', 'browse', 'inspect', 'filter', 'find', 'list', 'display',
                    'slide', 'slideshow', 'carousel', 'look', 'through', 'as', 'tag', 'tags', 'source',
                    'latest', 'newest', 'recent', 'recently', 'current', 'last', 'so', 'far', 'have', 'a', 'an', 'the', 'i', 'please',
                    'what', 'why', 'how', 'where', 'when', 'which', 'are', 'is', 'was', 'were', 'do', 'does', 'did',
                    'mean', 'means', 'meaning', 'purpose', 'used', 'for', 'explain', 'about', 'on', 'at', 'in', 'of',
                    'main', 'risk', 'risks', 'case', 'cases', 'each', 'likelihood', 'probability', 'chance', 'know', 'understand',
                    'status', 'statuses', 'tag', 'tags',
                    'can', 'you', 'find', 'get', 'make', 'create', 'need', 'want', 'wanna', 'them', 'to', 'me', 'all', 'any', 'rows', 'row',
                    'today', 'yesterday', 'week', 'month', 'high', 'medium', 'low', 'severity',
                    'ready', 'completed', 'complete', 'done', 'finished', 'generating', 'processing', 'pending', 'queued', 'queue', 'waiting',
                    'failed', 'failure', 'error', 'errored', 'skipped', 'partial', 'shared',
                    'violation', 'violations', 'incident', 'incidents', 'ppe',
                    'helmet', 'helmets', 'hardhat', 'hardhats', 'hard', 'hat', 'vest', 'vests',
                    'glove', 'gloves', 'mask', 'masks', 'goggle', 'goggles', 'boot', 'boots', 'shoe', 'shoes',
                    'jan', 'january', 'feb', 'february', 'mar', 'march', 'apr', 'april', 'may', 'jun', 'june',
                    'jul', 'july', 'aug', 'august', 'sep', 'sept', 'september', 'oct', 'october', 'nov', 'november', 'dec', 'december'
                ].includes(token))
                .filter((token) => !(dateExact && /^\d+(st|nd|rd|th)?$/.test(token)))
        };
    },

    extractReportExactDateFilter(rawQuery = '') {
        const source = String(rawQuery || '').trim();
        const lowerSource = source.toLowerCase();
        const normalized = this.normalizeText(source);

        const isoMatch = lowerSource.match(/\b(20\d{2})[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b/);
        if (isoMatch) {
            const [, year, month, day] = isoMatch;
            return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        }

        const slashMatch = lowerSource.match(/\b(0?[1-9]|[12]\d|3[01])[-/](0?[1-9]|1[0-2])[-/](20\d{2})\b/);
        if (slashMatch) {
            const [, day, month, year] = slashMatch;
            return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        }

        const monthNames = {
            jan: '01', january: '01',
            feb: '02', february: '02',
            mar: '03', march: '03',
            apr: '04', april: '04',
            may: '05',
            jun: '06', june: '06',
            jul: '07', july: '07',
            aug: '08', august: '08',
            sep: '09', sept: '09', september: '09',
            oct: '10', october: '10',
            nov: '11', november: '11',
            dec: '12', december: '12'
        };
        const monthPattern = Object.keys(monthNames).join('|');
        const namedMonthFirst = normalized.match(new RegExp(`\\b(${monthPattern})\\s+(0?[1-9]|[12]\\d|3[01])(?:st|nd|rd|th)?\\s+(20\\d{2})\\b`));
        if (namedMonthFirst) {
            const [, monthName, day, year] = namedMonthFirst;
            return `${year}-${monthNames[monthName]}-${String(day).padStart(2, '0')}`;
        }
        const namedDayFirst = normalized.match(new RegExp(`\\b(0?[1-9]|[12]\\d|3[01])(?:st|nd|rd|th)?\\s+(${monthPattern})\\s+(20\\d{2})\\b`));
        if (namedDayFirst) {
            const [, day, monthName, year] = namedDayFirst;
            return `${year}-${monthNames[monthName]}-${String(day).padStart(2, '0')}`;
        }

        return '';
    },

    matchesReportFilters(row, filters) {
        const sourceValues = this.normalizeSourceFilterValues(filters, true);
        if (sourceValues.length) {
            const scope = this.getSourceScope(row);
            if (!sourceValues.includes(scope)) return false;
        }

        const severityValues = this.normalizeSeverityFilterValues(filters);
        if (severityValues.length) {
            const severity = String(row?.severity || '').trim().toLowerCase();
            if (!severityValues.includes(severity)) return false;
        }

        if (filters.status) {
            const status = String(row?.status || '').trim().toLowerCase();
            const normalizedStatus = status === 'ready' || status === 'done' ? 'completed'
                : status === 'queued' || status === 'waiting' ? 'pending'
                    : status === 'processing' || status === 'running' ? 'generating'
                        : status;
            if (filters.status === 'pending' && normalizedStatus !== 'pending') return false;
            if (filters.status === 'generating' && normalizedStatus !== 'generating') return false;
            if (filters.status === 'completed' && normalizedStatus !== 'completed') return false;
            if (filters.status === 'failed' && normalizedStatus !== 'failed' && normalizedStatus !== 'error') return false;
            if (filters.status === 'skipped' && normalizedStatus !== 'skipped') return false;
            if (filters.status === 'partial' && normalizedStatus !== 'partial') return false;
        }

        if (filters.dateExact) {
            const rowDateKey = this.getRowDateKey(row);
            if (!rowDateKey) return false;
            if (rowDateKey !== filters.dateExact) return false;
        }

        if (filters.dateRange) {
            const rowDate = new Date(row?.timestamp || 0);
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            if (filters.dateRange === 'today' && rowDate < today) return false;
            if (filters.dateRange === 'yesterday') {
                const yesterday = new Date(today);
                yesterday.setDate(yesterday.getDate() - 1);
                if (rowDate < yesterday || rowDate >= today) return false;
            }
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

        if (filters.dateFrom || filters.dateTo) {
            const rowDateKey = this.getRowDateKey(row);
            if (!rowDateKey) return false;
            if (filters.dateFrom && rowDateKey < filters.dateFrom) return false;
            if (filters.dateTo && rowDateKey > filters.dateTo) return false;
        }

        if (Array.isArray(filters.searchTokens) && filters.searchTokens.length) {
            const haystack = this.normalizeText([
                row?.report_id,
                row?.device_id,
                row?.timestamp,
                row?.violation_summary,
                Array.isArray(row?.missing_ppe) ? row.missing_ppe.join(' ') : '',
                Array.isArray(row?.ppe_tags) ? row.ppe_tags.join(' ') : '',
                row?.severity,
                row?.status,
                row?.source_scope,
                row?.source_label
            ].join(' '));
            if (!filters.searchTokens.every((token) => haystack.includes(token))) return false;
        }

        if (Array.isArray(filters.ppeTypes) && filters.ppeTypes.length) {
            const missing = Array.isArray(row?.missing_ppe) ? row.missing_ppe : [];
            const ppeTags = Array.isArray(row?.ppe_tags) ? row.ppe_tags : [];
            const breakdownLabels = row?.breakdown && typeof row.breakdown === 'object'
                ? Object.entries(row.breakdown)
                    .filter(([, value]) => Number(value) > 0)
                    .map(([label]) => label)
                : [];
            const normalizedLabels = new Set([...missing, ...ppeTags, ...breakdownLabels].map((label) => this.normalizePpeFilterLabel(label)));
            if (!filters.ppeTypes.some((label) => normalizedLabels.has(this.normalizePpeFilterLabel(label)))) return false;
        }

        return true;
    },

    describeReportFilters(filters) {
        const parts = [];
        const sources = this.normalizeSourceFilterValues(filters, true);
        if (sources.length) {
            parts.push(`${sources.map((value) => this.formatSourceFilterLabel(value)).join(' or ')} rows`);
        }
        const severities = this.normalizeSeverityFilterValues(filters);
        if (severities.length) {
            parts.push(`${severities.map((value) => this.formatSeverityFilterLabel(value)).join(' or ')} severity`);
        }
        if (filters.status) parts.push(`${filters.status === 'completed' ? 'ready' : filters.status} status`);
        if (filters.dateExact) parts.push(filters.dateExact);
        if (filters.dateRange) parts.push(filters.dateRange);
        if (filters.dateFrom && filters.dateTo) parts.push(`${filters.dateFrom} to ${filters.dateTo}`);
        else if (filters.dateFrom) parts.push(`from ${filters.dateFrom}`);
        else if (filters.dateTo) parts.push(`until ${filters.dateTo}`);
        if (Array.isArray(filters.ppeTypes) && filters.ppeTypes.length) {
            const labels = filters.ppeTypes.map((label) => String(label || '')
                .replace(/^NO-/, '')
                .replace(/Safety /g, 'safety ')
                .toLowerCase());
            parts.push(`missing ${labels.join(', ')}`);
        }
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
        const compactMobile = window.innerWidth <= 520;
        const maxHeight = compactMobile ? 104 : 132;
        const minHeight = compactMobile ? 44 : 46;
        const next = Math.min(this.ui.input.scrollHeight, maxHeight);
        this.ui.input.style.height = `${Math.max(minHeight, next)}px`;
    },

    scrollMessagesToBottom() {
        if (!this.ui.messages) return;
        const messages = this.ui.messages;
        const settle = () => {
            messages.scrollTop = messages.scrollHeight;
        };
        settle();
        if (typeof window.requestAnimationFrame === 'function') {
            window.requestAnimationFrame(settle);
        }
        window.setTimeout(settle, 80);
        window.setTimeout(settle, 220);
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
        let text = String(value || '')
            .toLowerCase()
            .replace(/\bdon't\b/g, 'dont')
            .replace(/\bdoesn't\b/g, 'does not')
            .replace(/\bcan't\b/g, 'cannot')
            .replace(/\bwhat's\b/g, 'what is')
            .replace(/\banlytics\b/g, 'analytics')
            .replace(/\banalitic(s)?\b/g, 'analytics')
            .replace(/\bwats\b|\bwhats\b/g, 'what is')
            .replace(/\bstatuse\b|\bstatuz\b/g, 'status')
            .replace(/\bcamra\b|\bcamras\b|\bcam\b/g, 'camera')
            .replace(/\bcameras\b/g, 'camera')
            .replace(/\bviolashuns\b|\bviolashun\b|\bviolashions\b/g, 'violations')
            .replace(/\bteh\b/g, 'the')
            .replace(/\bbad stuff\b|\bbad news\b|\bno good results\b/g, 'violations')
            .replace(/\bmissing gear\b/g, 'ppe violations')
            .replace(/\bthing is on\b/g, 'system status')
            .replace(/\bboleh\b/g, 'can')
            .replace(/\btolong\b/g, 'please')
            .replace(/\bsaya nak\b|\bnak tengok\b/g, 'i want to see')
            .replace(/\bhari ini\b/g, 'today')
            .replace(/\bmasalah\b/g, 'issue')
            .replace(/\btak faham\b/g, 'do not understand')
            .replace(/\bcepat\b/g, 'quick')
            .replace(/[^a-z0-9\s-]/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
        return text;
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
