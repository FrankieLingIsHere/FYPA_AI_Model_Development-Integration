/*
 * Contract test for the active PPE taxonomy.
 *
 * Goggles/eye-protection classes were removed from the detector, so active
 * dashboard and analytics surfaces must not recreate a Missing Goggles bucket
 * from historical labels or free-text normalization.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function loadScript(relativePath, exportName) {
  const filePath = path.join(ROOT, relativePath);
  const code = `${fs.readFileSync(filePath, 'utf8')}\nglobalThis.${exportName} = ${exportName};`;
  const elements = {};
  const context = {
    console,
    setTimeout,
    clearTimeout,
    window: {
      location: { protocol: 'http:' },
    },
    document: {
      getElementById(id) {
        if (!elements[id]) {
          elements[id] = {
            id,
            innerHTML: '',
            textContent: '',
            style: {},
            addEventListener: () => {},
          };
        }
        return elements[id];
      },
    },
  };
  context.window.window = context.window;
  context.window.document = context.document;
  vm.createContext(context);
  vm.runInContext(code, context, { filename: filePath });
  return { exported: context[exportName], elements };
}

function testApiIgnoresRemovedGogglesTaxonomy() {
  const { exported: API } = loadScript('frontend/js/api.js', 'API');
  assert(API.canonicalViolationKey('NO-Goggles') === null, 'NO-Goggles should not canonicalize');
  assert(API.canonicalViolationKey('Missing safety glasses') === null, 'safety glasses should not become a violation key');

  const missing = API.extractMissingPpeLabels({
    missing_ppe: ['Goggles', 'Safety Glasses', 'Hardhat'],
  });
  assert(missing.length === 1 && missing[0] === 'Hardhat', `unexpected missing PPE labels: ${missing.join(', ')}`);

  const breakdown = API.buildBreakdown([
    { ppe_tags: ['NO-Goggles', 'NO-Mask'] },
    { violation_summary: 'PPE Violation Detected: Missing Goggles' },
  ]);
  assert(!Object.prototype.hasOwnProperty.call(breakdown, 'NO-Goggles'), 'breakdown should not expose NO-Goggles');
  assert(breakdown['NO-Mask'] === 1, `expected mask count to remain intact, got ${breakdown['NO-Mask']}`);
}

function testHomeDashboardDoesNotRenderMissingGoggles() {
  const { exported: HomePage, elements } = loadScript('frontend/js/pages/home.js', 'HomePage');
  HomePage.renderViolationTypes({
    breakdown: {
      'NO-Hardhat': 1,
      'NO-Goggles': 99,
      'NO-Mask': 2,
    },
  });
  const html = elements['violation-types'].innerHTML;
  assert(!html.includes('Missing Goggles'), 'home dashboard should not render Missing Goggles');
  assert(html.includes('Missing Hardhat'), 'home dashboard should keep supported PPE buckets');
  assert(html.includes('Missing Mask'), 'home dashboard should keep supported mask bucket');
}

function testAnalyticsDoesNotRenderOrAcceptMissingGoggles() {
  const { exported: AnalyticsPage, elements } = loadScript('frontend/js/pages/analytics.js', 'AnalyticsPage');
  assert(
    AnalyticsPage.normalizePpeFilterLabel('missing goggles') === 'missing goggles',
    'analytics filter normalization should not map goggles to NO-Goggles',
  );
  const sanitized = AnalyticsPage.sanitizeAssistantFilters
    ? AnalyticsPage.sanitizeAssistantFilters({ ppeTypes: ['NO-Goggles', 'NO-Mask'] })
    : {};
  if (sanitized.ppeTypes) {
    assert(!sanitized.ppeTypes.includes('NO-Goggles'), 'analytics assistant filters should drop NO-Goggles');
  }

  AnalyticsPage.renderViolationTypes({
    breakdown: {
      'NO-Goggles': 99,
      'NO-Safety Vest': 3,
    },
  });
  const html = elements['analytics-violation-types'].innerHTML;
  assert(!html.includes('Missing Goggles'), 'analytics breakdown should not render Missing Goggles');
  assert(html.includes('Missing Safety Vest'), 'analytics breakdown should keep supported PPE buckets');
}

function main() {
  testApiIgnoresRemovedGogglesTaxonomy();
  console.log('PASS: testApiIgnoresRemovedGogglesTaxonomy');
  testHomeDashboardDoesNotRenderMissingGoggles();
  console.log('PASS: testHomeDashboardDoesNotRenderMissingGoggles');
  testAnalyticsDoesNotRenderOrAcceptMissingGoggles();
  console.log('PASS: testAnalyticsDoesNotRenderOrAcceptMissingGoggles');
  console.log('PPE taxonomy contract test passed');
}

main();
