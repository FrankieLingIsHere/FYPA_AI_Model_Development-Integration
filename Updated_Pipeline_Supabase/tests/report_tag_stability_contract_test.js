/*
 * Contract test for report source tag stability.
 *
 * Matrix covered:
 * - Local reports stay Local while queued/generating.
 * - Cloud reports stay Cloud while local staging artifacts exist.
 * - Local Synced reports stay Local Synced when sync evidence exists.
 * - Historical bad Local Synced labels without sync evidence repair to Cloud.
 * - Shared reports are not downgraded by local runtime patches.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const REPORTS_JS = path.join(ROOT, 'frontend', 'js', 'pages', 'reports.js');

function loadReportsPage() {
  const code = `${fs.readFileSync(REPORTS_JS, 'utf8')}\nglobalThis.ReportsPage = ReportsPage;`;
  const context = {
    console,
    setTimeout,
    clearTimeout,
    document: {
      getElementById: () => null,
    },
  };
  vm.createContext(context);
  vm.runInContext(code, context, { filename: REPORTS_JS });
  return context.ReportsPage;
}

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, got ${actual}`);
  }
}

function assertTag(record, scope, label, message) {
  assertEqual(record.source_scope, scope, `${message} source_scope`);
  assertEqual(record.source_label, label, `${message} source_label`);
}

function testMergeMatrix() {
  const ReportsPage = loadReportsPage();
  const now = new Date().toISOString();
  const cases = [
    {
      name: 'local report stays local with ambiguous pending row',
      base: [{
        report_id: 'tag-local-queued-001',
        timestamp: now,
        status: 'pending',
        has_report: false,
        source_scope: 'local',
        source_label: 'Local',
        device_id: 'offline_local_cache',
      }],
      pending: [{
        report_id: 'tag-local-queued-001',
        timestamp: now,
        status: 'generating',
        has_report: false,
      }],
      expectedScope: 'local',
      expectedLabel: 'Local',
    },
    {
      name: 'synced local survives cloud pending row when sync marker exists',
      base: [{
        report_id: 'tag-synced-001',
        timestamp: now,
        status: 'pending',
        has_report: false,
        source_scope: 'synced_local',
        source_label: 'Local Synced',
        sync_source: 'sync_local_cache',
        report_html_key: 'violations/tag-synced-001/report.html',
      }],
      pending: [{
        report_id: 'tag-synced-001',
        timestamp: now,
        status: 'generating',
        has_report: false,
        source_scope: 'cloud',
        source_label: 'Cloud',
      }],
      expectedScope: 'synced_local',
      expectedLabel: 'Local Synced',
    },
    {
      name: 'bad synced-local label repairs to cloud when no sync evidence exists',
      base: [{
        report_id: 'tag-bad-synced-001',
        timestamp: now,
        status: 'pending',
        has_report: false,
        source_scope: 'synced_local',
        source_label: 'Local Synced',
      }],
      pending: [{
        report_id: 'tag-bad-synced-001',
        timestamp: now,
        status: 'generating',
        has_report: false,
        source_scope: 'cloud',
        source_label: 'Cloud',
      }],
      expectedScope: 'cloud',
      expectedLabel: 'Cloud',
    },
    {
      name: 'unsynced local report repairs back to local when bad synced-local scope has no sync proof',
      base: [{
        report_id: 'tag-unsynced-local-001',
        timestamp: now,
        status: 'pending',
        has_report: false,
        source_scope: 'synced_local',
        source_label: 'Local Synced',
        device_id: 'offline_local_cache',
        source: 'offline_local_cache',
      }],
      pending: [{
        report_id: 'tag-unsynced-local-001',
        timestamp: now,
        status: 'generating',
        has_report: false,
        source_scope: 'cloud',
        source_label: 'Cloud',
      }],
      expectedScope: 'local',
      expectedLabel: 'Local',
    },
  ];

  cases.forEach((entry) => {
    const merged = ReportsPage.mergePendingReports(entry.base, entry.pending);
    const record = merged.find((item) => item.report_id === entry.base[0].report_id);
    if (!record) {
      throw new Error(`${entry.name}: merged record missing`);
    }
    assertTag(record, entry.expectedScope, entry.expectedLabel, entry.name);
  });
}

function testRuntimePatchMatrix() {
  const ReportsPage = loadReportsPage();
  const cases = [
    {
      name: 'cloud report stays cloud when status payload looks local because of staging files',
      existing: {
        report_id: 'tag-cloud-runtime-001',
        status: 'pending',
        has_report: false,
        source_scope: 'cloud',
        source_label: 'Cloud',
        device_id: 'webcam_0',
      },
      patch: {
        status: 'generating',
        has_report: false,
        has_original: true,
        has_local_artifacts: true,
        local_image_url: 'blob:staged-preview',
        source_scope: 'local',
        source_label: 'Local',
      },
      expectedScope: 'cloud',
      expectedLabel: 'Cloud',
    },
    {
      name: 'local report stays local when a cloud patch is ambiguous',
      existing: {
        report_id: 'tag-local-runtime-001',
        status: 'pending',
        has_report: false,
        source_scope: 'local',
        source_label: 'Local',
        device_id: 'offline_local_cache',
      },
      patch: {
        status: 'generating',
        has_report: false,
        source_scope: 'cloud',
        source_label: 'Cloud',
      },
      expectedScope: 'local',
      expectedLabel: 'Local',
    },
    {
      name: 'local report stays local while reconnect sync is only queued',
      existing: {
        report_id: 'tag-local-sync-transition-001',
        status: 'pending',
        has_report: false,
        source_scope: 'local',
        source_label: 'Local',
        device_id: 'offline_local_cache',
        source: 'offline_local_cache',
      },
      patch: {
        status: 'generating',
        has_report: false,
        source_scope: 'synced_local',
        source_label: 'Local Synced',
        sync_source: 'sync_local_cache',
        sync_state: 'cloud_sync_queued',
      },
      expectedScope: 'local',
      expectedLabel: 'Local',
    },
    {
      name: 'local report becomes local synced after cloud report artifact exists',
      existing: {
        report_id: 'tag-local-sync-complete-001',
        status: 'completed',
        has_report: true,
        source_scope: 'local',
        source_label: 'Local',
        device_id: 'offline_local_cache',
        source: 'offline_local_cache',
      },
      patch: {
        status: 'completed',
        has_report: true,
        source_scope: 'synced_local',
        source_label: 'Local Synced',
        sync_source: 'sync_local_cache',
        sync_state: 'cloud_completed',
        report_html_key: 'violations/tag-local-sync-complete-001/report.html',
      },
      expectedScope: 'synced_local',
      expectedLabel: 'Local Synced',
    },
    {
      name: 'bad synced-local runtime patch with only local-origin hints repairs to local',
      existing: {
        report_id: 'tag-runtime-unsynced-local-001',
        status: 'pending',
        has_report: false,
        source_scope: 'synced_local',
        source_label: 'Local Synced',
        device_id: 'offline_local_cache',
        source: 'offline_local_cache',
      },
      patch: {
        status: 'generating',
        has_report: false,
      },
      expectedScope: 'local',
      expectedLabel: 'Local',
    },
    {
      name: 'local synced report stays local synced during cloud polling',
      existing: {
        report_id: 'tag-synced-runtime-001',
        status: 'pending',
        has_report: false,
        source_scope: 'synced_local',
        source_label: 'Local Synced',
        origin: 'local_synced',
        sync_source: 'sync_local_cache',
        report_html_key: 'violations/tag-synced-runtime-001/report.html',
      },
      patch: {
        status: 'generating',
        has_report: false,
        source_scope: 'cloud',
        source_label: 'Cloud',
      },
      expectedScope: 'synced_local',
      expectedLabel: 'Local Synced',
    },
    {
      name: 'shared report stays shared when local runtime patch arrives',
      existing: {
        report_id: 'tag-shared-runtime-001',
        status: 'pending',
        has_report: false,
        source_scope: 'shared',
        source_label: 'Shared',
      },
      patch: {
        status: 'generating',
        has_report: false,
        source_scope: 'local',
        source_label: 'Local',
      },
      expectedScope: 'shared',
      expectedLabel: 'Shared',
    },
  ];

  cases.forEach((entry) => {
    ReportsPage.violations = [entry.existing];
    const record = ReportsPage.upsertReportRuntimeState(
      entry.existing.report_id,
      entry.patch,
      entry.existing,
    );
    assertTag(record, entry.expectedScope, entry.expectedLabel, entry.name);
  });
}

function testLocalSyncEventMatrix() {
  const ReportsPage = loadReportsPage();
  const now = new Date().toISOString();

  ReportsPage.violations = [
    {
      report_id: 'tag-cloud-sync-event-001',
      timestamp: now,
      status: 'completed',
      has_report: true,
      source_scope: 'cloud',
      source_label: 'Cloud',
      device_id: 'webcam_0',
    },
    {
      report_id: 'tag-local-sync-event-001',
      timestamp: now,
      status: 'pending',
      has_report: false,
      source_scope: 'local',
      source_label: 'Local',
      device_id: 'offline_local_cache',
      source: 'offline_local_cache',
    }
  ];

  ReportsPage.renderReports = () => {};
  ReportsPage.notify = () => {};
  ReportsPage.loadReports = async () => {};

  ReportsPage.applyLocalSyncUpdate({
    success: true,
    queued_report_ids: ['tag-cloud-sync-event-001', 'tag-local-sync-event-001'],
    sync_source: 'sync_local_cache',
    sync_state: 'cloud_sync_queued',
  });

  let cloudRecord = ReportsPage.violations.find((item) => item.report_id === 'tag-cloud-sync-event-001');
  let localRecord = ReportsPage.violations.find((item) => item.report_id === 'tag-local-sync-event-001');

  assertTag(cloudRecord, 'cloud', 'Cloud', 'cloud report ignores queued local sync event');
  assertTag(localRecord, 'local', 'Local', 'local report stays local while sync is only queued');
  const queuedSyncInfo = ReportsPage.getSyncInfo(localRecord, 'local');
  assertEqual(queuedSyncInfo && queuedSyncInfo.label, 'Sync queued', 'queued local sync badge label');

  ReportsPage.applyLocalSyncUpdate({
    success: true,
    completed_report_ids: ['tag-cloud-sync-event-001', 'tag-local-sync-event-001'],
    sync_source: 'sync_local_cache',
    sync_state: 'cloud_completed',
  });

  cloudRecord = ReportsPage.violations.find((item) => item.report_id === 'tag-cloud-sync-event-001');
  localRecord = ReportsPage.violations.find((item) => item.report_id === 'tag-local-sync-event-001');

  assertTag(cloudRecord, 'cloud', 'Cloud', 'cloud report ignores completed local sync event');
  assertTag(localRecord, 'synced_local', 'Local Synced', 'local report accepts completed local sync event');
  const completedSyncInfo = ReportsPage.getSyncInfo(localRecord, 'synced_local');
  assertEqual(completedSyncInfo && completedSyncInfo.label, 'Synced', 'completed local sync badge label');
  assertEqual(localRecord.sync_state, 'cloud_completed', 'completed local sync event clears queued sync state');
}

function testReadyReportsAreNotDowngradedByLateSnapshots() {
  const ReportsPage = loadReportsPage();
  const now = new Date().toISOString();

  ReportsPage.violations = [{
    report_id: 'tag-ready-stability-001',
    timestamp: now,
    status: 'completed',
    has_report: true,
    has_cloud_report_artifact: true,
    report_html_key: 'violations/tag-ready-stability-001/report.html',
    source_scope: 'cloud',
    source_label: 'Cloud',
  }];
  ReportsPage.renderReports = () => {};

  const record = ReportsPage.upsertReportRuntimeState(
    'tag-ready-stability-001',
    {
      status: 'generating',
      has_report: false,
      source_scope: 'cloud',
      source_label: 'Cloud',
    },
    ReportsPage.violations[0],
  );

  assertEqual(record.status, 'completed', 'late generating snapshot must not downgrade ready status');
  assertEqual(record.has_report, true, 'late generating snapshot must preserve readable report evidence');
  assertEqual(ReportsPage.getStatusInfo(record).text, 'Ready', 'ready card must not flicker to generating/finalizing');
}

function testSyncedLocalBadgeWinsOverQueuedSyncState() {
  const ReportsPage = loadReportsPage();
  const record = {
    report_id: 'tag-synced-queued-badge-001',
    status: 'completed',
    has_report: true,
    source_scope: 'synced_local',
    source_label: 'Local Synced',
    sync_source: 'sync_local_cache',
    sync_state: 'cloud_sync_queued',
  };

  const syncInfo = ReportsPage.getSyncInfo(record, 'synced_local');
  assertEqual(syncInfo && syncInfo.label, 'Synced', 'Local Synced report must not keep Sync queued badge');
}

function testReportStatusProbeDoesNotForceFullListRefresh() {
  const ReportsPage = loadReportsPage();
  let loadCalls = 0;
  let prefetchCalls = 0;

  ReportsPage.violations = [{
    report_id: 'tag-status-probe-001',
    timestamp: new Date().toISOString(),
    status: 'pending',
    has_report: false,
    source_scope: 'cloud',
    source_label: 'Cloud',
    device_id: 'webcam_0',
  }];
  ReportsPage.loadReports = async () => { loadCalls += 1; };
  ReportsPage.prefetchReport = async () => { prefetchCalls += 1; };

  ReportsPage.applyReportStatusUpdate({
    report_id: 'tag-status-probe-001',
    status: 'completed',
    has_report: true,
    has_cloud_report_artifact: true,
    source_scope: 'cloud',
    source_label: 'Cloud',
  });

  const record = ReportsPage.violations.find((item) => item.report_id === 'tag-status-probe-001');
  assertEqual(record.status, 'completed', 'status probe marks report completed');
  assertEqual(record.has_report, true, 'status probe marks report ready');
  assertTag(record, 'cloud', 'Cloud', 'status probe preserves cloud tag');
  assertEqual(loadCalls, 0, 'status probe must not force full list refresh');
  assertEqual(prefetchCalls, 1, 'status probe warms only the completed report');
}

function testRealtimePayloadDoesNotForceFullListRefresh() {
  const ReportsPage = loadReportsPage();
  let loadCalls = 0;
  let prefetchCalls = 0;

  ReportsPage.violations = [];
  ReportsPage.loadReports = async () => { loadCalls += 1; };
  ReportsPage.prefetchReport = async () => { prefetchCalls += 1; };
  ReportsPage.renderReports = () => {};

  ReportsPage.applyRealtimePayload({
    reports: [{
      report_id: 'tag-realtime-status-001',
      timestamp: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      event_type: 'report_status',
      status: 'generating',
      has_report: false,
      source_scope: 'cloud',
      source_label: 'Cloud',
    }]
  });

  const record = ReportsPage.violations.find((item) => item.report_id === 'tag-realtime-status-001');
  assertEqual(record.status, 'generating', 'realtime payload updates processing status');
  assertTag(record, 'cloud', 'Cloud', 'realtime payload preserves cloud tag');
  assertEqual(loadCalls, 0, 'realtime payload must not force full list refresh');
  assertEqual(prefetchCalls, 0, 'generating realtime payload must not warm report HTML');
}

function main() {
  const tests = [
    testMergeMatrix,
    testRuntimePatchMatrix,
    testLocalSyncEventMatrix,
    testReadyReportsAreNotDowngradedByLateSnapshots,
    testSyncedLocalBadgeWinsOverQueuedSyncState,
    testReportStatusProbeDoesNotForceFullListRefresh,
    testRealtimePayloadDoesNotForceFullListRefresh,
  ];
  const failures = [];
  tests.forEach((testFn) => {
    try {
      testFn();
      console.log(`PASS: ${testFn.name}`);
    } catch (error) {
      failures.push(`${testFn.name}: ${error.message || error}`);
      console.error(`FAIL: ${testFn.name}: ${error.message || error}`);
    }
  });

  if (failures.length) {
    process.exit(1);
  }

  console.log('Report tag stability contract test passed');
}

main();
