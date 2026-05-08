import os
from pathlib import Path
import unittest


ROOT = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class ReportRoutingStaticTest(unittest.TestCase):
    def test_report_origin_routing_helpers_exist(self):
        api_js = (ROOT / 'frontend' / 'js' / 'api.js').read_text(encoding='utf-8')
        reports_js = (ROOT / 'frontend' / 'js' / 'pages' / 'reports.js').read_text(encoding='utf-8')

        self.assertIn('getReportBackendBase(sourceHint = null)', api_js)
        self.assertIn("scope === 'cloud' || scope === 'synced_local'", api_js)
        self.assertIn('configuredCloudBase && configuredCloudBase === normalized', api_js)
        self.assertIn("API.getImageUrl(violation.report_id, 'annotated.jpg', violation)", reports_js)
        self.assertIn('this.openReport(violation.report_id, violation)', reports_js)

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

        self.assertIn("host === 'localhost'", realtime_js)
        self.assertIn('return false;', realtime_js)
        self.assertIn('_push_realtime_report_event(preliminary_metadata', casm_app)
        self.assertIn("_push_realtime_report_event(realtime_metadata, event_type='report_status')", casm_app)
        self.assertIn("existing[flag_key] = bool(existing.get(flag_key)) or bool(local_row.get(flag_key))", casm_app)
        self.assertIn('realtime_report_events = deque', casm_app)

    def test_local_notifications_survive_initial_load_and_preliminary_rows(self):
        realtime_js = (ROOT / 'frontend' / 'js' / 'realtime.js').read_text(encoding='utf-8')
        monitor_js = (ROOT / 'frontend' / 'js' / 'violation-monitor.js').read_text(encoding='utf-8')

        self.assertIn('NEW real-time violation arrived during initial load', monitor_js)
        self.assertIn('violationTime > sessionStartWithBuffer', monitor_js)
        self.assertIn('emitViolationDetectedNotifications(payload)', realtime_js)
        self.assertIn('eventType === \'violation_detected\'', realtime_js)
        self.assertIn('ViolationMonitor._notifyViolationDetected(violation)', realtime_js)
        self.assertIn('rowNeedsLifecycleFallback', realtime_js)
        self.assertIn("progressStatus === 'generating'", realtime_js)
        self.assertIn('!progressRowHasReport', realtime_js)

    def test_synced_local_tag_survives_cloud_mode_repair(self):
        casm_app = (ROOT / 'casm_app.py').read_text(encoding='utf-8')

        self.assertIn('is_local_sync_marker_for_repair', casm_app)
        self.assertIn("source_scope_marker = 'synced_local'", casm_app)
        self.assertIn("'browser_local_draft_handoff'", casm_app)

    def test_local_sync_and_generation_quality_guards(self):
        casm_app = (ROOT / 'casm_app.py').read_text(encoding='utf-8')
        caption_image = (ROOT / 'caption_image.py').read_text(encoding='utf-8')

        self.assertIn("OLLAMA_VISION_READ_TIMEOUT_SECONDS = _safe_int_env('OLLAMA_VISION_READ_TIMEOUT_SECONDS', 360)", caption_image)
        self.assertIn('max_tokens=650', caption_image)
        self.assertIn('max_tokens=750', caption_image)
        self.assertIn('Do not answer with only one sentence.', caption_image)
        self.assertIn('no "Here is a description" preamble', caption_image)
        self.assertIn("GEMINI_VISION_THINKING_BUDGET = _safe_int_env('GEMINI_VISION_THINKING_BUDGET', 0)", caption_image)
        self.assertIn("'thinkingBudget': GEMINI_VISION_THINKING_BUDGET", caption_image)
        self.assertNotIn('allow_placeholder_report = True\n\n    logger.info', casm_app)
        self.assertIn('allow_placeholder_report and force_reprocess_requested', casm_app)
        self.assertIn('queue_sync_device_id = f"local_cache_sync_{report_id}_{time.time_ns()}"', casm_app)
        self.assertIn('device_id=queue_sync_device_id', casm_app)
        self.assertIn('def _realtime_source_payload(scope: str, reason: str)', casm_app)
        self.assertIn("os.getenv('SUPABASE_AUTO_SYNC_BATCH_SIZE', '4')", casm_app)


if __name__ == '__main__':
    unittest.main(verbosity=2)
