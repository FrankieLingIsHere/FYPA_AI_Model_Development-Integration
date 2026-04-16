"""
Pipeline Configuration
======================

Central configuration for all pipeline components.
"""

import os
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
    'head_region_strict': True,  # Enable strict head-region validation for hardhat detection
    'critical': {
        # These are now treated as HIGH severity but tracked as critical violations
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
    'max_new_tokens': 75,
    'prompt_template': "USER: <image>\nDescribe this workplace safety scene in detail, focusing on workers and safety equipment."
}

# =========================================================================
# OLLAMA CONFIGURATION (NLP Report Generation)
# =========================================================================

OLLAMA_CONFIG = {
    'base_url': os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434'),
    'api_url': os.getenv('OLLAMA_API_URL', f"{os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/')}/api/generate"),
    'embeddings_url': os.getenv('OLLAMA_EMBEDDINGS_URL', f"{os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/')}/api/embeddings"),
    'model': os.getenv('OLLAMA_MODEL', os.getenv('LOCAL_OLLAMA_UNIFIED_MODEL', 'gemma4')),
    'timeout': int(os.getenv('OLLAMA_TIMEOUT', '1200')),  # 20 minutes (Practically unlimited, but prevents indefinite deadlocks)
    'use_local_model': os.getenv('USE_LOCAL_MODEL', 'false').lower() == 'true',
    'temperature': float(os.getenv('OLLAMA_TEMPERATURE', '0.7')),
    'max_tokens': int(os.getenv('OLLAMA_MAX_TOKENS', '800'))
}

# =========================================================================
# GEMINI CONFIGURATION (Primary AI Provider — replaces Ollama)
# =========================================================================

GEMINI_CONFIG = {
    'api_key': os.getenv('GEMINI_API_KEY', os.getenv('GOOGLE_API_KEY', '')),
    'api_keys': os.getenv('GEMINI_API_KEYS', os.getenv('GOOGLE_API_KEYS', '')),
    'model': os.getenv('GEMINI_MODEL', 'gemini-2.5-flash'),
    'report_model': os.getenv('GEMINI_REPORT_MODEL', os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')),
    'vision_model': os.getenv('GEMINI_VISION_MODEL', os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')),
    'temperature': float(os.getenv('GEMINI_TEMPERATURE', '0.4')),
    'max_tokens': int(os.getenv('GEMINI_MAX_TOKENS', '2000')),
    'timeout': int(os.getenv('GEMINI_TIMEOUT', '120')),
    'max_retries': int(os.getenv('GEMINI_MAX_RETRIES', '3')),
    'paid_plan': os.getenv('GEMINI_PAID_PLAN', 'false').lower() == 'true',
    'min_interval': float(
        os.getenv(
            'GEMINI_MIN_INTERVAL',
            '0.35' if os.getenv('GEMINI_PAID_PLAN', 'false').lower() == 'true' else '4.0'
        )
    ),
    'enabled': os.getenv('GEMINI_ENABLED', 'true').lower() == 'true',
}

# =========================================================================
# MODEL API ROUTING (Provider switching)
# =========================================================================

def _split_csv(value: str) -> list:
    return [item.strip().lower() for item in value.split(',') if item.strip()]


MODEL_API_CONFIG = {
    # Set MODEL_API_ENABLED=true to enable direct provider APIs (OpenAI-compatible endpoints)
    'enabled': os.getenv('MODEL_API_ENABLED', 'false').lower() == 'true',

    # Provider order controls fallback chain for each task.
    # Supported entries: model_api, gemini, ollama, local
    'nlp_provider_order': _split_csv(os.getenv('NLP_PROVIDER_ORDER', 'model_api,gemini,ollama,local')),
    'embedding_provider_order': _split_csv(os.getenv('EMBEDDING_PROVIDER_ORDER', 'model_api,ollama')),

    # NLP endpoint (for Llama/Qwen/etc.)
    # Expected OpenAI-compatible /chat/completions API
    'nlp_api_url': os.getenv('NLP_API_URL', ''),
    'nlp_api_key': os.getenv('NLP_API_KEY', ''),
    'nlp_model': os.getenv('NLP_API_MODEL', 'meta-llama/Meta-Llama-3-8B-Instruct'),

    # Embeddings endpoint
    # Expected OpenAI-compatible /embeddings API
    'embedding_api_url': os.getenv('EMBEDDING_API_URL', ''),
    'embedding_api_key': os.getenv('EMBEDDING_API_KEY', ''),
    'embedding_model': os.getenv('EMBEDDING_API_MODEL', 'nomic-ai/nomic-embed-text-v1.5')
}

# =========================================================================
# RAG CONFIGURATION
# =========================================================================

def _resolve_rag_data_source() -> Path:
    explicit_path = str(os.getenv('RAG_DATA_SOURCE', '')).strip()
    if explicit_path:
        return Path(explicit_path)

    candidates = [
        BASE_DIR / 'pipeline' / 'backend' / 'integration' / 'safety_knowledge.txt',
        BASE_DIR / 'NLP_Luna' / 'Trim1.csv',
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[0]

RAG_CONFIG = {
    'enabled': True,  # Enable RAG with regulation data
    'use_chroma': False,  # Disabled — Gemini uses direct regulation injection instead of ChromaDB
    'chroma_path': BASE_DIR / 'pipeline' / 'backend' / 'chroma_db',
    'collection_name': 'dosh_guidelines',  # Actual collection name
    'embedding_model': 'nomic-embed-text',  # Ollama embedding model (only used if use_chroma=True)
    'data_source': _resolve_rag_data_source(),
    'regulations_file': BASE_DIR / 'pipeline' / 'backend' / 'data' / 'malaysian_regulations.json',
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
    
    Format: YYYYMMDD_HHMMSS_<device_hash>_<counter> (in MYT/UTC+8)
    
    Args:
        device_id: Optional device identifier
    
    Returns:
        Unique report ID string
    """
    from zoneinfo import ZoneInfo
    
    # Use Malaysian Time (UTC+8) consistently for report IDs
    myt = ZoneInfo('Asia/Kuala_Lumpur')
    now_myt = datetime.now(myt)
    timestamp = now_myt.strftime('%Y%m%d_%H%M%S')
    
    if device_id:
        # Create short hash of device_id
        device_hash = hashlib.md5(device_id.encode()).hexdigest()[:6]
    else:
        device_hash = 'local'
    
    # Add microseconds for uniqueness
    micro = now_myt.strftime('%f')[:4]
    
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
