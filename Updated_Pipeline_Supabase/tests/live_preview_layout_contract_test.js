// Readability: Test setup: document the contract this file protects.
/*
 * Static contract for Live page preview sizing.
 *
 * Local backend webcam streams often arrive at 640x480. The preview must still
 * occupy the same full-width stage as browser/cloud capture instead of shrinking
 * to the MJPEG frame's intrinsic size.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const LIVE_JS = path.join(ROOT, 'frontend', 'js', 'pages', 'live.js');

// Section: handle the assert workflow.
function assert(condition, message) {
  // Choose the correct browser state branch before continuing.
  if (!condition) {
    throw new Error(message);
  }
}

// Section: handle the get style for id workflow.
function getStyleForId(source, id) {
  const pattern = new RegExp(`<(?:img|video)[^>]+id="${id}"[^>]+style="([^"]+)"`, 'i');
  const match = source.match(pattern);
  assert(match && match[1], `${id} style not found`);
  return match[1];
}

// Section: handle the assert preview style workflow.
function assertPreviewStyle(style, label) {
  assert(/width:\s*100%/.test(style), `${label} must fill preview width`);
  assert(/aspect-ratio:\s*16\s*\/\s*9/.test(style), `${label} must reserve a stable 16:9 stage`);
  assert(/object-fit:\s*contain/.test(style), `${label} must preserve camera framing without cropping`);
  assert(/background:\s*#000/.test(style), `${label} must keep letterbox background black`);
}

// Section: handle the main workflow.
function main() {
  const source = fs.readFileSync(LIVE_JS, 'utf8');
  assert(/id="liveStreamContainer"[^>]+background:\s*#000/i.test(source), 'live stream container must use a black stage');
  assertPreviewStyle(getStyleForId(source, 'liveStream'), 'backend live stream');
  assertPreviewStyle(getStyleForId(source, 'phoneCameraPreview'), 'browser camera preview');
  console.log('PASS: live preview layout keeps local and cloud camera feeds full-width');
}

main();
