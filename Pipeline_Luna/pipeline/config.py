"""
Pipeline Configuration
======================
Centralized configuration for the PPE compliance detection and reporting pipeline.
All paths, model settings, and parameters are defined here.
"""

import os
from pathlib import Path

# =============================================================================
# PATHS
# =============================================================================

# Root directory (parent of pipeline folder)
ROOT_DIR = Path(__file__).parent.parent.absolute()
PIPELINE_DIR = Path(__file__).parent.absolute()

# Model paths
YOLO_MODEL_PATH = ROOT_DIR / 'Results' / 'ppe_yolov86' / 'weights' / 'best.pt'
# Fallback if the above doesn't exist
if not YOLO_MODEL_PATH.exists():
    # Try alternate location
    alt_path = ROOT_DIR / 'NewClassTest1' / 'Results' / 'ppe_yolov8_simple' / 'weights' / 'best.pt'
    if alt_path.exists():
        YOLO_MODEL_PATH = alt_path

# Output directories
VIOLATIONS_DIR = PIPELINE_DIR / 'violations'
REPORTS_DIR = PIPELINE_DIR / 'backend' / 'reports'
STATIC_DIR = PIPELINE_DIR / 'backend' / 'static'
TEMPLATES_DIR = PIPELINE_DIR / 'backend' / 'templates'

# Ensure directories exist
for dir_path in [VIOLATIONS_DIR, REPORTS_DIR, STATIC_DIR, TEMPLATES_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# =============================================================================
# YOLO DETECTION SETTINGS
# =============================================================================

YOLO_CONFIG = {
    'model_path': str(YOLO_MODEL_PATH),  # Custom PPE-trained model from Results
    'conf_threshold': 0.10,  # Confidence threshold
    'iou_threshold': 0.45,   # IoU threshold for NMS
    'imgsz': 640,            # Input image size
    'device': 0,             # GPU device (0) or 'cpu'
}

# PPE Classes from data/data.yaml (14 classes)
PPE_CLASSES = {
    0: 'Fall-Detected',
    1: 'Gloves',
    2: 'Goggles',
    3: 'Hardhat',
    4: 'Ladder',
    5: 'Mask',
    6: 'NO-Gloves',
    7: 'NO-Goggles',
    8: 'NO-Hardhat',
    9: 'NO-Mask',
    10: 'NO-Safety Vest',
    11: 'Person',
    12: 'Safety Cone',
    13: 'Safety Vest'
}

# Reverse mapping for quick lookup
CLASS_NAMES_TO_ID = {v: k for k, v in PPE_CLASSES.items()}

# =============================================================================
# VIOLATION DETECTION RULES (Construction Site Requirements)
# =============================================================================

VIOLATION_RULES = {
    # CRITICAL VIOLATIONS
    'critical': {
        'Fall-Detected': {
            'description': 'Fall detected - immediate emergency',
            'severity': 'CRITICAL',
            'requires_person': False  # Fall is violation regardless
        }
    },
    
    # REQUIRED PPE (Must be present for every person)
    'required_ppe': {
        'Hardhat': {
            'description': 'Hardhat missing - required at all times on construction site',
            'severity': 'HIGH',
            'negative_class': 'NO-Hardhat'
        }
        # Safety Vest temporarily disabled - model not detecting reliably
        # 'Safety Vest': {
        #     'description': 'Safety vest missing - required at all times on construction site',
        #     'severity': 'HIGH',
        #     'negative_class': 'NO-Safety Vest'
        # }
    },
    
    # OPTIONAL PPE (Logged but not critical violations)
    'optional_ppe': {
        'Gloves': {'negative_class': 'NO-Gloves', 'severity': 'LOW'},
        'Goggles': {'negative_class': 'NO-Goggles', 'severity': 'LOW'},
        'Mask': {'negative_class': 'NO-Mask', 'severity': 'LOW'}
    },
    
    # IoU threshold for person-PPE association
    'person_ppe_iou_threshold': 0.3,
    
    # Minimum confidence for person detection
    'person_confidence_threshold': 0.10,  # Lowered from 0.25 to detect more persons
    
    # Cooldown between detections (seconds)
    'violation_cooldown': 60,  # 1 minute minimum between detections
    
    # Maximum violations in queue
    'max_queue_size': 10
}

# =============================================================================
# LLAVA CAPTIONING SETTINGS
# =============================================================================

LLAVA_CONFIG = {
    'model_id': 'llava-hf/llava-1.5-7b-hf',
    'load_in_4bit': True,
    'max_new_tokens': 150,
    'prompt_template': "USER: <image>\nDescribe this workplace safety scene in detail, focusing on workers, their actions, and any safety equipment visible.",
}

# =============================================================================
# OLLAMA NLP SETTINGS
# =============================================================================

OLLAMA_CONFIG = {
    'api_url': 'http://localhost:11434/api/generate',
    'model': 'llama3.2:latest',  # Using Llama 3 variant, configurable
    'timeout': 120,  # seconds
    'stream': False,
    'format': 'json',
    # Alternate models for different use cases
    'alternate_models': {
        'llama3': 'llama3.2:latest',
        'llama3_large': 'llama3:70b',
        'deepseek': 'deepseek-r1:7b',
    }
}

# =============================================================================
# RAG (Retrieval-Augmented Generation) SETTINGS
# =============================================================================

RAG_CONFIG = {
    'enabled': True,
    'data_source': str(ROOT_DIR / 'NLP_Luna' / 'Trim1.csv'),
    'num_similar_incidents': 2,  # Number of similar incidents to retrieve
    'similarity_method': 'keyword',  # 'keyword' for basic, 'embedding' for future
    # Future: embedding model configuration
    'embedding_model': None,  # Will be used when switching to embedding-based RAG
}

# =============================================================================
# REPORT GENERATION SETTINGS
# =============================================================================

REPORT_CONFIG = {
    'include_annotated_image': True,
    'include_original_image': True,
    'include_detection_details': True,
    'include_caption': True,
    'include_nlp_analysis': True,
    'include_timeframe': True,  # Include timestamp metadata
    'format': 'both',  # 'html', 'pdf', or 'both'
    'timestamp_format': '%Y-%m-%d %H:%M:%S',
    'timeframe_format': '%Y%m%d_%H%M%S',  # For filenames and IDs
    'report_filename_format': 'violation_{report_id}',
    'enable_pdf_generation': True,
}

# =============================================================================
# FLASK API SETTINGS
# =============================================================================

FLASK_CONFIG = {
    'host': '0.0.0.0',
    'port': 5000,
    'debug': True,
    'threaded': True,
}

# =============================================================================
# VIDEO STREAM SETTINGS
# =============================================================================

STREAM_CONFIG = {
    'source': 0,  # 0 for webcam (demo), or RTSP URL string
    'rtsp_enabled': False,  # Enable for future RTSP support
    'rtsp_url': 'rtsp://username:password@ip:port/stream',  # Template for future use
    'fps_limit': 30,  # Target FPS for detection
    'frame_skip': 1,  # Process every frame (1 = no skip, 2 = every other frame, etc.)
    'violation_cooldown': 60,  # Seconds before detecting same violation again (1 minute)
    'display_width': 1280,
    'display_height': 720,
    'reconnect_attempts': 3,  # For RTSP reconnection
    'reconnect_delay': 5,  # Seconds between reconnection attempts
    'motion_jpeg_quality': 85,  # JPEG quality for Motion JPEG streaming (1-100)
}

# =============================================================================
# BRAND COLORS & STYLING
# =============================================================================

BRAND_COLORS = {
    'primary': '#E67E22',  # Dark Orange
    'secondary': '#5B7A9E',  # Mildly-dark Blue with purple tint
    'background': '#FFFFFF',  # White
    'text_dark': '#2C3E50',  # Dark text
    'text_light': '#ECF0F1',  # Light text
    'success': '#2ECC71',  # Green for success
    'warning': '#F39C12',  # Orange for warnings
    'danger': '#E74C3C',  # Red for critical
    'info': '#3498DB',  # Blue for info
}

# =============================================================================
# LOGGING SETTINGS
# =============================================================================

LOGGING_CONFIG = {
    'level': 'INFO',  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    'log_file': PIPELINE_DIR / 'pipeline.log',
}

# =============================================================================
# DATABASE SETTINGS (Foundation for future MySQL implementation)
# =============================================================================

DATABASE_CONFIG = {
    'enabled': True,  # Set to True when ready to use database
    'type': 'sqlite',  # 'sqlite' for development, 'mysql' for production
    
    # MySQL Configuration (for future implementation)
    'mysql': {
        'host': 'localhost',
        'port': 3306,
        'database': 'ppe_compliance',
        'user': 'ppe_user',
        'password': 'your_password_here',
        'charset': 'utf8mb4',
        'pool_size': 5,
        'pool_recycle': 3600,
    },
    
    # SQLite fallback (for development/testing)
    'sqlite': {
        'database': str(PIPELINE_DIR / 'violations.db'),
    },
    
    # Table schema definition
    'schema': {
        'violations': {
            'primary_key': 'report_id',  # VARCHAR(50) - Format: YYYYMMDD_HHMMSS
            'secondary_key': 'timeframe',  # DATETIME - Timestamp of violation
            'columns': [
                ('report_id', 'VARCHAR(50)', 'PRIMARY KEY'),
                ('timeframe', 'DATETIME', 'NOT NULL'),
                ('violation_summary', 'TEXT', 'NULL'),
                ('person_count', 'INT', 'NULL'),
                ('violation_count', 'INT', 'NULL'),
                ('image_path', 'VARCHAR(500)', 'NULL'),
                ('annotated_image_path', 'VARCHAR(500)', 'NULL'),
                ('caption', 'TEXT', 'NULL'),
                ('nlp_analysis', 'JSON', 'NULL'),  # MySQL 5.7+ supports JSON
                ('report_html_path', 'VARCHAR(500)', 'NULL'),
                ('report_pdf_path', 'VARCHAR(500)', 'NULL'),
                ('detection_data', 'JSON', 'NULL'),
                ('created_at', 'TIMESTAMP', 'DEFAULT CURRENT_TIMESTAMP'),
                ('updated_at', 'TIMESTAMP', 'DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'),
            ],
            'indexes': [
                ('idx_timeframe', 'timeframe'),
                ('idx_created_at', 'created_at'),
            ]
        },
        
        # Future table for detailed person-level violations
        'person_violations': {
            'primary_key': 'id',
            'columns': [
                ('id', 'INT', 'AUTO_INCREMENT PRIMARY KEY'),
                ('report_id', 'VARCHAR(50)', 'NOT NULL'),
                ('person_number', 'INT', 'NOT NULL'),
                ('violation_type', 'VARCHAR(100)', 'NULL'),
                ('confidence', 'FLOAT', 'NULL'),
                ('bbox_data', 'JSON', 'NULL'),
                ('FOREIGN KEY (report_id)', 'REFERENCES violations(report_id)', 'ON DELETE CASCADE'),
            ]
        }
    }
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_violation_path(violation_id: str) -> Path:
    """Get the directory path for a specific violation."""
    violation_dir = VIOLATIONS_DIR / violation_id
    violation_dir.mkdir(parents=True, exist_ok=True)
    return violation_dir

def get_report_path(violation_id: str, format: str = 'html') -> Path:
    """Get the full path for a violation report."""
    return REPORTS_DIR / f"violation_{violation_id}.{format}"

def validate_config():
    """Validate that all required paths and settings are correct."""
    issues = []
    
    if not YOLO_MODEL_PATH.exists():
        issues.append(f"YOLO model not found at: {YOLO_MODEL_PATH}")
    
    if not VIOLATIONS_DIR.exists():
        issues.append(f"Violations directory not found: {VIOLATIONS_DIR}")
    
    return issues

if __name__ == '__main__':
    print("=" * 70)
    print("PIPELINE CONFIGURATION")
    print("=" * 70)
    print(f"\nRoot Directory: {ROOT_DIR}")
    print(f"Pipeline Directory: {PIPELINE_DIR}")
    print(f"YOLO Model: {YOLO_MODEL_PATH}")
    print(f"  Exists: {YOLO_MODEL_PATH.exists()}")
    print(f"\nViolations Directory: {VIOLATIONS_DIR}")
    print(f"Reports Directory: {REPORTS_DIR}")
    
    print("\n" + "=" * 70)
    print("VALIDATION")
    print("=" * 70)
    issues = validate_config()
    if issues:
        print("\n[X] Configuration Issues:")
        for issue in issues:
            print(f"  - {issue}")
    else:
        print("\n[OK] All configuration checks passed!")
    
    print("\n" + "=" * 70)
