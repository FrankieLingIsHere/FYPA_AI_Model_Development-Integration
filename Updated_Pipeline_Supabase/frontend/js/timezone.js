/**
 * Timezone Utility for Frontend
 * Handles timezone conversion and display based on user selection
 */

// Get selected timezone offset from localStorage or default to Malaysia (UTC+8)
function getTimezoneOffset() {
    return parseFloat(localStorage.getItem('timezoneOffset') || '8');
}

// Save timezone offset to localStorage
function setTimezoneOffset(offset) {
    localStorage.setItem('timezoneOffset', offset.toString());
}

function getTimezoneLabel() {
    const selector = document.getElementById('timezone-selector');
    if (!selector) {
        const offset = getTimezoneOffset();
        const offsetStr = offset >= 0 ? `+${offset}` : `${offset}`;
        return `UTC${offsetStr}`;
    }

    const selectedOption = selector.options[selector.selectedIndex];
    return selectedOption ? selectedOption.textContent.trim() : 'UTC+8';
}

// Convert UTC timestamp to selected timezone
function convertToLocalTime(utcTimestamp) {
    const offset = getTimezoneOffset();
    const date = new Date(utcTimestamp);
    
    // Add timezone offset
    const localTime = new Date(date.getTime() + (offset * 60 * 60 * 1000));
    
    return localTime;
}

// Format timestamp for display
function formatTimestamp(timestamp, format = 'full') {
    const date = convertToLocalTime(timestamp);
    const offset = getTimezoneOffset();
    const offsetStr = offset >= 0 ? `+${offset}` : offset;
    
    const year = date.getUTCFullYear();
    const month = String(date.getUTCMonth() + 1).padStart(2, '0');
    const day = String(date.getUTCDate()).padStart(2, '0');
    const hours = String(date.getUTCHours()).padStart(2, '0');
    const minutes = String(date.getUTCMinutes()).padStart(2, '0');
    const seconds = String(date.getUTCSeconds()).padStart(2, '0');
    
    switch (format) {
        case 'full':
            return `${year}-${month}-${day} ${hours}:${minutes}:${seconds} (UTC${offsetStr})`;
        case 'datetime':
            return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
        case 'date':
            return `${year}-${month}-${day}`;
        case 'time':
            return `${hours}:${minutes}:${seconds}`;
        case 'short':
            return `${month}/${day} ${hours}:${minutes}`;
        default:
            return date.toISOString();
    }
}

// Get relative time (e.g., "2 hours ago")
function getRelativeTime(timestamp) {
    const now = new Date();
    const date = new Date(timestamp);
    const diffMs = now - date;
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHour = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHour / 24);
    
    if (diffSec < 60) return 'Just now';
    if (diffMin < 60) return `${diffMin} minute${diffMin > 1 ? 's' : ''} ago`;
    if (diffHour < 24) return `${diffHour} hour${diffHour > 1 ? 's' : ''} ago`;
    if (diffDay < 7) return `${diffDay} day${diffDay > 1 ? 's' : ''} ago`;
    
    return formatTimestamp(timestamp, 'date');
}

function formatDateTime(timestamp) {
    return formatTimestamp(timestamp, 'datetime');
}

function formatDate(timestamp) {
    return formatTimestamp(timestamp, 'date');
}

function formatTime(timestamp) {
    return formatTimestamp(timestamp, 'time');
}

function notifyTimezoneChange(message) {
    if (typeof NotificationManager !== 'undefined') {
        NotificationManager.info(message);
        return;
    }
    if (typeof showNotification === 'function') {
        showNotification(message, 'info');
        return;
    }
    console.log(message);
}

function bindTimezoneSelector(selector) {
    if (!selector) return;
    if (selector.dataset.timezoneBound === 'true') return;

    selector.dataset.timezoneBound = 'true';
    selector.addEventListener('change', (e) => {
        const newOffset = parseFloat(e.target.value);
        setTimezoneOffset(newOffset);

        const offsetStr = newOffset >= 0 ? `+${newOffset}` : newOffset;
        notifyTimezoneChange(`Timezone changed to UTC${offsetStr}`);
        updateAllTimestamps();
        window.dispatchEvent(new CustomEvent('ppe-timezone:changed', {
            detail: {
                offset: newOffset,
                label: getTimezoneLabel(),
                changedAt: Date.now()
            }
        }));
    });
}

// Initialize timezone selector
function initTimezoneSelector() {
    const selector = document.getElementById('timezone-selector');
    if (!selector) return;
    
    // Load saved timezone
    const savedOffset = getTimezoneOffset();
    selector.value = savedOffset;

    bindTimezoneSelector(selector);
    
    // Update all timestamps on page
    updateAllTimestamps();
}

function initSelector(selectorId = 'timezone-selector') {
    const selector = document.getElementById(selectorId);
    if (!selector) return;

    const savedOffset = getTimezoneOffset();
    selector.value = String(savedOffset);
    bindTimezoneSelector(selector);
    updateAllTimestamps();
}

// Update all elements with timestamp data
function updateAllTimestamps() {
    document.querySelectorAll('[data-timestamp]').forEach(element => {
        const timestamp = element.getAttribute('data-timestamp');
        const format = element.getAttribute('data-format') || 'full';
        element.textContent = formatTimestamp(timestamp, format);
    });
    
    document.querySelectorAll('[data-timestamp-relative]').forEach(element => {
        const timestamp = element.getAttribute('data-timestamp-relative');
        element.textContent = getRelativeTime(timestamp);
    });
}

// Initialize on page load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTimezoneSelector);
} else {
    initTimezoneSelector();
}

// Export functions for use in other scripts
window.TimezoneUtils = {
    getTimezoneOffset,
    setTimezoneOffset,
    getTimezoneLabel,
    convertToLocalTime,
    formatTimestamp,
    formatDateTime,
    formatDate,
    formatTime,
    initSelector,
    getRelativeTime,
    updateAllTimestamps
};

window.TimezoneManager = {
    getTimezoneOffset,
    setTimezoneOffset,
    getTimezoneLabel,
    convertToLocalTime,
    formatTimestamp,
    formatDateTime,
    formatDate,
    formatTime,
    initSelector,
    getRelativeTime,
    updateAllTimestamps
};
