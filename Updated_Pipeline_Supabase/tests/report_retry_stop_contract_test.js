// Readability: Test setup: document the contract this file protects.
/*
 * Contract tests for report retry stop behavior.
 *
 * Failed report generation must stay terminal until a new manual reprocess is
 * accepted by the backend. Stale optimistic "pending" cache rows and 503
 * worker failures must not keep the UI/worker loops alive.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const REPORTS_JS = path.join(ROOT, 'frontend', 'js', 'pages', 'reports.js');

// Section: handle the assert workflow.
function assert(condition, message) {
  // Choose the correct browser state branch before continuing.
  if (!condition) {
    throw new Error(message);
  }
}

// Section: handle the assert equal workflow.
function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, got ${actual}`);
  }
}

// Section: handle the load reports page workflow.
function loadReportsPage(overrides = {}) {
  const context = {
    console,
    document: {
      getElementById: () => null,
    },
    window: {
      location: {
        origin: 'https://cloud-frontend.example.test',
        hostname: 'cloud-frontend.example.test',
        protocol: 'https:',
      },
      addEventListener: () => {},
      dispatchEvent: () => true,
    },
    CustomEvent: function CustomEvent(type, init = {}) {
      // Return the prepared value to the caller.
      return { type, detail: init.detail || {} };
    },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    ...overrides,
  };
  vm.createContext(context);
  vm.runInContext(
    `${fs.readFileSync(REPORTS_JS, 'utf8')}\nglobalThis.ReportsPage = ReportsPage;`,
    context,
    { filename: REPORTS_JS },
  );
  // Return the prepared value to the caller.
  return context.ReportsPage;
}

// Section: handle the test stale pending cache does not revive failed report workflow.
function testStalePendingCacheDoesNotReviveFailedReport() {
  const ReportsPage = loadReportsPage();
  const merged = ReportsPage.mergePendingReports(
    [{
      report_id: 'failed-upload-001',
      status: 'failed',
      has_report: false,
      error_message: 'Report generation failed: upstream returned 503',
      source_scope: 'cloud',
      source_label: 'Cloud',
    }],
    [{
      report_id: 'failed-upload-001',
      status: 'pending',
      has_report: false,
      report_queued: true,
      source_scope: 'cloud',
      source_label: 'Cloud',
      updated_at: new Date().toISOString(),
    }],
  );

  const row = merged.find((item) => item.report_id === 'failed-upload-001');
  assert(row, 'failed row should still be present');
  assertEqual(row.status, 'failed', 'stale pending cache must not override failed status');
}

// Section: handle the test worker503 generate now stops as failed without polling workflow.
async function testWorker503GenerateNowStopsAsFailedWithoutPolling() {
  const calls = {
    cooldowns: 0,
    polls: 0,
    cacheUpserts: [],
    buttonEnabled: null,
    statusText: '',
    notifications: [],
  };
  const ReportsPage = loadReportsPage({
    API: {
      generateReportNow: async () => ({
        success: false,
        http_status: 503,
        worker_running: false,
        error: 'Queue worker is not running',
      }),
      upsertPendingReportCache: async (record) => {
        calls.cacheUpserts.push(record);
        // Return the prepared value to the caller.
        return record;
      },
    },
  });

  ReportsPage.violations = [{
    report_id: 'failed-upload-503',
    status: 'failed',
    has_report: false,
    source_scope: 'cloud',
    source_label: 'Cloud',
  }];
  ReportsPage.startModalPolling = () => { calls.polls += 1; };
  ReportsPage.startModalCooldown = () => { calls.cooldowns += 1; };
  ReportsPage.setModalProcessButtonEnabled = (enabled) => { calls.buttonEnabled = enabled; };
  ReportsPage.setModalStatusText = (message) => { calls.statusText = message; };
  ReportsPage.notify = (message, level) => { calls.notifications.push({ message, level }); };

  await ReportsPage.generateNow('failed-upload-503', {
    force: true,
    source: ReportsPage.violations[0],
  });

  const row = ReportsPage.violations.find((item) => item.report_id === 'failed-upload-503');
  assert(row, 'report row should still be present');
  assertEqual(row.status, 'failed', '503 worker failure should leave the report failed');
  assertEqual(row.terminal_generation_failure, true, '503 worker failure should be marked terminal in runtime state');
  assertEqual(calls.polls, 0, '503 worker failure must not start progress polling');
  assertEqual(calls.cooldowns, 0, '503 worker failure must not start retry cooldown');
  assertEqual(calls.cacheUpserts.length, 1, '503 worker failure should update optimistic caches as failed');
  assertEqual(calls.cacheUpserts[0].status, 'failed', '503 cache upsert should be terminal failed');
  assertEqual(calls.buttonEnabled, false, '503 worker failure should disable immediate re-clicking');
  assert(calls.statusText.includes('Queue worker is not running'), 'modal should show worker failure');
  assert(calls.notifications.some((item) => item.level === 'error'), 'error notification should be emitted');
}

// Section: handle the main workflow.
async function main() {
  const tests = [
    testStalePendingCacheDoesNotReviveFailedReport,
    testWorker503GenerateNowStopsAsFailedWithoutPolling,
  ];
  const failures = [];
  // Walk through the active items and update each one consistently.
  for (const testFn of tests) {
    // Keep this browser operation recoverable if it fails.
    try {
      await testFn();
      console.log(`PASS: ${testFn.name}`);
    } catch (error) {
      failures.push(`${testFn.name}: ${error.message || error}`);
      console.error(`FAIL: ${testFn.name}: ${error.message || error}`);
    }
  }

  // Choose the correct browser state branch before continuing.
  if (failures.length) {
    process.exit(1);
  }
  console.log('Report retry stop contract test passed');
}

main();
