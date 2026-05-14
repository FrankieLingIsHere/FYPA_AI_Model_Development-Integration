const fs = require('fs');
const path = require('path');

const { askMira } = require('./mira-simplerest-server');

const repoRoot = path.resolve(__dirname, '..', '..', '..');
const ideasPath = path.join(repoRoot, 'assistant_prompt_ideas.md');

function normalize(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[^\w\s-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function extractPrompts(markdown) {
  return Array.from(markdown.matchAll(/"([^"\r\n]+)"/g))
    .map((match) => match[1].trim())
    .filter(Boolean)
    .filter((prompt, index, prompts) => prompts.indexOf(prompt) === index);
}

function hasCasmSignal(prompt) {
  const query = normalize(prompt);
  return /\b(casm|ppe|helmet|hardhat|vest|glove|mask|goggle|boot|shoe|camera|cam|feed|stream|monitor|site|construction|zone|gate|warehouse|perimeter|entrance|dashboard|analytics|metric|chart|graph|trend|compliance|safe|safety|unsafe|violation|violations|incident|incidents|alert|alerts|report|reports|records?|audit|evidence|csv|spreadsheet|excel|export|download|data|log|logs|device|devices|edge|streamer|approval|approve|authorize|provision|filter|summary|manager|briefing|toolbox|worker|supervisor|admin|local mode|cloud mode|settings|hando?book|manual|documentation|tutorial|guide|screen|page|button|login|support|bug|error|offline|online|slow|broken|frozen|loading|status|health)\b/.test(query);
}

function isGracefulFallbackAllowed(prompt) {
  const query = normalize(prompt);
  if (!query) return true;
  if (/^[0-9\s?!.,]+$/.test(prompt)) return true;
  if (/^(asdfghjkl|blah blah|maybe maybe maybe|show show show|last last last|okay|nope|again|why|now)$/i.test(prompt.trim())) return true;
  const offTopicOnly = /\b(weather|pizza|joke|game|capital|mongolia|bored|banana|moon|universe|math|song|movie)\b/.test(query)
    && !hasCasmSignal(prompt);
  return offTopicOnly;
}

function classifyReply(text) {
  const reply = normalize(text);
  if (/botium_server_error|no_response/.test(reply)) return 'error';
  if (/cannot reveal secrets|bypass permissions/.test(reply)) return 'sensitive-denial';
  if (/permission-aware|safe to share|redact names/.test(reply)) return 'privacy-guidance';
  if (/local deterministic intent rules|i can help with casm workflows/.test(reply)) return 'capability';
  if (/new here|guide you through|easiest starting paths/.test(reply)) return 'onboarding';
  if (/combined request|split it into safe workspace actions/.test(reply)) return 'compound';
  if (/live monitor|camera stream workflow|starting site supervision/.test(reply)) return 'live-monitor';
  if (/analyze image|still-image checks|upload area/.test(reply)) return 'image-analysis';
  if (/live analytics snapshot|current pipeline snapshot/.test(reply)) return 'analytics';
  if (/reports csv is ready|analytics csv is ready|documentation csv is ready/.test(reply)) return 'export';
  if (/handbook match|open handbook|guide|tutorial loaded/.test(reply)) return 'guidance';
  if (/settings|profile|local pipeline|api mode/.test(reply)) return 'settings';
  if (/is ready|go to|open reports|open analytics|open camera/.test(reply)) return 'navigation';
  if (/partial read|could not confidently map|did not get a usable request/.test(reply)) return 'fallback';
  return 'other-covered';
}

async function main() {
  const markdown = fs.readFileSync(ideasPath, 'utf8');
  const prompts = extractPrompts(markdown);
  const results = [];
  const failures = [];

  for (const prompt of prompts) {
    const output = await askMira(prompt);
    const category = classifyReply(output.text);
    const fallback = category === 'fallback';
    const allowedFallback = isGracefulFallbackAllowed(prompt);
    const casmSignal = hasCasmSignal(prompt);
    const passed = category !== 'error' && (!fallback || allowedFallback || !casmSignal);
    const row = {
      prompt,
      category,
      casmSignal,
      allowedFallback,
      passed,
      response: output.text
    };
    results.push(row);
    if (!passed) failures.push(row);
  }

  const byCategory = results.reduce((acc, row) => {
    acc[row.category] = (acc[row.category] || 0) + 1;
    return acc;
  }, {});
  const summary = {
    source: path.relative(repoRoot, ideasPath).replace(/\\/g, '/'),
    totalPrompts: prompts.length,
    passed: results.length - failures.length,
    failed: failures.length,
    byCategory,
    failures: failures.map((row) => ({
      prompt: row.prompt,
      category: row.category,
      response: row.response.slice(0, 260)
    }))
  };

  console.log(JSON.stringify(summary, null, 2));

  if (failures.length) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
