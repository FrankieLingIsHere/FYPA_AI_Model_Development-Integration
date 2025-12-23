// Notification System for LUNA PPE Monitor
// ==========================================
// Toast notifications for violation detection and report generation

const NotificationManager = {
    container: null,
    notifications: [],

    init() {
        if (this.container) return;

        // Create notification container
        this.container = document.createElement('div');
        this.container.id = 'notification-container';
        this.container.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 10000;
            display: flex;
            flex-direction: column;
            gap: 10px;
            max-width: 400px;
        `;
        document.body.appendChild(this.container);
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
            padding: 16px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            display: flex;
            align-items: start;
            gap: 12px;
            min-width: 300px;
            animation: slideInRight 0.3s ease-out;
            cursor: pointer;
        `;

        notification.innerHTML = `
            <div style="flex-shrink: 0; font-size: 24px; color: ${colors[type]};">
                <i class="fas ${icons[type] || icons.info}"></i>
            </div>
            <div style="flex: 1; min-width: 0;">
                ${options.title ? `<div style="font-weight: 600; margin-bottom: 4px; color: #2c3e50;">${options.title}</div>` : ''}
                <div style="color: #7f8c8d; font-size: 14px; word-wrap: break-word;">${message}</div>
                ${options.action ? `
                    <button onclick="${options.action.onClick}" style="
                        margin-top: 8px;
                        padding: 6px 12px;
                        background: ${colors[type]};
                        color: white;
                        border: none;
                        border-radius: 4px;
                        cursor: pointer;
                        font-size: 13px;
                    ">
                        ${options.action.text}
                    </button>
                ` : ''}
            </div>
            <button onclick="NotificationManager.dismiss('${id}')" style="
                background: none;
                border: none;
                color: #95a5a6;
                cursor: pointer;
                font-size: 18px;
                flex-shrink: 0;
            ">
                <i class="fas fa-times"></i>
            </button>
        `;

        // Click to dismiss
        notification.addEventListener('click', (e) => {
            if (e.target.tagName !== 'BUTTON') {
                this.dismiss(id);
            }
        });

        this.container.appendChild(notification);
        this.notifications.push({ id, element: notification });

        // Auto dismiss
        if (duration > 0) {
            setTimeout(() => this.dismiss(id), duration);
        }

        return id;
    },

    dismiss(id) {
        const notif = this.notifications.find(n => n.id == id);
        if (notif) {
            notif.element.style.animation = 'slideOutRight 0.3s ease-out';
            setTimeout(() => {
                notif.element.remove();
                this.notifications = this.notifications.filter(n => n.id !== id);
            }, 300);
        }
    },

    dismissAll() {
        this.notifications.forEach(n => this.dismiss(n.id));
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
        return this.show(message, 'violation', 0, {
            title: '🚨 PPE Violation Detected',
            action: {
                text: 'View Report',
                onClick: `window.location.hash = '#/reports'; NotificationManager.dismiss('${reportId}')`
            },
            ...options
        });
    },

    reportGenerating(reportId, options = {}) {
        return this.show(
            'AI is analyzing the violation and generating a detailed safety report...',
            'report',
            10000,
            {
                title: '📝 Generating Report',
                action: {
                    text: 'View Progress',
                    onClick: `window.location.hash = '#/reports'; NotificationManager.dismiss('${reportId}')`
                },
                ...options
            }
        );
    },

    reportReady(reportId, options = {}) {
        return this.show(
            'Safety report is ready for review',
            'success',
            8000,
            {
                title: '✅ Report Complete',
                action: {
                    text: 'Open Report',
                    onClick: `window.open('${API_CONFIG.BASE_URL}/report/${reportId}', '_blank'); NotificationManager.dismiss('${reportId}')`
                },
                ...options
            }
        );
    }
};

// Add CSS animation
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInRight {
        from {
            transform: translateX(400px);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }

    @keyframes slideOutRight {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(400px);
            opacity: 0;
        }
    }

    .notification:hover {
        box-shadow: 0 6px 16px rgba(0,0,0,0.2);
        transform: translateY(-2px);
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
