// Notification System for LUNA PPE Monitor
// ==========================================
// Toast notifications for violation detection and report generation
// Enhanced: Bottom-right positioning, grouped notifications, max 3 visible

const NotificationManager = {
    container: null,
    notifications: [],
    maxVisible: 3,  // Maximum notifications shown at once
    groupedCount: 0,  // Count of hidden notifications

    init() {
        if (this.container) return;

        // Create notification container - BOTTOM RIGHT to avoid blocking controls
        this.container = document.createElement('div');
        this.container.id = 'notification-container';
        this.container.style.cssText = `
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 10000;
            display: flex;
            flex-direction: column-reverse;
            gap: 10px;
            max-width: 380px;
            max-height: calc(100vh - 100px);
            pointer-events: none;
        `;
        document.body.appendChild(this.container);

        // Create summary badge for grouped notifications
        this.summaryBadge = document.createElement('div');
        this.summaryBadge.id = 'notification-summary';
        this.summaryBadge.style.cssText = `
            display: none;
            background: linear-gradient(135deg, #3498db, #2980b9);
            color: white;
            padding: 12px 16px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            pointer-events: auto;
            text-align: center;
        `;
        this.summaryBadge.innerHTML = `
            <i class="fas fa-bell"></i>
            <span id="grouped-count">0</span> more notifications
            <span style="display: block; font-size: 12px; opacity: 0.8; margin-top: 4px;">
                Click to dismiss all
            </span>
        `;
        this.summaryBadge.addEventListener('click', () => this.dismissAll());
        this.container.appendChild(this.summaryBadge);
    },

    updateSummaryBadge() {
        const visibleCount = this.notifications.length;
        const hiddenCount = Math.max(0, visibleCount - this.maxVisible);

        if (hiddenCount > 0) {
            this.summaryBadge.style.display = 'block';
            document.getElementById('grouped-count').textContent = hiddenCount;
        } else {
            this.summaryBadge.style.display = 'none';
        }

        // Hide older notifications when over limit
        this.notifications.forEach((notif, index) => {
            if (index < visibleCount - this.maxVisible) {
                notif.element.style.display = 'none';
            } else {
                notif.element.style.display = 'flex';
            }
        });
    },

    show(message, type = 'info', duration = 5000, options = {}) {
        this.init();

        const id = Date.now() + Math.random();

        const notification = document.createElement('div');
        notification.id = `notif-${id}`;
        notification.className = `notification notification-${type}`;

        const icons = {
            'success': 'fa-check-circle',
            'error': 'fa-exclamation-circle',
            'warning': 'fa-exclamation-triangle',
            'info': 'fa-info-circle',
            'violation': 'fa-hard-hat',
            'report': 'fa-file-alt'
        };

        const colors = {
            'success': '#2ecc71',
            'error': '#e74c3c',
            'warning': '#f39c12',
            'info': '#3498db',
            'violation': '#e74c3c',
            'report': '#3498db'
        };

        notification.style.cssText = `
            background: white;
            border-left: 4px solid ${colors[type] || colors.info};
            border-radius: 8px;
            padding: 14px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            display: flex;
            align-items: start;
            gap: 10px;
            min-width: 280px;
            max-width: 100%;
            animation: slideInUp 0.3s ease-out;
            cursor: pointer;
            pointer-events: auto;
        `;

        // Simplified content for cleaner look
        const titleHtml = options.title ?
            `<div style="font-weight: 600; margin-bottom: 2px; color: #2c3e50; font-size: 13px;">${options.title}</div>` : '';

        notification.innerHTML = `
            <div style="flex-shrink: 0; font-size: 20px; color: ${colors[type]};">
                <i class="fas ${icons[type] || icons.info}"></i>
            </div>
            <div style="flex: 1; min-width: 0;">
                ${titleHtml}
                <div style="color: #7f8c8d; font-size: 13px; word-wrap: break-word; line-height: 1.4;">${message}</div>
                ${options.action ? `
                    <button onclick="${options.action.onClick}; event.stopPropagation();" style="
                        margin-top: 8px;
                        padding: 5px 10px;
                        background: ${colors[type]};
                        color: white;
                        border: none;
                        border-radius: 4px;
                        cursor: pointer;
                        font-size: 12px;
                    ">
                        ${options.action.text}
                    </button>
                ` : ''}
            </div>
            <button onclick="event.stopPropagation(); NotificationManager.dismiss('${id}')" style="
                background: none;
                border: none;
                color: #bdc3c7;
                cursor: pointer;
                font-size: 14px;
                flex-shrink: 0;
                padding: 0;
            ">
                <i class="fas fa-times"></i>
            </button>
        `;

        // Click anywhere to dismiss
        notification.addEventListener('click', (e) => {
            if (e.target.tagName !== 'BUTTON') {
                this.dismiss(id);
            }
        });

        this.container.insertBefore(notification, this.summaryBadge);
        this.notifications.push({ id, element: notification, type, timestamp: Date.now() });

        this.updateSummaryBadge();

        // Auto dismiss
        if (duration > 0) {
            setTimeout(() => this.dismiss(id), duration);
        }

        return id;
    },

    dismiss(id) {
        const index = this.notifications.findIndex(n => n.id == id);
        if (index !== -1) {
            const notif = this.notifications[index];
            notif.element.style.animation = 'slideOutDown 0.3s ease-out';
            setTimeout(() => {
                notif.element.remove();
                this.notifications.splice(index, 1);
                this.updateSummaryBadge();
            }, 300);
        }
    },

    dismissAll() {
        const ids = this.notifications.map(n => n.id);
        ids.forEach(id => this.dismiss(id));
    },

    // Convenience methods
    success(message, options = {}) {
        return this.show(message, 'success', options.duration || 4000, options);
    },

    error(message, options = {}) {
        return this.show(message, 'error', options.duration || 6000, options);
    },

    warning(message, options = {}) {
        return this.show(message, 'warning', options.duration || 5000, options);
    },

    info(message, options = {}) {
        return this.show(message, 'info', options.duration || 4000, options);
    },

    violation(message, reportId, options = {}) {
        return this.show(message, 'violation', 8000, {
            title: '🚨 Violation Detected',
            action: {
                text: 'View Reports',
                onClick: `window.location.hash = '#/reports'`
            },
            ...options
        });
    },

    reportGenerating(reportId, options = {}) {
        return this.show(
            'Generating safety report...',
            'report',
            8000,
            {
                title: '📝 Processing',
                ...options
            }
        );
    },

    reportReady(reportId, options = {}) {
        return this.show(
            'Report ready for review',
            'success',
            6000,
            {
                title: '✅ Complete',
                action: {
                    text: 'Open',
                    onClick: `window.open('${API_CONFIG.BASE_URL}/report/${reportId}', '_blank')`
                },
                ...options
            }
        );
    }
};

// Add CSS animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInUp {
        from {
            transform: translateY(100px);
            opacity: 0;
        }
        to {
            transform: translateY(0);
            opacity: 1;
        }
    }

    @keyframes slideOutDown {
        from {
            transform: translateY(0);
            opacity: 1;
        }
        to {
            transform: translateY(100px);
            opacity: 0;
        }
    }

    .notification:hover {
        box-shadow: 0 6px 16px rgba(0,0,0,0.2);
        transform: translateY(-2px);
        transition: all 0.2s ease;
    }
    
    #notification-summary:hover {
        background: linear-gradient(135deg, #2980b9, #1a5276);
        transform: scale(1.02);
        transition: all 0.2s ease;
    }
`;
document.head.appendChild(style);

// Initialize on load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => NotificationManager.init());
} else {
    NotificationManager.init();
}

