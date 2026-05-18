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
  const chartConfigs = [];
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
            getContext: () => ({}),
          };
        }
        return elements[id];
      },
    },
  };
  context.Chart = function Chart(_ctx, config) {
    chartConfigs.push(config);
    return { destroy: () => {} };
  };
  context.window.window = context.window;
  context.window.document = context.document;
  context.window.Chart = context.Chart;
  vm.createContext(context);
  vm.runInContext(code, context, { filename: filePath });
  return { exported: context[exportName], elements, chartConfigs };
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
  const palette = Object.values(HomePage.VIOLATION_TYPE_COLORS || {});
  assert(palette.length === 5, `home palette should cover five active PPE types, got ${palette.length}`);
  assert(new Set(palette).size === palette.length, 'home palette colors should be unique');
  assert(palette.every((color) => /^#[0-9a-f]{6}$/i.test(color)), `home palette should use concrete canvas-safe colors: ${palette.join(', ')}`);

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
  const { exported: AnalyticsPage, elements, chartConfigs } = loadScript('frontend/js/pages/analytics.js', 'AnalyticsPage');
  const palette = Object.values(AnalyticsPage.VIOLATION_TYPE_COLORS || {});
  assert(palette.length === 5, `analytics palette should cover five active PPE types, got ${palette.length}`);
  assert(new Set(palette).size === palette.length, 'analytics palette colors should be unique');
  assert(palette.every((color) => /^#[0-9a-f]{6}$/i.test(color)), `analytics palette should use concrete canvas-safe colors: ${palette.join(', ')}`);

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

  AnalyticsPage.initViolationPieChart([
    { name: 'Missing Hardhat', count: 4, color: AnalyticsPage.VIOLATION_TYPE_COLORS.hardhat },
    { name: 'Missing Safety Vest', count: 3, color: AnalyticsPage.VIOLATION_TYPE_COLORS.safetyVest },
    { name: 'Missing Gloves', count: 2, color: AnalyticsPage.VIOLATION_TYPE_COLORS.gloves },
    { name: 'Missing Mask', count: 1, color: AnalyticsPage.VIOLATION_TYPE_COLORS.mask },
    { name: 'Missing Safety Shoes', count: 1, color: AnalyticsPage.VIOLATION_TYPE_COLORS.safetyShoes },
  ]);
  const chartConfig = chartConfigs[0];
  assert(chartConfig && chartConfig.type === 'pie', 'analytics violation chart should initialize as a pie chart');
  const dataset = chartConfig.data.datasets[0];
  assert(new Set(dataset.backgroundColor).size === 5, 'pie chart should use five distinct slice colors');
  assert(dataset.borderColor === '#ffffff', 'pie chart should use white slice separators');
  assert(dataset.borderWidth === 2, `pie chart border width should be 2, got ${dataset.borderWidth}`);
  assert(dataset.hoverOffset === 6, `pie chart hover offset should be 6, got ${dataset.hoverOffset}`);
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
