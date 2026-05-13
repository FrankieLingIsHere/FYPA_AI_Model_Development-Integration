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
      name: 'local report becomes local synced only after explicit reconnect sync evidence appears',
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
    report_ids: ['tag-cloud-sync-event-001', 'tag-local-sync-event-001'],
    sync_source: 'sync_local_cache',
    sync_state: 'cloud_sync_queued',
  });

  const cloudRecord = ReportsPage.violations.find((item) => item.report_id === 'tag-cloud-sync-event-001');
  const localRecord = ReportsPage.violations.find((item) => item.report_id === 'tag-local-sync-event-001');

  assertTag(cloudRecord, 'cloud', 'Cloud', 'cloud report ignores local sync event');
  assertTag(localRecord, 'synced_local', 'Local Synced', 'local report accepts local sync event');
}

function main() {
  const tests = [
    testMergeMatrix,
    testRuntimePatchMatrix,
    testLocalSyncEventMatrix,
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
