// API Functions
const API = {
    imagePrefetchState: {
        completed: new Set(),
        inFlight: new Set(),
        lastBatchAt: 0
    },
    reportHtmlPrefetchState: {
        completed: new Set(),
        inFlight: new Set()
    },
    localDraftObjectUrls: new Map(),
    reportHtmlObjectUrls: new Map(),
    LOCAL_REPORT_DRAFTS_SCOPE: 'reports:local-drafts',
    LOCAL_REPORT_SYNC_TAG: 'casm-local-report-sync',
    dashboardWarmupState: {
        promise: null,
        startedAt: 0,
        completedAt: 0,
        results: {},
        forceQueued: false
    },

    /**
     * fetch() with a hard client-side timeout via AbortController. Used for
     * cloud-touching endpoints where a stalled response would otherwise hang
     * the UI forever (e.g. Local Mode Checkup → cloud provisioning).
     */
    async _fetchWithTimeout(url, init = {}, timeoutMs = 15000) {
        // Refuse to issue requests when the page itself is in an invalid
        // context (chrome-error://chromewebdata/, about:blank, data:URL).
        // Browsers block such cross-origin requests and report the noisy
        // "Unsafe attempt to load URL ... from frame with URL
        // chrome-error://chromewebdata/" warning. Failing fast here gives
        // callers a clear error to surface to the user instead.
        const docProtocol = String((typeof window !== 'undefined' && window.location && window.location.protocol) || '').toLowerCase();
        if (docProtocol === 'chrome-error:' || docProtocol === 'about:' || docProtocol === 'data:') {
            const e = new Error(`Refusing to fetch ${url}: page is in an invalid context (${docProtocol}). Reload the tab from the backend URL.`);
            e.name = 'InvalidContextError';
            throw e;
        }
        if (typeof navigator !== 'undefined' && navigator.onLine === false) {
            let isLocalTarget = false;
            try {
                isLocalTarget = this.isLocalBackendBase ? this.isLocalBackendBase(url) : false;
            } catch (err) { }
            
            if (!isLocalTarget) {
                const e = new Error(`Offline: skipped network request to ${url}`);
                e.name = 'OfflineSkippedError';
                throw e;
            }
        }

        const controller = new AbortController();
        const externalSignal = init && init.signal;
        if (externalSignal) {
            if (externalSignal.aborted) {
                controller.abort();
            } else {
                externalSignal.addEventListener('abort', () => controller.abort(), { once: true });
            }
        }
        const timer = setTimeout(() => controller.abort(), Math.max(1000, Number(timeoutMs) || 15000));
        try {
            return await fetch(url, { ...init, signal: controller.signal });
        } catch (err) {
            if (controller.signal.aborted) {
                const e = new Error(`Request timed out after ${timeoutMs}ms: ${url}`);
                e.name = 'TimeoutError';
                e.cause = err;
                throw e;
            }
            throw err;
        } finally {
            clearTimeout(timer);
        }
    },

    _normalizeBaseUrl(value) {
        const raw = String(value || '').trim();
        if (!raw || (typeof window !== 'undefined' && raw === window.location.origin)) {
            return '';
        }
        return raw.replace(/\/+$/, '');
    },

    getCloudBackendBaseUrl() {
        return this._normalizeBaseUrl(
            window.PPE_API_URL
            || (window.__PPE_CONFIG__ && window.__PPE_CONFIG__.API_BASE_URL)
            || ''
        );
    },

    getLocalBackendBaseUrl() {
        return this._normalizeBaseUrl((API_CONFIG && API_CONFIG.LOCAL_BACKEND_URL) || 'http://localhost:5000');
    },

    isLocalBackendBase(baseUrl) {
        try {
            const resolved = new URL(
                this._normalizeBaseUrl(baseUrl) || window.location.origin,
                window.location.origin
            );
            const host = String(resolved.hostname || '').toLowerCase();
            return host === 'localhost' || host === '127.0.0.1' || host === '0.0.0.0';
        } catch (error) {
            return false;
        }
    },

    isPageServedFromLocalHost() {
        try {
            const host = String((window.location && window.location.hostname) || '').toLowerCase();
            return host === 'localhost'
                || host === '127.0.0.1'
                || host === '0.0.0.0'
                || host.endsWith('.local');
        } catch (error) {
            return false;
        }
    },

    canUseLocalBackendFromPage(baseUrl = null) {
        const target = this._normalizeBaseUrl(baseUrl || this.getLocalBackendBaseUrl());
        if (!this.isLocalBackendBase(target)) return true;
        if (this.isPageServedFromLocalHost()) return true;

        // Deployed HTTPS frontends cannot safely POST to the user's loopback
        // Flask server; Chrome blocks this as Private Network Access and emits
        // console errors even when fetch() is caught.
        return false;
    },

    canUseRemoteCloudBackendFromPage(baseUrl) {
        const normalized = this._normalizeBaseUrl(baseUrl);
        if (!normalized) return false;
        const explicitOverride = String((typeof window !== 'undefined' && window.PPE_API_URL) || '').trim();
        if (explicitOverride) return true;
        const configuredCloudBase = this._normalizeBaseUrl(
            (typeof window !== 'undefined'
                && window.__PPE_CONFIG__
                && window.__PPE_CONFIG__.API_BASE_URL)
            || ''
        );
        if (configuredCloudBase && configuredCloudBase === normalized) return true;
        if (this.isPageServedFromLocalHost() && !this.isLocalBackendBase(normalized)) {
            return false;
        }
        return true;
    },

    shouldPersistLocalReportDraft(result = {}) {
        if (!result || typeof result !== 'object') return false;
        if (result.report_queued === false) return false;

        if (result.local_draft_required === true || result.requires_local_draft === true) {
            return true;
        }
        if (result.local_draft_required === false || result.requires_local_draft === false) {
            return false;
        }

        const explicitScope = this.inferReportSourceScope(result)
            || String(result.source_scope || result.report_scope || result.scope || '').trim().toLowerCase();
        if (explicitScope === 'local') return true;
        if (['cloud', 'synced_local', 'shared'].includes(explicitScope)) return false;

        if (typeof navigator !== 'undefined' && navigator.onLine === false) {
            return true;
        }

        try {
            const currentBase = this._normalizeBaseUrl(
                (typeof API_CONFIG !== 'undefined' && API_CONFIG.BASE_URL) || ''
            );
            return this.isLocalBackendBase(currentBase || (window.location && window.location.origin) || '');
        } catch (error) {
            return false;
        }
    },

    isExpectedOfflineFetchError(error) {
        const message = String(
            (error && (error.message || error.name || error.toString && error.toString())) || error || ''
        ).toLowerCase();
        return (
            message.includes('failed to fetch')
            || message.includes('err_connection_refused')
            || message.includes('networkerror')
            || message.includes('load failed')
            || message.includes('request timed out')
            || message.includes('timeouterror')
            || message.includes('offlineskippederror')
            || message.includes('offline: skipped')
        );
    },

    logFetchFailure(context, error) {
        const message = error && error.message ? error.message : error;
        if (this.isExpectedOfflineFetchError(error)) {
            console.warn(`${context}:`, message);
            return;
        }
        console.warn(`${context}:`, error);
    },

    getReportSourceMarker(record = {}) {
        return String(record.origin || record.sync_source || record.source || record.source_reason || '').trim().toLowerCase();
    },

    getReportSourceMarkers(record = {}) {
        return [
            record && record.origin,
            record && record.sync_source,
            record && record.source,
            record && record.source_reason
        ].map((value) => String(value || '').trim().toLowerCase()).filter(Boolean);
    },

    getReportDeviceKey(record = {}) {
        return String(record.device_id || '').trim().toLowerCase();
    },

    hasLocalArtifactOriginDevice(deviceId = '') {
        const normalized = String(deviceId || '').trim().toLowerCase();
        return (
            normalized === 'local_cache'
            || normalized === 'offline_local_cache'
            || normalized === 'browser_local_draft'
            || normalized === 'local_cache_sync'
            || normalized === 'sync_local_cache'
            || normalized.startsWith('local_')
            || normalized.startsWith('offline_')
            || normalized.startsWith('browser_local')
        );
    },

    hasStrictLocalArtifactOrigin(record = {}) {
        if (!record || typeof record !== 'object') return false;
        if (this.hasLocalReportIdPrefix(record.report_id || record.id)) return true;
        if (this.hasLocalArtifactOriginDevice(this.getReportDeviceKey(record))) return true;

        const detectionData = this.parseObjectMaybeJson(record.detection_data);
        if (detectionData && Object.keys(detectionData).length > 0) {
            const nested = {
                ...detectionData,
                report_id: record.report_id || detectionData.report_id,
                device_id: detectionData.device_id || record.device_id
            };
            if (this.hasLocalReportIdPrefix(nested.report_id || nested.id)) return true;
            if (this.hasLocalArtifactOriginDevice(this.getReportDeviceKey(nested))) return true;
        }

        return false;
    },

    getReportSyncState(record = {}) {
        return String(record.sync_state || record.syncState || record.cloud_sync_state || record.cloudSyncState || '').trim().toLowerCase();
    },

    hasCloudReportArtifacts(record = {}) {
        return !!(
            record
            && (
                record.has_cloud_artifacts
                || record.original_image_key
                || record.annotated_image_key
                || record.report_html_key
                || record.cloud_report_url
                || record.cloud_image_url
            )
        );
    },

    hasCloudReportArtifactEvidence(record = {}) {
        return !!(
            record
            && (
                record.has_cloud_report_artifact
                || record.has_cloud_report
                || record.report_html_key
                || record.report_pdf_key
                || record.cloud_report_url
            )
        );
    },

    hasLocalOriginMarkers(record = {}) {
        if (!record || typeof record !== 'object') return false;
        if (this.hasLocalReportIdPrefix(record.report_id || record.id)) return true;

        const sourceMarker = this.getReportSourceMarker(record);
        const handoffOnlyMarker = sourceMarker === 'browser_local_draft_handoff'
            || sourceMarker === 'sync_local_cache_partial';
        const localMarkers = new Set([
            'local',
            'local_pipeline',
            'local_pending_recovery',
            'offline_local',
            'offline_local_cache',
            'browser_local_draft',
            'sync_local_cache',
            'local_cache',
            'local_cache_sync',
            'offline_local_cache_sync',
            'local_synced'
        ]);
        if (handoffOnlyMarker) {
            return this.hasStrictLocalArtifactOrigin(record);
        }
        if (
            localMarkers.has(sourceMarker)
            || sourceMarker.startsWith('local_')
            || sourceMarker.startsWith('offline_')
            || (sourceMarker.startsWith('browser_local') && sourceMarker !== 'browser_local_draft_handoff')
        ) {
            return true;
        }

        const deviceId = this.getReportDeviceKey(record);
        return (
            deviceId === 'local_cache'
            || deviceId === 'offline_local_cache'
            || deviceId === 'local_cache_sync'
            || deviceId === 'sync_local_cache'
            || deviceId === 'browser_local_draft'
            || deviceId.startsWith('local_')
            || deviceId.startsWith('offline_')
            || deviceId.startsWith('browser_local')
        );
    },

    hasConfirmedSyncedLocalReport(record = {}) {
        if (!record || typeof record !== 'object') return false;
        const sourceMarkers = this.getReportSourceMarkers(record);
        const hasMarker = (marker) => sourceMarkers.includes(marker);
        const sourceMarker = sourceMarkers[0] || '';
        const deviceId = this.getReportDeviceKey(record);
        const syncState = this.getReportSyncState(record);
        const syncMarker = (
            hasMarker('sync_local_cache')
            || hasMarker('local_cache_sync')
            || hasMarker('offline_local_cache_sync')
            || deviceId === 'local_cache_sync'
            || deviceId === 'sync_local_cache'
        );
        if (syncMarker) {
            return this.hasCloudReportArtifactEvidence(record);
        }

        const strictLocalOrigin = this.hasStrictLocalArtifactOrigin(record);
        if (hasMarker('local_synced')) {
            return strictLocalOrigin && this.hasCloudReportArtifactEvidence(record);
        }
        if (hasMarker('browser_local_draft_handoff')) {
            return strictLocalOrigin && this.hasCloudReportArtifactEvidence(record);
        }

        const syncStateConfirmed = (
            syncState === 'synced'
            || syncState === 'cloud_completed'
            || syncState === 'completed_synced'
            || syncState.startsWith('cloud_sync_')
            || syncState.startsWith('sync_')
        );
        if (syncStateConfirmed && strictLocalOrigin && this.hasCloudReportArtifactEvidence(record)) {
            return true;
        }

        return false;
    },

    inferReportSourceScope(sourceHint = null) {
        if (typeof sourceHint === 'string') {
            const normalized = sourceHint.trim().toLowerCase();
            if (['local', 'cloud', 'shared', 'synced_local'].includes(normalized)) {
                return normalized;
            }
            if (normalized.includes('local synced')) return 'synced_local';
            if (normalized.includes('cloud')) return 'cloud';
            if (normalized.includes('local')) return 'local';
            return '';
        }

        const record = sourceHint && typeof sourceHint === 'object' ? sourceHint : {};
        const explicit = String(record.source_scope || record.report_scope || record.scope || '').trim().toLowerCase();
        if (explicit === 'synced_local') {
            if (this.hasConfirmedSyncedLocalReport(record)) return 'synced_local';
            return this.hasStrictLocalArtifactOrigin(record) ? 'local' : 'cloud';
        }
        if (['local', 'cloud', 'shared'].includes(explicit)) {
            return explicit;
        }
        if (explicit === 'local_synced') return 'synced_local';

        const sourceMarker = this.getReportSourceMarker(record);
        if (
            sourceMarker === 'sync_local_cache'
            || sourceMarker === 'local_cache_sync'
            || sourceMarker === 'offline_local_cache_sync'
        ) {
            if (this.hasConfirmedSyncedLocalReport(record)) return 'synced_local';
            return this.hasStrictLocalArtifactOrigin(record) ? 'local' : 'cloud';
        }
        if (sourceMarker === 'local_synced') {
            if (this.hasConfirmedSyncedLocalReport(record)) return 'synced_local';
            return this.hasStrictLocalArtifactOrigin(record) ? 'local' : 'cloud';
        }
        if (sourceMarker === 'browser_local_draft_handoff') {
            if (this.hasConfirmedSyncedLocalReport(record)) return 'synced_local';
            return this.hasStrictLocalArtifactOrigin(record) ? 'local' : 'cloud';
        }

        const label = String(record.source_label || '').trim().toLowerCase();
        if (label.includes('local synced')) {
            if (this.hasConfirmedSyncedLocalReport(record)) return 'synced_local';
            return this.hasStrictLocalArtifactOrigin(record) ? 'local' : 'cloud';
        }
        if (label.includes('cloud')) return 'cloud';
        if (label.includes('local')) return 'local';

        const deviceId = this.getReportDeviceKey(record);
        if (deviceId === 'local_cache_sync' || deviceId === 'sync_local_cache') {
            if (this.hasConfirmedSyncedLocalReport(record)) return 'synced_local';
            return this.hasStrictLocalArtifactOrigin(record) ? 'local' : 'cloud';
        }
        if (this.hasLocalOriginMarkers(record)) return 'local';
        return '';
    },

    hasLocalReportArtifacts(sourceHint = null) {
        const scope = this.inferReportSourceScope(sourceHint);
        if (scope === 'local') return true;

        const record = sourceHint && typeof sourceHint === 'object' ? sourceHint : {};
        const truthyLocalFlag = [
            record.has_local_report,
            record.has_local_artifacts,
            record.local_report_available,
            record.local_cache_available
        ].some((value) => value === true || value === 1 || String(value || '').toLowerCase() === 'true');

        if (truthyLocalFlag) return true;
        if (record.local_image_url || record.local_report_url) return true;

        const sourceMarker = this.getReportSourceMarker(record);
        const localSyncMarker = sourceMarker === 'sync_local_cache'
            || sourceMarker === 'local_cache_sync'
            || sourceMarker === 'offline_local_cache_sync'
            || (
                sourceMarker === 'local_synced'
                && this.hasConfirmedSyncedLocalReport(record)
            )
            || (
                sourceMarker === 'browser_local_draft_handoff'
                && this.hasConfirmedSyncedLocalReport(record)
            );

        const deviceId = this.getReportDeviceKey(record);
        const localDevice = this.hasLocalArtifactOriginDevice(deviceId);

        return scope === 'synced_local' && (localSyncMarker || localDevice);
    },

    hasConcreteLocalReportArtifacts(sourceHint = null) {
        const record = sourceHint && typeof sourceHint === 'object' ? sourceHint : {};
        const truthyLocalFlag = [
            record.has_local_report,
            record.has_local_artifacts,
            record.local_report_available,
            record.local_cache_available
        ].some((value) => value === true || value === 1 || String(value || '').toLowerCase() === 'true');

        return !!(
            truthyLocalFlag
            || record.local_image_url
            || record.local_report_url
            || record.original_blob
            || record.annotated_blob
            || record.report_html_blob
            || record.cached_report_html
        );
    },

    hasLocalReportIdPrefix(reportId) {
        const id = String(reportId || '').trim().toLowerCase();
        return /^(local|offline|browser_local|local-cache|offline-cache)[_-]/.test(id);
    },

    isStrictLocalOriginReport(sourceHint = null) {
        const record = sourceHint && typeof sourceHint === 'object' ? sourceHint : {};
        if (!record || typeof record !== 'object') return false;

        if (this.hasLocalReportIdPrefix(record.report_id || record.id)) {
            return true;
        }

        const detectionData = this.parseObjectMaybeJson(record.detection_data);
        if (detectionData && Object.keys(detectionData).length > 0) {
            const nested = {
                ...detectionData,
                report_id: record.report_id || detectionData.report_id,
                device_id: detectionData.device_id || record.device_id
            };
            if (this.isStrictLocalOriginReport(nested)) return true;
        }

        const scope = String(record.source_scope || record.report_scope || record.scope || '').trim().toLowerCase();
        if (scope === 'local') return true;

        const sourceMarker = this.getReportSourceMarker(record);
        const handoffOnlyMarker = sourceMarker === 'browser_local_draft_handoff'
            || sourceMarker === 'sync_local_cache_partial';
        const localMarkers = new Set([
            'local',
            'local_pipeline',
            'local_pending_recovery',
            'offline_local',
            'offline_local_cache',
            'browser_local_draft',
            'sync_local_cache',
            'local_cache',
            'local_cache_sync',
            'offline_local_cache_sync',
            'local_synced'
        ]);
        if (handoffOnlyMarker) {
            return this.hasStrictLocalArtifactOrigin(record);
        }
        if (
            localMarkers.has(sourceMarker)
            || sourceMarker.startsWith('local_')
            || sourceMarker.startsWith('offline_')
            || (sourceMarker.startsWith('browser_local') && sourceMarker !== 'browser_local_draft_handoff')
        ) {
            return true;
        }

        const deviceId = this.getReportDeviceKey(record);
        if (
            deviceId === 'local_cache'
            || deviceId === 'offline_local_cache'
            || deviceId === 'local_cache_sync'
            || deviceId === 'sync_local_cache'
            || deviceId === 'browser_local_draft'
            || deviceId.startsWith('local_')
            || deviceId.startsWith('offline_')
            || deviceId.startsWith('browser_local')
        ) {
            return true;
        }

        const label = String(record.source_label || '').trim().toLowerCase();
        return label === 'local';
    },

    isAlreadyCloudSyncedLocal(record = {}) {
        return this.hasConfirmedSyncedLocalReport(record);
    },

    async getLocalSyncCandidateSummary(options = {}) {
        const includeSynced = !!(options && options.includeSynced);
        const candidateIds = new Set();
        const inspectList = (list) => {
            if (!Array.isArray(list)) return;
            list.forEach((item) => {
                const reportId = String((item && item.report_id) || '').trim();
                if (!reportId || (!includeSynced && this.isAlreadyCloudSyncedLocal(item))) return;
                if (this.isStrictLocalOriginReport(item)) {
                    candidateIds.add(reportId);
                }
            });
        };

        try {
            inspectList(await this.readLocalReportDrafts());
        } catch (error) {
            console.debug('Could not inspect local report drafts for sync candidates:', error);
        }

        const cacheScopes = [
            'reports:pending',
            'violations:limit:100',
            'violations:limit:1000',
            'violations:limit:5000'
        ];
        await Promise.all(cacheScopes.map(async (scope) => {
            try {
                const cached = await this.readJsonCache(scope);
                if (cached && Array.isArray(cached.data)) {
                    inspectList(cached.data);
                }
            } catch (error) {
                console.debug('Could not inspect cached reports for sync candidates:', scope, error);
            }
        }));

        return {
            count: candidateIds.size,
            report_ids: Array.from(candidateIds)
        };
    },

    async filterStrictLocalSyncReportIds(reportIds = []) {
        const ids = Array.from(new Set(
            (Array.isArray(reportIds) ? reportIds : [reportIds])
                .map((id) => String(id || '').trim())
                .filter(Boolean)
        ));
        if (!ids.length) return [];

        const summary = await this.getLocalSyncCandidateSummary({ includeSynced: true });
        const candidateIds = new Set(summary.report_ids || []);
        return ids.filter((id) => candidateIds.has(id) || this.hasLocalReportIdPrefix(id));
    },

    getReportBackendBase(sourceHint = null) {
        const scope = this.inferReportSourceScope(sourceHint);
        const currentBase = this._normalizeBaseUrl(API_CONFIG.BASE_URL || '');
        const cloudBase = this.getCloudBackendBaseUrl();
        const localBase = this.getLocalBackendBaseUrl();

        if (
            scope === 'synced_local'
            && typeof navigator !== 'undefined'
            && navigator.onLine === false
            && this.hasConcreteLocalReportArtifacts(sourceHint)
        ) {
            return localBase || currentBase;
        }

        if (
            scope === 'synced_local'
            && this.isPageServedFromLocalHost()
            && this.hasConcreteLocalReportArtifacts(sourceHint)
        ) {
            return localBase || currentBase;
        }

        if (scope === 'cloud' || scope === 'synced_local' || scope === 'shared') {
            if (cloudBase && this.canUseRemoteCloudBackendFromPage(cloudBase)) return cloudBase;
            return this.isLocalBackendBase(currentBase) ? '' : currentBase;
        }

        if (scope === 'local') {
            return localBase || currentBase;
        }

        return currentBase;
    },

    buildReportScopedUrl(path, sourceHint = null) {
        const base = this.getReportBackendBase(sourceHint);
        return `${base || ''}${path}`;
    },

    getCloudReportScopedUrl(path) {
        const cloudBase = this.getCloudBackendBaseUrl();
        if (cloudBase && this.canUseRemoteCloudBackendFromPage(cloudBase)) {
            return `${cloudBase}${path}`;
        }

        const currentBase = this._normalizeBaseUrl(API_CONFIG.BASE_URL || '');
        if (!this.isLocalBackendBase(currentBase)) {
            return `${currentBase || ''}${path}`;
        }

        return `${currentBase || ''}${path}`;
    },

    isCloudReportScope(sourceHint = null) {
        const scope = this.inferReportSourceScope(sourceHint);
        return scope === 'cloud' || scope === 'synced_local' || scope === 'shared';
    },

    isCloudReportUnavailableOffline(sourceHint = null) {
        if (typeof navigator === 'undefined' || navigator.onLine !== false) return false;
        const scope = this.inferReportSourceScope(sourceHint);
        if (scope === 'synced_local' && this.hasConcreteLocalReportArtifacts(sourceHint)) return false;
        return scope === 'cloud' || scope === 'synced_local' || scope === 'shared';
    },

    parseObjectMaybeJson(value) {
        if (value && typeof value === 'object' && !Array.isArray(value)) {
            return value;
        }
        if (typeof value !== 'string') return {};
        try {
            const parsed = JSON.parse(value);
            return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
        } catch (error) {
            return {};
        }
    },

    canonicalViolationKey(rawKey) {
        if (!rawKey) return null;

        const normalized = rawKey
            .toString()
            .trim()
            .toUpperCase()
            .replace(/\s+/g, ' ')
            .replace(/^NO\s+/, 'NO-');

        const simplified = normalized
            .replace(/^MISSING\s+/, '')
            .replace(/^WITHOUT\s+/, '')
            .replace(/^NO[-\s]+/, '')
            .replace(/[\s_-]+/g, ' ')
            .trim();

        if (/HARD ?HAT|HELMET/.test(simplified)) return 'NO-Hardhat';
        if (/SAFETY ?VEST|HI ?VIS|HIGH ?VIS|VEST/.test(simplified)) return 'NO-Safety Vest';
        if (/GLOVE/.test(simplified)) return 'NO-Gloves';
        if (/MASK|RESPIRATOR/.test(simplified)) return 'NO-Mask';
        if (/GOGGLE|EYE/.test(simplified)) return 'NO-Goggles';
        if (/SAFETY ?SHOE|SAFETY ?BOOT|FOOTWEAR|BOOT/.test(simplified)) return 'NO-Safety Shoes';

        return null;
    },

    extractViolationKeys(violation) {
        const keys = [];
        const record = violation && typeof violation === 'object' ? violation : {};
        const detectionData = this.parseObjectMaybeJson(record.detection_data);

        const appendCanonical = (rawValue) => {
            const key = this.canonicalViolationKey(rawValue);
            if (key) keys.push(key);
        };

        if (Array.isArray(record.ppe_tags) && record.ppe_tags.length > 0) {
            record.ppe_tags.forEach(appendCanonical);
        }

        if (keys.length === 0 && Array.isArray(record.violations) && record.violations.length > 0) {
            record.violations.forEach(appendCanonical);
        }

        if (keys.length === 0 && Array.isArray(record.violation_types) && record.violation_types.length > 0) {
            record.violation_types.forEach(appendCanonical);
        }

        if (keys.length === 0 && Array.isArray(record.missing_ppe) && record.missing_ppe.length > 0) {
            record.missing_ppe.forEach((item) => appendCanonical(`NO-${item}`));
        }

        if (keys.length === 0 && Array.isArray(detectionData.ppe_tags)) {
            detectionData.ppe_tags.forEach(appendCanonical);
        }

        if (keys.length === 0 && Array.isArray(detectionData.violations)) {
            detectionData.violations.forEach(appendCanonical);
        }

        if (keys.length === 0 && Array.isArray(detectionData.missing_ppe)) {
            detectionData.missing_ppe.forEach((item) => appendCanonical(`NO-${item}`));
        }

        if (keys.length === 0 && Array.isArray(detectionData.violation_types)) {
            detectionData.violation_types.forEach(appendCanonical);
        }

        if (keys.length === 0 && Array.isArray(detectionData.detections)) {
            detectionData.detections.forEach((detection) => {
                if (!detection || typeof detection !== 'object') return;
                appendCanonical(detection.class_name || detection.label || detection.name || detection.class);
            });
        }

        if (keys.length === 0 && record.violation_summary) {
            const summary = record.violation_summary.toString();
            const matches = summary.match(/NO-[A-Za-z -]+/g) || [];
            matches.forEach((m) => appendCanonical(m.trim()));

            const missingMatches = summary.match(/Missing\s+[A-Za-z\s-]+/gi) || [];
            missingMatches.forEach((m) => appendCanonical(m.trim()));
        }

        return [...new Set(keys)];
    },

    violationKeyToMissingPpeLabel(key) {
        const canonical = this.canonicalViolationKey(key);
        if (canonical === 'NO-Hardhat') return 'Hardhat';
        if (canonical === 'NO-Safety Vest') return 'Safety Vest';
        if (canonical === 'NO-Gloves') return 'Gloves';
        if (canonical === 'NO-Mask') return 'Mask';
        if (canonical === 'NO-Goggles') return 'Goggles';
        if (canonical === 'NO-Safety Shoes') return 'Safety Shoes';
        return '';
    },

    extractMissingPpeLabels(violation) {
        const labels = this.extractViolationKeys(violation)
            .map((key) => this.violationKeyToMissingPpeLabel(key))
            .filter(Boolean);
        if (labels.length > 0) {
            return [...new Set(labels)];
        }

        const raw = Array.isArray(violation?.missing_ppe) ? violation.missing_ppe : [];
        return [...new Set(raw
            .map((item) => String(item || '').replace(/^NO[-\s]+/i, '').trim())
            .filter(Boolean))];
    },

    computeSafetyCompliance(stats) {
        const severity = stats?.severity || {};
        const high = Number(severity.high || 0);
        const medium = Number(severity.medium || 0);
        const low = Number(severity.low || 0);
        const total = Math.max(1, Number(stats?.total || (high + medium + low) || 0));
        const today = Number(stats?.today || 0);

        // Benchmark-inspired leading indicator proxy:
        // severity-weighted non-compliance burden + short-term frequency pressure.
        const weightedBurden = (high * 1.0) + (medium * 0.6) + (low * 0.3);
        const severityPenalty = (weightedBurden / total) * 45;
        const frequencyPenalty = Math.min(30, today * 2.5);
        const complianceScore = Math.round(Math.max(0, Math.min(100, 100 - severityPenalty - frequencyPenalty)));

        let benchmarkBand = 'critical';
        if (complianceScore >= 95) benchmarkBand = 'best-practice';
        else if (complianceScore >= 85) benchmarkBand = 'acceptable';
        else if (complianceScore >= 70) benchmarkBand = 'watchlist';

        return {
            score: complianceScore,
            benchmarkBand,
            benchmarkNote: 'Benchmark-inspired leading indicator aligned with construction PPE audit practice (95%+ is commonly targeted).'
        };
    },

    buildBreakdown(violations) {
        const breakdown = {
            'NO-Hardhat': 0,
            'NO-Safety Vest': 0,
            'NO-Gloves': 0,
            'NO-Mask': 0,
            'NO-Goggles': 0,
            'NO-Safety Shoes': 0
        };

        violations.forEach((violation) => {
            const keys = this.extractViolationKeys(violation);
            if (keys.length === 0) return;
            keys.forEach((key) => {
                const canonical = this.canonicalViolationKey(key);
                if (canonical && Object.prototype.hasOwnProperty.call(breakdown, canonical)) {
                    breakdown[canonical] += 1;
                }
            });
        });

        return breakdown;
    },

    computeDeltas(violations) {
        const now = new Date();
        const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const startYesterday = new Date(startToday);
        startYesterday.setDate(startYesterday.getDate() - 1);

        const startThisWeek = new Date(startToday);
        startThisWeek.setDate(startThisWeek.getDate() - ((startThisWeek.getDay() + 6) % 7));

        const startLastWeek = new Date(startThisWeek);
        startLastWeek.setDate(startLastWeek.getDate() - 7);

        let todayCount = 0;
        let yesterdayCount = 0;
        let thisWeekCount = 0;
        let lastWeekCount = 0;

        violations.forEach((v) => {
            if (!v?.timestamp) return;
            const ts = new Date(v.timestamp);
            if (Number.isNaN(ts.getTime())) return;

            if (ts >= startToday) todayCount += 1;
            else if (ts >= startYesterday) yesterdayCount += 1;

            if (ts >= startThisWeek) thisWeekCount += 1;
            else if (ts >= startLastWeek) lastWeekCount += 1;
        });

        return {
            todayDelta: todayCount - yesterdayCount,
            weekDelta: thisWeekCount - lastWeekCount
        };
    },

    countGeneratedReportsFromViolations(violations = []) {
        const list = Array.isArray(violations) ? violations : [];
        return list.filter((item) => {
            if (!item || typeof item !== 'object') return false;
            const status = String(item.status || '').trim().toLowerCase();
            return (
                item.has_report === true
                || status === 'completed'
                || status === 'ready'
                || status === 'partial'
                || !!item.report_html_key
                || !!item.local_report_url
            );
        }).length;
    },

    enrichStatsWithViolations(baseStats, violations) {
        const sortedViolations = [...violations].sort((a, b) => {
            const aTs = new Date(a.timestamp || 0).getTime();
            const bTs = new Date(b.timestamp || 0).getTime();
            return bTs - aTs;
        });

        const deltas = this.computeDeltas(sortedViolations);
        const generatedReports = this.countGeneratedReportsFromViolations(sortedViolations);

        const backendReportCount = Math.max(
            Number(baseStats.reportsGenerated) || 0,
            Number(baseStats.reports_generated) || 0,
            Number(baseStats.totalReports) || 0,
            Number(baseStats.reportsTotal) || 0,
            Number(baseStats.completed) || 0
        );
        const totalReportCount = Math.max(backendReportCount, generatedReports);

        return {
            ...baseStats,
            total: sortedViolations.length,
            reportsGenerated: totalReportCount,
            reports_generated: totalReportCount,
            totalReports: totalReportCount,
            reportsTotal: totalReportCount,
            breakdown: this.buildBreakdown(sortedViolations),
            todayDelta: deltas.todayDelta,
            weekDelta: deltas.weekDelta,
            recentViolations: sortedViolations.slice(0, 5)
        };
    },

    calculateStatsFromViolations(violations) {
        const list = Array.isArray(violations) ? violations : [];
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const weekAgo = new Date(today);
        weekAgo.setDate(weekAgo.getDate() - 7);

        const stats = {
            total: list.length,
            today: 0,
            thisWeek: 0,
            pending: 0,
            completed: 0,
            failed: 0,
            severity: { high: 0, medium: 0, low: 0 },
            breakdown: {},
            recentViolations: []
        };

        list.forEach((v) => {
            const vDate = new Date(v && v.timestamp ? v.timestamp : 0);
            if (!Number.isNaN(vDate.getTime())) {
                if (vDate >= today) stats.today += 1;
                if (vDate >= weekAgo) stats.thisWeek += 1;
            }

            const status = String((v && (v.status || (v.has_report ? 'completed' : 'pending'))) || 'pending').toLowerCase();
            if (status === 'completed') stats.completed += 1;
            else if (status === 'failed') stats.failed += 1;
            else stats.pending += 1;

            const severity = String((v && v.severity) || 'HIGH').toLowerCase();
            if (severity === 'high' || severity === 'critical') stats.severity.high += 1;
            else if (severity === 'medium') stats.severity.medium += 1;
            else stats.severity.low += 1;
        });

        return this.enrichStatsWithViolations(stats, list);
    },

    getCacheStorageKey(scope) {
        return `ppe-cache-v1:${scope}`;
    },

    reportHtmlCacheScope(reportId, sourceHint = null) {
        const rid = String(reportId || '').trim();
        return `report-html:universal:${rid}`;
    },

    isDashboardWarm(dataset, maxAgeMs = 90000) {
        const state = this.dashboardWarmupState || {};
        const completedAt = Number(state.completedAt || 0);
        if (!completedAt || (Date.now() - completedAt) > Math.max(1000, Number(maxAgeMs) || 90000)) {
            return false;
        }
        return !!(state.results && state.results[dataset]);
    },

    async waitForDashboardWarmup(datasets = [], timeoutMs = 800) {
        const required = Array.isArray(datasets) ? datasets : [datasets];
        const allWarm = () => required.every((name) => this.isDashboardWarm(name));
        if (allWarm()) return true;

        const state = this.dashboardWarmupState || {};
        if (!state.promise || timeoutMs <= 0) return false;

        try {
            await Promise.race([
                state.promise,
                new Promise((resolve) => setTimeout(resolve, Math.max(50, Number(timeoutMs) || 800)))
            ]);
        } catch (_) {
            // Warmup is an optimization path; page loads still have their normal fetch path.
        }
        return allWarm();
    },

    warmDashboardCaches(options = {}) {
        const state = this.dashboardWarmupState;
        const now = Date.now();
        const force = !!options.force;
        const minIntervalMs = Math.max(5000, Number(options.minIntervalMs || 90000));
        if (state.promise) {
            if (!force) return state.promise;
            if (state.forceQueued) return state.promise;
            state.forceQueued = true;
            return state.promise
                .catch(() => null)
                .then(() => {
                    state.forceQueued = false;
                    return this.warmDashboardCaches({
                        ...options,
                        force: true,
                        minIntervalMs: 5000
                    });
                });
        }
        if (!force && state.completedAt && (now - state.completedAt) < minIntervalMs) {
            return Promise.resolve(state.results || {});
        }

        state.startedAt = now;
        state.results = {};
        const timeoutMs = Math.max(3000, Math.min(Number(options.timeoutMs || 10000), 30000));

        const warmStats = async () => {
            const data = await this.fetchJsonNoCache(`${API_CONFIG.BASE_URL}/api/stats`, {
                cacheScope: 'stats:summary',
                timeoutMs
            });
            if (data && typeof data === 'object' && !data.error) {
                state.results.stats = true;
            }
            return data;
        };

        const warmViolations = async () => {
            const safeLimit = 1000;
            let list = await this.fetchJsonNoCache(
                `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.VIOLATIONS}?limit=${safeLimit}`,
                { timeoutMs }
            );
            list = Array.isArray(list) ? list : [];
            list = await this.mergeLocalReportDrafts(list, safeLimit);
            await this.writeJsonCache(`violations:limit:${safeLimit}`, this.stripLocalDraftRuntimeFields(list));
            state.results.violations = true;
            return list;
        };

        const warmPending = async () => {
            let list = await this.fetchJsonNoCache(`${API_CONFIG.BASE_URL}/api/reports/pending`, {
                timeoutMs: Math.max(3000, Math.min(timeoutMs, 12000))
            });
            list = Array.isArray(list) ? list : [];
            list = await this.mergeLocalReportDrafts(list, 100);
            await this.writeJsonCache('reports:pending', this.stripLocalDraftRuntimeFields(list));
            state.results.pending = true;
            return list;
        };

        state.promise = Promise.allSettled([
            warmStats(),
            warmViolations(),
            warmPending()
        ]).then((results) => {
            state.completedAt = Date.now();
            const summary = {
                stats: !!state.results.stats,
                violations: !!state.results.violations,
                pending: !!state.results.pending,
                failures: results
                    .map((result, index) => ({ result, name: ['stats', 'violations', 'pending'][index] }))
                    .filter((item) => item.result.status === 'rejected')
                    .map((item) => ({
                        dataset: item.name,
                        error: item.result.reason && item.result.reason.message
                            ? item.result.reason.message
                            : String(item.result.reason || 'unknown')
                    }))
            };
            try {
                if (typeof window !== 'undefined') {
                    window.dispatchEvent(new CustomEvent('ppe-dashboard:warmup', { detail: summary }));
                }
            } catch (_) { }
            if (summary.failures.length) {
                console.warn('Dashboard cache warmup completed with partial failures:', summary.failures);
            }
            return summary;
        }).finally(() => {
            state.promise = null;
        });

        return state.promise;
    },

    async writeJsonCache(scope, payload) {
        const envelope = {
            ts: Date.now(),
            data: payload
        };
        const key = this.getCacheStorageKey(scope);

        // 1. Always try IndexedDB first (primary)
        if (typeof IndexedDBManager !== 'undefined') {
            const success = await IndexedDBManager.setItem(key, envelope);
            if (success) return;
        }

        // 2. Fallback to localStorage (best-effort)
        try {
            localStorage.setItem(key, JSON.stringify(envelope));
        } catch (error) {
            // Storage quota likely exceeded
        }
    },

    async readJsonCache(scope) {
        const key = this.getCacheStorageKey(scope);

        // 1. Try IndexedDB first
        if (typeof IndexedDBManager !== 'undefined') {
            const cached = await IndexedDBManager.getItem(key);
            if (cached) return cached;
        }

        // 2. Fallback to localStorage
        try {
            const raw = localStorage.getItem(key);
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            if (!parsed || typeof parsed !== 'object') return null;

            // Migration: Move to IndexedDB for next time if possible
            if (typeof IndexedDBManager !== 'undefined') {
                IndexedDBManager.setItem(key, parsed);
            }

            return parsed;
        } catch (error) {
            return null;
        }
    },

    async removeJsonCache(scope) {
        const key = this.getCacheStorageKey(scope);
        if (typeof IndexedDBManager !== 'undefined' && typeof IndexedDBManager.removeItem === 'function') {
            await IndexedDBManager.removeItem(key);
        }
        try {
            localStorage.removeItem(key);
        } catch (error) {
            // Ignore localStorage access failures.
        }
    },

    async cacheReportHtml(reportId, sourceHint = null, options = {}) {
        const rid = String(reportId || '').trim();
        if (!rid) return false;
        if (typeof navigator !== 'undefined' && navigator.onLine === false) return false;
        const inlineImages = !!(options && options.inlineImages === true);

        const sourceScope = this.inferReportSourceScope(sourceHint);
        const cloudBase = this.getCloudBackendBaseUrl();
        if (
            (sourceScope === 'cloud' || sourceScope === 'synced_local' || sourceScope === 'shared')
            && !this.canUseRemoteCloudBackendFromPage(cloudBase)
            && !this.hasLocalReportArtifacts(sourceHint)
        ) {
            return false;
        }

        const url = this.getReportUrl(rid, sourceHint);
        try {
            const response = await this._fetchWithTimeout(url, {
                method: 'GET',
                headers: { Accept: 'text/html' },
                cache: 'no-store'
            }, 8000);

            if (!response || !response.ok) return false;
            const contentType = String(response.headers.get('content-type') || '').toLowerCase();
            const html = await response.text();
            if (!html || (!contentType.includes('text/html') && !/<html[\s>]/i.test(html))) {
                return false;
            }
            if (/Cloud report details are unavailable while offline/i.test(html)) {
                return false;
            }
            const preparedHtml = this.prepareCachedReportHtml(html, url);
            const cachedHtml = inlineImages
                ? await this.inlineCachedReportImages(preparedHtml, rid, sourceHint, url)
                : preparedHtml;

            await this.writeJsonCache(this.reportHtmlCacheScope(rid, sourceHint), {
                report_id: rid,
                url,
                source_scope: this.inferReportSourceScope(sourceHint) || '',
                html: cachedHtml,
                cached_at: new Date().toISOString()
            });
            return true;
        } catch (error) {
            return false;
        }
    },

    async inlineCachedReportImages(html, reportId, sourceHint = null, sourceUrl = '') {
        const raw = String(html || '');
        const rid = String(reportId || '').trim();
        if (!raw || !rid || typeof DOMParser === 'undefined') return raw;

        let documentRef = null;
        try {
            documentRef = new DOMParser().parseFromString(raw, 'text/html');
        } catch (error) {
            return raw;
        }
        if (!documentRef || !documentRef.documentElement) return raw;

        const imageCache = new Map();
        const resolveFilename = (src) => {
            const rawSrc = String(src || '').trim();
            if (!rawSrc || /^data:/i.test(rawSrc)) return '';

            try {
                const resolved = new URL(rawSrc, sourceUrl || window.location.origin);
                const parts = String(resolved.pathname || '').split('/').filter(Boolean);
                const filename = String(parts[parts.length - 1] || '').toLowerCase();
                const idFromImageRoute = parts.length >= 3 && parts[0] === 'image'
                    ? String(parts[1] || '')
                    : '';
                if (
                    (filename === 'original.jpg' || filename === 'annotated.jpg')
                    && (!idFromImageRoute || idFromImageRoute === rid)
                ) {
                    return filename;
                }
            } catch (error) {
                const match = rawSrc.match(/(?:^|\/)(original|annotated)\.jpg(?:[?#].*)?$/i);
                if (match && match[1]) return `${match[1].toLowerCase()}.jpg`;
            }
            return '';
        };

        const images = Array.from(documentRef.querySelectorAll('img[src]'));
        await Promise.all(images.map(async (img) => {
            const originalSrc = img.getAttribute('src') || '';
            const filename = resolveFilename(originalSrc);
            if (!filename) return;

            if (!imageCache.has(filename)) {
                imageCache.set(filename, await this.fetchReportImageDataUrl(rid, filename, sourceHint));
            }
            const dataUrl = imageCache.get(filename);
            if (!dataUrl) return;

            img.setAttribute('data-casm-cached-src', originalSrc);
            img.setAttribute('src', dataUrl);
        }));

        return `<!DOCTYPE html>\n${documentRef.documentElement.outerHTML}`;
    },

    async fetchReportImageDataUrl(reportId, filename, sourceHint = null) {
        const rid = String(reportId || '').trim();
        const safeFilename = String(filename || '').trim().toLowerCase();
        if (!rid || (safeFilename !== 'original.jpg' && safeFilename !== 'annotated.jpg')) return '';

        try {
            const response = await this._fetchWithTimeout(this.getImageUrl(rid, safeFilename, sourceHint), {
                method: 'GET',
                cache: 'no-store'
            }, 8000);
            if (!response || !response.ok) return '';

            const blob = await response.blob();
            if (!blob || !Number.isFinite(blob.size) || blob.size <= 0) return '';
            return await this.blobToDataUrl(blob);
        } catch (error) {
            return '';
        }
    },

    blobToDataUrl(blob) {
        return new Promise((resolve) => {
            try {
                const reader = new FileReader();
                reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : '');
                reader.onerror = () => resolve('');
                reader.readAsDataURL(blob);
            } catch (error) {
                resolve('');
            }
        });
    },

    prepareCachedReportHtml(html, sourceUrl) {
        const raw = String(html || '');
        if (!raw) return raw;
        if (/<base\s/i.test(raw)) return raw;

        let safeHref = '';
        try {
            const resolved = new URL(sourceUrl, window.location.origin);
            safeHref = `${resolved.origin}/`;
        } catch (error) {
            return raw;
        }

        const baseTag = `<base href="${safeHref}">`;
        if (/<head[^>]*>/i.test(raw)) {
            return raw.replace(/<head([^>]*)>/i, `<head$1>${baseTag}`);
        }
        if (/<html[^>]*>/i.test(raw)) {
            return raw.replace(/<html([^>]*)>/i, `<html$1><head>${baseTag}</head>`);
        }
        return `<!doctype html><html><head>${baseTag}</head><body>${raw}</body></html>`;
    },

    async getCachedReportHtml(reportId, sourceHint = null) {
        const rid = String(reportId || '').trim();
        if (!rid) return null;
        const cached = await this.readJsonCache(this.reportHtmlCacheScope(rid, sourceHint));
        if (cached && cached.data && typeof cached.data.html === 'string' && cached.data.html.trim()) {
            return cached.data;
        }
        return null;
    },

    async getCachedReportUrl(reportId, sourceHint = null) {
        const cached = await this.getCachedReportHtml(reportId, sourceHint);
        if (!cached || !cached.html) return null;

        const rid = String(reportId || '').trim();
        const existing = this.reportHtmlObjectUrls.get(rid);
        if (existing) {
            try { URL.revokeObjectURL(existing); } catch (error) {}
            this.reportHtmlObjectUrls.delete(rid);
        }

        const blob = new Blob([cached.html], { type: 'text/html;charset=utf-8' });
        const objectUrl = URL.createObjectURL(blob);
        this.reportHtmlObjectUrls.set(rid, objectUrl);
        return objectUrl;
    },

    async getOfflineCachedReportUrl(reportId, sourceHint = null) {
        return this.getCachedReportUrl(reportId, sourceHint);
    },

    prefetchReportHtmlFromList(list = [], options = {}) {
        if (typeof navigator !== 'undefined' && navigator.onLine === false) return;
        if (!Array.isArray(list) || !list.length) return;

        const state = this.reportHtmlPrefetchState;
        const limit = Math.max(1, Math.min(Number(options.limit || 40), 120));
        const seen = new Set();
        const candidates = list
            .filter((item) => {
                const reportId = String((item && item.report_id) || '').trim();
                if (!reportId || seen.has(reportId)) return false;
                seen.add(reportId);
                if (state.completed.has(reportId) || state.inFlight.has(reportId)) return false;
                const status = String((item && item.status) || '').trim().toLowerCase();
                const ready = !!(item && item.has_report) && (
                    status === 'completed' || status === 'partial' || status === 'unknown' || !status
                );
                if (!ready) return false;
                const scope = this.inferReportSourceScope(item);
                if (
                    (scope === 'cloud' || scope === 'synced_local' || scope === 'shared')
                    && !this.canUseRemoteCloudBackendFromPage(this.getCloudBackendBaseUrl())
                    && !this.hasLocalReportArtifacts(item)
                ) {
                    return false;
                }
                return scope === 'cloud' || scope === 'synced_local' || scope === 'shared';
            })
            .slice(0, limit);

        candidates.forEach((item, index) => {
            const reportId = String(item.report_id || '').trim();
            state.inFlight.add(reportId);
            setTimeout(() => {
                this.cacheReportHtml(reportId, item)
                    .then((cached) => {
                        if (cached) state.completed.add(reportId);
                    })
                    .catch(() => {
                        // Best-effort cache warmer.
                    })
                    .finally(() => {
                        state.inFlight.delete(reportId);
                    });
            }, 220 * index);
        });
    },

    dispatchLocalReportSyncUpdate(detail = {}) {
        try {
            if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
                window.dispatchEvent(new CustomEvent('ppe-local-report-sync:update', {
                    detail: {
                        origin: 'local_synced',
                        source_scope: 'synced_local',
                        source_label: 'Local Synced',
                        measured_at: new Date().toISOString(),
                        ...detail
                    }
                }));
            }
        } catch (error) {
            // CustomEvent is not available during non-browser syntax checks.
        }
    },

    dispatchReportQueueUpdate(detail = {}) {
        try {
            if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
                window.dispatchEvent(new CustomEvent('ppe-report-queue:update', {
                    detail: {
                        measured_at: new Date().toISOString(),
                        ...detail
                    }
                }));
            }
        } catch (error) {
            // CustomEvent is not available during non-browser syntax checks.
        }
    },

    async upsertPendingReportCache(record = {}) {
        const reportId = String((record && record.report_id) || '').trim();
        if (!reportId) return null;

        const sourceScope = this.inferReportSourceScope(record) || String(record.source_scope || '').trim().toLowerCase() || 'cloud';
        const sourceLabel = String(record.source_label || '').trim() || (
            sourceScope === 'local' ? 'Local'
                : sourceScope === 'synced_local' ? 'Local Synced'
                    : sourceScope === 'shared' ? 'Shared'
                        : 'Cloud'
        );
        const pendingRow = {
            ...record,
            report_id: reportId,
            timestamp: record.timestamp || record.created_at || new Date().toISOString(),
            status: record.status || (record.has_report ? 'completed' : 'pending'),
            has_report: !!record.has_report,
            source_scope: sourceScope,
            source_label: sourceLabel,
            updated_at: new Date().toISOString()
        };

        const cacheScopes = [
            'reports:pending',
            'violations:limit:100',
            'violations:limit:1000',
            'violations:limit:5000'
        ];
        await Promise.all(cacheScopes.map(async (cacheScope) => {
            const cached = await this.readJsonCache(cacheScope);
            const rows = cached && Array.isArray(cached.data) ? cached.data.slice() : [];
            const index = rows.findIndex((item) => String((item && item.report_id) || '').trim() === reportId);
            if (index >= 0) {
                rows[index] = this.mergeOptimisticReportRecord(rows[index], pendingRow);
            } else {
                rows.unshift(pendingRow);
            }
            await this.writeJsonCache(cacheScope, rows.slice(0, 5000));
        }));

        this.dispatchReportQueueUpdate({
            success: true,
            report_id: reportId,
            report: pendingRow
        });
        return pendingRow;
    },

    getLocalSyncBackendBaseUrl() {
        const localBase = this.getLocalBackendBaseUrl();
        const currentBase = this._normalizeBaseUrl((typeof API_CONFIG !== 'undefined' && API_CONFIG.BASE_URL) || '');
        return localBase || currentBase;
    },

    async registerLocalReportBackgroundSync(reason = 'local-report-sync') {
        try {
            if (
                typeof navigator === 'undefined'
                || typeof window === 'undefined'
                || !navigator.serviceWorker
                || !('SyncManager' in window)
            ) {
                return false;
            }
            const registration = await navigator.serviceWorker.ready;
            if (!registration || !registration.sync || typeof registration.sync.register !== 'function') {
                return false;
            }
            await registration.sync.register(this.LOCAL_REPORT_SYNC_TAG);
            return true;
        } catch (error) {
            console.debug('Background Sync registration skipped:', reason, error);
            return false;
        }
    },

    async markReportsAsLocalSynced(reportIds = [], detail = {}) {
        const requestedIds = Array.from(new Set(
            (Array.isArray(reportIds) ? reportIds : [reportIds])
                .map((id) => String(id || '').trim())
                .filter(Boolean)
        ));
        const ids = await this.filterStrictLocalSyncReportIds(requestedIds);
        if (!ids.length) return [];

        const completedDetailIds = new Set([
            ...(Array.isArray(detail.synced_report_ids) ? detail.synced_report_ids : []),
            ...(Array.isArray(detail.completed_report_ids) ? detail.completed_report_ids : []),
            ...(detail.completed === true && detail.report_id ? [detail.report_id] : [])
        ].map((id) => String(id || '').trim()).filter(Boolean));
        const detailSyncState = String(detail.sync_state || '').trim();
        const detailSyncStateQueued = /queued|pending|retry/i.test(detailSyncState);
        const updateReport = (item) => {
            if (!item || !ids.includes(String(item.report_id || '').trim())) return item;
            if (!this.isStrictLocalOriginReport(item)) return item;
            const reportId = String(item.report_id || '').trim();
            const completedForReport = detail.completed === true
                || completedDetailIds.has(reportId)
                || (!detailSyncStateQueued && /^(cloud_completed|synced)$/i.test(detailSyncState));
            const nextSyncState = completedForReport
                ? (detailSyncState && !detailSyncStateQueued ? detailSyncState : 'cloud_completed')
                : (detailSyncState || item.sync_state || 'cloud_sync_queued');
            return {
                ...item,
                source_scope: 'synced_local',
                source_label: 'Local Synced',
                origin: 'local_synced',
                sync_source: detail.sync_source || item.sync_source || 'sync_local_cache',
                source: detail.source || item.source || 'sync_local_cache',
                sync_state: nextSyncState,
                status: item.status || 'completed',
                updated_at: new Date().toISOString()
            };
        };

        try {
            const drafts = await this.readLocalReportDrafts();
            if (drafts.length) {
                await this.writeLocalReportDrafts(drafts.map(updateReport));
            }
        } catch (error) {
            // Draft reconciliation is best-effort; the UI event below still updates mounted views.
        }

        const cacheScopes = [
            'reports:pending',
            'violations:limit:100',
            'violations:limit:1000',
            'violations:limit:5000'
        ];
        await Promise.all(cacheScopes.map(async (scope) => {
            const cached = await this.readJsonCache(scope);
            if (!cached || !Array.isArray(cached.data)) return;
            await this.writeJsonCache(scope, cached.data.map(updateReport));
        }));

        const marksCompleted = ids.some((id) => completedDetailIds.has(id))
            || detail.completed === true
            || (!detailSyncStateQueued && /^(cloud_completed|synced)$/i.test(detailSyncState));
        this.dispatchLocalReportSyncUpdate({
            ...detail,
            report_ids: ids,
            queued_report_ids: detail.queued_report_ids || (marksCompleted ? [] : ids),
            completed_report_ids: detail.completed_report_ids || (marksCompleted ? ids : []),
            synced_report_ids: detail.synced_report_ids || (marksCompleted ? ids : [])
        });
        return ids;
    },

    async clearRuntimeTransitionCaches(reason = 'cloud-transition') {
        const scopes = [
            'stats:summary',
            'reports:pending',
            'violations:limit:100',
            'violations:limit:1000',
            'violations:limit:5000'
        ];
        await Promise.all(scopes.map((scope) => this.removeJsonCache(scope)));

        try {
            if (
                typeof navigator !== 'undefined'
                && navigator.serviceWorker
                && navigator.serviceWorker.controller
            ) {
                navigator.serviceWorker.controller.postMessage({
                    type: 'PPE_CLEAR_RUNTIME_API_CACHE',
                    reason,
                    measuredAt: Date.now()
                });
            }
        } catch (error) {
            // Service worker cache clearing is best-effort only.
        }
    },

    async repairReportSourceCaches(reportId, patch = {}) {
        const rid = String(reportId || '').trim();
        if (!rid) return;

        const scope = this.inferReportSourceScope({
            report_id: rid,
            ...patch
        }) || String(patch.source_scope || '').trim().toLowerCase();
        if (!['cloud', 'local', 'shared', 'synced_local'].includes(scope)) return;

        const label = patch.source_label || (
            scope === 'cloud' ? 'Cloud'
                : scope === 'local' ? 'Local'
                    : scope === 'synced_local' ? 'Local Synced'
                        : 'Shared'
        );

        const updateRecord = (item) => {
            if (!item || String(item.report_id || '').trim() !== rid) return item;
            const next = {
                ...item,
                ...patch,
                report_id: rid,
                source_scope: scope,
                source_label: label,
                updated_at: new Date().toISOString()
            };
            if (scope === 'cloud') {
                delete next.local_image_url;
                delete next.local_report_url;
                next.has_local_artifacts = false;
                next.has_local_report = false;
                next.origin = '';
                next.sync_source = '';
                next.source = 'manual_cloud_reprocess';
                next.source_reason = patch.source_reason || 'manual_cloud_reprocess_fallback';
                next.force_cloud_runtime = true;
            }
            return next;
        };

        if (scope === 'cloud') {
            try {
                await this.removeLocalReportDraft(rid);
            } catch (error) {
                // Best-effort cache repair only.
            }
        }

        const cacheScopes = [
            'reports:pending',
            'violations:limit:100',
            'violations:limit:1000',
            'violations:limit:5000'
        ];
        await Promise.all(cacheScopes.map(async (cacheScope) => {
            const cached = await this.readJsonCache(cacheScope);
            if (!cached || !Array.isArray(cached.data)) return;
            await this.writeJsonCache(cacheScope, cached.data.map(updateRecord));
        }));

        const baseKeys = Array.from(new Set([
            this._normalizeBaseUrl((typeof API_CONFIG !== 'undefined' && API_CONFIG.BASE_URL) || ''),
            this.getCloudBackendBaseUrl(),
            this.getLocalBackendBaseUrl(),
            ''
        ].map((base) => base || 'same-origin')));
        await Promise.all(baseKeys.flatMap((baseKey) => [
            this.removeJsonCache(`report-status:${baseKey}:${rid}`),
            this.removeJsonCache(`violation:${baseKey}:${rid}`)
        ]));
    },

    async readLocalReportDrafts() {
        const cached = await this.readJsonCache(this.LOCAL_REPORT_DRAFTS_SCOPE);
        const drafts = cached && Array.isArray(cached.data) ? cached.data : [];
        return drafts
            .filter((draft) => draft && draft.report_id)
            .map((draft) => this.normalizeLocalReportDraft(draft))
            .filter(Boolean);
    },

    async writeLocalReportDrafts(drafts) {
        const normalized = Array.isArray(drafts)
            ? drafts.map((draft) => this.normalizeLocalReportDraft(draft)).filter(Boolean)
            : [];
        await this.writeJsonCache(this.LOCAL_REPORT_DRAFTS_SCOPE, normalized);
        return normalized;
    },

    normalizeLocalReportDraft(draft) {
        const reportId = String((draft && draft.report_id) || '').trim();
        if (!reportId) return null;
        const sourceScope = String(draft.source_scope || '').trim() || 'local';
        const syncState = String(draft.sync_state || '').trim() || 'pending_local_generation';
        const status = String(draft.status || '').trim() || (
            syncState === 'synced' || sourceScope === 'synced_local' ? 'completed' : 'pending'
        );

        return {
            ...draft,
            report_id: reportId,
            timestamp: draft.timestamp || new Date().toISOString(),
            status,
            severity: draft.severity || 'HIGH',
            missing_ppe: this.extractMissingPpeLabels(draft),
            ppe_tags: this.extractViolationKeys(draft),
            violation_count: Number(draft.violation_count || this.extractMissingPpeLabels(draft).length || 0),
            violation_summary: draft.violation_summary || 'Violation queued for local report generation',
            has_original: draft.has_original !== false,
            has_annotated: !!draft.has_annotated,
            has_report: !!draft.has_report,
            source_scope: syncState === 'synced' ? 'synced_local' : sourceScope,
            source_label: draft.source_label || (syncState === 'synced' ? 'Local Synced' : 'Local'),
            sync_state: syncState,
            updated_at: draft.updated_at || new Date().toISOString()
        };
    },

    isCompletedLocalReportDraftForCloudSync(draft = {}) {
        if (!draft || typeof draft !== 'object') return false;
        const status = String(draft.status || '').trim().toLowerCase();
        const syncState = String(draft.sync_state || '').trim().toLowerCase();
        const completed = (
            status === 'completed'
            || status === 'ready'
            || syncState === 'completed'
            || syncState === 'ready_for_sync'
            || syncState === 'local_report_ready'
        );
        const hasReportArtifact = !!(
            draft.has_report === true
            || draft.has_local_report === true
            || draft.local_report_url
            || draft.report_html_key
            || draft.report_html
            || draft.report_html_blob
            || draft.report_blob
        );
        return completed && hasReportArtifact;
    },

    async upsertLocalReportDraft(draft) {
        const normalized = this.normalizeLocalReportDraft(draft);
        if (!normalized) return null;

        const drafts = await this.readLocalReportDrafts();
        const byId = new Map(drafts.map((item) => [item.report_id, item]));
        const existing = byId.get(normalized.report_id) || {};
        byId.set(normalized.report_id, {
            ...existing,
            ...normalized,
            original_blob: normalized.original_blob || existing.original_blob || null,
            annotated_blob: normalized.annotated_blob || existing.annotated_blob || null,
            has_original: !!(normalized.has_original || existing.has_original || normalized.original_blob || existing.original_blob),
            has_annotated: !!(normalized.has_annotated || existing.has_annotated || normalized.annotated_blob || existing.annotated_blob),
            updated_at: new Date().toISOString()
        });

        await this.writeLocalReportDrafts(Array.from(byId.values()));
        void this.registerLocalReportBackgroundSync('local draft upsert');
        return byId.get(normalized.report_id);
    },

    async removeLocalReportDraft(reportId) {
        const rid = String(reportId || '').trim();
        if (!rid) return false;
        this.revokeLocalDraftObjectUrl(rid);
        const drafts = await this.readLocalReportDrafts();
        await this.writeLocalReportDrafts(drafts.filter((draft) => draft.report_id !== rid));
        return true;
    },

    revokeLocalDraftObjectUrl(reportId) {
        const rid = String(reportId || '').trim();
        if (!rid || !this.localDraftObjectUrls.has(rid)) return;
        try {
            URL.revokeObjectURL(this.localDraftObjectUrls.get(rid));
        } catch (e) {
            // Ignore stale object URLs.
        }
        this.localDraftObjectUrls.delete(rid);
    },

    attachLocalDraftImageUrls(drafts = []) {
        return drafts.map((draft) => {
            if (!draft || !draft.report_id) return draft;
            const blob = draft.annotated_blob || draft.original_blob || null;
            if (!blob || typeof URL === 'undefined' || typeof URL.createObjectURL !== 'function') {
                return draft;
            }

            if (!this.localDraftObjectUrls.has(draft.report_id)) {
                try {
                    this.localDraftObjectUrls.set(draft.report_id, URL.createObjectURL(blob));
                } catch (e) {
                    return draft;
                }
            }

            return {
                ...draft,
                local_image_url: this.localDraftObjectUrls.get(draft.report_id),
                has_original: true,
                has_annotated: !!draft.has_annotated
            };
        });
    },

    async mergeLocalReportDrafts(list, maxLimit = 1000) {
        const drafts = this.attachLocalDraftImageUrls(await this.readLocalReportDrafts());
        if (!drafts.length) return Array.isArray(list) ? list : [];
        return this._mergeOptimistically(Array.isArray(list) ? list : [], drafts, maxLimit);
    },

    async reconcileLocalReportDrafts(list = []) {
        const drafts = await this.readLocalReportDrafts();
        if (!drafts.length || !Array.isArray(list)) return;

        const byId = new Map(list.map((item) => [String((item && item.report_id) || '').trim(), item]));
        const retained = [];
        for (const draft of drafts) {
            const current = byId.get(draft.report_id);
            const sourceScope = String((current && current.source_scope) || '').trim().toLowerCase();
            const syncSource = String((current && (current.sync_source || current.source)) || '').trim().toLowerCase();
            const status = String((current && current.status) || '').trim().toLowerCase();
            const synced = (
                this.hasConfirmedSyncedLocalReport(current || {})
                || (current && current.has_report && status === 'completed' && sourceScope !== 'local')
                || (
                    syncSource === 'sync_local_cache'
                    && current
                    && current.has_report
                    && this.hasCloudReportArtifactEvidence(current)
                )
            );
            if (synced) {
                this.revokeLocalDraftObjectUrl(draft.report_id);
                continue;
            }
            retained.push(draft);
        }

        if (retained.length !== drafts.length) {
            await this.writeLocalReportDrafts(retained);
        }
    },

    stripLocalDraftRuntimeFields(list = []) {
        if (!Array.isArray(list)) return [];
        return list.map((item) => {
            if (!item || typeof item !== 'object') return item;
            const {
                original_blob,
                annotated_blob,
                local_image_url,
                ...rest
            } = item;
            return rest;
        });
    },

    async fetchJsonWithCache(url, options = {}) {
        const scope = options.cacheScope || url;
        const cached = await this.readJsonCache(scope);

        if (cached && !options.noCache) {
            const age = Date.now() - cached.ts;
            if (age < (options.ttl || 300000)) {
                return cached.data;
            }
        }

        if (!navigator.onLine && cached) {
            return cached.data;
        }

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), options.timeoutMs || 8000);

        try {
            const response = await fetch(url, {
                signal: controller.signal,
                cache: options.preferFresh ? 'no-store' : 'default'
            });
            if (!response.ok) throw new Error(`Request failed: ${response.status}`);
            const data = await response.json();
            if (data && !data.error) {
                this.writeJsonCache(scope, data);
                return data;
            }
            return data;
        } catch (error) {
            if (cached) {
                console.warn(`Using cached response for ${scope}:`, error.message || error);
                return cached.data;
            }
            throw error;
        } finally {
            clearTimeout(timeoutId);
        }
    },

    async fetchJsonNoCache(url, options = {}) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), options.timeoutMs || 12000);

        try {
            const response = await fetch(url, {
                signal: controller.signal,
                cache: 'no-store'
            });
            if (!response.ok) throw new Error(`Request failed: ${response.status}`);
            const data = await response.json();
            if (options.cacheScope) {
                await this.writeJsonCache(options.cacheScope, data);
            }
            return data;
        } finally {
            clearTimeout(timeoutId);
        }
    },

    prefetchViolationImages(violations = []) {
        if (!Array.isArray(violations) || violations.length === 0) return;
        if (navigator.onLine === false) return;

        const now = Date.now();
        const state = this.imagePrefetchState || { completed: new Set(), inFlight: new Set(), lastBatchAt: 0 };

        // Prevent repeated broad prefetch storms across pages and refresh loops.
        if (now - Number(state.lastBatchAt || 0) < 12000) {
            return;
        }
        state.lastBatchAt = now;

        const candidates = [];
        violations.slice(0, 12).forEach((violation) => {
            if (!violation || !violation.report_id) return;
            if (violation.local_image_url || String(violation.source_scope || '').toLowerCase() === 'local') return;
            if (
                this.isCloudReportScope(violation)
                && !this.canUseRemoteCloudBackendFromPage(this.getCloudBackendBaseUrl())
                && !this.hasLocalReportArtifacts(violation)
            ) {
                return;
            }
            if (violation.has_original) {
                candidates.push({
                    key: `${violation.report_id}:original.jpg`,
                    url: this.getImageUrl(violation.report_id, 'original.jpg', violation)
                });
            }
            if (violation.has_annotated) {
                candidates.push({
                    key: `${violation.report_id}:annotated.jpg`,
                    url: this.getImageUrl(violation.report_id, 'annotated.jpg', violation)
                });
            }
        });

        const selected = candidates
            .filter((item) => !state.completed.has(item.key) && !state.inFlight.has(item.key))
            .slice(0, 6);

        selected.forEach((item, index) => {
            state.inFlight.add(item.key);
            setTimeout(() => {
                fetch(item.url, { cache: 'force-cache' })
                    .then((response) => {
                        if (response && response.ok) {
                            state.completed.add(item.key);
                        }
                    })
                    .catch(() => {
                        // Ignore prefetch failures; this is an optimization path.
                    })
                    .finally(() => {
                        state.inFlight.delete(item.key);
                    });
            }, index * 90);
        });
    },

    mergeOptimisticReportRecord(existing = null, incoming = null) {
        if (!existing || typeof existing !== 'object') return incoming;
        if (!incoming || typeof incoming !== 'object') return existing;

        const merged = {
            ...existing,
            ...incoming
        };

        ['has_original', 'has_annotated', 'has_report', 'has_local_artifacts', 'has_local_report'].forEach((key) => {
            if (existing[key] === true || incoming[key] === true) {
                merged[key] = true;
            }
        });

        const existingScope = this.inferReportSourceScope(existing);
        const incomingScope = this.inferReportSourceScope(incoming);
        const existingLabel = String(existing.source_label || '').trim().toLowerCase();
        const incomingLabel = String(incoming.source_label || '').trim().toLowerCase();
        const syncedLocal = (
            existingScope === 'synced_local'
            || incomingScope === 'synced_local'
            || existingLabel.includes('local synced')
            || incomingLabel.includes('local synced')
        ) && (
            this.hasConfirmedSyncedLocalReport(existing)
            || this.hasConfirmedSyncedLocalReport(incoming)
        );

        if (syncedLocal) {
            const existingStrictLocal = this.isStrictLocalOriginReport(existing);
            const incomingStrictLocal = this.isStrictLocalOriginReport(incoming);
            const existingCloudAuthoritative = existingScope === 'cloud' && !existingStrictLocal;
            const incomingCloudAuthoritative = incomingScope === 'cloud' && !incomingStrictLocal;

            if (incomingCloudAuthoritative || existingCloudAuthoritative) {
                const cloudSource = incomingCloudAuthoritative ? incoming : existing;
                const cloudStatus = String(cloudSource.status || '').trim().toLowerCase();
                const cloudInFlight = ['pending', 'queued', 'processing', 'generating'].includes(cloudStatus);
                if (cloudInFlight || !this.hasLocalReportArtifacts(cloudSource)) {
                    merged.source_scope = 'cloud';
                    merged.source_label = 'Cloud';
                    merged.origin = '';
                    merged.sync_source = '';
                    merged.source = '';
                    return merged;
                }
            }

            merged.source_scope = 'synced_local';
            merged.source_label = 'Local Synced';
            merged.origin = merged.origin || existing.origin || incoming.origin || 'local_synced';
            merged.sync_source = merged.sync_source || existing.sync_source || incoming.sync_source || 'sync_local_cache';
            return merged;
        }

        const strictLocal = this.isStrictLocalOriginReport(existing) || this.isStrictLocalOriginReport(incoming);
        if (strictLocal && incomingScope !== 'cloud' && existingScope !== 'cloud') {
            merged.source_scope = 'local';
            merged.source_label = String(merged.source_label || '').trim() || 'Local';
        }

        return merged;
    },

    _mergeOptimistically(listA, listB, maxLimit = 1000) {
        if (!Array.isArray(listA)) listA = [];
        if (!Array.isArray(listB)) listB = [];
        const byId = new Map();

        listA.forEach(v => {
            if (v && v.report_id) byId.set(v.report_id, v);
        });
        listB.forEach(v => {
            if (!v || !v.report_id) return;
            const existing = byId.get(v.report_id);
            byId.set(v.report_id, existing ? this.mergeOptimisticReportRecord(existing, v) : v);
        });

        const merged = Array.from(byId.values());
        merged.sort((a, b) => {
            const aTime = new Date(a.timestamp || 0).getTime();
            const bTime = new Date(b.timestamp || 0).getTime();
            return bTime - aTime;
        });
        return merged.slice(0, maxLimit);
    },

    // Fetch all violations with status info
    async getViolations(options = {}) {
        const requestedLimit = Number(options.limit);
        const safeLimit = Number.isFinite(requestedLimit)
            ? Math.max(1, Math.min(Math.floor(requestedLimit), 5000))
            : 1000;
        const requestedTimeout = Number(options.timeoutMs);
        const timeoutMs = Number.isFinite(requestedTimeout)
            ? Math.max(2000, Math.min(Math.floor(requestedTimeout), 30000))
            : 10000;
        const noCache = !!options.noCache;
        const cacheScope = `violations:limit:${safeLimit}`;

        if (!noCache) {
            const cached = await this.readJsonCache(cacheScope);
            if (cached && Array.isArray(cached.data)) {
                const merged = await this.mergeLocalReportDrafts(cached.data, safeLimit);
                this.prefetchReportHtmlFromList(merged, { limit: 24 });
                return merged;
            }
        }

        try {
            const url = `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.VIOLATIONS}?limit=${safeLimit}`;
            let list = await this.fetchJsonNoCache(url, { cacheScope: null, timeoutMs });
            list = Array.isArray(list) ? list : [];

            // OPTIMISTIC UI MERGING: Merge cloud reports if in local mode
            const cloudUrlBase = String((window.__PPE_CONFIG__ && window.__PPE_CONFIG__.API_BASE_URL) || window.PPE_API_URL || '').trim().replace(/\/+$/, '');
            if (cloudUrlBase && API_CONFIG.BASE_URL !== cloudUrlBase && this.canUseRemoteCloudBackendFromPage(cloudUrlBase)) {
                try {
                    const cloudUrl = `${cloudUrlBase}${API_CONFIG.ENDPOINTS.VIOLATIONS}?limit=${safeLimit}`;
                    const cloudData = await this.fetchJsonNoCache(cloudUrl, { timeoutMs: 5000 });
                    if (Array.isArray(cloudData)) {
                        list = this._mergeOptimistically(cloudData, list, safeLimit);
                    }
                } catch (e) {
                    console.warn('Failed to fetch cloud reports for merge:', e);
                }
            }

            // Fallback merging with cache (retains cloud reports offline)
            const cached = await this.readJsonCache(cacheScope);
            if (cached && Array.isArray(cached.data)) {
                list = this._mergeOptimistically(cached.data, list, safeLimit);
            }

            list = await this.mergeLocalReportDrafts(list, safeLimit);
            await this.reconcileLocalReportDrafts(list);
            this.writeJsonCache(cacheScope, this.stripLocalDraftRuntimeFields(list));
            this.prefetchViolationImages(list);
            this.prefetchReportHtmlFromList(list, { limit: 40 });
            return list;
        } catch (error) {
            this.logFetchFailure('Error fetching violations', error);
            const cached = await this.readJsonCache(cacheScope);
            if (cached && Array.isArray(cached.data)) {
                const merged = await this.mergeLocalReportDrafts(cached.data, safeLimit);
                this.prefetchReportHtmlFromList(merged, { limit: 24 });
                return merged;
            }
            const merged = await this.mergeLocalReportDrafts([], safeLimit);
            this.prefetchReportHtmlFromList(merged, { limit: 24 });
            return merged;
        }
    },

    // Get violation by ID with status info
    async getViolation(reportId, options = {}) {
        try {
            const sourceHint = options.source || options.violation || options;
            const base = this.getReportBackendBase(sourceHint);
            const baseKey = base || 'same-origin';
            const url = this.buildReportScopedUrl(`/api/violation/${reportId}`, sourceHint);
            return await this.fetchJsonWithCache(url, {
                cacheScope: `violation:${baseKey}:${reportId}`
            });
        } catch (error) {
            this.logFetchFailure('Error fetching violation', error);
            return null;
        }
    },

    // Get report status
    async getReportStatus(reportId, options = {}) {
        const requestedTimeout = Number(options.timeoutMs);
        const timeoutMs = Number.isFinite(requestedTimeout)
            ? Math.max(2000, Math.min(Math.floor(requestedTimeout), 30000))
            : 7000;
        const noCache = !!options.noCache;
        const sourceHint = options.source || options.violation || options.sourceHint || options;
        const base = this.getReportBackendBase(sourceHint);
        const baseKey = base || 'same-origin';
        const cacheScope = `report-status:${baseKey}:${reportId}`;

        try {
            const url = this.buildReportScopedUrl(`/api/report/${reportId}/status`, sourceHint);
            return noCache
                ? await this.fetchJsonNoCache(url, { cacheScope, timeoutMs })
                : await this.fetchJsonWithCache(url, { cacheScope, timeoutMs });
        } catch (error) {
            this.logFetchFailure('Error fetching report status', error);
            if (noCache) {
                const cached = await this.readJsonCache(cacheScope);
                if (cached && cached.data && typeof cached.data === 'object') {
                    return cached.data;
                }
            }
            return { status: 'unknown', message: 'Unable to check status' };
        }
    },

    // Get pending reports
    async getPendingReports(options = {}) {
        const requestedTimeout = Number(options.timeoutMs);
        const timeoutMs = Number.isFinite(requestedTimeout)
            ? Math.max(2000, Math.min(Math.floor(requestedTimeout), 30000))
            : 9000;
        const noCache = !!options.noCache;
        const cacheScope = 'reports:pending';

        if (!noCache) {
            const cached = await this.readJsonCache(cacheScope);
            if (cached && Array.isArray(cached.data)) {
                return await this.mergeLocalReportDrafts(cached.data, 100);
            }
        }

        try {
            const url = `${API_CONFIG.BASE_URL}/api/reports/pending`;
            let list = await this.fetchJsonNoCache(url, { cacheScope: null, timeoutMs });
            list = Array.isArray(list) ? list : [];

            // OPTIMISTIC UI MERGING
            const cloudUrlBase = String((window.__PPE_CONFIG__ && window.__PPE_CONFIG__.API_BASE_URL) || window.PPE_API_URL || '').trim().replace(/\/+$/, '');
            if (cloudUrlBase && API_CONFIG.BASE_URL !== cloudUrlBase && this.canUseRemoteCloudBackendFromPage(cloudUrlBase)) {
                try {
                    const cloudUrl = `${cloudUrlBase}/api/reports/pending`;
                    const cloudData = await this.fetchJsonNoCache(cloudUrl, { timeoutMs: 5000 });
                    if (Array.isArray(cloudData)) {
                        list = this._mergeOptimistically(cloudData, list, 100);
                    }
                } catch (e) {
                    console.warn('Failed to fetch cloud pending for merge:', e);
                }
            }

            const cached = await this.readJsonCache(cacheScope);
            if (cached && Array.isArray(cached.data)) {
                list = this._mergeOptimistically(cached.data, list, 100);
            }

            list = await this.mergeLocalReportDrafts(list, 100);
            this.writeJsonCache(cacheScope, this.stripLocalDraftRuntimeFields(list));
            return list;
        } catch (error) {
            this.logFetchFailure('Error fetching pending reports', error);
            const cached = await this.readJsonCache(cacheScope);
            if (cached && Array.isArray(cached.data)) {
                return await this.mergeLocalReportDrafts(cached.data, 100);
            }
            return await this.mergeLocalReportDrafts([], 100);
        }
    },

    // Get violation statistics with status breakdown
    async getStats() {
        const currentBase = this._normalizeBaseUrl(API_CONFIG.BASE_URL || '');
        const cloudBase = this.getCloudBackendBaseUrl();
        const localBase = this.getLocalBackendBaseUrl();
        if (cloudBase && this.isLocalBackendBase(currentBase)) {
            try {
                const safeLimit = 5000;
                const urls = [
                    ...(this.canUseRemoteCloudBackendFromPage(cloudBase)
                        ? [`${cloudBase}${API_CONFIG.ENDPOINTS.VIOLATIONS}?limit=${safeLimit}`]
                        : []),
                    `${localBase}${API_CONFIG.ENDPOINTS.VIOLATIONS}?limit=${safeLimit}`
                ];
                const results = await Promise.allSettled(
                    urls.map((url) => this.fetchJsonNoCache(url, { timeoutMs: 9000 }))
                );

                let merged = [];
                let cachedCloudRows = [];
                results.forEach((result) => {
                    if (result.status === 'fulfilled' && Array.isArray(result.value)) {
                        merged = this._mergeOptimistically(merged, result.value, safeLimit);
                    }
                });
                const cachedScopes = [
                    `violations:limit:${safeLimit}`,
                    'violations:limit:1000',
                    'violations:limit:100'
                ];
                for (const scope of cachedScopes) {
                    const cached = await this.readJsonCache(scope);
                    if (cached && Array.isArray(cached.data)) {
                        merged = this._mergeOptimistically(merged, cached.data, safeLimit);
                        cachedCloudRows = this._mergeOptimistically(cachedCloudRows, cached.data, safeLimit);
                    }
                }
                merged = await this.mergeLocalReportDrafts(merged, safeLimit);
                if (merged.length > 0) {
                    try {
                        const mergeResponse = await this._fetchWithTimeout(`${localBase}/api/stats/merge-cache`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            cache: 'no-store',
                            body: JSON.stringify({
                                cached_rows: this.stripLocalDraftRuntimeFields(merged),
                                cached_cloud_rows_count: cachedCloudRows.length,
                                client_merged_count: merged.length
                            })
                        }, 9000);
                        const mergedStats = await mergeResponse.json().catch(() => null);
                        if (mergeResponse.ok && mergedStats && typeof mergedStats === 'object' && !mergedStats.error) {
                            return this.enrichStatsWithViolations(mergedStats, merged);
                        }
                    } catch (backendMergeError) {
                        console.warn('Local backend cached stats merge unavailable, using browser aggregate:', backendMergeError && backendMergeError.message ? backendMergeError.message : backendMergeError);
                    }
                    return this.calculateStatsFromViolations(merged);
                }
            } catch (unifiedError) {
                console.warn('Unified local/cloud stats fetch failed, falling back to active backend:', unifiedError);
            }
        }

        try {
            // Try fetching pre-calculated stats from backend first (includes breakdown & deltas)
            const data = await this.fetchJsonWithCache(`${API_CONFIG.BASE_URL}/api/stats`, {
                cacheScope: 'stats:summary',
                timeoutMs: 9000
            });
            if (data && typeof data === 'object') {
                const needsEnrichment =
                    data.todayDelta === undefined ||
                    data.weekDelta === undefined ||
                    !data.breakdown ||
                    !data.recentViolations;

                if (!needsEnrichment) {
                    return data;
                }

                const targetLimit = Math.max(Number(data.total || 0), 1000);
                const violations = await this.getViolations({ limit: targetLimit });
                return this.enrichStatsWithViolations(data, violations);
            }
        } catch (e) {
            console.warn('Backend stats endpoint failed, falling back to client-side calc:', e);
        }

        try {
            const violations = await this.getViolations({ limit: 1000 });
            return this.calculateStatsFromViolations(violations);
        } catch (error) {
            this.logFetchFailure('Error calculating stats', error);
            return {
                total: 0,
                today: 0,
                thisWeek: 0,
                pending: 0,
                completed: 0,
                failed: 0,
                severity: { high: 0, medium: 0, low: 0 },
                breakdown: {},
                recentViolations: []
            };
        }
    },

    // Get image URL
    getImageUrl(reportId, filename, sourceHint = null) {
        return this.buildReportScopedUrl(API_CONFIG.ENDPOINTS.IMAGE(reportId, filename), sourceHint);
    },

    // Get report URL
    getReportUrl(reportId, sourceHint = null) {
        return this.buildReportScopedUrl(API_CONFIG.ENDPOINTS.REPORT(reportId), sourceHint);
    },

    getReportNavigationUrl(reportId, sourceHint = null) {
        const path = API_CONFIG.ENDPOINTS.REPORT(reportId);
        const scope = this.inferReportSourceScope(sourceHint);
        const cloudBase = this.getCloudBackendBaseUrl();
        const localBase = this.getLocalBackendBaseUrl();
        const currentBase = this._normalizeBaseUrl(API_CONFIG.BASE_URL || '');
        const offline = typeof navigator !== 'undefined' && navigator.onLine === false;

        if (scope === 'cloud' && this.isCloudReportUnavailableOffline(sourceHint)) {
            return cloudBase ? `${cloudBase}${path}` : this.getReportUrl(reportId, sourceHint);
        }

        if (scope === 'local') {
            return `${localBase || currentBase || ''}${path}`;
        }

        if (scope === 'synced_local' && offline && this.hasConcreteLocalReportArtifacts(sourceHint)) {
            return `${localBase || currentBase || ''}${path}`;
        }

        if (
            scope === 'synced_local'
            && this.isPageServedFromLocalHost()
            && this.hasConcreteLocalReportArtifacts(sourceHint)
        ) {
            return `${localBase || currentBase || ''}${path}`;
        }

        if ((scope === 'cloud' || scope === 'synced_local' || scope === 'shared') && cloudBase) {
            return `${cloudBase}${path}`;
        }

        return this.getReportUrl(reportId, sourceHint);
    },

    async prefetchReport(reportId, options = {}) {
        let htmlCached = false;
        const sourceHint = options.source || options.violation || options.sourceHint || options;
        const sourceScope = this.inferReportSourceScope(sourceHint);
        const cloudBase = this.getCloudBackendBaseUrl();
        if (typeof navigator !== 'undefined' && navigator.onLine === false) {
            return { success: false, skipped_offline: true, html_cached: false };
        }
        if (
            (sourceScope === 'cloud' || sourceScope === 'synced_local' || sourceScope === 'shared')
            && !this.canUseRemoteCloudBackendFromPage(cloudBase)
            && !this.hasLocalReportArtifacts(sourceHint)
        ) {
            return { success: false, skipped_remote_prefetch: true, html_cached: false };
        }
        try {
            const response = await fetch(this.buildReportScopedUrl(`/api/report/${reportId}/prefetch`, sourceHint), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                cache: 'no-store'
            });
            htmlCached = await this.cacheReportHtml(reportId, sourceHint);
            if (!response.ok) {
                return { success: htmlCached, html_cached: htmlCached, error: `Prefetch failed: ${response.status}` };
            }
            const data = await response.json().catch(() => ({}));
            return data && typeof data === 'object'
                ? { ...data, html_cached: htmlCached, success: !!(data.success || htmlCached) }
                : { success: htmlCached, html_cached: htmlCached, error: 'Invalid prefetch response' };
        } catch (error) {
            htmlCached = await this.cacheReportHtml(reportId, sourceHint);
            return {
                success: htmlCached,
                html_cached: htmlCached,
                error: String(error && error.message ? error.message : error)
            };
        }
    },

    // Get event logs
    async getLogs(limit = 50, eventType = null) {
        try {
            let url = `${API_CONFIG.BASE_URL}/api/logs?limit=${limit}`;
            if (eventType) url += `&event_type=${eventType}`;
            const data = await this.fetchJsonWithCache(url, {
                cacheScope: `logs:${limit}:${eventType || 'all'}`,
                timeoutMs: 9000
            });
            return Array.isArray(data) ? data : [];
        } catch (error) {
            this.logFetchFailure('Error fetching logs', error);
            return [];
        }
    },

    async getDeviceStats(deviceId) {
        try {
            const url = `${API_CONFIG.BASE_URL}/api/device/${deviceId}/stats`;
            const data = await this.fetchJsonWithCache(url, {
                cacheScope: `device-stats:${deviceId}`,
                timeoutMs: 9000
            });
            return data && typeof data === 'object' ? data : {};
        } catch (error) {
            this.logFetchFailure('Error fetching device stats', error);
            return {};
        }
    },

    // Reprocess a single report
    async reprocessReport(reportId) {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/report/${reportId}/reprocess`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            if (!response.ok) throw new Error('Failed to trigger reprocess');
            return await response.json();
        } catch (error) {
            this.logFetchFailure('Error reprocessing report', error);
            return { success: false, error: error.message };
        }
    },

    async generateReportNow(reportId, options = {}) {
        try {
            const sourceHint = options.source || options.violation || options.sourceHint || null;
            const sourceScope = sourceHint ? this.inferReportSourceScope(sourceHint) : '';
            const requestPath = `/api/report/${reportId}/generate-now`;
            const primaryUrl = sourceHint
                ? this.buildReportScopedUrl(requestPath, sourceHint)
                : `${API_CONFIG.BASE_URL}${requestPath}`;
            const cloudUrl = this.getCloudReportScopedUrl(requestPath);
            const localRouteUnavailable = (
                this.isLocalBackendBase(primaryUrl)
                && !this.canUseLocalBackendFromPage(primaryUrl)
                && cloudUrl !== primaryUrl
            );
            const buildPayload = (scopeOverride = '') => {
                const effectiveScope = scopeOverride || sourceScope;
                const usingCloudFallback = scopeOverride === 'cloud';
                const sourceExplicitScope = String(sourceHint && (sourceHint.source_scope || sourceHint.report_scope || sourceHint.scope) || '').trim().toLowerCase();
                const sourceLabelText = String(sourceHint && sourceHint.source_label || '').trim().toLowerCase();
                const repairingToCloud = effectiveScope === 'cloud'
                    && sourceHint
                    && !this.hasConfirmedSyncedLocalReport(sourceHint)
                    && (
                        this.hasLocalOriginMarkers(sourceHint)
                        || sourceExplicitScope === 'synced_local'
                        || sourceLabelText.includes('local synced')
                    );
                return JSON.stringify({
                    force: !!options.force,
                    source_scope: effectiveScope || undefined,
                    source_label: (usingCloudFallback || repairingToCloud)
                        ? 'Cloud'
                        : (sourceHint && sourceHint.source_label ? sourceHint.source_label : undefined),
                    sync_source: (usingCloudFallback || repairingToCloud)
                        ? undefined
                        : (sourceHint && (sourceHint.sync_source || sourceHint.source) ? (sourceHint.sync_source || sourceHint.source) : undefined)
                });
            };
            const submit = async (url, scopeOverride = '') => fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: buildPayload(scopeOverride)
            });

            let response;
            let usedCloudFallback = false;
            if (localRouteUnavailable) {
                response = await submit(cloudUrl, 'cloud');
                usedCloudFallback = true;
            } else {
                try {
                    response = await submit(primaryUrl);
                } catch (primaryError) {
                    if (
                        this.isExpectedOfflineFetchError(primaryError)
                        && this.isLocalBackendBase(primaryUrl)
                        && cloudUrl !== primaryUrl
                    ) {
                        this.logFetchFailure('Local report reprocess route unavailable; retrying cloud route', primaryError);
                        response = await submit(cloudUrl, 'cloud');
                        usedCloudFallback = true;
                    } else {
                        throw primaryError;
                    }
                }
            }
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                return {
                    success: false,
                    error: data.error || 'Failed to trigger priority generation',
                    rejected_reason: data.rejected_reason || '',
                    queue_size: Number(data.queue_size || 0),
                    queue_capacity: Number(data.queue_capacity || 0),
                    worker_running: data.worker_running,
                    http_status: response.status,
                    routed_via_cloud_fallback: usedCloudFallback
                };
            }
            const result = {
                ...data,
                routed_via_cloud_fallback: !!(usedCloudFallback || data.routed_via_cloud_fallback)
            };
            if (result.source_scope === 'cloud' || result.routed_via_cloud_fallback) {
                await this.repairReportSourceCaches(reportId, {
                    ...(sourceHint && typeof sourceHint === 'object' ? sourceHint : {}),
                    ...result,
                    status: result.status || 'pending',
                    source_scope: 'cloud',
                    source_label: 'Cloud',
                    source_reason: 'manual_cloud_reprocess_fallback',
                    routed_via_cloud_fallback: !!result.routed_via_cloud_fallback,
                    force_cloud_runtime: true
                });
            }
            return result;
        } catch (error) {
            this.logFetchFailure('Error triggering priority generation', error);
            return { success: false, error: error.message };
        }
    },

    async getProviderRoutingSettings() {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/settings/provider-routing`);
            if (!response.ok) throw new Error('Failed to fetch provider routing settings');
            return await response.json();
        } catch (error) {
            this.logFetchFailure('Error fetching provider routing settings', error);
            return null;
        }
    },

    async updateProviderRoutingSettings(settings) {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/settings/provider-routing`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });
            if (!response.ok) throw new Error('Failed to update provider routing settings');
            return await response.json();
        } catch (error) {
            this.logFetchFailure('Error updating provider routing settings', error);
            return { success: false, error: error.message };
        }
    },

    async getDiskSpaceStatus() {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}/api/settings/disk-space-status`);
            if (!response.ok) throw new Error('Failed to fetch disk space status');
            return await response.json();
        } catch (error) {
            this.logFetchFailure('Error fetching disk space status', error);
            return null;
        }
    },

    async getReliabilityStats(windowSize = 50) {
        try {
            const safeWindow = Number.isFinite(Number(windowSize)) ? Number(windowSize) : 50;
            const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.RELIABILITY_STATS}?window=${safeWindow}`);
            if (!response.ok) throw new Error('Failed to fetch reliability stats');
            return await response.json();
        } catch (error) {
            this.logFetchFailure('Error fetching reliability stats', error);
            return { success: false, error: error.message };
        }
    },

    async getProviderRuntimeStatus() {
        try {
            const response = await fetch(`${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.PROVIDER_RUNTIME_STATUS}`, {
                cache: 'no-store'
            });
            if (!response.ok) throw new Error('Failed to fetch provider runtime status');
            return await response.json();
        } catch (error) {
            this.logFetchFailure('Error fetching provider runtime status', error);
            return { success: false, error: error.message };
        }
    },

    async getReportRecoveryOptions(options = {}) {
        try {
            const machineId = String(
                (options && (options.machineId || options.machine_id)) || ''
            ).trim();
            const query = new URLSearchParams();
            if (machineId) {
                query.set('machine_id', machineId);
            }
            if (options && (options.checkupOnly || options.checkup_only)) {
                query.set('checkup_only', '1');
            }

            const querySuffix = query.toString();
            const endpoint = `${API_CONFIG.BASE_URL}/api/reports/recovery/options${querySuffix ? `?${querySuffix}` : ''}`;

            const response = await this._fetchWithTimeout(endpoint, {
                cache: 'no-store'
            }, 12000);
            if (!response.ok) throw new Error('Failed to fetch recovery options');
            return await response.json();
        } catch (error) {
            this.logFetchFailure('Error fetching report recovery options', error);
            return { success: false, error: error.message };
        }
    },

    async executeReportRecovery(mode, reportIds = null) {
        try {
            const payload = { mode };
            if (Array.isArray(reportIds) && reportIds.length > 0) {
                payload.report_ids = reportIds;
            }

            const response = await fetch(`${API_CONFIG.BASE_URL}/api/reports/recovery/execute`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.error || 'Failed to execute report recovery');
            }
            return data;
        } catch (error) {
            this.logFetchFailure('Error executing report recovery', error);
            return { success: false, error: error.message };
        }
    },

    async prepareLocalMode(options = {}) {
        try {
            const payload = {
                auto_pull: options.autoPull !== false,
                set_local_first: options.setLocalFirst !== false,
                wait_seconds: Number(options.waitSeconds || 8),
                pull_timeout_seconds: Number(options.pullTimeoutSeconds || 600)
            };

            const response = await this._fetchWithTimeout(`${API_CONFIG.BASE_URL}/api/local-mode/prepare`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }, Math.max(15000, (Number(payload.pull_timeout_seconds) || 60) * 1000 + 5000));

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                return {
                    success: false,
                    ...data,
                    error: data.error || data.message || 'Failed to prepare local mode'
                };
            }
            return data;
        } catch (error) {
            this.logFetchFailure('Error preparing local mode', error);
            return { success: false, error: error.message };
        }
    },

    async autoProvisionLocalModeCredentials(options = {}) {
        try {
            const payload = {};
            if (options.cloudUrl) {
                payload.cloud_url = String(options.cloudUrl).trim();
            }
            if (options.provision_secret) {
                payload.provision_secret = String(options.provision_secret).trim();
            }

            const response = await this._fetchWithTimeout(`${API_CONFIG.BASE_URL}/api/local-mode/provisioning/auto`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }, 20000);

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                return {
                    success: false,
                    ...data,
                    error: data.error || data.message || `Auto-provisioning failed (${response.status})`
                };
            }

            return data;
        } catch (error) {
            this.logFetchFailure('Error auto-provisioning local mode credentials', error);
            return { success: false, error: error.message };
        }
    },

    async requestCloudProvisioningApproval(options = {}) {
        try {
            const machineId = String(
                (options && (options.machineId || options.machine_id)) || ''
            ).trim();
            if (!machineId) {
                return {
                    success: false,
                    error: 'machine_id is required to request provisioning approval'
                };
            }

            // Proof-of-prior-trust: if the caller already holds the current
            // provision_secret (from a prior approved registration), include it
            // so the backend can authenticate the rotation without an admin
            // token. Brand-new devices simply omit this field and must be
            // approved out-of-band.
            const currentSecret = String(
                (options && (options.currentProvisionSecret || options.provisionSecret || options.provision_secret)) || ''
            ).trim();

            const body = { machine_id: machineId };
            if (currentSecret) {
                body.current_provision_secret = currentSecret;
            }

            const response = await this._fetchWithTimeout(`${API_CONFIG.BASE_URL}/api/provision/request`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            }, 25000);

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                return {
                    success: false,
                    ...data,
                    machine_id: String(data.machine_id || machineId).trim(),
                    error: data.error || data.message || `Provision request failed (${response.status})`
                };
            }

            const rawRequestStatus = String((data && data.status) || '').trim().toLowerCase();
            const rawDeviceStatus = String(
                (data && (data.device_status || data.provisioning_status)) || rawRequestStatus || ''
            ).trim().toLowerCase();
            const normalizedDeviceStatus = (() => {
                if (rawDeviceStatus === 'pending' || rawDeviceStatus === 'pending_approval') return 'pending_approval';
                if (rawDeviceStatus === 'approved') return 'approved';
                if (rawDeviceStatus === 'provisioned') return 'provisioned';
                if (rawDeviceStatus === 'active') return 'active';
                if (rawDeviceStatus === 'rejected') return 'rejected';
                if (rawRequestStatus === 'stored') return 'pending_approval';
                return rawDeviceStatus || 'idle';
            })();

            return {
                success: true,
                ...data,
                request_status: rawRequestStatus || undefined,
                status: normalizedDeviceStatus,
                machine_id: String(data.machine_id || machineId).trim()
            };
        } catch (error) {
            this.logFetchFailure('Error requesting cloud provisioning approval', error);
            return { success: false, error: error.message };
        }
    },

    async getCloudProvisioningStatus(options = {}) {
        try {
            const machineId = String(
                (options && (options.machineId || options.machine_id)) || ''
            ).trim();
            const provisionSecret = String(
                (options && (options.provisionSecret || options.provision_secret)) || ''
            ).trim();

            if (!machineId) {
                return {
                    success: false,
                    error: 'machine_id is required to fetch cloud provisioning status'
                };
            }

            if (!provisionSecret) {
                return {
                    success: false,
                    machine_id: machineId,
                    error: 'provision_secret is required to fetch cloud provisioning status'
                };
            }

            const buildStatusUrl = (includeSecretInQuery = false) => {
                const query = new URLSearchParams();
                query.set('machine_id', machineId);
                if (includeSecretInQuery) {
                    query.set('provision_secret', provisionSecret);
                }
                return `${API_CONFIG.BASE_URL}/api/provision/status?${query.toString()}`;
            };

            let response;
            try {
                response = await this._fetchWithTimeout(buildStatusUrl(false), {
                    cache: 'no-store',
                    headers: {
                        'X-Provision-Secret': provisionSecret
                    }
                }, 12000);
            } catch (headerRequestError) {
                // Fallback for environments where custom header preflight is blocked.
                response = await this._fetchWithTimeout(buildStatusUrl(true), {
                    cache: 'no-store'
                }, 12000);
            }

            const data = await response.json().catch(() => ({}));
            const status = String((data && data.status) || '').trim().toLowerCase();

            if (response.status === 403 && status === 'rejected') {
                return {
                    success: true,
                    ...data,
                    status: 'rejected',
                    machine_id: String(data.machine_id || machineId).trim()
                };
            }

            if (!response.ok) {
                return {
                    success: false,
                    ...data,
                    status,
                    machine_id: String(data.machine_id || machineId).trim(),
                    error: data.error || data.message || `Provision status failed (${response.status})`
                };
            }

            return {
                success: true,
                ...data,
                status,
                machine_id: String(data.machine_id || machineId).trim()
            };
        } catch (error) {
            this.logFetchFailure('Error fetching cloud provisioning status', error);
            return { success: false, error: error.message };
        }
    },

    async getLocalModeProvisioningStatus(options = {}) {
        try {
            const machineId = String(
                (options && (options.machineId || options.machine_id)) || ''
            ).trim();
            const query = new URLSearchParams();
            if (machineId) {
                query.set('machine_id', machineId);
            }

            const querySuffix = query.toString();
            const endpoint = `${API_CONFIG.BASE_URL}/api/local-mode/provisioning/status${querySuffix ? `?${querySuffix}` : ''}`;

            const response = await this._fetchWithTimeout(endpoint, {
                cache: 'no-store'
            }, 12000);
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                return {
                    success: false,
                    ...data,
                    error: data.error || data.message || 'Failed to fetch local provisioning status'
                };
            }
            return data;
        } catch (error) {
            this.logFetchFailure('Error fetching local provisioning status', error);
            return { success: false, error: error.message };
        }
    },

    async switchPipelineMode(mode) {
        const normalized = String(mode || '').trim().toLowerCase();
        if (normalized !== 'local' && normalized !== 'cloud') {
            return { success: false, error: 'Mode must be either local or cloud' };
        }
        return this.updateProviderRoutingSettings({
            routing_profile: normalized
        });
    },

    async syncLocalCacheToSupabase(options = {}) {
        try {
            const limit = Number(options.limit || 120);
            const reason = String(options.reason || '').trim() || 'manual_api';
            const dryRun = !!options.dryRun;
            const origin = String(options.origin || 'local_synced').trim() || 'local_synced';
            const normalizedReason = reason.toLowerCase();
            const allowLocalModeSync = !!options.allowLocalModeSync
                || normalizedReason === 'reconnect_auto'
                || normalizedReason === 'auto_reconnect'
                || normalizedReason.includes('reconnect')
                || normalizedReason.includes('online');
            const syncBase = this._normalizeBaseUrl(options.baseUrl || options.syncBaseUrl || this.getLocalSyncBackendBaseUrl());
            const localLoopbackBlocked = this.isLocalBackendBase(syncBase)
                && !this.canUseLocalBackendFromPage(syncBase)
                && options.allowBrowserLoopback !== true;
            if (localLoopbackBlocked) {
                return {
                    success: true,
                    skipped_browser_loopback_blocked: true,
                    reconcile_reason: reason,
                    origin,
                    dry_run: dryRun,
                    scanned: 0,
                    candidates: 0,
                    enqueued: 0,
                    skipped: 0,
                    queued_report_ids: []
                };
            }
            if (typeof navigator !== 'undefined' && navigator.onLine === false && !dryRun) {
                return {
                    success: true,
                    skipped_offline: true,
                    reconcile_reason: reason,
                    origin,
                    dry_run: false,
                    scanned: 0,
                    candidates: 0,
                    enqueued: 0,
                    skipped: 0,
                    queued_report_ids: []
                };
            }

            if (!dryRun && options.skipCandidateCheck !== true) {
                const candidates = await this.getLocalSyncCandidateSummary();
                if (!candidates.count) {
                    let backendCandidates = 0;
                    let backendCandidateProbe = null;
                    if (options.backendCandidateCheck !== false) {
                        try {
                            const probeResponse = await this._fetchWithTimeout(`${syncBase}/api/reports/sync-local-cache`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                cache: 'no-store',
                                body: JSON.stringify({
                                    limit,
                                    reason,
                                    dry_run: true,
                                    origin,
                                    source_scope: 'synced_local',
                                    allow_local_mode_sync: allowLocalModeSync
                                })
                            }, Number(options.candidateTimeoutMs || 12000));
                            backendCandidateProbe = await probeResponse.json().catch(() => ({}));
                            if (probeResponse.ok && backendCandidateProbe && backendCandidateProbe.success !== false) {
                                backendCandidates = Number(backendCandidateProbe.candidates || 0);
                            }
                        } catch (probeError) {
                            console.debug('Backend local-cache candidate probe skipped:', probeError);
                        }
                    }

                    if (backendCandidates <= 0) {
                        return {
                            success: true,
                            skipped_no_local_candidates: true,
                            reconcile_reason: reason,
                            origin,
                            dry_run: false,
                            scanned: Number((backendCandidateProbe && backendCandidateProbe.scanned) || 0),
                            candidates: 0,
                            enqueued: 0,
                            skipped: 0,
                            queued_report_ids: []
                        };
                    }
                }
            }

            const response = await this._fetchWithTimeout(`${syncBase}/api/reports/sync-local-cache`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                cache: 'no-store',
                body: JSON.stringify({
                    limit,
                    reason,
                    dry_run: dryRun,
                    origin,
                    source_scope: 'synced_local',
                    allow_local_mode_sync: allowLocalModeSync
                })
            }, Number(options.timeoutMs || 30000));

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                return {
                    success: false,
                    ...data,
                    error: data.error || 'Failed to sync local cache to Supabase'
                };
            }
            const reportIds = [
                ...(Array.isArray(data.synced_report_ids) ? data.synced_report_ids : []),
                ...(Array.isArray(data.completed_report_ids) ? data.completed_report_ids : [])
            ];
            const strictReportIds = await this.filterStrictLocalSyncReportIds(reportIds);
            if (strictReportIds.length) {
                await this.markReportsAsLocalSynced(strictReportIds, {
                    ...data,
                    origin,
                    source_scope: 'synced_local',
                    source_label: 'Local Synced',
                    sync_source: 'sync_local_cache',
                    sync_state: 'cloud_completed'
                });
            }
            return data;
        } catch (error) {
            console.warn('Local cache sync skipped or failed:', error && error.message ? error.message : error);
            void this.registerLocalReportBackgroundSync('sync local cache failed');
            return { success: false, error: error.message };
        }
    },

    async handoffLocalReportDraftsToCloud(options = {}) {
        const limit = Math.max(1, Math.min(Number(options.limit || 10), 50));
        const reason = String(options.reason || '').trim() || 'browser_reconnect';
        const force = !!options.force;
        const retryWindowMs = Math.max(15000, Number(options.retryWindowMs || 120000));
        const drafts = (await this.readLocalReportDrafts())
            .filter((draft) => this.isStrictLocalOriginReport(draft));
        const now = Date.now();
        let attempted = 0;
        let queued = 0;
        let completed = 0;
        let skipped = 0;
        const queuedReportIds = [];
        const completedReportIds = [];
        const errors = [];

        for (const draft of drafts) {
            if (attempted >= limit) break;
            if (!draft || !draft.report_id || !draft.original_blob) {
                skipped += 1;
                continue;
            }

            if (!this.isCompletedLocalReportDraftForCloudSync(draft)) {
                skipped += 1;
                continue;
            }

            const syncState = String(draft.sync_state || '').toLowerCase();
            if (['synced', 'cloud_completed'].includes(syncState)) {
                skipped += 1;
                continue;
            }

            const lastHandoffAt = Date.parse(draft.cloud_handoff_at || draft.handoff_attempted_at || '');
            const recentHandoff = Number.isFinite(lastHandoffAt) && now - lastHandoffAt < retryWindowMs;
            if (
                recentHandoff
                && (
                    !force
                    || ['cloud_generation_queued', 'cloud_handoff_uploaded'].includes(syncState)
                )
            ) {
                skipped += 1;
                continue;
            }

            attempted += 1;
            const metadata = this.stripLocalDraftRuntimeFields([{
                ...draft,
                handoff_reason: reason,
                handoff_client: 'browser_indexeddb_draft'
            }])[0] || {};

            const form = new FormData();
            form.append('report_id', draft.report_id);
            form.append('reason', reason);
            form.append('metadata', JSON.stringify(metadata));
            form.append('image', draft.original_blob, `${draft.report_id}.jpg`);

            try {
                const response = await this._fetchWithTimeout(
                    `${API_CONFIG.BASE_URL}/api/reports/local-draft-handoff`,
                    {
                        method: 'POST',
                        body: form
                    },
                    Number(options.timeoutMs || 25000)
                );
                const data = await response.json().catch(() => ({}));
                if (!response.ok || data.success === false) {
                    throw new Error(data.error || 'Local draft handoff failed');
                }

                if (data.already_completed) {
                    completed += 1;
                    completedReportIds.push(draft.report_id);
                    await this.removeLocalReportDraft(draft.report_id);
                    continue;
                }

                if (data.queued) {
                    queued += 1;
                    queuedReportIds.push(draft.report_id);
                }
                await this.upsertLocalReportDraft({
                    ...draft,
                    source_scope: data.source_scope || 'cloud',
                    source_label: data.source_label || (data.source_scope === 'synced_local' ? 'Local Synced' : 'Cloud'),
                    origin: data.source_scope === 'synced_local' ? 'local_synced' : (draft.origin || ''),
                    sync_source: data.sync_source || 'browser_local_draft_handoff',
                    sync_state: data.queued ? 'cloud_generation_queued' : 'cloud_handoff_uploaded',
                    cloud_handoff_at: new Date().toISOString(),
                    cloud_adopt_after_epoch: data.cloud_adopt_after_epoch || null,
                    handoff_attempted_at: new Date().toISOString(),
                    status: data.queued ? 'pending' : (draft.status || 'pending')
                });
                if (!data.queued) queuedReportIds.push(draft.report_id);
            } catch (error) {
                errors.push(`${draft.report_id}: ${error.message}`);
                try {
                    await this.upsertLocalReportDraft({
                        ...draft,
                        sync_state: 'cloud_handoff_retry',
                        handoff_attempted_at: new Date().toISOString(),
                        handoff_error: error.message
                    });
                } catch (writeErr) {
                    // Keep the original draft if the status update cannot be saved.
                }
            }
        }

        if (completedReportIds.length) {
            await this.markReportsAsLocalSynced(completedReportIds, {
                origin: 'local_synced',
                source_scope: 'synced_local',
                source_label: 'Local Synced',
                sync_source: 'browser_local_draft_handoff',
                sync_state: 'cloud_completed',
                queued_report_ids: queuedReportIds,
                completed_report_ids: completedReportIds
            });
        }

        return {
            success: errors.length === 0,
            attempted,
            queued,
            completed,
            skipped,
            queued_report_ids: queuedReportIds,
            completed_report_ids: completedReportIds,
            errors
        };
    },

    getRealtimeStreamUrl() {
        return `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.REALTIME_STREAM}`;
    },

    getRealtimeSnapshotUrl() {
        return `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.REALTIME_SNAPSHOT}`;
    },

    getSupabaseRealtimeConfig() {
        const runtime = window.__PPE_CONFIG__ || {};
        return {
            url: runtime.SUPABASE_URL || window.PPE_SUPABASE_URL || '',
            anonKey: runtime.SUPABASE_ANON_KEY || window.PPE_SUPABASE_ANON_KEY || ''
        };
    }
};

try {
    window.API = window.API || API;
} catch (e) {
    // Ignore non-browser contexts used by syntax checks.
}
