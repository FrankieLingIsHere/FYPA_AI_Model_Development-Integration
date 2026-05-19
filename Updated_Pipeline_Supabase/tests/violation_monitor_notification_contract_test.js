/*
 * Contract test for violation/report lifecycle toast ordering.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const VIOLATION_MONITOR_JS = path.join(ROOT, 'frontend', 'js', 'violation-monitor.js');

function loadViolationMonitor(extraContext = {}) {
  const code = `${fs.readFileSync(VIOLATION_MONITOR_JS, 'utf8')}\nglobalThis.ViolationMonitor = ViolationMonitor;`;
  const context = {
    console,
    setTimeout: () => 0,
    clearTimeout: () => {},
    localStorage: {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    },
    document: {
      readyState: 'loading',
      hidden: false,
      addEventListener: () => {},
      removeEventListener: () => {},
      getElementById: () => null,
    },
    window: {
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => {},
      open: () => {},
      AudioAlert: null,
    },
    Router: {
      navigate: () => {},
    },
    API: {
      getReportUrl: (reportId) => `/report/${reportId}`,
    },
    API_CONFIG: {
      BASE_URL: '',
    },
    CustomEvent: function CustomEvent(type, params = {}) {
      this.type = type;
      this.detail = params.detail;
    },
    ...extraContext,
  };
  vm.createContext(context);
  vm.runInContext(code, context, { filename: VIOLATION_MONITOR_JS });
  return context.ViolationMonitor;
}

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, got ${actual}`);
  }
}

function testReadyBackfillsGeneratingToast() {
  const calls = [];
  const reportId = 'toast-fast-ready-001';
  const ViolationMonitor = loadViolationMonitor({
    NotificationManager: {
      reportGenerating: (rid, options = {}) => calls.push({
        type: 'generating',
        reportId: rid,
        title: options.title,
        actionText: options.action && options.action.text,
      }),
      reportReady: (rid, options = {}) => calls.push({
        type: 'ready',
        reportId: rid,
        title: options.title,
        actionText: options.action && options.action.text,
      }),
      show: (message, type) => calls.push({ type, message }),
    },
  });

  ViolationMonitor.notifiedEvents = new Set();
  ViolationMonitor._notifyReportReady({
    report_id: reportId,
    timestamp: new Date().toISOString(),
    status: 'completed',
    has_report: true,
  });

  assertEqual(
    calls.map((item) => item.type).join(','),
    'generating,ready',
    'ready notification should backfill missing generating toast first',
  );
  assertEqual(ViolationMonitor.notifiedEvents.has(`generating_${reportId}`), true, 'generating event marked notified');
  assertEqual(ViolationMonitor.notifiedEvents.has(`ready_${reportId}`), true, 'ready event marked notified');
}

function testReadyDoesNotDuplicateExistingGeneratingToast() {
  const calls = [];
  const reportId = 'toast-existing-generating-001';
  const ViolationMonitor = loadViolationMonitor({
    NotificationManager: {
      reportGenerating: (rid) => calls.push({ type: 'generating', reportId: rid }),
      reportReady: (rid) => calls.push({ type: 'ready', reportId: rid }),
      show: (message, type) => calls.push({ type, message }),
    },
  });

  ViolationMonitor.notifiedEvents = new Set([`generating_${reportId}`]);
  ViolationMonitor._notifyReportReady({
    report_id: reportId,
    timestamp: new Date().toISOString(),
    status: 'completed',
    has_report: true,
  });

  assertEqual(
    calls.map((item) => item.type).join(','),
    'ready',
    'ready notification should not duplicate an existing generating toast',
  );
}

function main() {
  const tests = [
    testReadyBackfillsGeneratingToast,
    testReadyDoesNotDuplicateExistingGeneratingToast,
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

  console.log('Violation monitor notification contract test passed');
}

main();
