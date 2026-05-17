/*
 * Contract test for cross-mode report cache stability.
 *
 * The Reports page relies on JSON list caches for cloud/synced rows and blob
 * draft caches for local artifacts. Runtime transitions must not drop the JSON
 * bridge, or local mode appears to contain only blob-backed artifacts until a
 * hard refresh.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const CONFIG_JS = path.join(ROOT, 'frontend', 'js', 'config.js');
const API_JS = path.join(ROOT, 'frontend', 'js', 'api.js');

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

function createLocalStorageMock() {
  const storage = new Map();
  return {
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

function loadApiContext() {
  const localStorage = createLocalStorageMock();
  const windowObject = {
    PPE_API_URL: '',
    __PPE_CONFIG__: { API_BASE_URL: 'https://cloud-api.example.test' },
    location: {
      origin: 'https://cloud-frontend.example.test',
      hostname: 'cloud-frontend.example.test',
      protocol: 'https:',
    },
    dispatchEvent: () => {},
  };
  const context = {
    console,
    fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
    navigator: { onLine: true },
    window: windowObject,
    localStorage,
    URL,
    setTimeout,
    clearTimeout,
    CustomEvent: function CustomEvent(type, init) {
      this.type = type;
      this.detail = init && init.detail;
    },
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

async function testRuntimeTransitionPreservesReportListCaches() {
  const { API } = loadApiContext();
  const cloudRow = {
    report_id: 'cache-cloud-001',
    status: 'completed',
    has_report: true,
    report_html_key: 'violations/cache-cloud-001/report.html',
    source_scope: 'cloud',
    source_label: 'Cloud',
  };
  const pendingRow = {
    report_id: 'cache-pending-001',
    status: 'generating',
    source_scope: 'cloud',
    source_label: 'Cloud',
  };

  await API.writeJsonCache('stats:summary', { total: 2 });
  await API.writeJsonCache('violations:limit:1000', [cloudRow]);
  await API.writeJsonCache('reports:pending', [pendingRow]);

  await API.clearRuntimeTransitionCaches('contract-test');

  const stats = await API.readJsonCache('stats:summary');
  const violations = await API.readJsonCache('violations:limit:1000');
  const pending = await API.readJsonCache('reports:pending');

  assertEqual(stats, null, 'volatile stats cache should be cleared');
  assert(Array.isArray(violations && violations.data), 'violations list cache should survive transition');
  assert(Array.isArray(pending && pending.data), 'pending list cache should survive transition');
  assertEqual(violations.data[0].report_id, 'cache-cloud-001', 'cloud row retained across transition');
  assertEqual(pending.data[0].report_id, 'cache-pending-001', 'pending row retained across transition');
}

function testSyncedLocalMergeSurvivesCloudPendingSnapshot() {
  const { API } = loadApiContext();
  const synced = {
    report_id: 'cache-synced-001',
    status: 'completed',
    has_report: true,
    has_cloud_report_artifact: true,
    report_html_key: 'violations/cache-synced-001/report.html',
    source_scope: 'synced_local',
    source_label: 'Local Synced',
    origin: 'local_synced',
    sync_source: 'sync_local_cache',
  };
  const cloudPending = {
    report_id: 'cache-synced-001',
    status: 'generating',
    has_report: false,
    source_scope: 'cloud',
    source_label: 'Cloud',
  };

  const cloudAfterSynced = API._mergeOptimistically([synced], [cloudPending], 10)[0];
  const syncedAfterCloud = API._mergeOptimistically([cloudPending], [synced], 10)[0];

  assertEqual(cloudAfterSynced.source_scope, 'synced_local', 'cloud pending snapshot must not demote synced local cache');
  assertEqual(cloudAfterSynced.source_label, 'Local Synced', 'synced local label after cloud pending snapshot');
  assertEqual(syncedAfterCloud.source_scope, 'synced_local', 'synced local draft must win over stale cloud pending row');
  assertEqual(syncedAfterCloud.source_label, 'Local Synced', 'synced local label after stale cloud row');
}

function testCloudCompletedLocalDraftNormalizesAsSyncedLocal() {
  const { API } = loadApiContext();
  const draft = API.normalizeLocalReportDraft({
    report_id: 'cache-local-draft-001',
    status: 'completed',
    has_report: true,
    has_cloud_report_artifact: true,
    report_html_key: 'violations/cache-local-draft-001/report.html',
    source_scope: 'local',
    source_label: 'Local',
    sync_state: 'cloud_completed',
  });

  assertEqual(draft.source_scope, 'synced_local', 'cloud_completed local draft should normalize to synced local');
  assertEqual(draft.source_label, 'Local Synced', 'cloud_completed local draft label');
}

async function main() {
  const tests = [
    testRuntimeTransitionPreservesReportListCaches,
    testSyncedLocalMergeSurvivesCloudPendingSnapshot,
    testCloudCompletedLocalDraftNormalizesAsSyncedLocal,
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

  console.log('Report cache transition contract test passed');
}

main();
