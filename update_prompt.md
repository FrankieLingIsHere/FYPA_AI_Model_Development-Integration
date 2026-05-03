# 🛠️ Local Mode Issues & Requirements

## 1. Supabase Access in Local Mode

* In **local mode**, the system currently cannot access Supabase.
* Expected behavior:

  * The system should **not depend on Supabase** when running locally.
  * All data (reports, logs, outputs) must be **saved and retrieved locally**.

---

## 2. Report Generation Performance

* Problem: Report generation in local mode is **too slow**.
* Requirements:

  * Provide a **fast test mode** that:

    * Skips the LLM processing (e.g., Gemma).
    * Generates a **basic or mock report output** instantly.
  * This helps verify:

    * The pipeline works correctly.
    * The delay is caused by the LLM and not other components.

---

## 3. Local File Saving

* Ensure that in local mode:

  * Reports are **saved to local storage** (e.g., filesystem).
  * No cloud dependency is required.
  * File paths should be clearly defined and consistent.

---

## 4. LLM (Gemma) Health Check

* Add a **diagnostic check** for Gemma:

  * Confirm whether Gemma is:

    * Running
    * Responding correctly
  * Provide a **simple test response** (e.g., a short prompt → quick reply).
  * Output should clearly indicate:

    * ✅ Working
    * ❌ Not working

---

## 5. Checkup Status UI Issue

* Problem:

  * The checkup status initially shows **green (OK)**.
  * Then it **randomly switches to orange (warning/loading)**.
  * Appears to be repeatedly refreshing or re-running.

* Expected behavior:

  * The checkup should:

    * Run **only once per session/load**.
    * Display a **stable result** (no flickering or auto-refresh).
  * Status should remain:

    * ✅ Green → if system is healthy
    * ⚠️ Orange → only if there is an actual issue
  * Do NOT re-trigger checkup unless:

    * User manually refreshes
    * Or explicitly requests a new check

---

## 6. Testing Mode (Recommended Feature)

* Add a **“Local Test Mode”** that:

  * Disables:

    * Supabase
    * LLM (Gemma)
  * Enables:

    * Fast report generation
    * Local file saving only
  * Purpose:

    * Quickly validate system behavior without external dependencies

---

## ✅ Summary of Goals

* Fully functional **offline/local mode**
* Faster testing workflow (no LLM delay)
* Reliable **local file storage**
* Clear **Gemma health check**
* Stable **checkup status (no auto-refresh flicker)**
