import os
from pathlib import Path
import unittest


ROOT = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class ReportRoutingStaticTest(unittest.TestCase):
    def test_report_origin_routing_helpers_exist(self):
        api_js = (ROOT / 'frontend' / 'js' / 'api.js').read_text(encoding='utf-8')
        reports_js = (ROOT / 'frontend' / 'js' / 'pages' / 'reports.js').read_text(encoding='utf-8')
        app_js = (ROOT / 'frontend' / 'js' / 'app.js').read_text(encoding='utf-8')
        analytics_js = (ROOT / 'frontend' / 'js' / 'pages' / 'analytics.js').read_text(encoding='utf-8')

        self.assertIn('getReportBackendBase(sourceHint = null)', api_js)
        self.assertIn("scope === 'cloud' || scope === 'synced_local'", api_js)
        self.assertIn('configuredCloudBase && configuredCloudBase === normalized', api_js)
        self.assertIn("API.getImageUrl(violation.report_id, 'annotated.jpg', violation)", reports_js)
        self.assertIn('this.openReport(violation.report_id, violation)', reports_js)
        self.assertIn('warmDashboardCaches({ reason: \'startup\'', app_js)
        self.assertIn("API.waitForDashboardWarmup(['violations', 'pending']", reports_js)
        self.assertIn("API.waitForDashboardWarmup(['stats', 'violations']", analytics_js)

    def test_local_mode_metrics_use_cloud_and_local_fetches(self):
        api_js = (ROOT / 'frontend' / 'js' / 'api.js').read_text(encoding='utf-8')

        self.assertIn('Promise.allSettled', api_js)
        self.assertIn('calculateStatsFromViolations(merged)', api_js)
        self.assertIn('this.mergeLocalReportDrafts(merged, safeLimit)', api_js)
        self.assertIn('cached_rows: this.stripLocalDraftRuntimeFields(merged)', api_js)
        self.assertNotIn('return readyCount || list.length', api_js)
        self.assertIn("status === 'completed'", api_js)
        self.assertIn("!!item.local_report_url", api_js)

    def test_backend_stats_scope_matches_cloud_staging_semantics(self):
        casm_app = (ROOT / 'casm_app.py').read_text(encoding='utf-8')

        self.assertIn("active_profile = _normalize_provider_profile(os.getenv('CASM_ROUTING_PROFILE', ''))", casm_app)
        self.assertIn("explicit_scope == 'synced_local'", casm_app)
        self.assertIn("active_profile == 'cloud' and has_local_artifacts and not is_local_device", casm_app)
        self.assertIn('return \'cloud\'', casm_app)

    def test_local_realtime_uses_sse_and_backend_push_rows(self):
        realtime_js = (ROOT / 'frontend' / 'js' / 'realtime.js').read_text(encoding='utf-8')
        casm_app = (ROOT / 'casm_app.py').read_text(encoding='utf-8')
        supabase_report_generator = (ROOT / 'pipeline' / 'backend' / 'core' / 'supabase_report_generator.py').read_text(encoding='utf-8')

        self.assertIn("host === 'localhost'", realtime_js)
        self.assertIn('return false;', realtime_js)
        self.assertIn('_push_realtime_report_event(preliminary_metadata', casm_app)
        self.assertIn("_push_realtime_report_event(realtime_metadata, event_type='report_status')", casm_app)
        self.assertIn("_push_processing_status('generating')", casm_app)
        self.assertIn("existing[flag_key] = bool(existing.get(flag_key)) or bool(local_row.get(flag_key))", casm_app)
        self.assertIn('realtime_report_events = deque', casm_app)
        self.assertIn("'status_sequence': status_sequence", casm_app)
        self.assertIn('normalizeStatusSequence(sequence)', reports_js := (ROOT / 'frontend' / 'js' / 'pages' / 'reports.js').read_text(encoding='utf-8'))
        self.assertIn('display_status_until', reports_js)
        self.assertIn('minGeneratingDisplayMs', reports_js)
        self.assertIn("def _signal_local_report_ready(reason: str = 'local_report_html_ready')", casm_app)
        self.assertIn("'report_openable_after_seconds'", casm_app)
        self.assertIn("'report_ready_callback': _signal_local_report_ready", casm_app)
        self.assertIn('ready_callback = report_data.get(\'report_ready_callback\')', supabase_report_generator)
        self.assertIn('supabase_local_report_html_written', supabase_report_generator)
        self.assertLess(
            supabase_report_generator.index('supabase_local_report_html_written'),
            supabase_report_generator.index('# Step 1.5: Validate caption against annotations'),
            'Report-ready callback must run before validation/upload/persistence work',
        )

    def test_local_notifications_survive_initial_load_and_preliminary_rows(self):
        realtime_js = (ROOT / 'frontend' / 'js' / 'realtime.js').read_text(encoding='utf-8')
        monitor_js = (ROOT / 'frontend' / 'js' / 'violation-monitor.js').read_text(encoding='utf-8')

        self.assertIn('Initial load hydrated', monitor_js)
        self.assertIn('startup notifications suppressed', monitor_js)
        self.assertIn('violationTime >= this.sessionStartTime', monitor_js)
        self.assertIn('isLifecycleEventDuringSession(violation)', monitor_js)
        self.assertNotIn('NEW real-time violation arrived during initial load', monitor_js)
        self.assertIn('emitViolationDetectedNotifications(payload)', realtime_js)
        self.assertIn('eventType === \'violation_detected\'', realtime_js)
        self.assertIn('eventEpoch >= this.sessionStartedAtMs', realtime_js)
        self.assertIn('statusNotificationsHydrated', realtime_js)
        self.assertNotIn('isFreshLocalLifecycleRow', realtime_js)
        self.assertIn('ViolationMonitor._notifyViolationDetected(violation)', realtime_js)
        self.assertIn('ViolationMonitor.applyRealtimePayload(payload)', realtime_js)
        self.assertNotIn("ViolationMonitor.checkForNewViolations({ noCache: true, reason: 'realtime-update' })", realtime_js)
        self.assertIn('this.fetchRealtimeSnapshot({ fresh: true })', realtime_js)
        self.assertIn('fresh=1', realtime_js)
        self.assertIn('rowNeedsLifecycleFallback', realtime_js)
        self.assertIn("progressStatus === 'generating'", realtime_js)
        self.assertIn('!progressRowHasReport', realtime_js)

    def test_synced_local_tag_survives_cloud_mode_repair(self):
        casm_app = (ROOT / 'casm_app.py').read_text(encoding='utf-8')
        reports_js = (ROOT / 'frontend' / 'js' / 'pages' / 'reports.js').read_text(encoding='utf-8')

        self.assertIn('confirmed_synced_local = _has_confirmed_synced_local_evidence', casm_app)
        self.assertIn("source_scope_marker = 'synced_local'", casm_app)
        self.assertIn("'browser_local_draft_handoff'", casm_app)
        self.assertIn('resolveStableRuntimeSourceScope', reports_js)
        self.assertIn('hasSyncedLocalEvidence(existing)', reports_js)
        self.assertIn("status_info.get('source_scope') != 'local'", casm_app)

    def test_local_sync_and_generation_quality_guards(self):
        casm_app = (ROOT / 'casm_app.py').read_text(encoding='utf-8')
        caption_image = (ROOT / 'caption_image.py').read_text(encoding='utf-8')

        self.assertIn("OLLAMA_VISION_READ_TIMEOUT_SECONDS = _safe_int_env('OLLAMA_VISION_READ_TIMEOUT_SECONDS', 60)", caption_image)
        self.assertIn('LOCAL_OLLAMA_VISION_READ_TIMEOUT_SECONDS = max(', caption_image)
        self.assertIn("_safe_int_env('LOCAL_OLLAMA_VISION_READ_TIMEOUT_SECONDS', 120)", caption_image)
        self.assertIn('LOCAL_OLLAMA_CPU_VISION_READ_TIMEOUT_SECONDS = max(', caption_image)
        self.assertIn("_safe_int_env('LOCAL_OLLAMA_CPU_VISION_READ_TIMEOUT_SECONDS', 210)", caption_image)
        self.assertIn("else None", caption_image)
        self.assertIn("if OLLAMA_VISION_NUM_GPU is not None:", caption_image)
        self.assertIn('max_tokens=LOCAL_OLLAMA_CAPTION_MAX_TOKENS if strict_local_profile else 650', caption_image)
        self.assertIn('max_tokens=750', caption_image)
        self.assertIn('Do not answer with only one sentence.', caption_image)
        self.assertIn('no "Here is a description" preamble', caption_image)
        self.assertIn("GEMINI_VISION_THINKING_BUDGET = _safe_int_env('GEMINI_VISION_THINKING_BUDGET', 0)", caption_image)
        self.assertIn("'thinkingBudget': GEMINI_VISION_THINKING_BUDGET", caption_image)
        self.assertNotIn('allow_placeholder_report = True\n\n    logger.info', casm_app)
        self.assertIn('allow_placeholder_report and force_reprocess_requested', casm_app)
        self.assertIn('queue_sync_device_id = f"local_cache_sync_{report_id}_{time.time_ns()}"', casm_app)
        self.assertIn('device_id=queue_sync_device_id', casm_app)
        self.assertIn('allow_local_mode_sync=True', casm_app)
        self.assertIn('local_mode_sync_allowed = bool(allow_local_mode_sync or is_auto_reconnect)', casm_app)
        self.assertIn('def _realtime_source_payload(scope: str, reason: str)', casm_app)
        self.assertIn("os.getenv('SUPABASE_AUTO_SYNC_BATCH_SIZE', '4')", casm_app)
        self.assertIn('def _normalize_violation_type_label(value: Any) -> str:', casm_app)
        self.assertIn("'ppe_tags': violation_types_raw", casm_app)
        self.assertIn("'missing_ppe': missing_ppe_values", casm_app)
        self.assertIn("for detail_key in ('missing_ppe', 'ppe_tags')", casm_app)

    def test_live_prepare_and_first_run_capture_guards_exist(self):
        casm_app = (ROOT / 'casm_app.py').read_text(encoding='utf-8')
        live_js = (ROOT / 'frontend' / 'js' / 'pages' / 'live.js').read_text(encoding='utf-8')
        config_js = (ROOT / 'frontend' / 'js' / 'config.js').read_text(encoding='utf-8')
        infer_image = (ROOT / 'infer_image.py').read_text(encoding='utf-8')
        live_source_adapter = (ROOT / 'pipeline' / 'backend' / 'core' / 'live_source_adapter.py').read_text(encoding='utf-8')

        self.assertIn("@app.route('/api/live/prepare', methods=['POST'])", casm_app)
        self.assertIn("_prepare_live_runtime(", casm_app)
        self.assertIn("annotated_frame: Optional[np.ndarray] = None", casm_app)
        self.assertIn("Saved annotated image at capture time", casm_app)
        self.assertIn("warmup_model(conf=0.25, imgsz=640)", casm_app)
        self.assertIn("max_report_attempts = 2 if cloud_retry_allowed else 1", casm_app)
        self.assertIn("Retrying cloud report generation for", casm_app)
        self.assertIn("prepareLiveRuntime(", live_js)
        self.assertIn("void prepareLiveRuntime('live-page-mount');", live_js)
        self.assertIn("backendWebcamDevices.length === 0", live_js)
        self.assertIn("const refreshParam = notify ? '?refresh=1' : ''", live_js)
        self.assertIn("LIVE_PREPARE: '/api/live/prepare'", config_js)
        self.assertIn("def warmup_model(", infer_image)
        self.assertIn("def is_model_ready(", infer_image)
        self.assertIn('WEBCAM_NEGATIVE_PROBE_CACHE_SECONDS', live_source_adapter)
        self.assertIn('cache_valid = self._webcam_probe_cache_ts > 0', live_source_adapter)

    def test_cloud_heartbeat_and_provisioning_labels_stay_visible(self):
        casm_app = (ROOT / 'casm_app.py').read_text(encoding='utf-8')
        app_js = (ROOT / 'frontend' / 'js' / 'app.js').read_text(encoding='utf-8')
        settings_js = (ROOT / 'frontend' / 'js' / 'settings-modal.js').read_text(encoding='utf-8')
        reports_js = (ROOT / 'frontend' / 'js' / 'pages' / 'reports.js').read_text(encoding='utf-8')
        report_generator = (ROOT / 'pipeline' / 'backend' / 'core' / 'report_generator.py').read_text(encoding='utf-8')

        self.assertIn("'matches_requested_machine': bool(matched_requested_machine)", casm_app)
        self.assertIn("heartbeat_summary.get('matches_requested_machine', True)", casm_app)
        self.assertIn("provision_status = 'idle'", casm_app)
        self.assertIn('scheduleProvisioningHeartbeatRefreshBurst', app_js)
        self.assertIn('heartbeatMatchesThisMachine', app_js)
        self.assertIn('online-heartbeat-followup', app_js)
        self.assertIn('PROVIDER_PROFILE_MANUAL_LOCK_KEY', app_js)
        self.assertIn('getManualProviderProfileLock()', app_js)
        self.assertIn("this.manualProviderProfile = manualLock === 'local' ? 'local' : ''", app_js)
        self.assertIn("manualProfile === 'local' && options.allowWhileLocal !== true", app_js)
        self.assertNotIn("(this.currentMode === 'local' || manualProfile === 'local') && options.allowWhileLocal !== true", app_js)
        self.assertIn('allowLocalModeSync', (ROOT / 'frontend' / 'js' / 'api.js').read_text(encoding='utf-8'))
        self.assertIn('ensureHeartbeatRefreshPolling', settings_js)
        self.assertIn('heartbeatMatchesThisMachine', settings_js)
        self.assertIn('setProviderProfileManualLock', settings_js)
        self.assertIn('Request Reprovisioning', settings_js)
        self.assertIn('Cloud heartbeat: fresh ${scopeLabel}', settings_js)
        self.assertIn("'LOCAL_REPORT_ALLOW_NLP_FALLBACK', 'false'", casm_app)
        self.assertIn("'LOCAL_REPORT_RULE_BASED_FAST_PATH', 'false'", report_generator)
        self.assertIn("OLLAMA_FORCE_LOCAL_READ_TIMEOUT_SECONDS', '150'", report_generator)
        self.assertIn('OLLAMA_FORCE_LOCAL_JSON_SCHEMA', report_generator)
        self.assertIn('def _build_ollama_report_json_schema', report_generator)
        self.assertIn('getSyncInfo(violation', reports_js)
        self.assertIn('Sync queued', reports_js)


if __name__ == '__main__':
    unittest.main(verbosity=2)
