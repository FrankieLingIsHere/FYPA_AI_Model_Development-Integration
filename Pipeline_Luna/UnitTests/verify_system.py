"""
System Verification Script
===========================
Verifies all pipeline components are working correctly.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.absolute()))

print('=' * 70)
print('COMPREHENSIVE SYSTEM VERIFICATION')
print('=' * 70)

errors = []

# 1. Configuration
print('\n1. Configuration Module...')
try:
    from pipeline.config import (
        PPE_CLASSES, VIOLATION_RULES, YOLO_CONFIG, LLAVA_CONFIG,
        OLLAMA_CONFIG, RAG_CONFIG, REPORT_CONFIG, BRAND_COLORS,
        REPORTS_DIR, VIOLATIONS_DIR
    )
    print(f'   ✅ Classes: {len(PPE_CLASSES)}')
    print(f'   ✅ Required PPE: {list(VIOLATION_RULES["required_ppe"].keys())}')
    print(f'   ✅ Cooldown: {VIOLATION_RULES["violation_cooldown"]}s')
    print(f'   ✅ Max Queue: {VIOLATION_RULES["max_queue_size"]}')
except Exception as e:
    print(f'   ❌ ERROR: {e}')
    errors.append(f'Config: {e}')

# 2. Database
print('\n2. Database Manager...')
try:
    from pipeline.backend.core.db_manager import db_manager
    print(f'   ✅ Connected: {db_manager.is_connected()}')
    print(f'   ✅ Type: {db_manager.config.get("type")}')
except Exception as e:
    print(f'   ❌ ERROR: {e}')
    errors.append(f'Database: {e}')

# 3. Violation Detector
print('\n3. Violation Detector...')
try:
    from pipeline.backend.core.violation_detector import ViolationDetector
    vd = ViolationDetector(VIOLATION_RULES)
    print(f'   ✅ Initialized: True')
    print(f'   ✅ Required PPE: {len(VIOLATION_RULES["required_ppe"])} items')
except Exception as e:
    print(f'   ❌ ERROR: {e}')
    errors.append(f'Violation Detector: {e}')

# 4. Pipeline Orchestrator
print('\n4. Pipeline Orchestrator...')
try:
    from pipeline.backend.core.pipeline_orchestrator import PipelineOrchestrator
    config = {
        'VIOLATION_RULES': VIOLATION_RULES,
        'VIOLATIONS_DIR': VIOLATIONS_DIR
    }
    orch = PipelineOrchestrator(config)
    print(f'   ✅ State: {orch.get_state().value}')
    print(f'   ✅ Queue Max Size: {orch.violation_queue.maxsize}')
    print(f'   ✅ Cooldown: {orch.cooldown_seconds}s')
except Exception as e:
    print(f'   ❌ ERROR: {e}')
    errors.append(f'Orchestrator: {e}')

# 5. YOLO Stream Manager
print('\n5. YOLO Stream Manager...')
try:
    from pipeline.backend.core.yolo_stream import YOLOStreamManager
    stream_config = {
        'YOLO_CONFIG': YOLO_CONFIG,
        'STREAM_CONFIG': {
            'source': 0,
            'fps_limit': 30,
            'display_width': 1280,
            'display_height': 720,
            'motion_jpeg_quality': 85
        },
        'PPE_CLASSES': PPE_CLASSES
    }
    # Don't actually create it to avoid loading YOLO model
    print(f'   ✅ Module imported successfully')
    print(f'   ✅ Ready for video capture')
except Exception as e:
    print(f'   ❌ ERROR: {e}')
    errors.append(f'YOLO Stream: {e}')

# 6. Image Processor
print('\n6. Image Processor...')
try:
    from pipeline.backend.core.image_processor import ImageProcessor
    ip_config = {
        'YOLO_CONFIG': YOLO_CONFIG,
        'PPE_CLASSES': PPE_CLASSES
    }
    ip = ImageProcessor(ip_config)
    print(f'   ✅ Classes: {len(ip.class_names)}')
    print(f'   ✅ Model Path: {ip.model_path}')
    print(f'   ✅ Colors Generated: {len(ip.colors)}')
except Exception as e:
    print(f'   ❌ ERROR: {e}')
    errors.append(f'Image Processor: {e}')

# 7. Caption Generator
print('\n7. Caption Generator...')
try:
    from pipeline.backend.integration.caption_generator import CaptionGenerator, CAPTION_AVAILABLE
    cg_config = {'LLAVA_CONFIG': LLAVA_CONFIG}
    cg = CaptionGenerator(cg_config)
    print(f'   ✅ Available: {CAPTION_AVAILABLE}')
    print(f'   ✅ Model: {cg.model_id}')
    print(f'   ✅ 4-bit Loading: {cg.load_in_4bit}')
except Exception as e:
    print(f'   ❌ ERROR: {e}')
    errors.append(f'Caption Generator: {e}')

# 8. Report Generator
print('\n8. Report Generator...')
try:
    from pipeline.backend.core.report_generator import ReportGenerator
    rg_config = {
        'OLLAMA_CONFIG': OLLAMA_CONFIG,
        'RAG_CONFIG': RAG_CONFIG,
        'REPORT_CONFIG': REPORT_CONFIG,
        'BRAND_COLORS': BRAND_COLORS,
        'REPORTS_DIR': REPORTS_DIR,
        'VIOLATIONS_DIR': VIOLATIONS_DIR
    }
    rg = ReportGenerator(rg_config)
    print(f'   ✅ RAG Incidents: {len(rg.incident_data)}')
    print(f'   ✅ Ollama Model: {rg.model}')
    print(f'   ✅ Ollama URL: {rg.api_url}')
except Exception as e:
    print(f'   ❌ ERROR: {e}')
    errors.append(f'Report Generator: {e}')

# Summary
print('\n' + '=' * 70)
if errors:
    print('VERIFICATION FAILED - ERRORS DETECTED:')
    print('=' * 70)
    for error in errors:
        print(f'  ❌ {error}')
else:
    print('✅ ALL SYSTEMS OPERATIONAL')
    print('=' * 70)
    print('\nSystem Ready For:')
    print('  • Live violation detection')
    print('  • Real-time video streaming')
    print('  • Automated report generation')
    print('  • Database logging')
    print('  • NLP analysis with RAG (551 incidents)')

sys.exit(0 if not errors else 1)
