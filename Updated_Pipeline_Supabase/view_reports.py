"""
Supabase Report Viewer - View PPE Violation Reports from Supabase
==================================================================

Flask server to view violation reports stored in Supabase Postgres
with images and reports served via signed URLs from Supabase Storage.

Usage:
    python view_reports.py
    
    Then open browser to: http://localhost:5001
"""

from flask import Flask, render_template, send_from_directory, jsonify, abort, Response, redirect
from pathlib import Path
import json
from datetime import datetime
import logging
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import Supabase managers
from pipeline.backend.core.supabase_db import create_db_manager_from_env
from pipeline.backend.core.supabase_storage import create_storage_manager_from_env

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__, 
            template_folder='report_templates',
            static_folder='frontend',
            static_url_path='/static')

# Initialize Supabase managers
try:
    db_manager = create_db_manager_from_env()
    storage_manager = create_storage_manager_from_env()
    logger.info("Supabase managers initialized")
except Exception as e:
    logger.error(f"Failed to initialize Supabase managers: {e}")
    logger.error("Make sure SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and SUPABASE_DB_URL are set")
    raise

# =========================================================================
# ROUTES
# =========================================================================

@app.route('/')
def index():
    """Serve the modern frontend application."""
    # Try to serve from frontend directory
    frontend_index = Path('frontend/index.html')
    if frontend_index.exists():
        return send_from_directory('frontend', 'index.html')
    
    # Fallback to simple HTML
    return render_template_string(SIMPLE_INDEX)


@app.route('/api/violations')
def api_violations():
    """
    API endpoint to list all violations from Supabase.
    
    Returns JSON array of violations with metadata.
    """
    try:
        violations = db_manager.get_recent_violations(limit=100)
        
        # Format violations for API response
        formatted_violations = []
        for v in violations:
            formatted_violations.append({
                'report_id': v['report_id'],
                'timestamp': v['timestamp'].isoformat() if v.get('timestamp') else None,
                'person_count': v.get('person_count', 0),
                'violation_count': v.get('violation_count', 0),
                'severity': v.get('severity', 'UNKNOWN'),
                'violation_summary': v.get('violation_summary'),
                'has_original': bool(v.get('original_image_key')),
                'has_annotated': bool(v.get('annotated_image_key')),
                'has_report': bool(v.get('report_html_key'))
            })
        
        return jsonify(formatted_violations)
        
    except Exception as e:
        logger.error(f"Error fetching violations: {e}")
        return jsonify({'error': 'Failed to fetch violations'}), 500


@app.route('/report/<report_id>')
def view_report(report_id):
    """
    View a specific violation report.
    
    Fetches report HTML from Supabase Storage via signed URL.
    """
    try:
        # Get violation from database
        violation = db_manager.get_violation(report_id)
        
        if not violation:
            abort(404, description="Report not found")
        
        # Get signed URL for HTML report
        report_html_key = violation.get('report_html_key')
        if not report_html_key:
            abort(404, description="Report HTML not found")
        
        # Generate signed URL and redirect
        signed_url = storage_manager.get_signed_url(report_html_key)
        
        if signed_url:
            # Redirect to signed URL
            return redirect(signed_url)
        else:
            abort(500, description="Failed to generate signed URL")
            
    except Exception as e:
        logger.error(f"Error viewing report {report_id}: {e}")
        abort(500, description="Internal server error")


@app.route('/image/<report_id>/<filename>')
def get_image(report_id, filename):
    """
    Serve violation images via signed URLs from Supabase Storage.
    
    Args:
        report_id: Report identifier
        filename: Image filename ('original.jpg' or 'annotated.jpg')
    """
    try:
        # Validate filename
        if filename not in ['original.jpg', 'annotated.jpg']:
            abort(400, description="Invalid filename")
        
        # Get violation from database
        violation = db_manager.get_violation(report_id)
        
        if not violation:
            abort(404, description="Report not found")
        
        # Get storage key for the requested image
        if filename == 'original.jpg':
            image_key = violation.get('original_image_key')
        else:
            image_key = violation.get('annotated_image_key')
        
        if not image_key:
            abort(404, description="Image not found")
        
        # Generate signed URL and redirect
        signed_url = storage_manager.get_signed_url(image_key)
        
        if signed_url:
            return redirect(signed_url)
        else:
            abort(500, description="Failed to generate signed URL")
            
    except Exception as e:
        logger.error(f"Error serving image {report_id}/{filename}: {e}")
        abort(500, description="Internal server error")


@app.route('/api/stats')
def api_stats():
    """
    API endpoint for violation statistics.
    
    Returns summary statistics from the database.
    """
    try:
        violations = db_manager.get_recent_violations(limit=1000)
        
        total_violations = len(violations)
        total_people = sum(v.get('person_count', 0) for v in violations)
        
        # Count by severity
        severity_counts = {}
        for v in violations:
            severity = v.get('severity', 'UNKNOWN')
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
        
        stats = {
            'total_violations': total_violations,
            'total_people_detected': total_people,
            'severity_breakdown': severity_counts,
            'latest_violation': violations[0]['timestamp'].isoformat() if violations else None
        }
        
        return jsonify(stats)
        
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        return jsonify({'error': 'Failed to fetch statistics'}), 500


@app.route('/api/system/info')
def system_info():
    """System information endpoint."""
    return jsonify({
        'system': 'LUNA PPE Safety Monitor - Supabase Edition',
        'version': '1.0.0-supabase',
        'database': 'Supabase Postgres',
        'storage': 'Supabase Storage',
        'status': 'operational'
    })


# =========================================================================
# SIMPLE FALLBACK INDEX
# =========================================================================

SIMPLE_INDEX = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LUNA Reports - Supabase Edition</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 2rem;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            padding: 2rem;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        
        h1 {
            color: #2c3e50;
            margin-bottom: 1rem;
            font-size: 2.5rem;
        }
        
        .badge {
            display: inline-block;
            padding: 0.5rem 1rem;
            background: #667eea;
            color: white;
            border-radius: 20px;
            font-size: 0.9rem;
            margin-bottom: 2rem;
        }
        
        .violations-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 1.5rem;
            margin-top: 2rem;
        }
        
        .violation-card {
            border: 2px solid #e0e0e0;
            border-radius: 12px;
            padding: 1.5rem;
            transition: all 0.3s ease;
            cursor: pointer;
        }
        
        .violation-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 8px 24px rgba(0,0,0,0.15);
            border-color: #667eea;
        }
        
        .violation-card h3 {
            color: #2c3e50;
            margin-bottom: 0.5rem;
        }
        
        .violation-card p {
            color: #7f8c8d;
            margin: 0.25rem 0;
        }
        
        .severity {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 12px;
            font-size: 0.85rem;
            font-weight: 600;
            margin-top: 0.5rem;
        }
        
        .severity-HIGH {
            background: rgba(231,76,60,0.1);
            color: #e74c3c;
        }
        
        .severity-MEDIUM {
            background: rgba(243,156,18,0.1);
            color: #f39c12;
        }
        
        .severity-LOW {
            background: rgba(46,204,113,0.1);
            color: #2ecc71;
        }
        
        .loading {
            text-align: center;
            padding: 3rem;
            color: #7f8c8d;
        }
        
        .error {
            background: rgba(231,76,60,0.1);
            color: #e74c3c;
            padding: 1rem;
            border-radius: 8px;
            margin-top: 1rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🌙 LUNA Reports</h1>
        <span class="badge">☁️ Supabase Edition</span>
        
        <div id="stats"></div>
        <div id="violations" class="violations-grid">
            <div class="loading">Loading violations...</div>
        </div>
    </div>
    
    <script>
        // Fetch and display violations
        fetch('/api/violations')
            .then(response => response.json())
            .then(violations => {
                const container = document.getElementById('violations');
                
                if (violations.length === 0) {
                    container.innerHTML = '<div class="loading">No violations found</div>';
                    return;
                }
                
                container.innerHTML = violations.map(v => `
                    <div class="violation-card" onclick="window.location.href='/report/${v.report_id}'">
                        <h3>Report ${v.report_id}</h3>
                        <p><strong>Time:</strong> ${new Date(v.timestamp).toLocaleString()}</p>
                        <p><strong>People:</strong> ${v.person_count}</p>
                        <p><strong>Violations:</strong> ${v.violation_count}</p>
                        <p>${v.violation_summary || 'No summary available'}</p>
                        <span class="severity severity-${v.severity}">${v.severity}</span>
                    </div>
                `).join('');
            })
            .catch(error => {
                document.getElementById('violations').innerHTML = 
                    '<div class="error">Failed to load violations: ' + error.message + '</div>';
            });
        
        // Fetch and display stats
        fetch('/api/stats')
            .then(response => response.json())
            .then(stats => {
                document.getElementById('stats').innerHTML = `
                    <div style="background: #f8f9fa; padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
                        <strong>Total Violations:</strong> ${stats.total_violations} | 
                        <strong>People Detected:</strong> ${stats.total_people_detected} | 
                        <strong>Latest:</strong> ${stats.latest_violation ? new Date(stats.latest_violation).toLocaleString() : 'N/A'}
                    </div>
                `;
            });
    </script>
</body>
</html>
'''


# =========================================================================
# MAIN
# =========================================================================

if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("LUNA PPE Violation Report Viewer - Supabase Edition")
    logger.info("=" * 60)
    logger.info("Database: Supabase Postgres")
    logger.info("Storage: Supabase Storage (Private Buckets)")
    logger.info("")
    logger.info("Starting server at: http://localhost:5001")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)
    
    app.run(host='0.0.0.0', port=5001, debug=True)
