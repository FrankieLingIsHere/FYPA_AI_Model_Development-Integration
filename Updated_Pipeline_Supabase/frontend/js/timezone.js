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

function storageGet(key, fallback = '') {
    try {
        const value = localStorage.getItem(key);
        return value == null ? fallback : value;
    } catch (error) {
        return fallback;
    }
}

function storageSet(key, value) {
    try {
        localStorage.setItem(key, value);
    } catch (error) {
        // Ignore localStorage write failures.
    }
}

function storageRemove(key) {
    try {
        localStorage.removeItem(key);
    } catch (error) {
        // Ignore localStorage write failures.
    }
}

function isNumericTimezoneValue(value) {
    return /^[-+]?\d+(\.\d+)?$/.test(String(value || '').trim());
}

function parseOffsetHours(value) {
    const parsed = Number.parseFloat(String(value || '').trim());
    return Number.isFinite(parsed) ? parsed : null;
}

function sameOffsetHours(a, b) {
    if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
    return Math.abs(a - b) < 1e-9;
}

function formatOffsetLabelFromMinutes(offsetMinutes) {
    const safeMinutes = Number.isFinite(offsetMinutes) ? Math.round(offsetMinutes) : DEFAULT_OFFSET_MINUTES;
    const absMinutes = Math.abs(safeMinutes);
    const hours = Math.floor(absMinutes / 60);
    const minutes = absMinutes % 60;
    const sign = safeMinutes >= 0 ? '+' : '-';
    return `UTC${sign}${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
}

function hasUserTimezonePreference() {
    const storedId = String(storageGet(TIMEZONE_ID_KEY, '') || '').trim();
    const storedOffset = String(storageGet(TIMEZONE_OFFSET_KEY, '') || '').trim();
    return !!storedId || !!storedOffset;
}

function getDatabaseTimezoneInfo() {
    return {
        timezoneId: timezoneState.databaseTimezoneId,
        offsetMinutes: timezoneState.databaseOffsetMinutes,
        offsetLabel: timezoneState.databaseOffsetLabel,
        synced: !!timezoneState.synced
    };
}

function getSelectorOption(selector, predicate) {
    if (!selector || !selector.options) return null;
    const options = Array.from(selector.options);
    return options.find(predicate) || null;
}

function selectOptionForOffset(selector, offsetHours) {
    if (!selector || !Number.isFinite(offsetHours)) return false;
    const byValue = getSelectorOption(selector, (option) => {
        const optionValue = parseOffsetHours(option.value);
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
    if (byLegacy) {
        selector.value = byLegacy.value;
        return true;
    }

    return false;
}

function ensureDatabaseTimezoneOption(selector) {
    if (!selector) return;
    const timezoneId = String(timezoneState.databaseTimezoneId || '').trim();
    if (!timezoneId) return;

    const existing = getSelectorOption(selector, (option) => option.value === timezoneId);
    if (existing) {
        return;
    }

    const option = document.createElement('option');
    option.value = timezoneId;
    option.textContent = `Database (${timezoneId})`;
    option.setAttribute('data-legacy-offset', String(timezoneState.databaseOffsetMinutes / 60));
    selector.insertBefore(option, selector.firstChild || null);
}

function syncSelectorToStoredPreference(selector) {
    if (!selector) return;

    const storedId = String(storageGet(TIMEZONE_ID_KEY, '') || '').trim();
    if (storedId && getSelectorOption(selector, (option) => option.value === storedId)) {
        selector.value = storedId;
        return;
    }

    const storedOffset = parseOffsetHours(storageGet(TIMEZONE_OFFSET_KEY, ''));
    if (storedOffset !== null && selectOptionForOffset(selector, storedOffset)) {
        return;
    }

    const databaseId = String(timezoneState.databaseTimezoneId || '').trim();
    if (databaseId && getSelectorOption(selector, (option) => option.value === databaseId)) {
        selector.value = databaseId;
    }
}

function persistSelectionFromSelector(selector) {
    if (!selector) return;

    const selectedValue = String(selector.value || '').trim();
    const selectedOption = selector.options[selector.selectedIndex] || null;
    if (!selectedValue) return;

    if (isNumericTimezoneValue(selectedValue)) {
        const offsetHours = parseOffsetHours(selectedValue);
        if (offsetHours !== null) {
            storageSet(TIMEZONE_OFFSET_KEY, String(offsetHours));
        }
        storageRemove(TIMEZONE_ID_KEY);
        return;
    }

    storageSet(TIMEZONE_ID_KEY, selectedValue);
    if (selectedOption) {
        const legacyOffset = parseOffsetHours(selectedOption.getAttribute('data-legacy-offset'));
        if (legacyOffset !== null) {
            storageSet(TIMEZONE_OFFSET_KEY, String(legacyOffset));
        }
    }
}

function resolveSelectedTimezone() {
    const selector = document.getElementById('timezone-selector');
    const selectedOption = selector ? selector.options[selector.selectedIndex] : null;
    let selectedValue = selector ? String(selector.value || '').trim() : '';

    if (!selectedValue) {
        const storedId = String(storageGet(TIMEZONE_ID_KEY, '') || '').trim();
        if (storedId) {
            selectedValue = storedId;
        } else {
            const storedOffset = parseOffsetHours(storageGet(TIMEZONE_OFFSET_KEY, ''));
            if (storedOffset !== null) {
                selectedValue = String(storedOffset);
            }
        }
    }

    if (selectedValue && !isNumericTimezoneValue(selectedValue)) {
        const timezoneId = selectedValue;
        const legacyOffset = selectedOption
            ? parseOffsetHours(selectedOption.getAttribute('data-legacy-offset'))
            : null;
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

    return {
        mode: 'offset',
        timezoneId: null,
        offsetMinutes,
        label: selectedOption ? selectedOption.textContent.trim() : formatOffsetLabelFromMinutes(offsetMinutes)
    };
}

function getTimezoneOffset() {
    return resolveSelectedTimezone().offsetMinutes / 60;
}

function setTimezoneOffset(offset) {
    const offsetHours = parseOffsetHours(offset);
    if (offsetHours === null) return;

    storageSet(TIMEZONE_OFFSET_KEY, String(offsetHours));
    storageRemove(TIMEZONE_ID_KEY);

    const selector = document.getElementById('timezone-selector');
    if (selector) {
        selectOptionForOffset(selector, offsetHours);
    }
}

function getTimezoneId() {
    return resolveSelectedTimezone().timezoneId;
}

function setTimezoneId(timezoneId) {
    const normalized = String(timezoneId || '').trim();
    if (!normalized) return;

    storageSet(TIMEZONE_ID_KEY, normalized);
    const selector = document.getElementById('timezone-selector');
    if (selector && getSelectorOption(selector, (option) => option.value === normalized)) {
        selector.value = normalized;
        const selectedOption = selector.options[selector.selectedIndex] || null;
        if (selectedOption) {
            const legacyOffset = parseOffsetHours(selectedOption.getAttribute('data-legacy-offset'));
            if (legacyOffset !== null) {
                storageSet(TIMEZONE_OFFSET_KEY, String(legacyOffset));
            }
        }
    }
}

function getTimezoneLabel() {
    const resolved = resolveSelectedTimezone();
    if (resolved.label) return resolved.label;
    if (resolved.mode === 'iana' && resolved.timezoneId) return resolved.timezoneId;
    return formatOffsetLabelFromMinutes(resolved.offsetMinutes);
}

function normalizeTimestampString(raw) {
    const text = String(raw || '').trim();
    if (!text) return '';
    if (text.includes('T')) return text;
    return text.replace(' ', 'T');
}

function hasExplicitTimezoneDesignator(raw) {
    return /(Z|[+\-]\d{2}:?\d{2})$/i.test(String(raw || '').trim());
}

function parseNaiveIsoParts(raw) {
    const match = String(raw || '').trim().match(
        /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2})(?::(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?)?)?$/
    );
    if (!match) return null;

    const millisecondsRaw = match[7] || '0';
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

function getTimeZoneOffsetMinutesForInstant(date, timeZone) {
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

        return Math.round((asUtc - date.getTime()) / 60000);
    } catch (error) {
        return null;
    }
}

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
    if (offsetMinutes1 === null) return null;

    let timestampMs = guessUtc - (offsetMinutes1 * 60000);
    const offsetMinutes2 = getTimeZoneOffsetMinutesForInstant(new Date(timestampMs), timeZone);
    if (offsetMinutes2 !== null && offsetMinutes2 !== offsetMinutes1) {
        timestampMs = guessUtc - (offsetMinutes2 * 60000);
    }

    return new Date(timestampMs);
}

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
    return new Date(utcGuess - (offsetMinutes * 60000));
}

function normalizeTimestampInput(timestamp) {
    if (timestamp == null) return null;

    if (timestamp instanceof Date) {
        return Number.isNaN(timestamp.getTime()) ? null : new Date(timestamp.getTime());
    }

    if (typeof timestamp === 'number') {
        const date = new Date(timestamp);
        return Number.isNaN(date.getTime()) ? null : date;
    }

    const normalized = normalizeTimestampString(timestamp);
    if (!normalized) return null;

    if (hasExplicitTimezoneDesignator(normalized)) {
        const explicitDate = new Date(normalized);
        return Number.isNaN(explicitDate.getTime()) ? null : explicitDate;
    }

    const parts = parseNaiveIsoParts(normalized);
    if (parts) {
        if (timezoneState.databaseTimezoneId) {
            const parsedByZone = parseNaiveTimestampInTimezone(parts, timezoneState.databaseTimezoneId);
            if (parsedByZone && !Number.isNaN(parsedByZone.getTime())) {
                return parsedByZone;
            }
        }

        const fallbackOffset = Number.isFinite(timezoneState.databaseOffsetMinutes)
            ? timezoneState.databaseOffsetMinutes
            : DEFAULT_OFFSET_MINUTES;
        const parsedByOffset = parseNaiveTimestampWithOffset(parts, fallbackOffset);
        if (!Number.isNaN(parsedByOffset.getTime())) {
            return parsedByOffset;
        }
    }

    const fallbackDate = new Date(normalized);
    return Number.isNaN(fallbackDate.getTime()) ? null : fallbackDate;
}

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
        if (part.type !== 'literal') {
            map[part.type] = part.value;
        }
    });

    return {
        year: map.year,
        month: map.month,
        day: map.day,
        hour: map.hour,
        minute: map.minute,
        second: map.second
    };
}

function getDateTimePartsWithOffset(date, offsetMinutes) {
    const shifted = new Date(date.getTime() + (offsetMinutes * 60000));
    return {
        year: String(shifted.getUTCFullYear()),
        month: String(shifted.getUTCMonth() + 1).padStart(2, '0'),
        day: String(shifted.getUTCDate()).padStart(2, '0'),
        hour: String(shifted.getUTCHours()).padStart(2, '0'),
        minute: String(shifted.getUTCMinutes()).padStart(2, '0'),
        second: String(shifted.getUTCSeconds()).padStart(2, '0')
    };
}

function convertToLocalTime(timestamp) {
    const date = normalizeTimestampInput(timestamp);
    if (!date) return null;

    const selected = resolveSelectedTimezone();
    if (selected.mode === 'offset') {
        return new Date(date.getTime() + (selected.offsetMinutes * 60000));
    }
    return date;
}

function formatTimestamp(timestamp, format = 'full') {
    const date = normalizeTimestampInput(timestamp);
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

    switch (format) {
        case 'full':
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
            return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
    }
}

function getRelativeTime(timestamp) {
    const date = normalizeTimestampInput(timestamp);
    if (!date) return 'Unknown';

    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
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

function bindTimezoneSelector(selector) {
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

function refreshDatabaseTimezoneContext(selector) {
    if (timezoneState.syncPromise) return timezoneState.syncPromise;

    timezoneState.syncPromise = fetch('/api/system/timezone', { cache: 'no-store' })
        .then((response) => {
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

            if (selector) {
                ensureDatabaseTimezoneOption(selector);
                if (!hasUserTimezonePreference()) {
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

    return timezoneState.syncPromise;
}

function initTimezoneSelector() {
    initSelector('timezone-selector');
}

function initSelector(selectorId = 'timezone-selector') {
    const selector = document.getElementById(selectorId);
    if (!selector) return;

    ensureDatabaseTimezoneOption(selector);
    syncSelectorToStoredPreference(selector);
    bindTimezoneSelector(selector);
    updateAllTimestamps();
    refreshDatabaseTimezoneContext(selector);
}

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
