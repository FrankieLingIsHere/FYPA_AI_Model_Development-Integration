

try:
    print("1. Importing ViolationDetector...")
    from pipeline.backend.core.violation_detector import ViolationDetector
    print("   OK")
    
    print("2. Importing CaptionGenerator...")
    from pipeline.backend.integration.caption_generator import CaptionGenerator
    print("   OK")
    
    print("3. Importing Supabase Report Generator...")
    from pipeline.backend.core.supabase_report_generator import create_supabase_report_generator
    print("   OK")
    
    print("4. Importing Supabase DB...")
    from pipeline.backend.core.supabase_db import create_db_manager_from_env
    print("   OK")
    
    print("5. Importing Supabase Storage...")
    from pipeline.backend.core.supabase_storage import create_storage_manager_from_env
    print("   OK")
    
    print("6. Importing Violation Queue...")
    from pipeline.backend.core.violation_queue import ViolationQueueManager
    print("   OK")
    
    print("7. Importing Config...")
    from pipeline.config import VIOLATION_RULES
    print("   OK")

except Exception as e:
    print(f"\n❌ IMPORT ERROR: {e}")
    import traceback
    traceback.print_exc()
except SyntaxError as e:
    print(f"\n❌ SYNTAX ERROR: {e}")

