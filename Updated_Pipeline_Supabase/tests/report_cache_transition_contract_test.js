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

function testMixedTagReconnectSnapshotsDoNotCollapseCards() {
  const { API } = loadApiContext();
  const cachedRows = [
    {
      report_id: 'cache-mixed-cloud-001',
      timestamp: '2026-05-17T08:00:00Z',
      status: 'completed',
      has_report: true,
      has_cloud_report_artifact: true,
      report_html_key: 'violations/cache-mixed-cloud-001/report.html',
      source_scope: 'cloud',
      source_label: 'Cloud',
    },
    {
      report_id: 'cache-mixed-local-001',
      timestamp: '2026-05-17T08:01:00Z',
      status: 'completed',
      has_report: true,
      has_local_report: true,
      local_report_url: 'blob:local-report',
      device_id: 'offline_local_cache',
      source: 'offline_local_cache',
      source_scope: 'local',
      source_label: 'Local',
    },
    {
      report_id: 'cache-mixed-synced-001',
      timestamp: '2026-05-17T08:02:00Z',
      status: 'completed',
      has_report: true,
      has_cloud_report_artifact: true,
      report_html_key: 'violations/cache-mixed-synced-001/report.html',
      origin: 'local_synced',
      sync_source: 'sync_local_cache',
      source_scope: 'synced_local',
      source_label: 'Local Synced',
    },
    {
      report_id: 'cache-mixed-shared-001',
      timestamp: '2026-05-17T08:03:00Z',
      status: 'completed',
      has_report: true,
      report_html_key: 'violations/cache-mixed-shared-001/report.html',
      source_scope: 'shared',
      source_label: 'Shared',
    },
  ];
  const staleCloudSnapshots = cachedRows.map((row) => ({
    report_id: row.report_id,
    timestamp: row.timestamp,
    status: 'generating',
    has_report: false,
    source_scope: 'cloud',
    source_label: 'Cloud',
  }));

  const merged = API._mergeOptimistically(cachedRows, staleCloudSnapshots, 20);
  const byId = new Map(merged.map((row) => [row.report_id, row]));

  assertEqual(byId.get('cache-mixed-cloud-001').source_scope, 'cloud', 'cloud card remains cloud');
  assertEqual(byId.get('cache-mixed-local-001').source_scope, 'local', 'local card must not collapse to cloud');
  assertEqual(byId.get('cache-mixed-local-001').source_label, 'Local', 'local card label after reconnect snapshot');
  assertEqual(byId.get('cache-mixed-synced-001').source_scope, 'synced_local', 'synced local card must not collapse to cloud');
  assertEqual(byId.get('cache-mixed-synced-001').source_label, 'Local Synced', 'synced local card label after reconnect snapshot');
  assertEqual(byId.get('cache-mixed-shared-001').source_scope, 'shared', 'shared card must not collapse to cloud');
  assertEqual(byId.get('cache-mixed-shared-001').source_label, 'Shared', 'shared card label after reconnect snapshot');
  cachedRows.forEach((row) => {
    assertEqual(byId.get(row.report_id).has_report, true, `${row.report_id} keeps readable artifact evidence`);
  });
}

function testLocalModeMirrorSnapshotsDoNotPoisonCachedTags() {
  const { API } = loadApiContext();
  const cachedRows = [
    {
      report_id: 'cache-mirror-cloud-001',
      timestamp: '2026-05-17T09:00:00Z',
      status: 'completed',
      has_report: true,
      has_cloud_report_artifact: true,
      report_html_key: 'violations/cache-mirror-cloud-001/report.html',
      source_scope: 'cloud',
      source_label: 'Cloud',
    },
    {
      report_id: 'cache-mirror-synced-001',
      timestamp: '2026-05-17T09:01:00Z',
      status: 'completed',
      has_report: true,
      has_cloud_report_artifact: true,
      report_html_key: 'violations/cache-mirror-synced-001/report.html',
      source_scope: 'synced_local',
      source_label: 'Local Synced',
      origin: 'local_synced',
      sync_source: 'sync_local_cache',
    },
    {
      report_id: 'cache-mirror-shared-001',
      timestamp: '2026-05-17T09:02:00Z',
      status: 'completed',
      has_report: true,
      report_html_key: 'violations/cache-mirror-shared-001/report.html',
      source_scope: 'shared',
      source_label: 'Shared',
    },
    {
      report_id: 'cache-mirror-local-001',
      timestamp: '2026-05-17T09:03:00Z',
      status: 'completed',
      has_report: true,
      has_local_report: true,
      local_report_url: 'blob:local-report',
      device_id: 'offline_local_cache',
      source: 'offline_local_cache',
      source_scope: 'local',
      source_label: 'Local',
    },
  ];
  const localMirrorRows = cachedRows.map((row) => ({
    report_id: row.report_id,
    timestamp: row.timestamp,
    status: 'completed',
    has_report: true,
    has_local_report: true,
    source_scope: 'local',
    source_label: 'Local',
  }));

  const merged = API._mergeOptimistically(cachedRows, localMirrorRows, 20);
  const byId = new Map(merged.map((row) => [row.report_id, row]));

  assertEqual(byId.get('cache-mirror-cloud-001').source_scope, 'cloud', 'local filesystem mirror must not relabel cloud cache');
  assertEqual(byId.get('cache-mirror-cloud-001').source_label, 'Cloud', 'cloud label after local mirror');
  assertEqual(byId.get('cache-mirror-synced-001').source_scope, 'synced_local', 'local filesystem mirror must not relabel synced cache');
  assertEqual(byId.get('cache-mirror-synced-001').source_label, 'Local Synced', 'synced label after local mirror');
  assertEqual(byId.get('cache-mirror-shared-001').source_scope, 'shared', 'local filesystem mirror must not relabel shared cache');
  assertEqual(byId.get('cache-mirror-shared-001').source_label, 'Shared', 'shared label after local mirror');
  assertEqual(byId.get('cache-mirror-local-001').source_scope, 'local', 'real local artifact remains local');
  assertEqual(byId.get('cache-mirror-local-001').source_label, 'Local', 'real local label after local mirror');
}

async function main() {
  const tests = [
    testRuntimeTransitionPreservesReportListCaches,
    testSyncedLocalMergeSurvivesCloudPendingSnapshot,
    testCloudCompletedLocalDraftNormalizesAsSyncedLocal,
    testMixedTagReconnectSnapshotsDoNotCollapseCards,
    testLocalModeMirrorSnapshotsDoNotPoisonCachedTags,
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
