// Timezone Management Utility
// Provides timezone selection and date formatting with Malaysian Time (MYT, UTC+8) as default

const TimezoneManager = {
    // Malaysian Time as default
    DEFAULT_TIMEZONE: 'Asia/Kuala_Lumpur',
    STORAGE_KEY: 'luna_timezone',

    // Available timezones for dropdown
    TIMEZONES: [
        { id: 'Asia/Kuala_Lumpur', label: 'Malaysian Time (MYT, UTC+8)', offset: '+08:00' },
        { id: 'Asia/Singapore', label: 'Singapore Time (SGT, UTC+8)', offset: '+08:00' },
        { id: 'Asia/Jakarta', label: 'Indonesia Time (WIB, UTC+7)', offset: '+07:00' },
        { id: 'Asia/Bangkok', label: 'Thailand Time (ICT, UTC+7)', offset: '+07:00' },
        { id: 'Asia/Tokyo', label: 'Japan Time (JST, UTC+9)', offset: '+09:00' },
        { id: 'Asia/Shanghai', label: 'China Time (CST, UTC+8)', offset: '+08:00' },
        { id: 'Australia/Sydney', label: 'Australia Eastern (AEST, UTC+10/+11)', offset: '+10:00' },
        { id: 'Europe/London', label: 'UK Time (GMT/BST)', offset: '+00:00' },
        { id: 'America/New_York', label: 'US Eastern (EST/EDT)', offset: '-05:00' },
        { id: 'America/Los_Angeles', label: 'US Pacific (PST/PDT)', offset: '-08:00' },
        { id: 'UTC', label: 'UTC (Coordinated Universal Time)', offset: '+00:00' },
    ],

    /**
     * Get the currently selected timezone
     * @returns {string} Timezone ID (e.g., 'Asia/Kuala_Lumpur')
     */
    getCurrentTimezone() {
        try {
            const stored = localStorage.getItem(this.STORAGE_KEY);
            if (stored && this.TIMEZONES.some(tz => tz.id === stored)) {
                return stored;
            }
        } catch (e) {
            console.warn('Error reading timezone from localStorage:', e);
        }
        return this.DEFAULT_TIMEZONE;
    },

    /**
     * Set the timezone preference
     * @param {string} timezoneId - Timezone ID to set
     * @returns {boolean} Success status
     */
    setTimezone(timezoneId) {
        if (!this.TIMEZONES.some(tz => tz.id === timezoneId)) {
            console.warn('Invalid timezone:', timezoneId);
            return false;
        }

        try {
            localStorage.setItem(this.STORAGE_KEY, timezoneId);
            // Dispatch event for components to update
            window.dispatchEvent(new CustomEvent('timezoneChanged', {
                detail: { timezone: timezoneId }
            }));
            return true;
        } catch (e) {
            console.error('Error saving timezone to localStorage:', e);
            return false;
        }
    },

    /**
     * Format a date using the selected timezone
     * @param {Date|string} date - Date to format
     * @param {Object} options - Intl.DateTimeFormat options (optional)
     * @returns {string} Formatted date string
     */
    formatDate(date, options = {}) {
        const dateObj = this.parseServerTimestamp ? this.parseServerTimestamp(date) :
            (date instanceof Date ? date : new Date(date));

        if (isNaN(dateObj.getTime())) {
            console.warn('Invalid date provided to formatDate:', date);
            return 'Invalid Date';
        }

        const defaultOptions = {
            timeZone: this.getCurrentTimezone(),
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            ...options
        };

        try {
            return new Intl.DateTimeFormat('en-MY', defaultOptions).format(dateObj);
        } catch (e) {
            console.error('Error formatting date:', e);
            return dateObj.toLocaleDateString();
        }
    },

    /**
     * Parse a timestamp from the server, treating it as MYT if no timezone specified.
     * Server timestamps are in Malaysian Time but may lack timezone suffix.
     * @param {Date|string} date - Date to parse
     * @returns {Date} Properly parsed Date object
     */
    parseServerTimestamp(date) {
        if (date instanceof Date) {
            return date;
        }

        const dateStr = String(date);

        // If timestamp already has timezone info (Z, +, or -), parse directly
        if (dateStr.includes('Z') || dateStr.includes('+') || /T.*-/.test(dateStr)) {
            return new Date(dateStr);
        }

        // No timezone info - assume it's MYT (UTC+8)
        // Append +08:00 to treat as Malaysian Time
        return new Date(dateStr + '+08:00');
    },

    /**
     * Format a date and time using the selected timezone
     * @param {Date|string} date - Date to format (assumed to be MYT if no TZ specified)
     * @returns {string} Formatted date and time string
     */
    formatDateTime(date) {
        const dateObj = this.parseServerTimestamp(date);

        if (isNaN(dateObj.getTime())) {
            console.warn('Invalid date provided to formatDateTime:', date);
            return 'Invalid Date';
        }

        const options = {
            timeZone: this.getCurrentTimezone(),
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true
        };

        try {
            return new Intl.DateTimeFormat('en-MY', options).format(dateObj);
        } catch (e) {
            console.error('Error formatting datetime:', e);
            return dateObj.toLocaleString();
        }
    },

    /**
     * Format time only using the selected timezone
     * @param {Date|string} date - Date to format
     * @returns {string} Formatted time string
     */
    formatTime(date) {
        const dateObj = date instanceof Date ? date : new Date(date);

        if (isNaN(dateObj.getTime())) {
            return 'Invalid Time';
        }

        const options = {
            timeZone: this.getCurrentTimezone(),
            hour: '2-digit',
            minute: '2-digit',
            hour12: true
        };

        try {
            return new Intl.DateTimeFormat('en-MY', options).format(dateObj);
        } catch (e) {
            return dateObj.toLocaleTimeString();
        }
    },

    /**
     * Get the current time in the selected timezone
     * @returns {string} Current time formatted
     */
    getCurrentTime() {
        return this.formatTime(new Date());
    },

    /**
     * Get timezone label for display
     * @param {string} timezoneId - Timezone ID (optional, uses current if not provided)
     * @returns {string} Timezone label
     */
    getTimezoneLabel(timezoneId = null) {
        const tz = timezoneId || this.getCurrentTimezone();
        const found = this.TIMEZONES.find(t => t.id === tz);
        return found ? found.label : tz;
    },

    /**
     * Get short timezone abbreviation
     * @returns {string} Short timezone code (e.g., "MYT")
     */
    getTimezoneAbbreviation() {
        const tz = this.getCurrentTimezone();
        // Extract abbreviation from label
        const found = this.TIMEZONES.find(t => t.id === tz);
        if (found) {
            const match = found.label.match(/\(([A-Z]{2,4})/);
            return match ? match[1] : 'TZ';
        }
        return 'TZ';
    },

    /**
     * Initialize the custom timezone dropdown in the UI
     */
    initSelector() {
        const dropdown = document.getElementById('timezoneDropdown');
        const optionsContainer = document.getElementById('timezoneOptions');
        const selectedText = document.getElementById('selectedTimezoneText');
        const selectedEl = dropdown ? dropdown.querySelector('.tz-selected') : null;

        if (!dropdown || !optionsContainer || !selectedText) {
            console.warn('Timezone dropdown elements not found');
            return;
        }

        // Toggle Dropdown
        selectedEl.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('active');
        });

        // Close when clicking outside
        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target)) {
                dropdown.classList.remove('active');
            }
        });

        // Float-up behavior: Close when mouse leaves the sidebar area
        const sidebar = document.querySelector('.sidebar');
        if (sidebar) {
            sidebar.addEventListener('mouseleave', () => {
                dropdown.classList.remove('active');
            });
        }

        // Populate Options
        this.renderOptions(optionsContainer, selectedText, dropdown);
    },

    renderOptions(container, labelEl, dropdown) {
        container.innerHTML = '';
        const currentTz = this.getCurrentTimezone();

        // Update Label
        const currentData = this.TIMEZONES.find(t => t.id === currentTz);
        if (currentData) {
            labelEl.textContent = currentData.label;
        } else {
            // Custom timezone support
            labelEl.textContent = currentTz;
        }

        this.TIMEZONES.forEach(tz => {
            const div = document.createElement('div');
            div.className = `tz-option ${tz.id === currentTz ? 'selected' : ''}`;
            div.textContent = tz.label;

            div.addEventListener('click', (e) => {
                e.stopPropagation();

                // Normal selection
                this.setTimezone(tz.id);
                console.log('Timezone changed to:', tz.id);
                labelEl.textContent = tz.label;
                dropdown.classList.remove('active');
                this.renderOptions(container, labelEl, dropdown);
            });

            container.appendChild(div);
        });

        // Add "Other..." Option
        const otherDiv = document.createElement('div');
        otherDiv.className = 'tz-option';
        otherDiv.innerHTML = '<i class="fas fa-edit"></i> Other...';
        otherDiv.addEventListener('click', (e) => {
            e.stopPropagation();
            const userInput = prompt("Enter your IANA Timezone (e.g. 'Europe/Paris' or 'Asia/Dubai'):");
            if (userInput && userInput.trim() !== "") {
                try {
                    // Validate timezone
                    Intl.DateTimeFormat(undefined, { timeZone: userInput });

                    // Save custom standard
                    this.setTimezone(userInput);
                    labelEl.textContent = userInput;
                    dropdown.classList.remove('active');
                    this.renderOptions(container, labelEl, dropdown);
                } catch (err) {
                    alert("Invalid Timezone ID. Please use format like 'Asia/Dubai'");
                }
            }
        });
        container.appendChild(otherDiv);
    }
};

// Make globally available
window.TimezoneManager = TimezoneManager;
