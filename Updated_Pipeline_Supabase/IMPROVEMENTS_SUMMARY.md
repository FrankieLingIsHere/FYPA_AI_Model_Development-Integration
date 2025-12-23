# LUNA PPE Monitor - Enhanced User Experience & Validation
===========================================================

## Recent Improvements (Latest Update)

This document describes three major enhancements implemented to improve user experience and report accuracy:

### 1. 📊 In-Progress Reports Display (Pipeline_Luna Style)

**What Changed:**
- Reports now appear immediately in the Reports page, even while generating
- Visual indicators show report status (Queued, Generating, Ready, Failed)
- Users can click on generating reports to see progress modal
- Matches Pipeline_Luna's "show all reports" behavior

**Implementation:**
- Modified [frontend/js/pages/reports.js](frontend/js/pages/reports.js)
  - Removed filtering that hid non-ready reports
  - Added overlay with status icon for in-progress reports
  - Enhanced `renderReportCard()` to show all states
  - Status badges: 🕐 Queued, ⏳ Generating, ✅ Ready, ❌ Failed

**User Experience:**
```
Before: Reports appear only when fully generated
After:  Reports visible immediately with status indicators
        - Click ready report → Opens report
        - Click generating report → Shows progress modal
        - Auto-refreshes every 10 seconds
```

---

### 2. ✅ Caption Validation (Cross-Check LLaVA vs YOLO)

**What Changed:**
- Automatic validation of LLaVA captions against YOLO detections
- Detects contradictions between caption and annotations
- Flags potential accuracy issues in real-time
- Stores validation results with confidence scores

**Implementation:**

**New File:** [pipeline/backend/integration/caption_validator.py](pipeline/backend/integration/caption_validator.py)
- `CaptionValidator` class with NLP pattern matching
- PPE class mappings (hardhat, mask, safety_vest, gloves, etc.)
- Negation detection ("not wearing", "without", "missing")
- Presence detection ("wearing", "with", "equipped")
- Confidence scoring algorithm

**Modified:** [pipeline/backend/core/supabase_report_generator.py](pipeline/backend/core/supabase_report_generator.py)
- Integrated `validate_caption()` in report generation workflow
- Runs validation after local files generated, before Supabase upload
- Stores validation results in `detection_data` JSON field

**Modified:** [luna_app.py](luna_app.py)
- Enhanced `/api/violations` endpoint to include validation data
- Returns `caption_validation` with each violation

**Validation Output:**
```python
{
    'is_valid': True/False,
    'confidence': 0.85,  # 0-1 score
    'contradictions': [
        "YOLO detected hardhat but caption says it's missing: 'worker without helmet'"
    ],
    'warnings': [
        "Caption mentions safety vest ambiguously"
    ],
    'detected_items': {
        'person': True,
        'hardhat': False,
        'mask': True
    },
    'caption_mentions': {
        'hardhat': {
            'mentioned': True,
            'present': False,  # Caption says NOT wearing
            'context': 'worker without helmet on construction site'
        }
    },
    'validation_summary': '❌ Validation failed (1 contradiction) - caption partially accurate'
}
```

**Detection Logic:**
1. Extract what YOLO detected (classes)
2. Parse caption for PPE mentions
3. Determine if caption says item is present/absent/ambiguous
4. Compare: contradiction = "YOLO detected X but caption says not X"
5. Calculate confidence based on agreement rate
6. Log warnings for low confidence detections or ambiguous captions

---

### 3. 🔔 Real-Time User Notifications

**What Changed:**
- Toast notifications for all violation events
- Live updates during report generation
- Alerts for caption validation warnings
- Persistent notifications for critical events

**Implementation:**

**New File:** [frontend/js/notifications.js](frontend/js/notifications.js)
- `NotificationManager` singleton class
- Material Design toast notifications
- Auto-dismiss with configurable duration
- Action buttons (View Report, View Progress)
- Icons and color-coding by type

**New File:** [frontend/js/violation-monitor.js](frontend/js/violation-monitor.js)
- `ViolationMonitor` background service
- Polls `/api/violations` every 5 seconds
- Detects new violations and status changes
- Triggers appropriate notifications

**Modified:** [frontend/index.html](frontend/index.html)
- Added script imports for notification system
- Loads before API and app initialization

**Notification Types:**

| Type | When | Duration | Dismissable | Icon |
|------|------|----------|-------------|------|
| **Violation Detected** | New violation appears | Persistent | Yes | 🚨 |
| **Report Generating** | Status = generating | 10s | Yes | 📝 |
| **Report Ready** | Status = completed | 8s | Yes | ✅ |
| **Report Failed** | Status = failed | 8s | Yes | ❌ |
| **Validation Warning** | Caption contradiction | 7s | Yes | ⚠️ |
| **Info** | General updates | 4s | Yes | ℹ️ |
| **Success** | Success events | 4s | Yes | ✅ |
| **Error** | Error events | 6s | Yes | ❌ |

**User Interaction:**
```javascript
// New violation detected
NotificationManager.violation(
    "PPE Violation detected at 14:32:15 - Severity: HIGH",
    reportId,
    { duration: 0 }  // Stays until user dismisses
);

// Report generating
NotificationManager.reportGenerating(reportId);
// → Shows progress, links to Reports page

// Report ready
NotificationManager.reportReady(reportId);
// → "Open Report" button opens in new tab

// Caption validation warning
NotificationManager.warning(
    "Caption may not match detections: YOLO detected hardhat but caption says missing",
    {
        title: '⚠️ Caption Validation Warning',
        action: { text: 'View Report', onClick: '...' }
    }
);
```

**Monitoring Flow:**
1. `ViolationMonitor.start()` on page load
2. Checks violations every 5 seconds
3. Tracks `lastSeenViolations` set
4. For new violations:
   - Send "Violation Detected" notification
   - If generating, send "Report Generating" notification
5. For existing violations:
   - Check status changes
   - If completed → "Report Ready" notification
   - If failed → "Report Failed" error
   - If validation issues → Warning notification
6. Prevents duplicate notifications with `notifiedReports` set

---

## File Structure

```
Updated_Pipeline_Supabase/
├── frontend/
│   ├── index.html                      # ✏️ Added notification scripts
│   └── js/
│       ├── notifications.js            # 🆕 Toast notification system
│       ├── violation-monitor.js        # 🆕 Real-time monitoring service
│       └── pages/
│           └── reports.js              # ✏️ Show all reports, not just ready
├── pipeline/
│   └── backend/
│       ├── core/
│       │   └── supabase_report_generator.py  # ✏️ Integrated validation
│       └── integration/
│           └── caption_validator.py    # 🆕 Caption cross-checking logic
└── luna_app.py                         # ✏️ Enhanced /api/violations endpoint
```

**Legend:** 🆕 New file, ✏️ Modified file

---

## Usage Examples

### 1. Viewing In-Progress Reports

**Navigate to Reports Page:**
```
http://localhost:5000/#/reports
```

**What You'll See:**
- All reports listed immediately
- In-progress reports have:
  - Semi-transparent overlay
  - Status icon (spinning for "Generating")
  - "Generating..." or "Queued" badge

**Click Behavior:**
- **Ready report:** Opens full report in new tab
- **Generating report:** Shows modal:
  ```
  ╔════════════════════════════════╗
  ║       ⏳ Report Generating     ║
  ║                                ║
  ║  The AI is analyzing the       ║
  ║  violation and generating a    ║
  ║  detailed report. This usually ║
  ║  takes 30-60 seconds.          ║
  ║                                ║
  ║  [Close]  [Check Status]       ║
  ╚════════════════════════════════╝
  ```

### 2. Caption Validation in Action

**Run Live Detection:**
```bash
python luna_app.py
```

**Check Validation Results:**

1. **In Backend Logs:**
   ```
   [INFO] Caption validated: ✅ Caption matches annotations with high confidence
   ```
   or
   ```
   [WARNING] Caption validation failed for 20250603_143215:
   [WARNING]   - YOLO detected hardhat but caption says it's missing: 'worker without helmet on site'
   ```

2. **In API Response:**
   ```bash
   curl http://localhost:5000/api/violations
   ```
   ```json
   {
     "report_id": "20250603_143215",
     "detection_data": {
       "caption_validation": {
         "is_valid": false,
         "confidence": 0.4,
         "contradictions": [
           "YOLO detected hardhat but caption says it's missing"
         ],
         "validation_summary": "❌ Validation failed (1 contradiction)"
       }
     }
   }
   ```

3. **In UI (Notification):**
   - If validation fails, warning notification appears:
   ```
   ⚠️ Caption Validation Warning
   Caption may not match detections: YOLO detected hardhat but caption says missing
   [View Report]
   ```

### 3. Testing Notifications

**Open Browser Console:**
```javascript
// Test all notification types
ViolationMonitor.testNotifications();

// Manual notifications
NotificationManager.success('Test successful!');
NotificationManager.error('Test error');
NotificationManager.warning('Test warning');
NotificationManager.info('Test info');

// Test violation notification
NotificationManager.violation('PPE violation at entrance', 'TEST-001');

// Test report notifications
NotificationManager.reportGenerating('TEST-001');
setTimeout(() => {
    NotificationManager.reportReady('TEST-001');
}, 5000);
```

**Monitor in Real-Time:**
- Open Reports page
- Run live detection or upload image
- Watch notifications appear as events occur

---

## Configuration

### Notification Timing

Edit [violation-monitor.js](frontend/js/violation-monitor.js):
```javascript
const ViolationMonitor = {
    // Check for new violations every X milliseconds
    checkInterval: 5000,  // Default: 5 seconds
    
    // Change in start() method:
    this.checkInterval = setInterval(() => {
        this.checkForNewViolations();
    }, 5000);  // ← Adjust here
};
```

### Notification Duration

Edit [notifications.js](frontend/js/notifications.js):
```javascript
// In NotificationManager:
success(message, options = {}) {
    return this.show(message, 'success', options.duration || 4000, options);
    //                                    Change duration here ↑
},

error(message, options = {}) {
    return this.show(message, 'error', options.duration || 6000, options);
},

warning(message, options = {}) {
    return this.show(message, 'warning', options.duration || 5000, options);
},
```

### Caption Validation Sensitivity

Edit [caption_validator.py](pipeline/backend/integration/caption_validator.py):
```python
class CaptionValidator:
    # Add more PPE classes
    PPE_CLASSES = {
        'hardhat': ['helmet', 'hard hat', 'hardhat'],
        'boots': ['boot', 'boots', 'footwear'],  # ← Add more keywords
        # ...
    }
    
    # Add more negation patterns
    NEGATION_PATTERNS = [
        r'\bnot?\s+wearing\b',
        r'\bwithout\b',
        r'\bmissing\b',
        r'\byour_custom_pattern\b',  # ← Add here
    ]
    
    # Adjust confidence calculation
    def _calculate_confidence(self, ...):
        score = 1.0
        score -= len(contradictions) * 0.3  # ← Penalty per contradiction
        score -= len(warnings) * 0.1        # ← Penalty per warning
        # ...
```

---

## Database Schema Updates

Caption validation data is stored in the `violations` table's `detection_data` JSONB column:

```sql
-- Supabase query to view validation data
SELECT 
    report_id,
    detection_data->'caption_validation'->>'is_valid' as valid,
    detection_data->'caption_validation'->>'confidence' as confidence,
    detection_data->'caption_validation'->'contradictions' as contradictions
FROM violations
WHERE detection_data ? 'caption_validation'
ORDER BY timestamp DESC;
```

**Example Output:**
```
report_id        | valid | confidence | contradictions
-----------------|-------|------------|------------------
20250603_143215  | false | 0.4        | ["YOLO detected..."]
20250603_142830  | true  | 0.92       | []
```

---

## Troubleshooting

### Notifications Not Appearing

1. **Check Console for Errors:**
   ```javascript
   // In browser console
   console.log(NotificationManager);
   console.log(ViolationMonitor);
   ```

2. **Verify Scripts Loaded:**
   - View Page Source → Check script order:
   ```html
   <script src="/static/js/notifications.js"></script>  <!-- Must be first -->
   <script src="/static/js/violation-monitor.js"></script>
   ```

3. **Check Monitoring Status:**
   ```javascript
   ViolationMonitor.isMonitoring  // Should be true
   ```

4. **Restart Monitoring:**
   ```javascript
   ViolationMonitor.stop();
   ViolationMonitor.start();
   ```

### Validation Not Running

1. **Check Import:**
   ```python
   # In supabase_report_generator.py
   from pipeline.backend.integration.caption_validator import validate_caption
   ```

2. **Check Logs:**
   ```bash
   python luna_app.py 2>&1 | grep -i "validation"
   ```

3. **Test Validation Directly:**
   ```python
   from pipeline.backend.integration.caption_validator import validate_caption
   
   result = validate_caption(
       caption="Worker without helmet on construction site",
       annotations=[{'class': 'hardhat', 'confidence': 0.9}],
       detected_classes=['hardhat', 'person']
   )
   print(result)
   ```

### Reports Not Showing While Generating

1. **Check Status Field:**
   ```bash
   curl http://localhost:5000/api/violations | jq '.[0].status'
   ```
   Should return: `"pending"`, `"generating"`, `"completed"`, or `"failed"`

2. **Check Frontend Filtering:**
   - In [reports.js](frontend/js/pages/reports.js), ensure `renderReports()` doesn't filter:
   ```javascript
   renderReports() {
       const filtered = this.getFilteredViolations();
       // Should NOT have: filtered = filtered.filter(v => this.isReportReady(v));
       list.innerHTML = `<div class="grid">${filtered.map(...).join('')}</div>`;
   }
   ```

3. **Force Refresh:**
   - Click "Refresh" button on Reports page
   - Or in console: `ReportsPage.refreshReports()`

---

## Performance Considerations

### Notification Polling

- **Current:** Polls every 5 seconds
- **Impact:** ~12 API calls per minute
- **Optimization:** Use WebSocket for real-time push (future enhancement)

### Caption Validation

- **Overhead:** ~50-100ms per validation
- **When:** Runs once during report generation
- **Impact:** Minimal (report generation takes 30-60 seconds anyway)

### Auto-Refresh

- **Current:** Reports page refreshes every 10 seconds when pending reports exist
- **Impact:** Low (only refreshes when needed)
- **Optimization:** Stop auto-refresh when all reports completed

---

## Future Enhancements

1. **WebSocket Support**
   - Replace polling with server-push notifications
   - Real-time updates without API calls

2. **Notification Preferences**
   - User settings to enable/disable notification types
   - Volume control (critical only, all, none)

3. **Enhanced Validation**
   - Use LLaVA to re-caption with specific questions
   - Confidence threshold for flagging
   - Auto-regenerate caption if validation fails

4. **Notification History**
   - Persistent notification log
   - Review past alerts
   - Export to CSV/JSON

5. **Mobile Notifications**
   - Push notifications via service worker
   - SMS/email alerts for critical violations

---

## API Reference

### GET /api/violations

**Response with Validation:**
```json
[
  {
    "report_id": "20250603_143215",
    "timestamp": "2025-06-03T14:32:15",
    "status": "completed",
    "has_report": true,
    "detection_data": {
      "caption_validation": {
        "is_valid": false,
        "confidence": 0.4,
        "contradictions": ["YOLO detected hardhat but caption says missing"],
        "warnings": ["Low confidence detections (2 items below 50%)"],
        "detected_items": {
          "person": true,
          "hardhat": true,
          "mask": false
        },
        "caption_mentions": {
          "hardhat": {
            "mentioned": true,
            "present": false,
            "context": "worker without helmet on construction site"
          }
        },
        "validation_summary": "❌ Validation failed (1 contradiction)"
      }
    }
  }
]
```

---

## Testing Checklist

- [ ] Navigate to Reports page → All reports visible
- [ ] Click on completed report → Opens in new tab
- [ ] Click on generating report → Modal appears
- [ ] Run live demo → Violation notification appears
- [ ] Wait 30-60s → "Report Generating" notification
- [ ] Wait for completion → "Report Ready" notification
- [ ] Create contradiction (e.g., hardhat detected, caption says "no helmet")
  - [ ] Backend logs show validation warning
  - [ ] Frontend shows validation warning notification
- [ ] Open console → `ViolationMonitor.testNotifications()`
  - [ ] See all 6 notification types
- [ ] Leave Reports page open → Auto-refresh every 10s
- [ ] Stop/start monitoring:
  ```javascript
  ViolationMonitor.stop();
  ViolationMonitor.start();
  ```

---

## Summary

These three improvements provide:

1. **Better Visibility** - Users see all reports immediately, not just completed ones
2. **Higher Accuracy** - Automatic validation catches caption/annotation mismatches
3. **Improved UX** - Real-time notifications keep users informed without manual checking

All changes maintain backward compatibility and work with both Supabase and SQLite fallback modes.
