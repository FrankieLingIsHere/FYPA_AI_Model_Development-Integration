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
        self.assertIn("API.getImageUrl(violation.report_id, 'annotated.jpg', violation)", reports_js)
        self.assertIn('this.openReport(violation.report_id, violation)', reports_js)

    def test_local_mode_metrics_use_cloud_and_local_fetches(self):
        api_js = (ROOT / 'frontend' / 'js' / 'api.js').read_text(encoding='utf-8')

        self.assertIn('Promise.allSettled', api_js)
        self.assertIn('calculateStatsFromViolations(merged)', api_js)
        self.assertIn('this.mergeLocalReportDrafts(merged, safeLimit)', api_js)

    def test_local_realtime_uses_sse_and_backend_push_rows(self):
        realtime_js = (ROOT / 'frontend' / 'js' / 'realtime.js').read_text(encoding='utf-8')
        casm_app = (ROOT / 'casm_app.py').read_text(encoding='utf-8')

        self.assertIn("host === 'localhost'", realtime_js)
        self.assertIn('return false;', realtime_js)
        self.assertIn('_push_realtime_report_event(preliminary_metadata', casm_app)
        self.assertIn('realtime_report_events = deque', casm_app)

    def test_synced_local_tag_survives_cloud_mode_repair(self):
        casm_app = (ROOT / 'casm_app.py').read_text(encoding='utf-8')

        self.assertIn('is_local_sync_marker_for_repair', casm_app)
        self.assertIn("source_scope_marker = 'synced_local'", casm_app)
        self.assertIn("'browser_local_draft_handoff'", casm_app)


if __name__ == '__main__':
    unittest.main(verbosity=2)
