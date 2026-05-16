/*
 * Contract test for manual report reprocess routing.
 *
 * Historical rows can carry stale Local / Local Synced source hints. From the
 * deployed cloud UI, a manual Reprocess Now click must not POST to localhost
 * and fail with "Failed to fetch"; it should route to the cloud backend and
 * let the backend repair the report state.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const CONFIG_JS = path.join(ROOT, 'frontend', 'js', 'config.js');
const API_JS = path.join(ROOT, 'frontend', 'js', 'api.js');
const REPORTS_JS = path.join(ROOT, 'frontend', 'js', 'pages', 'reports.js');

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, got ${actual}`);
  }
}

function createResponse(ok, status, payload) {
  return {
    ok,
    status,
    json: async () => payload,
  };
}

function loadApiContext(fetchImpl, windowOverrides = {}) {
  const windowObject = {
    PPE_API_URL: '',
    __PPE_CONFIG__: { API_BASE_URL: 'https://cloud-api.example.test' },
    location: {
      origin: 'https://cloud-frontend.example.test',
      hostname: 'cloud-frontend.example.test',
      protocol: 'https:',
    },
    ...windowOverrides,
  };
  const context = {
    console,
    fetch: fetchImpl,
    navigator: { onLine: true },
    window: windowObject,
    URL,
    setTimeout,
    clearTimeout,
  };
  vm.createContext(context);
  vm.runInContext(
    `${fs.readFileSync(CONFIG_JS, 'utf8')}\nglobalThis.API_CONFIG = API_CONFIG; globalThis.APP_STATE = APP_STATE;`,
    context,
    { filename: CONFIG_JS },
  );
  vm.runInContext(
    `${fs.readFileSync(API_JS, 'utf8')}\nglobalThis.API = API;`,
    context,
    { filename: API_JS },
  );
  return context;
}

function loadReportsPage() {
  const context = {
    console,
    document: { getElementById: () => null },
    setTimeout,
    clearTimeout,
  };
  vm.createContext(context);
  vm.runInContext(
    `${fs.readFileSync(REPORTS_JS, 'utf8')}\nglobalThis.ReportsPage = ReportsPage;`,
    context,
    { filename: REPORTS_JS },
  );
  return context.ReportsPage;
}

async function testCloudPageSkipsUnusableLocalReprocessRoute() {
  const calls = [];
  const context = loadApiContext(async (url, init) => {
    calls.push({ url, init });
    return createResponse(true, 200, {
      success: true,
      status: 'pending',
      source_scope: 'cloud',
      source_label: 'Cloud',
    });
  });

  const result = await context.API.generateReportNow('bad-local-001', {
    force: true,
    source: {
      report_id: 'bad-local-001',
      source_scope: 'local',
      source_label: 'Local',
      source: 'offline_local_cache',
      has_local_artifacts: true,
    },
  });

  assertEqual(calls.length, 1, 'deployed cloud page should not call local backend first');
  assertEqual(
    calls[0].url,
    'https://cloud-api.example.test/api/report/bad-local-001/generate-now',
    'manual reprocess cloud fallback URL',
  );
  const body = JSON.parse(calls[0].init.body);
  assertEqual(body.source_scope, 'cloud', 'manual cloud fallback should repair source scope');
  assertEqual(body.source_label, 'Cloud', 'manual cloud fallback should repair source label');
  assert(!Object.prototype.hasOwnProperty.call(body, 'sync_source'), 'manual cloud fallback should drop stale local sync source');
  assertEqual(result.routed_via_cloud_fallback, true, 'result should mark cloud fallback routing');
}

async function testLocalFetchFailureRetriesCloudRouteWhenCloudOverrideExists() {
  const calls = [];
  const context = loadApiContext(
    async (url, init) => {
      calls.push({ url, init });
      if (String(url).startsWith('http://127.0.0.1:5000')) {
        throw new TypeError('Failed to fetch');
      }
      return createResponse(true, 200, {
        success: true,
        status: 'pending',
        source_scope: 'cloud',
        source_label: 'Cloud',
      });
    },
    {
      PPE_API_URL: 'https://cloud-api.example.test',
      location: {
        origin: 'http://localhost:5000',
        hostname: 'localhost',
        protocol: 'http:',
      },
    },
  );
  context.API_CONFIG.LOCAL_BACKEND_URL = 'http://127.0.0.1:5000';

  const result = await context.API.generateReportNow('bad-local-002', {
    force: true,
    source: {
      report_id: 'bad-local-002',
      source_scope: 'local',
      source_label: 'Local',
      has_local_artifacts: true,
    },
  });

  assertEqual(calls.length, 2, 'local route failure should retry the cloud route');
  assertEqual(calls[0].url, 'http://127.0.0.1:5000/api/report/bad-local-002/generate-now', 'primary local route');
  assertEqual(calls[1].url, 'https://cloud-api.example.test/api/report/bad-local-002/generate-now', 'fallback cloud route');
  assertEqual(JSON.parse(calls[1].init.body).source_scope, 'cloud', 'fallback retry should use cloud scope');
  assertEqual(result.routed_via_cloud_fallback, true, 'fallback retry should be marked');
}

function testCloudFallbackPatchOverridesStaleLocalAnchor() {
  const ReportsPage = loadReportsPage();
  ReportsPage.violations = [{
    report_id: 'bad-local-003',
    status: 'completed',
    has_report: false,
    source_scope: 'local',
    source_label: 'Local',
    source: 'offline_local_cache',
  }];

  const record = ReportsPage.upsertReportRuntimeState('bad-local-003', {
    status: 'pending',
    has_report: false,
    source_scope: 'cloud',
    source_label: 'Cloud',
    source_reason: 'manual_cloud_reprocess_fallback',
    routed_via_cloud_fallback: true,
  }, ReportsPage.violations[0]);

  assertEqual(record.source_scope, 'cloud', 'cloud fallback patch source scope');
  assertEqual(record.source_label, 'Cloud', 'cloud fallback patch source label');
}

async function main() {
  const tests = [
    testCloudPageSkipsUnusableLocalReprocessRoute,
    testLocalFetchFailureRetriesCloudRouteWhenCloudOverrideExists,
    testCloudFallbackPatchOverridesStaleLocalAnchor,
  ];
  const failures = [];
  for (const testFn of tests) {
    try {
      await testFn();
      console.log(`PASS: ${testFn.name}`);
    } catch (error) {
      failures.push(`${testFn.name}: ${error.message || error}`);
      console.error(`FAIL: ${testFn.name}: ${error.message || error}`);
    }
  }

  if (failures.length) {
    process.exit(1);
  }
  console.log('Report reprocess routing contract test passed');
}

main();
