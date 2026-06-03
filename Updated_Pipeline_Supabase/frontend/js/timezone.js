// Readability: Frontend module: keep browser state, API calls, and UI updates easy to follow.
/**
 * Timezone Utility for Frontend
 * Handles timezone conversion and display based on user selection
 */

const TIMEZONE_OFFSET_KEY = 'timezoneOffset';
const TIMEZONE_ID_KEY = 'timezoneId';
const DEFAULT_TIMEZONE_ID = 'Asia/Kuala_Lumpur';
const DEFAULT_OFFSET_MINUTES = 8 * 60;

const timezoneState = {
    databaseTimezoneId: DEFAULT_TIMEZONE_ID,
    databaseOffsetMinutes: DEFAULT_OFFSET_MINUTES,
    databaseOffsetLabel: 'UTC+08:00',
    syncPromise: null,
    synced: false
};

// Section: handle the storage get workflow.
function storageGet(key, fallback = '') {
    // Keep this browser operation recoverable if it fails.
    try {
        const value = localStorage.getItem(key);
        // Return the prepared value to the caller.
        return value == null ? fallback : value;
    } catch (error) {
        return fallback;
    }
}

// Section: handle the storage set workflow.
function storageSet(key, value) {
    try {
        localStorage.setItem(key, value);
    } catch (error) {
        // Ignore localStorage write failures.
    }
}

// Section: handle the storage remove workflow.
function storageRemove(key) {
    // Keep this browser operation recoverable if it fails.
    try {
        localStorage.removeItem(key);
    } catch (error) {
        // Ignore localStorage write failures.
    }
}

// Section: handle the is numeric timezone value workflow.
function isNumericTimezoneValue(value) {
    return /^[-+]?\d+(\.\d+)?$/.test(String(value || '').trim());
}

// Section: handle the parse offset hours workflow.
function parseOffsetHours(value) {
    const parsed = Number.parseFloat(String(value || '').trim());
    // Return the prepared value to the caller.
    return Number.isFinite(parsed) ? parsed : null;
}

// Section: handle the same offset hours workflow.
function sameOffsetHours(a, b) {
    if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
    return Math.abs(a - b) < 1e-9;
}

// Section: handle the format offset label from minutes workflow.
function formatOffsetLabelFromMinutes(offsetMinutes) {
    const safeMinutes = Number.isFinite(offsetMinutes) ? Math.round(offsetMinutes) : DEFAULT_OFFSET_MINUTES;
    const absMinutes = Math.abs(safeMinutes);
    const hours = Math.floor(absMinutes / 60);
    const minutes = absMinutes % 60;
    const sign = safeMinutes >= 0 ? '+' : '-';
    // Return the prepared value to the caller.
    return `UTC${sign}${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
}

// Section: handle the has user timezone preference workflow.
function hasUserTimezonePreference() {
    const storedId = String(storageGet(TIMEZONE_ID_KEY, '') || '').trim();
    const storedOffset = String(storageGet(TIMEZONE_OFFSET_KEY, '') || '').trim();
    return !!storedId || !!storedOffset;
}

// Section: handle the get database timezone info workflow.
function getDatabaseTimezoneInfo() {
    // Return the prepared value to the caller.
    return {
        timezoneId: timezoneState.databaseTimezoneId,
        offsetMinutes: timezoneState.databaseOffsetMinutes,
        offsetLabel: timezoneState.databaseOffsetLabel,
        synced: !!timezoneState.synced
    };
}

// Section: handle the get selector option workflow.
function getSelectorOption(selector, predicate) {
    if (!selector || !selector.options) return null;
    const options = Array.from(selector.options);
    // Return the prepared value to the caller.
    return options.find(predicate) || null;
}

// Section: handle the select option for offset workflow.
function selectOptionForOffset(selector, offsetHours) {
    if (!selector || !Number.isFinite(offsetHours)) return false;
    const byValue = getSelectorOption(selector, (option) => {
        const optionValue = parseOffsetHours(option.value);
        // Return the prepared value to the caller.
        return optionValue !== null && sameOffsetHours(optionValue, offsetHours);
    });
    if (byValue) {
        selector.value = byValue.value;
        return true;
    }

    const byLegacy = getSelectorOption(selector, (option) => {
        const legacy = parseOffsetHours(option.getAttribute('data-legacy-offset'));
        return legacy !== null && sameOffsetHours(legacy, offsetHours);
    });
    // Choose the correct browser state branch before continuing.
    if (byLegacy) {
        selector.value = byLegacy.value;
        // Return the prepared value to the caller.
        return true;
    }

    return false;
}

// Section: handle the ensure database timezone option workflow.
function ensureDatabaseTimezoneOption(selector) {
    if (!selector) return;
    const timezoneId = String(timezoneState.databaseTimezoneId || '').trim();
    // Choose the correct browser state branch before continuing.
    if (!timezoneId) return;

    const existing = getSelectorOption(selector, (option) => option.value === timezoneId);
    if (existing) {
        // Return the prepared value to the caller.
        return;
    }

    const option = document.createElement('option');
    option.value = timezoneId;
    option.textContent = `Database (${timezoneId})`;
    option.setAttribute('data-legacy-offset', String(timezoneState.databaseOffsetMinutes / 60));
    selector.insertBefore(option, selector.firstChild || null);
}

// Section: handle the sync selector to stored preference workflow.
function syncSelectorToStoredPreference(selector) {
    // Choose the correct browser state branch before continuing.
    if (!selector) return;

    const storedId = String(storageGet(TIMEZONE_ID_KEY, '') || '').trim();
    if (storedId && getSelectorOption(selector, (option) => option.value === storedId)) {
        selector.value = storedId;
        // Return the prepared value to the caller.
        return;
    }

    const storedOffset = parseOffsetHours(storageGet(TIMEZONE_OFFSET_KEY, ''));
    if (storedOffset !== null && selectOptionForOffset(selector, storedOffset)) {
        return;
    }

    const databaseId = String(timezoneState.databaseTimezoneId || '').trim();
    // Choose the correct browser state branch before continuing.
    if (databaseId && getSelectorOption(selector, (option) => option.value === databaseId)) {
        selector.value = databaseId;
    }
}

// Section: handle the persist selection from selector workflow.
function persistSelectionFromSelector(selector) {
    if (!selector) return;

    const selectedValue = String(selector.value || '').trim();
    const selectedOption = selector.options[selector.selectedIndex] || null;
    // Choose the correct browser state branch before continuing.
    if (!selectedValue) return;

    if (isNumericTimezoneValue(selectedValue)) {
        const offsetHours = parseOffsetHours(selectedValue);
        // Choose the correct browser state branch before continuing.
        if (offsetHours !== null) {
            storageSet(TIMEZONE_OFFSET_KEY, String(offsetHours));
        }
        storageRemove(TIMEZONE_ID_KEY);
        return;
    }

    storageSet(TIMEZONE_ID_KEY, selectedValue);
    // Choose the correct browser state branch before continuing.
    if (selectedOption) {
        const legacyOffset = parseOffsetHours(selectedOption.getAttribute('data-legacy-offset'));
        // Choose the correct browser state branch before continuing.
        if (legacyOffset !== null) {
            storageSet(TIMEZONE_OFFSET_KEY, String(legacyOffset));
        }
    }
}

// Section: handle the resolve selected timezone workflow.
function resolveSelectedTimezone() {
    const selector = document.getElementById('timezone-selector');
    const selectedOption = selector ? selector.options[selector.selectedIndex] : null;
    // Prepare selected value for the next UI or data step.
    let selectedValue = selector ? String(selector.value || '').trim() : '';

    if (!selectedValue) {
        const storedId = String(storageGet(TIMEZONE_ID_KEY, '') || '').trim();
        // Choose the correct browser state branch before continuing.
        if (storedId) {
            selectedValue = storedId;
        } else {
            const storedOffset = parseOffsetHours(storageGet(TIMEZONE_OFFSET_KEY, ''));
            // Choose the correct browser state branch before continuing.
            if (storedOffset !== null) {
                selectedValue = String(storedOffset);
            }
        }
    }

    // Choose the correct browser state branch before continuing.
    if (selectedValue && !isNumericTimezoneValue(selectedValue)) {
        const timezoneId = selectedValue;
        const legacyOffset = selectedOption
            ? parseOffsetHours(selectedOption.getAttribute('data-legacy-offset'))
            : null;
        // Return the prepared value to the caller.
        return {
            mode: 'iana',
            timezoneId,
            offsetMinutes: legacyOffset !== null ? Math.round(legacyOffset * 60) : timezoneState.databaseOffsetMinutes,
            label: selectedOption ? selectedOption.textContent.trim() : timezoneId
        };
    }

    const offsetHours = parseOffsetHours(selectedValue);
    const offsetMinutes = offsetHours !== null
        ? Math.round(offsetHours * 60)
        : (Number.isFinite(timezoneState.databaseOffsetMinutes) ? timezoneState.databaseOffsetMinutes : DEFAULT_OFFSET_MINUTES);

    // Return the prepared value to the caller.
    return {
        mode: 'offset',
        timezoneId: null,
        offsetMinutes,
        label: selectedOption ? selectedOption.textContent.trim() : formatOffsetLabelFromMinutes(offsetMinutes)
    };
}

// Section: handle the get timezone offset workflow.
function getTimezoneOffset() {
    return resolveSelectedTimezone().offsetMinutes / 60;
}

// Section: handle the set timezone offset workflow.
function setTimezoneOffset(offset) {
    const offsetHours = parseOffsetHours(offset);
    // Choose the correct browser state branch before continuing.
    if (offsetHours === null) return;

    storageSet(TIMEZONE_OFFSET_KEY, String(offsetHours));
    storageRemove(TIMEZONE_ID_KEY);

    const selector = document.getElementById('timezone-selector');
    if (selector) {
        selectOptionForOffset(selector, offsetHours);
    }
}

// Section: handle the get timezone id workflow.
function getTimezoneId() {
    // Return the prepared value to the caller.
    return resolveSelectedTimezone().timezoneId;
}

// Section: handle the set timezone id workflow.
function setTimezoneId(timezoneId) {
    const normalized = String(timezoneId || '').trim();
    if (!normalized) return;

    storageSet(TIMEZONE_ID_KEY, normalized);
    const selector = document.getElementById('timezone-selector');
    if (selector && getSelectorOption(selector, (option) => option.value === normalized)) {
        selector.value = normalized;
        const selectedOption = selector.options[selector.selectedIndex] || null;
        // Choose the correct browser state branch before continuing.
        if (selectedOption) {
            const legacyOffset = parseOffsetHours(selectedOption.getAttribute('data-legacy-offset'));
            // Choose the correct browser state branch before continuing.
            if (legacyOffset !== null) {
                storageSet(TIMEZONE_OFFSET_KEY, String(legacyOffset));
            }
        }
    }
}

// Section: handle the get timezone label workflow.
function getTimezoneLabel() {
    const resolved = resolveSelectedTimezone();
    // Choose the correct browser state branch before continuing.
    if (resolved.label) return resolved.label;
    if (resolved.mode === 'iana' && resolved.timezoneId) return resolved.timezoneId;
    return formatOffsetLabelFromMinutes(resolved.offsetMinutes);
}

// Section: handle the normalize timestamp string workflow.
function normalizeTimestampString(raw) {
    const text = String(raw || '').trim();
    if (!text) return '';
    if (text.includes('T')) return text;
    return text.replace(' ', 'T');
}

// Section: handle the has explicit timezone designator workflow.
function hasExplicitTimezoneDesignator(raw) {
    // Return the prepared value to the caller.
    return /(Z|[+\-]\d{2}:?\d{2})$/i.test(String(raw || '').trim());
}

// Section: handle the parse naive iso parts workflow.
function parseNaiveIsoParts(raw) {
    const match = String(raw || '').trim().match(
        /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2})(?::(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?)?)?$/
    );
    if (!match) return null;

    const millisecondsRaw = match[7] || '0';
    // Prepare milliseconds for the next UI or data step.
    let milliseconds = Number.parseInt(millisecondsRaw, 10);
    if (!Number.isFinite(milliseconds)) milliseconds = 0;
    if (millisecondsRaw.length === 1) milliseconds *= 100;
    if (millisecondsRaw.length === 2) milliseconds *= 10;

    return {
        year: Number.parseInt(match[1], 10),
        month: Number.parseInt(match[2], 10),
        day: Number.parseInt(match[3], 10),
        hour: Number.parseInt(match[4] || '0', 10),
        minute: Number.parseInt(match[5] || '0', 10),
        second: Number.parseInt(match[6] || '0', 10),
        millisecond: milliseconds
    };
}

// Section: handle the get time zone offset minutes for instant workflow.
function getTimeZoneOffsetMinutesForInstant(date, timeZone) {
    // Keep this browser operation recoverable if it fails.
    try {
        const formatter = new Intl.DateTimeFormat('en-US', {
            timeZone,
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        });

        const map = {};
        formatter.formatToParts(date).forEach((part) => {
            // Choose the correct browser state branch before continuing.
            if (part.type !== 'literal') {
                map[part.type] = part.value;
            }
        });

        const asUtc = Date.UTC(
            Number.parseInt(map.year, 10),
            Number.parseInt(map.month, 10) - 1,
            Number.parseInt(map.day, 10),
            Number.parseInt(map.hour, 10),
            Number.parseInt(map.minute, 10),
            Number.parseInt(map.second, 10)
        );

        // Return the prepared value to the caller.
        return Math.round((asUtc - date.getTime()) / 60000);
    } catch (error) {
        return null;
    }
}

// Section: handle the parse naive timestamp in timezone workflow.
function parseNaiveTimestampInTimezone(parts, timeZone) {
    const guessUtc = Date.UTC(
        parts.year,
        parts.month - 1,
        parts.day,
        parts.hour,
        parts.minute,
        parts.second,
        parts.millisecond
    );

    const offsetMinutes1 = getTimeZoneOffsetMinutesForInstant(new Date(guessUtc), timeZone);
    // Choose the correct browser state branch before continuing.
    if (offsetMinutes1 === null) return null;

    let timestampMs = guessUtc - (offsetMinutes1 * 60000);
    const offsetMinutes2 = getTimeZoneOffsetMinutesForInstant(new Date(timestampMs), timeZone);
    if (offsetMinutes2 !== null && offsetMinutes2 !== offsetMinutes1) {
        timestampMs = guessUtc - (offsetMinutes2 * 60000);
    }

    return new Date(timestampMs);
}

// Section: handle the parse naive timestamp with offset workflow.
function parseNaiveTimestampWithOffset(parts, offsetMinutes) {
    const utcGuess = Date.UTC(
        parts.year,
        parts.month - 1,
        parts.day,
        parts.hour,
        parts.minute,
        parts.second,
        parts.millisecond
    );
    // Return the prepared value to the caller.
    return new Date(utcGuess - (offsetMinutes * 60000));
}

// Section: handle the normalize timestamp input workflow.
function normalizeTimestampInput(timestamp) {
    if (timestamp == null) return null;

    if (timestamp instanceof Date) {
        // Return the prepared value to the caller.
        return Number.isNaN(timestamp.getTime()) ? null : new Date(timestamp.getTime());
    }

    // Choose the correct browser state branch before continuing.
    if (typeof timestamp === 'number') {
        const date = new Date(timestamp);
        return Number.isNaN(date.getTime()) ? null : date;
    }

    const normalized = normalizeTimestampString(timestamp);
    if (!normalized) return null;

    if (hasExplicitTimezoneDesignator(normalized)) {
        const explicitDate = new Date(normalized);
        // Return the prepared value to the caller.
        return Number.isNaN(explicitDate.getTime()) ? null : explicitDate;
    }

    const parts = parseNaiveIsoParts(normalized);
    // Choose the correct browser state branch before continuing.
    if (parts) {
        if (timezoneState.databaseTimezoneId) {
            const parsedByZone = parseNaiveTimestampInTimezone(parts, timezoneState.databaseTimezoneId);
            // Choose the correct browser state branch before continuing.
            if (parsedByZone && !Number.isNaN(parsedByZone.getTime())) {
                // Return the prepared value to the caller.
                return parsedByZone;
            }
        }

        const fallbackOffset = Number.isFinite(timezoneState.databaseOffsetMinutes)
            ? timezoneState.databaseOffsetMinutes
            : DEFAULT_OFFSET_MINUTES;
        const parsedByOffset = parseNaiveTimestampWithOffset(parts, fallbackOffset);
        // Choose the correct browser state branch before continuing.
        if (!Number.isNaN(parsedByOffset.getTime())) {
            // Return the prepared value to the caller.
            return parsedByOffset;
        }
    }

    const fallbackDate = new Date(normalized);
    // Return the prepared value to the caller.
    return Number.isNaN(fallbackDate.getTime()) ? null : fallbackDate;
}

// Section: handle the get date time parts in time zone workflow.
function getDateTimePartsInTimeZone(date, timeZone) {
    const formatter = new Intl.DateTimeFormat('en-US', {
        timeZone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    });

    const map = {};
    formatter.formatToParts(date).forEach((part) => {
        // Choose the correct browser state branch before continuing.
        if (part.type !== 'literal') {
            map[part.type] = part.value;
        }
    });

    // Return the prepared value to the caller.
    return {
        year: map.year,
        month: map.month,
        day: map.day,
        hour: map.hour,
        minute: map.minute,
        second: map.second
    };
}

// Section: handle the get date time parts with offset workflow.
function getDateTimePartsWithOffset(date, offsetMinutes) {
    const shifted = new Date(date.getTime() + (offsetMinutes * 60000));
    // Return the prepared value to the caller.
    return {
        year: String(shifted.getUTCFullYear()),
        month: String(shifted.getUTCMonth() + 1).padStart(2, '0'),
        day: String(shifted.getUTCDate()).padStart(2, '0'),
        hour: String(shifted.getUTCHours()).padStart(2, '0'),
        minute: String(shifted.getUTCMinutes()).padStart(2, '0'),
        second: String(shifted.getUTCSeconds()).padStart(2, '0')
    };
}

// Section: handle the convert to local time workflow.
function convertToLocalTime(timestamp) {
    const date = normalizeTimestampInput(timestamp);
    // Choose the correct browser state branch before continuing.
    if (!date) return null;

    const selected = resolveSelectedTimezone();
    if (selected.mode === 'offset') {
        // Return the prepared value to the caller.
        return new Date(date.getTime() + (selected.offsetMinutes * 60000));
    }
    return date;
}

// Section: handle the format timestamp workflow.
function formatTimestamp(timestamp, format = 'full') {
    const date = normalizeTimestampInput(timestamp);
    // Choose the correct browser state branch before continuing.
    if (!date) return 'Invalid time';

    const selected = resolveSelectedTimezone();
    const parts = selected.mode === 'iana' && selected.timezoneId
        ? getDateTimePartsInTimeZone(date, selected.timezoneId)
        : getDateTimePartsWithOffset(date, selected.offsetMinutes);

    const year = parts.year;
    const month = parts.month;
    const day = parts.day;
    const hours = parts.hour;
    const minutes = parts.minute;
    const seconds = parts.second;

    // Route the current value to the matching UI behaviour.
    switch (format) {
        case 'full':
            // Return the prepared value to the caller.
            return `${year}-${month}-${day} ${hours}:${minutes}:${seconds} (${getTimezoneLabel()})`;
        case 'datetime':
            return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
        case 'date':
            return `${year}-${month}-${day}`;
        case 'time':
            return `${hours}:${minutes}:${seconds}`;
        case 'short':
            return `${month}/${day} ${hours}:${minutes}`;
        default:
            // Return the prepared value to the caller.
            return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
    }
}

// Section: handle the get relative time workflow.
function getRelativeTime(timestamp) {
    const date = normalizeTimestampInput(timestamp);
    // Choose the correct browser state branch before continuing.
    if (!date) return 'Unknown';

    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHour = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHour / 24);

    if (diffSec < 60) return 'Just now';
    // Choose the correct browser state branch before continuing.
    if (diffMin < 60) return `${diffMin} minute${diffMin > 1 ? 's' : ''} ago`;
    if (diffHour < 24) return `${diffHour} hour${diffHour > 1 ? 's' : ''} ago`;
    if (diffDay < 7) return `${diffDay} day${diffDay > 1 ? 's' : ''} ago`;

    return formatTimestamp(timestamp, 'date');
}

// Section: handle the format date time workflow.
function formatDateTime(timestamp) {
    return formatTimestamp(timestamp, 'datetime');
}

// Section: handle the format date workflow.
function formatDate(timestamp) {
    // Return the prepared value to the caller.
    return formatTimestamp(timestamp, 'date');
}

// Section: handle the format time workflow.
function formatTime(timestamp) {
    return formatTimestamp(timestamp, 'time');
}

// Section: handle the notify timezone change workflow.
function notifyTimezoneChange(message) {
    if (typeof NotificationManager !== 'undefined') {
        NotificationManager.info(message);
        // Return the prepared value to the caller.
        return;
    }
    // Choose the correct browser state branch before continuing.
    if (typeof showNotification === 'function') {
        showNotification(message, 'info');
        return;
    }
    console.log(message);
}

// Section: handle the dispatch timezone changed workflow.
function dispatchTimezoneChanged() {
    window.dispatchEvent(new CustomEvent('ppe-timezone:changed', {
        detail: {
            offset: getTimezoneOffset(),
            label: getTimezoneLabel(),
            timezoneId: getTimezoneId(),
            databaseTimezone: timezoneState.databaseTimezoneId,
            changedAt: Date.now()
        }
    }));
}

// Section: handle the bind timezone selector workflow.
function bindTimezoneSelector(selector) {
    // Choose the correct browser state branch before continuing.
    if (!selector) return;
    if (selector.dataset.timezoneBound === 'true') return;

    selector.dataset.timezoneBound = 'true';
    selector.addEventListener('change', () => {
        persistSelectionFromSelector(selector);
        notifyTimezoneChange(`Timezone changed to ${getTimezoneLabel()}`);
        updateAllTimestamps();
        dispatchTimezoneChanged();
    });
}

// Section: handle the refresh database timezone context workflow.
function refreshDatabaseTimezoneContext(selector) {
    // Choose the correct browser state branch before continuing.
    if (timezoneState.syncPromise) return timezoneState.syncPromise;

    timezoneState.syncPromise = fetch('/api/system/timezone', { cache: 'no-store' })
        .then((response) => {
            // Choose the correct browser state branch before continuing.
            if (!response.ok) {
                throw new Error(`timezone endpoint failed: ${response.status}`);
            }
            return response.json();
        })
        .then((payload) => {
            if (!payload || payload.success === false) {
                throw new Error((payload && payload.error) || 'timezone payload invalid');
            }

            const timezoneId = String(payload.database_timezone || '').trim();
            const offsetMinutes = Number(payload.database_utc_offset_minutes);
            // Choose the correct browser state branch before continuing.
            if (timezoneId) {
                timezoneState.databaseTimezoneId = timezoneId;
            }
            if (Number.isFinite(offsetMinutes)) {
                timezoneState.databaseOffsetMinutes = Math.round(offsetMinutes);
            }
            timezoneState.databaseOffsetLabel = String(
                payload.database_offset_label || formatOffsetLabelFromMinutes(timezoneState.databaseOffsetMinutes)
            );
            timezoneState.synced = true;

            // Choose the correct browser state branch before continuing.
            if (selector) {
                ensureDatabaseTimezoneOption(selector);
                // Choose the correct browser state branch before continuing.
                if (!hasUserTimezonePreference()) {
                    // Choose the correct browser state branch before continuing.
                    if (getSelectorOption(selector, (option) => option.value === timezoneState.databaseTimezoneId)) {
                        selector.value = timezoneState.databaseTimezoneId;
                    }
                    persistSelectionFromSelector(selector);
                }
            }

            updateAllTimestamps();
        })
        .catch(() => {
            timezoneState.synced = true;
        })
        .finally(() => {
            timezoneState.syncPromise = null;
        });

    // Return the prepared value to the caller.
    return timezoneState.syncPromise;
}

// Section: handle the init timezone selector workflow.
function initTimezoneSelector() {
    initSelector('timezone-selector');
}

// Section: handle the init selector workflow.
function initSelector(selectorId = 'timezone-selector') {
    const selector = document.getElementById(selectorId);
    if (!selector) return;

    ensureDatabaseTimezoneOption(selector);
    syncSelectorToStoredPreference(selector);
    bindTimezoneSelector(selector);
    updateAllTimestamps();
    refreshDatabaseTimezoneContext(selector);
}

// Section: handle the update all timestamps workflow.
function updateAllTimestamps() {
    document.querySelectorAll('[data-timestamp]').forEach((element) => {
        const timestamp = element.getAttribute('data-timestamp');
        const format = element.getAttribute('data-format') || 'full';
        element.textContent = formatTimestamp(timestamp, format);
    });

    document.querySelectorAll('[data-timestamp-relative]').forEach((element) => {
        const timestamp = element.getAttribute('data-timestamp-relative');
        element.textContent = getRelativeTime(timestamp);
    });
}

// Choose the correct browser state branch before continuing.
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTimezoneSelector);
} else {
    initTimezoneSelector();
}

window.TimezoneUtils = {
    getTimezoneOffset,
    setTimezoneOffset,
    getTimezoneId,
    setTimezoneId,
    getTimezoneLabel,
    getDatabaseTimezoneInfo,
    convertToLocalTime,
    formatTimestamp,
    formatDateTime,
    formatDate,
    formatTime,
    initSelector,
    getRelativeTime,
    updateAllTimestamps,
    refreshDatabaseTimezoneContext
};

window.TimezoneManager = {
    getTimezoneOffset,
    setTimezoneOffset,
    getTimezoneId,
    setTimezoneId,
    getTimezoneLabel,
    getDatabaseTimezoneInfo,
    convertToLocalTime,
    formatTimestamp,
    formatDateTime,
    formatDate,
    formatTime,
    initSelector,
    getRelativeTime,
    updateAllTimestamps,
    refreshDatabaseTimezoneContext
};
