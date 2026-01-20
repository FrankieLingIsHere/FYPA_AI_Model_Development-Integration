// Violation Monitor - Smart Notification System
// ==============================================
// NOTIFICATION BEHAVIOR:
// - On page load: ONE summary notification for new violations since last visit
// - During session: Specific real-time notifications ONLY for live detections
//   (detected through live monitor or image upload during this session)

const ViolationMonitor = {
    isMonitoring: false,
    checkInterval: null,
    knownViolations: new Map(),      // Map of reportId -> {status, timestamp}
    notifiedEvents: new Set(),        // Track which events we've notified about
    sessionStartTime: null,           // When this session started
    isInitialLoad: true,              // First load flag - shows summary only
    lastVisitTime: null,              // From localStorage
    
    // LocalStorage key for tracking last visit
    STORAGE_KEY: 'luna_last_visit_time',

    start() {
        if (this.isMonitoring) return;

        this.isMonitoring = true;
        this.isInitialLoad = true;
        this.sessionStartTime = new Date();
        this.knownViolations = new Map();
        this.notifiedEvents = new Set();
        
        // Get last visit time from localStorage
        this.lastVisitTime = this._getLastVisitTime();
        
        // Initial check - will show summary notification only
        this.checkForNewViolations();

        // Check every 3 seconds for new violations during session
        this.checkInterval = setInterval(() => {
            this.checkForNewViolations();
        }, 3000);

        // Save visit time when user leaves
        window.addEventListener('beforeunload', () => this._saveVisitTime());
        
        console.log('[ViolationMonitor] Started monitoring');
        console.log(`[ViolationMonitor] Last visit: ${this.lastVisitTime ? this.lastVisitTime.toLocaleString() : 'First visit'}`);
        console.log(`[ViolationMonitor] Session start: ${this.sessionStartTime.toLocaleString()}`);
    },

    stop() {
        if (!this.isMonitoring) return;

        this.isMonitoring = false;
        this._saveVisitTime();
        
        if (this.checkInterval) {
            clearInterval(this.checkInterval);
            this.checkInterval = null;
        }

        console.log('[ViolationMonitor] Stopped monitoring');
    },
    
    _getLastVisitTime() {
        try {
            const stored = localStorage.getItem(this.STORAGE_KEY);
            return stored ? new Date(stored) : null;
        } catch (e) {
            console.warn('[ViolationMonitor] Could not read localStorage:', e);
            return null;
        }
    },
    
    _saveVisitTime() {
        try {
            localStorage.setItem(this.STORAGE_KEY, new Date().toISOString());
        } catch (e) {
            console.warn('[ViolationMonitor] Could not save to localStorage:', e);
        }
    },

    async checkForNewViolations() {
        try {
            const violations = await API.getViolations();
            
            if (this.isInitialLoad) {
                // INITIAL LOAD: Show summary notification, not individual ones
                this._handleInitialLoad(violations);
                this.isInitialLoad = false;
                return;
            }
            
            // REAL-TIME MODE: Only notify for violations detected AFTER session started
            for (const violation of violations) {
                const reportId = violation.report_id;
                const status = violation.status || (violation.has_report ? 'completed' : 'pending');
                const violationTime = new Date(violation.timestamp);
                const previousData = this.knownViolations.get(reportId);
                
                // Check if this is a NEW violation (not seen before)
                if (!previousData) {
                    // Only show real-time notifications for violations created AFTER session started
                    const isNewDuringSession = violationTime > this.sessionStartTime;
                    
                    if (isNewDuringSession) {
                        console.log(`[ViolationMonitor] 🆕 NEW real-time violation: ${reportId}`);
                        this._notifyViolationDetected(violation);
                        
                        if (status === 'generating') {
                            setTimeout(() => this._notifyReportGenerating(violation), 1500);
                        } else if (status === 'completed') {
                            setTimeout(() => this._notifyReportReady(violation), 1500);
                        }
                    }
                    
                    // Track this violation
                    this.knownViolations.set(reportId, { status, timestamp: violationTime });
                } 
                // Check for STATUS CHANGES on violations we're tracking
                else if (previousData.status !== status) {
                    console.log(`[ViolationMonitor] Status change: ${reportId} ${previousData.status} -> ${status}`);
                    
                    // Only notify status changes for real-time violations (detected during session)
                    const wasRealtime = previousData.timestamp > this.sessionStartTime;
                    
                    if (wasRealtime) {
                        if (status === 'generating' && previousData.status === 'pending') {
                            this._notifyReportGenerating(violation);
                        }
                        else if (status === 'completed') {
                            this._notifyReportReady(violation);
                        }
                        else if (status === 'failed') {
                            this._notifyReportFailed(violation);
                        }
                    }
                    
                    // Update tracked status
                    this.knownViolations.set(reportId, { status, timestamp: previousData.timestamp });
                }
                
                // Check for validation warnings (only for real-time violations)
                const isRealtime = this.knownViolations.get(reportId)?.timestamp > this.sessionStartTime;
                if (isRealtime) {
                    this._checkValidationWarnings(violation);
                }
            }
        } catch (error) {
            console.error('[ViolationMonitor] Error checking violations:', error);
        }
    },
    
    _handleInitialLoad(violations) {
        if (!violations || violations.length === 0) {
            console.log('[ViolationMonitor] No violations in database');
            return;
        }
        
        // Count violations and status
        let newSinceLastVisit = 0;
        let pendingCount = 0;
        let generatingCount = 0;
        let failedCount = 0;
        
        for (const v of violations) {
            const violationTime = new Date(v.timestamp);
            const status = v.status || (v.has_report ? 'completed' : 'pending');
            
            // Track all violations
            this.knownViolations.set(v.report_id, { status, timestamp: violationTime });
            
            // Count new violations since last visit
            if (this.lastVisitTime && violationTime > this.lastVisitTime) {
                newSinceLastVisit++;
            }
            
            // Count by status
            if (status === 'pending') pendingCount++;
            if (status === 'generating') generatingCount++;
            if (status === 'failed') failedCount++;
        }
        
        console.log(`[ViolationMonitor] Initial load: ${violations.length} total, ${newSinceLastVisit} new since last visit`);
        
        // Show ONE summary notification if there are new violations since last visit
        if (newSinceLastVisit > 0) {
            NotificationManager.show(
                `${newSinceLastVisit} new violation${newSinceLastVisit > 1 ? 's' : ''} detected since your last visit`,
                'info',
                8000,
                {
                    title: '📋 Violation Summary',
                    action: {
                        text: 'View Reports',
                        onClick: `Router.navigate('reports')`
                    }
                }
            );
        }
        
        // Show pending/generating summary if any (combined into one)
        const inProgress = pendingCount + generatingCount;
        if (inProgress > 0) {
            setTimeout(() => {
                NotificationManager.show(
                    `${inProgress} report${inProgress > 1 ? 's are' : ' is'} currently being processed`,
                    'warning',
                    6000,
                    {
                        title: '⏳ Reports In Progress'
                    }
                );
            }, 1500);
        }
        
        // Show failed summary if any
        if (failedCount > 0) {
            setTimeout(() => {
                NotificationManager.show(
                    `${failedCount} report${failedCount > 1 ? 's' : ''} failed to generate`,
                    'error',
                    6000,
                    {
                        title: '❌ Failed Reports',
                        action: {
                            text: 'View Details',
                            onClick: `Router.navigate('reports')`
                        }
                    }
                );
            }, 3000);
        }
    },

    // Real-time notification: Violation detected (NEW during session)
    _notifyViolationDetected(violation) {
        const notifKey = `detected_${violation.report_id}`;
        if (this.notifiedEvents.has(notifKey)) return;

        this.notifiedEvents.add(notifKey);

        const severity = violation.severity || 'HIGH';
        const timestamp = new Date(violation.timestamp).toLocaleTimeString();
        const reportId = violation.report_id;

        // Derive a human-friendly type string: prefer explicit type, else missing PPE, else try parsing summary
        let derivedType = null;
        if (violation.violation_type && violation.violation_type !== 'PPE Violation') {
            derivedType = violation.violation_type;
        }

        if (!derivedType) {
            if (Array.isArray(violation.missing_ppe) && violation.missing_ppe.length > 0) {
                if (violation.missing_ppe.length === 1) derivedType = `Missing ${violation.missing_ppe[0]}`;
                else if (violation.missing_ppe.length === 2) derivedType = `Missing ${violation.missing_ppe[0]} and ${violation.missing_ppe[1]}`;
                else derivedType = `Missing ${violation.missing_ppe.slice(0,5).join(', ')}`;
            }
        }

        if (!derivedType && violation.violation_summary) {
            const s = violation.violation_summary;
            const m = s.match(/Missing:?\s*([^\.\n]+)/i) || s.match(/PPE Violation Detected:\s*(.+)/i);
            if (m && m[1]) {
                const parts = m[1].split(',').map(x => x.trim()).filter(Boolean);
                if (parts.length === 1) derivedType = `Missing ${parts[0]}`;
                else if (parts.length === 2) derivedType = `Missing ${parts[0]} and ${parts[1]}`;
                else derivedType = `Missing ${parts.slice(0,5).join(', ')}`;
            }
        }

        if (!derivedType) derivedType = 'PPE Violation';

        NotificationManager.show(
            `${derivedType} at ${timestamp} - Severity: ${severity}`,
            'violation',
            0,  // Persist until dismissed
            {
                title: '🚨 PPE Violation Detected!',
                action: {
                    text: 'View Report',
                    onClick: `ViolationMonitor.navigateToReport('${reportId}')`
                }
            }
        );

        console.log(`[ViolationMonitor] 🚨 VIOLATION: ${violation.report_id} (${derivedType})`);
        // Trigger audio alert (if available) for immediate real-time detections
        try {
            if (window.AudioAlert && typeof window.AudioAlert.speakViolation === 'function') {
                console.log('[ViolationMonitor] Calling AudioAlert.speakViolation for', violation.report_id);
                AudioAlert.speakViolation(violation);
            } else {
                console.log('[ViolationMonitor] AudioAlert not available to speak violation');
            }
        } catch (e) {
            console.error('[ViolationMonitor] Error calling AudioAlert:', e);
        }
    },

    // Real-time notification: Report generating
    _notifyReportGenerating(violation) {
        const notifKey = `generating_${violation.report_id}`;
        if (this.notifiedEvents.has(notifKey)) return;
        
        this.notifiedEvents.add(notifKey);
        const reportId = violation.report_id;
        
        NotificationManager.show(
            `Analyzing violation and generating safety report...`,
            'report',
            10000,
            {
                title: '📝 Generating Report',
                action: {
                    text: 'View Progress',
                    onClick: `ViolationMonitor.navigateToReport('${reportId}')`
                }
            }
        );
        
        console.log(`[ViolationMonitor] 📝 GENERATING: ${violation.report_id}`);
    },

    // Real-time notification: Report ready
    _notifyReportReady(violation) {
        const notifKey = `ready_${violation.report_id}`;
        if (this.notifiedEvents.has(notifKey)) return;
        
        this.notifiedEvents.add(notifKey);
        
        NotificationManager.show(
            `Safety report is ready for review`,
            'success',
            10000,
            {
                title: '✅ Report Complete!',
                action: {
                    text: 'Open Report',
                    onClick: `window.open('${API_CONFIG.BASE_URL}/report/${violation.report_id}', '_blank')`
                }
            }
        );
        
        console.log(`[ViolationMonitor] ✅ READY: ${violation.report_id}`);
    },

    // Real-time notification: Report failed
    _notifyReportFailed(violation) {
        const notifKey = `failed_${violation.report_id}`;
        if (this.notifiedEvents.has(notifKey)) return;
        
        this.notifiedEvents.add(notifKey);
        const reportId = violation.report_id;
        const errorMsg = violation.error_message || 'Unknown error';
        
        NotificationManager.show(
            `Report generation failed: ${errorMsg.slice(0, 80)}`,
            'error',
            10000,
            {
                title: '❌ Report Failed',
                action: {
                    text: 'View Details',
                    onClick: `ViolationMonitor.navigateToReport('${reportId}')`
                }
            }
        );
        
        console.log(`[ViolationMonitor] ❌ FAILED: ${violation.report_id}`);
    },

    // Check for caption validation warnings (real-time only)
    _checkValidationWarnings(violation) {
        const validation = violation.detection_data?.caption_validation;
        if (!validation || validation.is_valid !== false) return;
        
        const notifKey = `validation_${violation.report_id}`;
        if (this.notifiedEvents.has(notifKey)) return;
        
        this.notifiedEvents.add(notifKey);
        const reportId = violation.report_id;
        
        const contradictions = validation.contradictions || [];
        let message = 'Caption validation issues detected';
        if (contradictions.length > 0) {
            // Clean up the message
            message = contradictions[0]
                .replace('⚠️ PPE Mismatch: ', '')
                .slice(0, 100);
        }
        
        NotificationManager.show(
            message,
            'warning',
            8000,
            {
                title: '⚠️ PPE Caption Mismatch',
                action: {
                    text: 'View Report',
                    onClick: `ViolationMonitor.navigateToReport('${reportId}')`
                }
            }
        );
        
        console.warn(`[ViolationMonitor] ⚠️ VALIDATION: ${violation.report_id}`);
    },

    // Navigate to reports page and scroll to specific report
    navigateToReport(reportId) {
        console.log(`[ViolationMonitor] Navigating to report: ${reportId}`);
        
        // Navigate to reports page
        Router.navigate('reports');
        
        // Wait for page to render, then scroll to specific report
        setTimeout(() => {
            const reportCard = document.getElementById(`report-${reportId}`);
            if (reportCard) {
                reportCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
                // Highlight the card briefly
                reportCard.style.boxShadow = '0 0 20px rgba(231, 76, 60, 0.6)';
                reportCard.style.transition = 'box-shadow 0.3s ease';
                setTimeout(() => {
                    reportCard.style.boxShadow = '';
                }, 2000);
            }
        }, 500);
    },

    // Manual trigger for testing
    testNotifications() {
        console.log('[ViolationMonitor] Testing notifications...');
        
        NotificationManager.info('Info notification test');
        setTimeout(() => NotificationManager.success('Success notification test'), 1000);
        setTimeout(() => NotificationManager.warning('Warning notification test'), 2000);
        setTimeout(() => NotificationManager.error('Error notification test'), 3000);
        setTimeout(() => {
            NotificationManager.show('Test violation detected', 'violation', 0, {
                title: '🚨 Test Violation'
            });
        }, 4000);
    },
    
    // Clear last visit time (for testing - shows all as new)
    resetLastVisit() {
        localStorage.removeItem(this.STORAGE_KEY);
        console.log('[ViolationMonitor] Last visit time cleared - refresh to test');
    },
    
    // Force show summary (for testing)
    showSummary() {
        this.isInitialLoad = true;
        this.lastVisitTime = null;
        this.checkForNewViolations();
    }
};

// Auto-start monitoring when page loads
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        setTimeout(() => ViolationMonitor.start(), 2000);
    });
} else {
    setTimeout(() => ViolationMonitor.start(), 2000);
}

// Save visit time when page unloads
window.addEventListener('beforeunload', () => {
    ViolationMonitor.stop();
});
