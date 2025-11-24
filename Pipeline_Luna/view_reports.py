"""
Simple Report Viewer - View PPE Violation Reports
=================================================

Simple Flask server to view generated violation reports.

Usage:
    python view_reports.py
    
    Then open browser to: http://localhost:5001
"""

from flask import Flask, render_template, send_from_directory, jsonify, abort
from pathlib import Path
import json
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__, 
            template_folder='report_templates',
            static_folder='frontend',
            static_url_path='/static')

# Violations directory
VIOLATIONS_DIR = Path('pipeline/violations')
VIOLATIONS_DIR.mkdir(parents=True, exist_ok=True)

# =========================================================================
# ROUTES
# =========================================================================

@app.route('/')
def index():
    """Serve the modern frontend application."""
    return send_from_directory('frontend', 'index.html')


@app.route('/old-reports')
def old_reports():
    """List all violation reports (old template)."""
    # Get all violation directories
    violations = []
    
    if VIOLATIONS_DIR.exists():
        for violation_dir in sorted(VIOLATIONS_DIR.iterdir(), reverse=True):
            if violation_dir.is_dir():
                # Parse report ID (timestamp)
                report_id = violation_dir.name
                try:
                    timestamp = datetime.strptime(report_id, '%Y%m%d_%H%M%S')
                    
                    # Check for files
                    has_original = (violation_dir / 'original.jpg').exists()
                    has_annotated = (violation_dir / 'annotated.jpg').exists()
                    has_report = (violation_dir / 'report.html').exists()
                    
                    violations.append({
                        'report_id': report_id,
                        'timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                        'has_original': has_original,
                        'has_annotated': has_annotated,
                        'has_report': has_report
                    })
                except ValueError:
                    logger.warning(f"Skipping invalid report directory: {report_id}")
                    continue
    
    return render_template('index.html', violations=violations)


@app.route('/report/<report_id>')
def view_report(report_id):
    """View a specific violation report."""
    violation_dir = VIOLATIONS_DIR / report_id
    
    if not violation_dir.exists():
        abort(404, description="Report not found")
    
    # Check if HTML report exists
    report_html = violation_dir / 'report.html'
    if report_html.exists():
        # Serve the generated report
        return send_from_directory(violation_dir, 'report.html')
    else:
        # Generate simple report on-the-fly
        try:
            timestamp = datetime.strptime(report_id, '%Y%m%d_%H%M%S')
            
            return render_template('simple_report.html',
                report_id=report_id,
                timestamp=timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                has_original=(violation_dir / 'original.jpg').exists(),
                has_annotated=(violation_dir / 'annotated.jpg').exists()
            )
        except ValueError:
            abort(400, description="Invalid report ID format")


@app.route('/image/<report_id>/<filename>')
def get_image(report_id, filename):
    """Serve violation images."""
    violation_dir = VIOLATIONS_DIR / report_id
    
    if not violation_dir.exists():
        abort(404, description="Report not found")
    
    if filename not in ['original.jpg', 'annotated.jpg']:
        abort(400, description="Invalid filename")
    
    image_path = violation_dir / filename
    if not image_path.exists():
        abort(404, description="Image not found")
    
    return send_from_directory(str(violation_dir), filename)


@app.route('/violations/<path:filepath>')
def serve_violation_files(filepath):
    """Serve files from violations directory."""
    return send_from_directory(str(VIOLATIONS_DIR), filepath)


@app.route('/api/violations')
def api_violations():
    """API endpoint to list all violations."""
    violations = []
    
    if VIOLATIONS_DIR.exists():
        for violation_dir in sorted(VIOLATIONS_DIR.iterdir(), reverse=True):
            if violation_dir.is_dir():
                report_id = violation_dir.name
                try:
                    timestamp = datetime.strptime(report_id, '%Y%m%d_%H%M%S')
                    
                    violations.append({
                        'report_id': report_id,
                        'timestamp': timestamp.isoformat(),
                        'has_original': (violation_dir / 'original.jpg').exists(),
                        'has_annotated': (violation_dir / 'annotated.jpg').exists(),
                        'has_report': (violation_dir / 'report.html').exists()
                    })
                except ValueError:
                    continue
    
    return jsonify(violations)


# =========================================================================
# MAIN
# =========================================================================

if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("PPE Violation Report Viewer")
    logger.info("=" * 60)
    logger.info(f"Violations directory: {VIOLATIONS_DIR.absolute()}")
    logger.info("")
    logger.info("Starting server at: http://localhost:5001")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)
    
    app.run(host='0.0.0.0', port=5001, debug=True)
