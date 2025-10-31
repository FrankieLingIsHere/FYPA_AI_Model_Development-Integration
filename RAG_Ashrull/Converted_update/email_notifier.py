"""
Email Notification System for AI Safety Inspector
Sends email alerts when safety analysis is completed
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
import json

class EmailNotifier:
    """
    Email notification service for sending analysis results
    """
    
    def __init__(self, smtp_server, smtp_port, sender_email, sender_password):
        """
        Initialize email notifier
        
        Args:
            smtp_server: SMTP server address (e.g., 'smtp.gmail.com')
            smtp_port: SMTP port (587 for TLS, 465 for SSL)
            sender_email: Email address to send from
            sender_password: App password for email account
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender_email = sender_email
        self.sender_password = sender_password
        
    def send_analysis_notification(self, recipient_email, analysis_data, scenario_text):
        """
        Send email notification with analysis results
        
        Args:
            recipient_email: Email address to send notification to
            analysis_data: Dictionary containing analysis results
            scenario_text: Original scenario text
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            # Create message
            message = MIMEMultipart("alternative")
            message["Subject"] = f"⚠️ Safety Analysis Alert - {analysis_data.get('risk_level', 'UNKNOWN')} Risk Detected"
            message["From"] = self.sender_email
            message["To"] = recipient_email
            message["Date"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S")
            
            # Create email body
            html_body = self._create_html_email(analysis_data, scenario_text)
            text_body = self._create_text_email(analysis_data, scenario_text)
            
            # Attach both plain text and HTML versions
            part1 = MIMEText(text_body, "plain")
            part2 = MIMEText(html_body, "html")
            
            message.attach(part1)
            message.attach(part2)
            
            # Send email
            print(f"\n📧 Sending email notification to: {recipient_email}")
            
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()  # Secure the connection
                server.login(self.sender_email, self.sender_password)
                server.send_message(message)
            
            print(f"✅ Email notification sent successfully!")
            return True
            
        except Exception as e:
            print(f"❌ Failed to send email: {e}")
            return False
    
    def _create_html_email(self, analysis_data, scenario_text):
        """Create HTML formatted email"""
        
        risk_level = analysis_data.get('risk_level', 'UNKNOWN')
        confidence = analysis_data.get('confidence_score', '0')
        persons = analysis_data.get('persons', [])
        
        # Risk level color coding
        risk_colors = {
            'HIGH': '#e74c3c',
            'MEDIUM': '#f39c12',
            'LOW': '#2ecc71'
        }
        risk_color = risk_colors.get(risk_level, '#95a5a6')
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 30px;
                    border-radius: 10px;
                    text-align: center;
                    margin-bottom: 30px;
                }}
                .risk-badge {{
                    background-color: {risk_color};
                    color: white;
                    padding: 10px 20px;
                    border-radius: 50px;
                    font-size: 18px;
                    font-weight: bold;
                    display: inline-block;
                    margin: 10px 0;
                }}
                .confidence {{
                    font-size: 14px;
                    opacity: 0.9;
                }}
                .section {{
                    background: #f8f9fa;
                    padding: 20px;
                    border-radius: 8px;
                    margin-bottom: 20px;
                    border-left: 4px solid #3498db;
                }}
                .section h3 {{
                    margin-top: 0;
                    color: #2c3e50;
                }}
                .worker-card {{
                    background: white;
                    padding: 15px;
                    border-radius: 8px;
                    margin-bottom: 15px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .ppe-status {{
                    display: inline-block;
                    padding: 5px 10px;
                    border-radius: 5px;
                    font-size: 12px;
                    font-weight: bold;
                    margin: 2px;
                }}
                .ppe-mentioned {{
                    background: #d1fae5;
                    color: #065f46;
                }}
                .ppe-missing {{
                    background: #fee2e2;
                    color: #991b1b;
                }}
                .ppe-not-mentioned {{
                    background: #f1f5f9;
                    color: #475569;
                }}
                ul {{
                    padding-left: 20px;
                }}
                li {{
                    margin-bottom: 8px;
                }}
                .footer {{
                    text-align: center;
                    color: #7f8c8d;
                    font-size: 12px;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid #ecf0f1;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🦺 AI Safety Inspector Alert</h1>
                <div class="risk-badge">{risk_level} RISK DETECTED</div>
                <div class="confidence">Confidence: {confidence}%</div>
                <p style="font-size: 14px; margin: 10px 0 0 0;">
                    {datetime.now().strftime("%B %d, %Y at %I:%M %p")}
                </p>
            </div>
            
            <div class="section">
                <h3>📋 Scenario Analyzed</h3>
                <p><strong>{scenario_text}</strong></p>
            </div>
            
            <div class="section">
                <h3>👥 Workers Detected: {len(persons)}</h3>
        """
        
        # Add each worker's details
        for person in persons:
            worker_id = person.get('id', 1)
            description = person.get('description', '')
            ppe = person.get('ppe', {})
            hazards = person.get('hazards_faced', [])
            risks = person.get('risks', [])
            actions = person.get('actions', [])
            
            html += f"""
                <div class="worker-card">
                    <h4>Worker {worker_id}</h4>
                    <p><em>{description}</em></p>
                    
                    <p><strong>🦺 PPE Status:</strong></p>
                    <div>
            """
            
            # PPE status badges
            for ppe_item, status in ppe.items():
                ppe_class = 'ppe-mentioned' if status == 'Mentioned' else (
                    'ppe-missing' if status == 'Missing' else 'ppe-not-mentioned'
                )
                icon = '✅' if status == 'Mentioned' else ('❌' if status == 'Missing' else '⚠️')
                html += f'<span class="ppe-status {ppe_class}">{icon} {ppe_item.replace("_", " ").title()}: {status}</span> '
            
            html += """
                    </div>
            """
            
            # Add hazards if any
            if hazards:
                html += """
                    <p><strong>⚠️ Hazards Faced:</strong></p>
                    <ul>
                """
                for hazard in hazards[:3]:
                    html += f"<li>{hazard}</li>"
                html += "</ul>"
            
            # Add risks if any
            if risks:
                html += """
                    <p><strong>🛡️ Potential Risks:</strong></p>
                    <ul>
                """
                for risk in risks[:3]:
                    html += f"<li>{risk}</li>"
                html += "</ul>"
            
            # Add actions if any
            if actions:
                html += """
                    <p><strong>📋 Suggested Actions:</strong></p>
                    <ul>
                """
                for action in actions[:3]:
                    html += f"<li>{action}</li>"
                html += "</ul>"
            
            html += "</div>"
        
        html += """
            </div>
            
            <div class="footer">
                <p>This is an automated notification from AI Safety Inspector</p>
                <p>Powered by RAG-based PPE Violation Detection System</p>
            </div>
        </body>
        </html>
        """
        
        return html
    
    def _create_text_email(self, analysis_data, scenario_text):
        """Create plain text email"""
        
        risk_level = analysis_data.get('risk_level', 'UNKNOWN')
        confidence = analysis_data.get('confidence_score', '0')
        persons = analysis_data.get('persons', [])
        
        text = f"""
AI SAFETY INSPECTOR ALERT
========================

RISK LEVEL: {risk_level}
Confidence: {confidence}%
Date: {datetime.now().strftime("%B %d, %Y at %I:%M %p")}

SCENARIO ANALYZED:
{scenario_text}

WORKERS DETECTED: {len(persons)}
"""
        
        for person in persons:
            worker_id = person.get('id', 1)
            description = person.get('description', '')
            ppe = person.get('ppe', {})
            hazards = person.get('hazards_faced', [])
            risks = person.get('risks', [])
            actions = person.get('actions', [])
            
            text += f"""
---
WORKER {worker_id}
Description: {description}

PPE Status:
"""
            for ppe_item, status in ppe.items():
                icon = '✓' if status == 'Mentioned' else ('✗' if status == 'Missing' else '?')
                text += f"  {icon} {ppe_item.replace('_', ' ').title()}: {status}\n"
            
            if hazards:
                text += "\nHazards Faced:\n"
                for hazard in hazards[:3]:
                    text += f"  - {hazard}\n"
            
            if risks:
                text += "\nPotential Risks:\n"
                for risk in risks[:3]:
                    text += f"  - {risk}\n"
            
            if actions:
                text += "\nSuggested Actions:\n"
                for action in actions[:3]:
                    text += f"  - {action}\n"
        
        text += """
---
This is an automated notification from AI Safety Inspector
Powered by RAG-based PPE Violation Detection System
"""
        
        return text


# Configuration and convenience functions
def load_email_config(config_file='email_config.json'):
    """
    Load email configuration from JSON file
    
    Returns:
        dict: Email configuration
    """
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        print(f"⚠️ Email config file not found: {config_file}")
        print("💡 Using default configuration (update email_config.json)")
        return {
            "smtp_server": "smtp.gmail.com",
            "smtp_port": 587,
            "sender_email": "your-email@gmail.com",
            "sender_password": "your-app-password",
            "recipient_email": "admin@example.com",
            "enabled": False
        }


def send_notification(analysis_data, scenario_text, config=None):
    """
    Convenience function to send notification
    
    Args:
        analysis_data: Analysis results dictionary
        scenario_text: Original scenario text
        config: Email configuration (optional, will load from file if not provided)
        
    Returns:
        bool: True if sent successfully
    """
    if config is None:
        config = load_email_config()
    
    # Check if notifications are enabled
    if not config.get('enabled', False):
        print("ℹ️ Email notifications are disabled in config")
        return False
    
    # Create notifier and send
    notifier = EmailNotifier(
        smtp_server=config['smtp_server'],
        smtp_port=config['smtp_port'],
        sender_email=config['sender_email'],
        sender_password=config['sender_password']
    )
    
    return notifier.send_analysis_notification(
        recipient_email=config['recipient_email'],
        analysis_data=analysis_data,
        scenario_text=scenario_text
    )


# Example usage
if __name__ == "__main__":
    # Test the email notifier
    print("Testing Email Notifier...")
    
    # Sample analysis data
    test_data = {
        'risk_level': 'HIGH',
        'confidence_score': '85',
        'persons': [
            {
                'id': 1,
                'description': 'Worker bending down cutting concrete',
                'ppe': {
                    'hardhat': 'Missing',
                    'safety_glasses': 'Missing',
                    'gloves': 'Missing',
                    'safety_vest': 'Not Mentioned',
                    'footwear': 'Not Mentioned'
                },
                'hazards_faced': ['Dust exposure', 'Flying debris'],
                'risks': ['Head injury risk', 'Eye injury risk'],
                'actions': ['Wear hardhat immediately', 'Wear safety glasses']
            }
        ]
    }
    
    test_scenario = "A worker cutting concrete without proper PPE"
    
    # Load config and send
    config = load_email_config()
    if config.get('enabled'):
        send_notification(test_data, test_scenario, config)
    else:
        print("⚠️ Email notifications disabled. Update email_config.json to enable.")

