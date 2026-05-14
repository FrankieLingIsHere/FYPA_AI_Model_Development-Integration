const fs = require('fs');
const http = require('http');
const path = require('path');
const vm = require('vm');

const port = Number(process.env.MIRA_BOTIUM_PORT || 47823);
const repoRoot = path.resolve(__dirname, '..', '..', '..');
const assistantPath = path.join(repoRoot, 'Updated_Pipeline_Supabase', 'frontend', 'js', 'assistant.js');

function toIsoAtDayOffset(offsetDays, hour = 9) {
  const date = new Date();
  date.setHours(hour, 0, 0, 0);
  date.setDate(date.getDate() + offsetDays);
  return date.toISOString();
}

const fixtureRows = [
  {
    report_id: 'BOTIUM-YDAY-HARDHAT',
    timestamp: toIsoAtDayOffset(-1, 8),
    status: 'completed',
    severity: 'high',
    device_id: 'CAM-001',
    violation_count: 1,
    missing_ppe: ['NO-Hardhat'],
    source_scope: 'cloud',
    source_label: 'Cloud',
    violation_summary: 'Worker missing hardhat at front gate'
  },
  {
    report_id: 'BOTIUM-TODAY-VEST',
    timestamp: toIsoAtDayOffset(0, 10),
    status: 'pending',
    severity: 'medium',
    device_id: 'CAM-002',
    violation_count: 1,
    missing_ppe: ['NO-Safety Vest'],
    source_scope: 'local',
    source_label: 'Local',
    violation_summary: 'Worker missing safety vest at warehouse'
  },
  {
    report_id: 'BOTIUM-WEEK-GLOVES',
    timestamp: toIsoAtDayOffset(-3, 14),
    status: 'completed',
    severity: 'low',
    device_id: 'CAM-003',
    violation_count: 1,
    missing_ppe: ['NO-Gloves'],
    source_scope: 'synced_local',
    source_label: 'Local Synced',
    violation_summary: 'Worker missing gloves near storage'
  }
];

function buildStats(rows = fixtureRows) {
  const severity = { high: 0, medium: 0, low: 0 };
  const breakdown = {};
  rows.forEach((row) => {
    const level = String(row.severity || '').toLowerCase();
    if (severity[level] !== undefined) severity[level] += 1;
    (row.missing_ppe || []).forEach((label) => {
      breakdown[label] = (breakdown[label] || 0) + 1;
    });
  });
  return {
    total: rows.length,
    today: rows.filter((row) => new Date(row.timestamp).toDateString() === new Date().toDateString()).length,
    reportsGenerated: rows.filter((row) => String(row.status || '').toLowerCase() === 'completed').length,
    severity,
    breakdown
  };
}

function createSandbox() {
  const localStore = new Map();
  const sandbox = {
    console,
    setTimeout,
    clearTimeout,
    APP_STATE: { currentPage: 'home' },
    window: {
      setTimeout,
      clearTimeout,
      dispatchEvent() {},
      addEventListener() {},
      removeEventListener() {},
      CASM_TUTORIAL_FLOWS: {
        cloud: [{ title: 'Cloud start', summary: 'Open Live Monitor and start a cloud run.', bullets: ['Use camera stream.'] }],
        local: [{ title: 'Local start', summary: 'Run the local readiness check first.', bullets: ['Use Settings Checkup.'] }]
      }
    },
    document: {
      addEventListener() {},
      querySelectorAll() { return []; },
      querySelector() { return null; }
    },
    localStorage: {
      getItem(key) { return localStore.has(key) ? localStore.get(key) : null; },
      setItem(key, value) { localStore.set(key, String(value)); },
      removeItem(key) { localStore.delete(key); }
    },
    API: {
      async getStats() {
        return buildStats();
      },
      async getViolations() {
        return fixtureRows;
      }
    },
    AnalyticsPage: {
      buildStatsFromViolations(rows) {
        return buildStats(Array.isArray(rows) ? rows : []);
      },
      normalizeStats(stats, rows) {
        const sourceRows = Array.isArray(rows) ? rows : fixtureRows;
        return {
          ...buildStats(sourceRows),
          ...(stats || {})
        };
      },
      buildDerivedMetrics(stats, rows) {
        const sourceRows = Array.isArray(rows) ? rows : fixtureRows;
        const completed = sourceRows.filter((row) => String(row.status || '').toLowerCase() === 'completed').length;
        const total = Math.max(1, sourceRows.length);
        const high = Number(stats?.severity?.high || 0);
        return {
          readyRate: Math.round((completed / total) * 100),
          pending: Math.max(0, sourceRows.length - completed),
          highShare: Math.round((high / total) * 100),
          peakWindow: '08:00-12:00',
          peakWindowCount: sourceRows.length,
          lastViolationDisplay: sourceRows[0] ? 'recent fixture row' : 'none',
          topType: Object.keys(stats?.breakdown || {})[0] || 'NO-Hardhat',
          dominantSource: 'cloud',
          dominantSourceCount: sourceRows.filter((row) => row.source_scope === 'cloud').length,
          sourceMix: { cloud: 1, local: 1, synced_local: 1 },
          localOriginCount: sourceRows.filter((row) => row.source_scope !== 'cloud').length,
          cloudOriginCount: sourceRows.filter((row) => row.source_scope === 'cloud').length,
          dailyAverage: sourceRows.length / 7
        };
      }
    }
  };
  vm.createContext(sandbox);
  const code = `${fs.readFileSync(assistantPath, 'utf8')}\n;globalThis.CASMAssistant = CASMAssistant;`;
  vm.runInContext(code, sandbox, { filename: assistantPath });
  return sandbox;
}

function messageToText(message) {
  const parts = [];
  if (message.text) parts.push(message.text);
  (message.bullets || []).forEach((item) => parts.push(item));
  (message.metrics || []).forEach((metric) => {
    parts.push(`${metric.label}: ${metric.value} ${metric.note || ''}`.trim());
  });
  (message.docs || []).forEach((doc) => parts.push(`${doc.title || ''} ${doc.snippet || ''}`.trim()));
  if (message.tutorial) {
    parts.push(`${message.tutorial.title || ''} ${message.tutorial.summary || ''}`.trim());
  }
  if (Array.isArray(message.actions) && message.actions.length) {
    parts.push(`Actions: ${message.actions.map((action) => action.label || action.type || 'action').join(', ')}`);
  }
  return parts.filter(Boolean).join(' | ');
}

async function askMira(text) {
  const sandbox = createSandbox();
  const assistant = sandbox.CASMAssistant;
  const replies = [];
  const session = {
    id: 'botium-session',
    title: 'Botium session',
    context: {},
    messages: []
  };

  assistant.docsIndex = assistant.buildDocsIndex();
  assistant.getActiveSession = () => session;
  assistant.pushMessage = (message) => {
    replies.push(message);
    session.messages.push(message);
  };
  assistant.performAction = async () => {};
  assistant.saveState = () => {};
  assistant.renderMessages = () => {};
  assistant.renderPromptDeck = () => {};
  assistant.renderSessionRail = () => {};
  assistant.refreshSessionUi = () => {};
  assistant.downloadCsv = (filename) => {
    session.context.lastDownloadedCsv = filename;
  };

  await assistant.answer(String(text || ''));
  return {
    text: replies.map(messageToText).join(' | ') || 'NO_RESPONSE',
    context: session.context
  };
}

const server = http.createServer((req, res) => {
  if (req.method === 'GET' && req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ok: true }));
    return;
  }

  if (req.method !== 'POST' || req.url !== '/message') {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'not found' }));
    return;
  }

  let body = '';
  req.on('data', (chunk) => {
    body += chunk;
  });
  req.on('end', async () => {
    try {
      const payload = body ? JSON.parse(body) : {};
      console.log(`[mira-botium] received: ${String(payload.text || payload.messageText || '').slice(0, 120)}`);
      const output = await askMira(payload.text || payload.messageText || '');
      console.log(`[mira-botium] replied: ${String(output.text || '').slice(0, 160)}`);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(output));
    } catch (error) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ text: `BOTIUM_SERVER_ERROR ${error.message}` }));
    }
  });
});

server.listen(port, '127.0.0.1', () => {
  console.log(`Mira Botium SimpleRest wrapper listening on http://127.0.0.1:${port}`);
});
