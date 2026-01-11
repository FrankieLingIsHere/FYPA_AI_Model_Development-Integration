"""
Pipeline Configuration
======================

Central configuration for all pipeline components.
"""

from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).parent.parent
PIPELINE_DIR = BASE_DIR / 'pipeline'
VIOLATIONS_DIR = PIPELINE_DIR / 'violations'
REPORTS_DIR = PIPELINE_DIR / 'reports'

# Create directories
VIOLATIONS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# =========================================================================
# PPE DETECTION CLASSES
# =========================================================================

PPE_CLASSES = [
    'Hardhat',
    'NO-Hardhat',
    'Mask',
    'NO-Mask',
    'Safety Vest',
    'NO-Safety Vest',
    'Gloves',
    'NO-Gloves',
    'Safety Cone',
    'Safety Shoes',
    'NO-Safety Shoes',
    'machinery',
    'vehicle',
    'Person'
]

# =========================================================================
# VIOLATION RULES
# =========================================================================

VIOLATION_RULES = {
    'required_ppe': {
        'hardhat': {
            'required': True,
            'severity': 'HIGH',
            'positive_classes': ['Hardhat'],
            'negative_classes': ['NO-Hardhat']
        },
        'vest': {
            'required': True,
            'severity': 'HIGH',
            'positive_classes': ['Safety Vest'],
            'negative_classes': ['NO-Safety Vest']
        },
        'mask': {
            'required': False,
            'severity': 'MEDIUM',
            'positive_classes': ['Mask'],
            'negative_classes': ['NO-Mask']
        },
        'gloves': {
            'required': False,
            'severity': 'MEDIUM',
            'positive_classes': ['Gloves'],
            'negative_classes': ['NO-Gloves']
        },
        'shoes': {
            'required': False,
            'severity': 'MEDIUM',
            'positive_classes': ['Safety Shoes'],
            'negative_classes': ['NO-Safety Shoes']
        }
    },
    'person_ppe_iou_threshold': 0.4,  # Increased from 0.3 to reduce false associations (pillows, lanterns near heads)
    'person_confidence_threshold': 0.25,
    'head_region_strict': True,  # Enable strict head-region validation for hardhat detection
    'critical': {
        'NO-Hardhat': True,
        'NO-Safety Vest': True
    },
    'max_queue_size': 10,
    'violation_cooldown': 60
}

# =========================================================================
# YOLO CONFIGURATION
# =========================================================================

YOLO_CONFIG = {
    'model_path': 'Results/ppe_yolov86/weights/best.pt',
    'conf_threshold': 0.10,
    'iou_threshold': 0.45,
    'imgsz': 640,
    'device': 'cuda',  # or 'cpu'
    'half': False,  # Disable half precision to avoid dtype errors
    'verbose': False
}

# =========================================================================
# LLAVA CONFIGURATION (Image Captioning)
# =========================================================================

LLAVA_CONFIG = {
    'model_id': 'llava-hf/llava-1.5-7b-hf',
    'load_in_4bit': True,
    'max_new_tokens': 150,
    'prompt_template': "USER: <image>\nDescribe this workplace safety scene in detail, focusing on workers and safety equipment."
}

# =========================================================================
# OLLAMA CONFIGURATION (NLP Report Generation)
# =========================================================================

OLLAMA_CONFIG = {
    'base_url': 'http://localhost:11434',
    'model': 'llama3',
    'timeout': 600,  # 10 minutes for detailed NLP analysis
    'use_local_model': False,
    'temperature': 0.7,
    'max_tokens': 2000
}

# =========================================================================
# RAG CONFIGURATION
# =========================================================================

RAG_CONFIG = {
    'enabled': True,  # Enable RAG with Chroma DB
    'use_chroma': True,  # Use Chroma DB for DOSH documentation
    'chroma_path': BASE_DIR / 'pipeline' / 'backend' / 'chroma_db',
    'collection_name': 'dosh_guidelines',  # Actual collection name
    'embedding_model': 'nomic-embed-text',  # Ollama embedding model
    'data_source': BASE_DIR / 'pipeline' / 'backend' / 'integration' / 'safety_knowledge.txt',  # Fallback CSV
    'num_similar_incidents': 2,
    'chunk_size': 500,
    'top_k': 3  # Number of relevant DOSH chunks to retrieve
}

# =========================================================================
# REPORT CONFIGURATION
# =========================================================================

REPORT_CONFIG = {
    'company_name': 'LUNA Safety Systems',
    'report_title': 'PPE Compliance Report',
    'include_recommendations': True,
    'include_severity': True,
    'generate_pdf': False,  # Set to True to enable PDF generation
    'logo_path': None
}

# =========================================================================
# BRAND COLORS
# =========================================================================

BRAND_COLORS = {
    'primary': '#2c3e50',
    'secondary': '#3498db',
    'success': '#2ecc71',
    'warning': '#f39c12',
    'danger': '#e74c3c',
    'info': '#17a2b8',
    'light': '#ecf0f1',
    'dark': '#34495e'
}

# =========================================================================
# STREAMING CONFIGURATION
# =========================================================================

STREAM_CONFIG = {
    'resolution': (640, 480),
    'fps': 30,
    'jpeg_quality': 85,
    'camera_index': 0
}

# =========================================================================
# DATABASE CONFIGURATION
# =========================================================================

DATABASE_CONFIG = {
    'db_path': PIPELINE_DIR / 'violations.db',
    'enable_logging': True
}

# =========================================================================
# SUPABASE CONFIGURATION
# =========================================================================

import os
import hashlib
from datetime import datetime

SUPABASE_CONFIG = {
    'url': os.getenv('SUPABASE_URL', ''),
    'service_role_key': os.getenv('SUPABASE_SERVICE_ROLE_KEY', ''),
    'db_url': os.getenv('SUPABASE_DB_URL', ''),
    'images_bucket': os.getenv('SUPABASE_IMAGES_BUCKET', 'violation-images'),
    'reports_bucket': os.getenv('SUPABASE_REPORTS_BUCKET', 'reports'),
    'signed_url_ttl': int(os.getenv('SUPABASE_SIGNED_URL_TTL_SECONDS', '3600')),
    'upload_pdf': os.getenv('UPLOAD_PDF', 'false').lower() == 'true',
    'connection_retry_max': 3,
    'connection_retry_delay': 2
}

# =========================================================================
# QUEUE CONFIGURATION (Multi-Device Handling)
# =========================================================================

QUEUE_CONFIG = {
    'max_queue_size': 100,           # Maximum violations in queue
    'batch_size': 5,                  # Violations to process per batch
    'rate_limit_per_device': 10,      # Max violations per device per minute
    'num_workers': 2,                 # Worker threads for processing
    'processing_timeout': 300,        # Seconds before timeout
    'retry_failed': True,             # Retry failed reports
    'max_retries': 3                  # Max retry attempts
}

# =========================================================================
# HELPER FUNCTIONS
# =========================================================================

def generate_report_id(device_id: str = None) -> str:
    """
    Generate a unique report ID that prevents collisions from multiple devices.
    
    Format: YYYYMMDD_HHMMSS_<device_hash>_<counter>
    
    Args:
        device_id: Optional device identifier
    
    Returns:
        Unique report ID string
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if device_id:
        # Create short hash of device_id
        device_hash = hashlib.md5(device_id.encode()).hexdigest()[:6]
    else:
        device_hash = 'local'
    
    # Add microseconds for uniqueness
    micro = datetime.now().strftime('%f')[:4]
    
    return f"{timestamp}_{device_hash}_{micro}"


def is_supabase_configured() -> bool:
    """Check if Supabase is properly configured."""
    return bool(
        SUPABASE_CONFIG.get('url') and 
        SUPABASE_CONFIG.get('service_role_key') and
        SUPABASE_CONFIG.get('db_url')
    )


def get_severity_priority(severity: str) -> int:
    """
    Get priority level for a severity (lower = higher priority).
    
    Args:
        severity: Severity string (CRITICAL, HIGH, MEDIUM, LOW)
    
    Returns:
        Priority integer (1-4)
    """
    priorities = {
        'CRITICAL': 1,
        'HIGH': 2,
        'MEDIUM': 3,
        'LOW': 4
    }
    return priorities.get(severity.upper(), 3)
