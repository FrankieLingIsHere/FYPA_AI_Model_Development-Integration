# CASM Pipeline — Full Audit Report
**Date:** April 27, 2026  
**Scope:** Full codebase audit — backend, frontend JS, pipeline modules, queue system, startup/config  
**Status:** Issues identified, NO fixes applied yet — awaiting approval

---

## Summary

| ID | Severity | Component | File | Issue |
|----|----------|-----------|------|-------|
| C1 | 🔴 Critical | config | `pipeline/config.py` | Duplicate dict key `head_region_strict` |
| C2 | 🔴 Critical | captioning | `pipeline/backend/integration/caption_generator.py` | No local caption fallback when Gemini is offline and legacy model absent |
| C3 | 🔴 Critical | report generator | `pipeline/backend/core/report_generator.py` | `strict_local_profile` goes stale outside `_apply_provider_profile` |
| C4 | 🔴 Critical | frontend live | `frontend/js/pages/live.js` | `isLikelyRemoteBackend` is a frozen const — webcam never routes to local backend |
| C5 | 🔴 Critical | frontend config | `frontend/js/config.js` | `runtimeApiBaseOverride` permanently blocks offline URL fallback |
| H1 | 🟠 High | settings modal | `frontend/js/settings-modal.js` | "Apply Local Profile" does not redirect `API_CONFIG.BASE_URL` |
| H2 | 🟠 High | runtime config | `frontend/js/runtime-config.js` | HTTPS deployed frontend → HTTP local backend blocked by mixed content |
| H3 | 🟠 High | backend | `casm_app.py` | Supabase errors wipe global managers destructively with long backoff |
| H4 | 🟠 High | backend | `casm_app.py` | `generate_frames()` can spawn duplicate queue workers on stream restart |
| H5 | 🟠 High | captioning | `pipeline/backend/integration/caption_generator.py` | `backend='legacy'` vs `LEGACY_CAPTION_AVAILABLE=False` mismatch edge case |
| M1 | 🟡 Medium | config | `pipeline/config.py` | 20-minute Ollama timeout stalls queue worker thread |
| M2 | 🟡 Medium | backend | `casm_app.py` | Silent failure on dynamic `caption_image` import during profile switch |
| M3 | 🟡 Medium | frontend | `frontend/js/app.js` | Race condition in `backendResolutionInFlight` |
| M4 | 🟡 Medium | detector | `pipeline/backend/core/violation_detector.py` | Silently affected by C1 duplicate key if edited inconsistently |
| M5 | 🟡 Medium | frontend reports | `frontend/js/pages/reports.js` | Modal poll has no max timeout — spins forever if queue is dead |
| L1 | 🔵 Low | settings modal | `frontend/js/settings-modal.js` | Checkup calls Railway URL even when offline |
| L2 | 🔵 Low | local llama | `pipeline/backend/core/local_llama.py` | Not wired into provider order, effectively unreachable |
| L3 | 🔵 Low | startup | `pipeline/config.py` / `casm_app.py` | Hardcoded YOLO model path blocks startup if `best.pt` is missing |

---

## 🔴 Critical Issues

### C1 — Duplicate Key in `VIOLATION_RULES` Dict
**File:** `pipeline/config.py`, lines 78–79  
**Problem:**  
```python
'head_region_strict': True,  # line 78
'head_region_strict': True,  # line 79 — exact duplicate
```
Python silently discards the first definition, keeping only the last. Right now both are `True` so the behaviour is correct, but this is a latent bug — if one is ever changed without updating the other, the wrong value will silently win. Any future developer editing head-region logic will be confused.  
**Impact:** Low currently, but high risk in future edits.  
**Fix needed:** Remove the duplicate line.

---

### C2 — No Local Caption Fallback When Offline
**File:** `pipeline/backend/integration/caption_generator.py`, line 75  
**Problem:**  
When running in local/offline mode, `use_gemini` defaults to `True` (because `GEMINI_CONFIG` is not passed from `casm_app.py`, so `gemini_config.get('enabled', True)` returns `True`). When Gemini fails due to no internet, the fallback is `LEGACY_CAPTION_AVAILABLE` — which requires Qwen2.5-VL downloaded via llama.cpp. If that model is not installed, `generate_caption()` returns the error string `"Image captioning not available — Gemini API key not configured"` as the caption text, which is then fed directly into the NLP report prompt, corrupting the report output.  

**Root cause also in `casm_app.py`:**  
```python
# casm_app.py line 1710-1711
caption_config = {'LLAVA_CONFIG': LLAVA_CONFIG}
caption_generator = CaptionGenerator(caption_config)
# ^^^^^ GEMINI_CONFIG is NOT included in this dict
```
**Impact:** Reports generated in offline mode contain garbage caption text.  
**Fix needed:**
1. Pass `GEMINI_CONFIG` to `CaptionGenerator` in `casm_app.py`
2. Guard against returning error strings as caption content in `generate_caption()`

---

### C3 — `strict_local_profile` Goes Stale
**File:** `pipeline/backend/core/report_generator.py`, init block  
**Problem:**  
`self.strict_local_profile` is computed once at `__init__` from `routing_profile`. `_apply_provider_profile()` in `casm_app.py` correctly patches `report_generator.routing_profile` and `report_generator.use_gemini` at runtime. However, if `routing_profile` is changed via any code path other than `_apply_provider_profile()`, `strict_local_profile` is never recalculated.  
Currently `_apply_provider_profile` is the only writer, so this is not a live bug — but it is a fragile design that a future code path will likely break.  
**Impact:** Incorrect provider selection (Gemini used when strict local profile is active).  
**Fix needed:** Convert `strict_local_profile` to a `@property` that derives from the current `routing_profile`.

---

### C4 — `isLikelyRemoteBackend` Is a Frozen Const in `live.js`
**File:** `frontend/js/pages/live.js`, line 263  
**Problem:**  
```javascript
// live.js line 263 — computed ONCE at mount() call time, never updated
const isLikelyRemoteBackend = (() => {
    const base = API_CONFIG.BASE_URL;
    return base && !base.includes('127.0.0.1') && !base.includes('localhost');
})();
```
After the user switches to local mode, `API_CONFIG.BASE_URL` changes to `http://127.0.0.1:5000` — but `isLikelyRemoteBackend` was already captured as `true` when the page first mounted against the Railway URL. It is never re-evaluated.  
Line 507 then uses it:
```javascript
if (selectedSource === 'webcam' && (isLikelyRemoteBackend || !!selectedBrowserDeviceId)) return true;
```
This forces webcam to use browser `getUserMedia()` (client-side capture), so `/api/live/start` is never called and YOLO detection never runs.  
**Compare:** In `app.js` line 101, the same check is correctly a `function` that re-evaluates on each call.  
**Impact:** Live webcam detection does not work after switching to local mode.  
**Fix needed:** Change from IIFE const to a function call: `isLikelyRemoteBackend()`.

---

### C5 — `runtimeApiBaseOverride` Permanently Blocks Offline URL Fallback
**File:** `frontend/js/config.js`, line 14–30 (approx)  
**Problem:**  
`API_CONFIG.BASE_URL` getter checks `runtimeApiBaseOverride !== null` first. At app boot, this is set to the Railway HTTPS URL. The offline fallback:
```javascript
if (navigator.onLine === false) return this.LOCAL_BACKEND_URL;
```
…is **never reached** because the `runtimeApiBaseOverride !== null` branch returns early. Even when the browser goes offline, `BASE_URL` keeps returning the Railway URL.  
**Impact:** All API calls (`generate-now`, `live/start`, `sync-local-cache`, etc.) continue targeting Railway even when fully offline, so they all fail with network errors.  
**Fix needed:** In `resolveWorkingBackendBaseUrl`, when `preferLocal=true` or all remote probes fail, explicitly set `runtimeApiBaseOverride = null` to let the offline logic run.

---

## 🟠 High Issues

### H1 — "Apply Local Profile" Does Not Update `API_CONFIG.BASE_URL`
**File:** `frontend/js/settings-modal.js`, around line 1065  
**Problem:**  
`applyProviderRoutingLocalProfile()` only POSTs `routing_profile: 'local'` to `/api/settings/provider-routing`. This changes which NLP model the backend uses (Ollama instead of Gemini), but does NOT redirect the frontend's `API_CONFIG.BASE_URL` to `http://localhost:5000`.  
After clicking "Apply Local Profile", the user sees a success message but every subsequent API call (generate report, start live, etc.) still goes to the Railway cloud URL.  
**Impact:** User believes local mode is active, but all traffic still goes to cloud.  
**Fix needed:** After the POST succeeds, call `resolveWorkingBackendBaseUrl({ preferLocal: true, force: true })`.

---

### H2 — HTTPS Deployed Frontend Cannot Reach HTTP Local Backend
**File:** `frontend/js/runtime-config.js`  
**Problem:**  
The deployed frontend is served over HTTPS (`https://fypaaimodeldevelopment-integration-production.up.railway.app`). The local backend is HTTP (`http://127.0.0.1:5000`). Browsers enforce the **Mixed Active Content** policy: any `fetch()`, `XMLHttpRequest`, or `<img src>` pointing to an HTTP resource from an HTTPS page is silently blocked with no JS exception — the request just never leaves the browser.  
This affects:
- All `API.*` calls from the deployed frontend when pointing to local backend
- The MJPEG live stream (`<img>` tag pointing to `http://127.0.0.1:5000/api/live/stream`)
- Any binary asset download from local backend  

**Impact:** This is the single most fundamental blocker for using local mode from the deployed production frontend. It cannot be fixed in JS alone.  
**Fix needed (options):**
1. Run the local backend over HTTPS (self-signed cert + `flask-tls` or `gunicorn --certfile`)
2. Access the local UI only via `http://127.0.0.1:5000` directly (not the deployed HTTPS frontend)
3. Use a local HTTPS proxy (`nginx` or `caddy`) in front of the Flask server

---

### H3 — Supabase Errors Destructively Wipe Global Managers
**File:** `casm_app.py`, `_activate_local_offline_runtime()` at line 1065  
**Problem:**  
Any Supabase connectivity failure that passes `_is_supabase_connectivity_failure(e)` triggers `_activate_local_offline_runtime()`, which sets:
```python
db_manager = None
storage_manager = None
```
These are global variables. Even if the Supabase error was transient (e.g., a single timeout), the managers are destroyed and must be rebuilt by the Supabase runtime recovery cycle. The backoff starts at 90 seconds, can grow to 900 seconds (15 minutes). During the backoff window, all requests that could still succeed against Supabase are blocked.  
**Compound issue:** On Railway cloud, `_is_hosted_runtime_environment()` returns `True`, so `_activate_local_offline_runtime()` returns immediately without doing anything — meaning the `db_manager = None` path is never taken on cloud. But this also means the offline fallback **never activates on the cloud deployment**.  
**Impact:** A single DB timeout → 90s+ outage of all report saving/retrieval.  
**Fix needed:** Use a retry counter before wiping managers, or mark them as "degraded" instead of `None`.

---

### H4 — `generate_frames()` Can Spawn Duplicate Queue Workers
**File:** `casm_app.py`, `generate_frames()` around line 9991  
**Problem:**  
`generate_frames()` calls `initialize_pipeline_components()` when the pipeline is not yet ready. `initialize_pipeline_components()` creates a new `ViolationQueueManager` only if `violation_queue is None`. However, if a previous stream session caused the queue worker thread to die (e.g., uncaught exception), `violation_queue` is still not `None` (the manager object exists), but the worker thread inside it is dead. A new stream session will try to use the dead worker.  
Conversely, if `violation_queue` IS reset to `None` during an error recovery path, starting a new stream creates a second manager alongside still-running cleanup threads from the first.  
**Impact:** Violations are not processed (dead worker), or processed twice (duplicate worker).  
**Fix needed:** Add a `violation_queue.is_worker_alive()` check and restart the worker thread if it has died, rather than relying on manager-level None checks.

---

### H5 — `backend='legacy'` vs `LEGACY_CAPTION_AVAILABLE=False` Edge Case
**File:** `pipeline/backend/integration/caption_generator.py`  
**Problem:**  
If `use_gemini=False` (e.g., Gemini disabled explicitly), `self.backend` is set to `'legacy' if LEGACY_CAPTION_AVAILABLE else 'none'` at `__init__` time. `LEGACY_CAPTION_AVAILABLE` is evaluated once at module import. In a partial-import scenario (e.g., llama.cpp loads but then unloads), `self.backend` could be `'legacy'` while `LEGACY_CAPTION_AVAILABLE` is now `False`. The `generate_caption()` method checks `if LEGACY_CAPTION_AVAILABLE:` (module-level var) rather than `if self.backend == 'legacy':`, so the fallback branch is silently skipped.  
**Impact:** Captions fail silently without raising an error or logging clearly.  
**Fix needed:** Use `self.backend` as the source of truth inside `generate_caption()`.

---

## 🟡 Medium Issues

### M1 — 20-Minute Ollama Timeout Stalls Queue Worker
**File:** `pipeline/config.py`, line 126  
```python
'timeout': int(os.getenv('OLLAMA_TIMEOUT', '1200')),  # 20 minutes
```
If Ollama hangs mid-generation (model deadlock, OOM, etc.), the queue worker HTTP call blocks for up to 20 minutes before timing out. The watchdog only detects a stale heartbeat after `QUEUE_WORKER_HEARTBEAT_STALE_SECONDS` (default 180s), so there is a window where the entire violation queue is frozen with no user-visible indication.  
**Impact:** Queue freezes for up to 20 minutes; new violations are not processed.  
**Fix needed:** Set a more aggressive default (e.g., 120–300 seconds) or add per-request progress heartbeats.

---

### M2 — Silent Failure on Dynamic Import in Profile Switch
**File:** `casm_app.py`, `_apply_provider_profile()` around line 5350  
```python
try:
    from caption_image import update_runtime_provider_settings
    update_runtime_provider_settings(profile)
except Exception:
    pass  # silently ignored
```
If `caption_image.py` has a module-level error or `update_runtime_provider_settings` raises, the vision provider profile is never updated but the route handler returns HTTP 200 with `success: true`.  
**Impact:** Vision captioning continues using wrong provider after a profile switch.  
**Fix needed:** Log the exception at minimum; ideally surface it as a non-fatal warning in the API response.

---

### M3 — Race Condition in `backendResolutionInFlight`
**File:** `frontend/js/app.js`, `resolveWorkingBackendBaseUrl()` around line 755  
**Problem:**  
```javascript
if (backendResolutionInFlight) return backendResolutionInFlight;
backendResolutionInFlight = _doResolve();
try { ... } finally { backendResolutionInFlight = null; }
```
If two callers invoke `resolveWorkingBackendBaseUrl()` concurrently (before `_doResolve()` assigns to `backendResolutionInFlight`), both see `null` and both start independent resolution races. Both may then write different values to `API_CONFIG.BASE_URL` in an indeterminate order.  
**Impact:** API traffic may briefly land on the wrong backend (Railway vs local) after a network status change.  
**Fix needed:** Set `backendResolutionInFlight` synchronously before the first `await`.

---

### M4 — `violation_detector.py` Silently Affected by C1
**File:** `pipeline/backend/core/violation_detector.py`  
Depends on `config.VIOLATION_RULES['head_region_strict']`. If C1 is ever edited such that the two duplicate keys have different values, the detector will silently use whichever value Python kept (the last one). There will be no error or warning.  
**Impact:** Hardhat false-positive rate unexpectedly changes with no traceable cause.  
**Fix needed:** Fix C1 first.

---

### M5 — Report Modal Poll Has No Timeout
**File:** `frontend/js/pages/reports.js`, `startModalPolling()`  
**Problem:**  
When `generateReportNow()` is called, the UI opens a status modal and polls `/api/report/<id>/status` until it receives a terminal state (`completed`, `failed`, `error`). There is no maximum poll count or wall-clock timeout. If the queue worker is dead and the report stays in `"generating"` forever, the modal spins indefinitely.  
**Impact:** User is locked in a loading state with no way to dismiss except refreshing the page.  
**Fix needed:** Add a max poll count (e.g., 60 × 5s = 5 minutes) and show a timeout error with a dismiss button.

---

## 🔵 Low Issues

### L1 — Local Mode Checkup Calls Railway URL When Offline
**File:** `frontend/js/settings-modal.js`, `runLocalModeCheckup()`  
`runLocalModeCheckup()` calls `API.getReportRecoveryOptions()`, which uses `API_CONFIG.BASE_URL`. Because of C5, this URL is still Railway when offline. The checkup therefore cannot reach local diagnostics when the user is offline, making its results unreliable for genuinely offline scenarios.  
**Fix needed:** Fix C5 first; checkup will then naturally use the local backend URL when offline.

---

### L2 — `local_llama.py` Not Wired Into Provider Order
**File:** `pipeline/backend/core/local_llama.py`  
`local_llama.py` loads `torch` and `transformers` on import (heavy dependencies). It is imported at module level in some files but not wired into `report_generator.py`'s `_resolve_effective_nlp_provider_order()`. It is therefore never actually used for report generation. The import cost is paid for nothing.  
**Fix needed:** Either wire it into the provider order as a third local fallback after Ollama, or remove the import if it is not intended to be used.

---

### L3 — Hardcoded YOLO Model Path Blocks Startup
**File:** `pipeline/config.py`, line 109; `casm_app.py` startup  
```python
'model_path': 'Results/ppe_yolov86/weights/best.pt',
```
If this file is absent (fresh clone, moved weights, renamed folder), `resolve_model_path()` fails during the startup warm-up. The startup sequence marks `yolo_model` as `error` and raises `RuntimeError('YOLO model path check failed: ...')`, which causes the entire app to fail to reach ready state.  
**Fix needed:** Either make the path configurable via an env var, or gracefully degrade to "no YOLO" mode with a warning instead of a startup-blocking error.

---

## Previously Identified Issues (Phase 2 — also pending approval)

These four were identified earlier and are included here for completeness:

| ID | File | Bug | Impact |
|----|------|-----|--------|
| P1 | `live.js` L263 | Same as C4 above | Webcam never uses local YOLO |
| P2 | `config.js` L14 | Same as C5 above | All API calls stay on Railway offline |
| P3 | `settings-modal.js` L1065 | Same as H1 above | Local mode appears active but is not |
| P4 | `runtime-config.js` | Same as H2 above | HTTPS → HTTP mixed content block |

---

## Recommended Fix Priority

If fixing the offline/local mode use case specifically, fix in this order:

1. **H2** — Must solve HTTPS/HTTP first (architectural, needs decision)
2. **C5** — Fix `runtimeApiBaseOverride` blocking offline URL
3. **C4** — Fix frozen `isLikelyRemoteBackend` in `live.js`
4. **H1** — Fix "Apply Local Profile" to also redirect `BASE_URL`
5. **C2** — Fix caption config so Gemini config is passed correctly
6. **H3** — Soften Supabase error handling to avoid destroying managers on transient errors
7. **M5** — Add report modal poll timeout so UI doesn't get stuck
8. **C1** — Remove duplicate config key
9. Remaining medium/low issues as time permits
