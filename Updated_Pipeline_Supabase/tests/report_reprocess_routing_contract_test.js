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

function createLocalStorageMock() {
  const storage = new Map();
  return {
    storage,
    get length() {
      return storage.size;
    },
    key(index) {
      return Array.from(storage.keys())[index] || null;
    },
    getItem(key) {
      const normalized = String(key);
      return storage.has(normalized) ? storage.get(normalized) : null;
    },
    setItem(key, value) {
      storage.set(String(key), String(value));
    },
    removeItem(key) {
      storage.delete(String(key));
    },
    clear() {
      storage.clear();
    },
  };
}

function loadApiContext(fetchImpl, windowOverrides = {}) {
  const localStorage = createLocalStorageMock();
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
    localStorage,
    __localStorageMap: localStorage.storage,
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

async function testCloudFallbackRepairsStaleLocalReportCaches() {
  const context = loadApiContext(async () => createResponse(true, 200, {
    success: true,
    status: 'pending',
    source_scope: 'cloud',
    source_label: 'Cloud',
    has_report: false,
  }));
  const reportId = 'bad-local-004';
  const staleLocalRow = {
    report_id: reportId,
    status: 'processing',
    source_scope: 'local',
    source_label: 'Local',
    source: 'offline_local_cache',
    has_local_artifacts: true,
    has_local_report: true,
    local_image_url: 'blob:stale-original',
    local_report_url: 'blob:stale-report',
  };

  await context.API.writeLocalReportDrafts([staleLocalRow]);
  await context.API.writeJsonCache('reports:pending', [staleLocalRow]);
  await context.API.writeJsonCache('violations:limit:1000', [staleLocalRow]);
  await context.API.writeJsonCache(`report-status:https://cloud-api.example.test:${reportId}`, staleLocalRow);
  await context.API.writeJsonCache(`violation:https://cloud-api.example.test:${reportId}`, staleLocalRow);

  const result = await context.API.generateReportNow(reportId, {
    force: true,
    source: staleLocalRow,
  });

  assertEqual(result.success, true, 'cloud fallback result should succeed');
  assertEqual(result.routed_via_cloud_fallback, true, 'cloud cache repair should mark fallback routing');

  const drafts = await context.API.readLocalReportDrafts();
  assert(!drafts.some((item) => item.report_id === reportId), 'stale local draft should be removed');

  const pending = await context.API.readJsonCache('reports:pending');
  const pendingRow = pending.data.find((item) => item.report_id === reportId);
  assertEqual(pendingRow.source_scope, 'cloud', 'pending cache source scope should be repaired');
  assertEqual(pendingRow.source_label, 'Cloud', 'pending cache source label should be repaired');
  assertEqual(pendingRow.source, 'manual_cloud_reprocess', 'pending cache local source marker should be replaced');
  assertEqual(pendingRow.has_local_artifacts, false, 'pending cache local artifact flag should be cleared');
  assert(!Object.prototype.hasOwnProperty.call(pendingRow, 'local_report_url'), 'pending cache local report URL should be removed');

  const violations = await context.API.readJsonCache('violations:limit:1000');
  const violationRow = violations.data.find((item) => item.report_id === reportId);
  assertEqual(violationRow.source_scope, 'cloud', 'violations cache source scope should be repaired');
  assertEqual(violationRow.source_label, 'Cloud', 'violations cache source label should be repaired');

  const staleStatus = await context.API.readJsonCache(`report-status:https://cloud-api.example.test:${reportId}`);
  const staleDetail = await context.API.readJsonCache(`violation:https://cloud-api.example.test:${reportId}`);
  assertEqual(staleStatus, null, 'stale per-report status cache should be removed');
  assertEqual(staleDetail, null, 'stale per-report detail cache should be removed');
}

function testCloudInferenceResultDoesNotCreateBrowserLocalDraft() {
  const cloudContext = loadApiContext(async () => createResponse(true, 200, {}));
  const cloudResult = {
    success: true,
    report_queued: true,
    report_id: 'cloud-queued-001',
    source_scope: 'cloud',
    source_label: 'Cloud',
    local_draft_required: false,
  };
  assertEqual(
    cloudContext.API.shouldPersistLocalReportDraft(cloudResult),
    false,
    'cloud queued reports must not be cached as browser local drafts',
  );

  const localResult = {
    success: true,
    report_queued: true,
    report_id: 'local-queued-001',
    source_scope: 'local',
    source_label: 'Local',
    local_draft_required: true,
  };
  assertEqual(
    cloudContext.API.shouldPersistLocalReportDraft(localResult),
    true,
    'explicit local queued reports should keep the browser local draft fallback',
  );

  const syncedLocalResult = {
    success: true,
    report_queued: true,
    report_id: 'synced-local-queued-001',
    source_scope: 'synced_local',
    source_label: 'Local Synced',
    sync_source: 'sync_local_cache',
  };
  assertEqual(
    cloudContext.API.shouldPersistLocalReportDraft(syncedLocalResult),
    false,
    'local-synced rows already handed to cloud storage should not be re-cached as unsynced local drafts',
  );

  const unknownCloudResult = {
    success: true,
    report_queued: true,
    report_id: 'cloud-queued-unknown-scope',
  };
  assertEqual(
    cloudContext.API.shouldPersistLocalReportDraft(unknownCloudResult),
    false,
    'deployed cloud pages should not infer local drafts when scope is absent',
  );

  const localPageContext = loadApiContext(
    async () => createResponse(true, 200, {}),
    {
      location: {
        origin: 'http://localhost:5000',
        hostname: 'localhost',
        protocol: 'http:',
      },
    },
  );
  localPageContext.API_CONFIG.BASE_URL = '';
  assertEqual(
    localPageContext.API.shouldPersistLocalReportDraft(unknownCloudResult),
    true,
    'same-origin localhost can keep local report drafts when the backend has not sent a scope yet',
  );
}

async function main() {
  const tests = [
    testCloudPageSkipsUnusableLocalReprocessRoute,
    testLocalFetchFailureRetriesCloudRouteWhenCloudOverrideExists,
    testCloudFallbackPatchOverridesStaleLocalAnchor,
    testCloudFallbackRepairsStaleLocalReportCaches,
    testCloudInferenceResultDoesNotCreateBrowserLocalDraft,
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
