
print("Step 1: Start")
import sys
print("Step 2: Sys imported")
try:
    from dotenv import load_dotenv
    print("Step 3: Dotenv imported")
except ImportError:
    print("Step 3: Dotenv failed")

try:
    import argparse
    print("Step 4: Argparse imported")
except:
    print("Step 4: Argparse failed")

try:
    from pipeline.backend.core.supabase_db import create_db_manager_from_env
    print("Step 5: Supabase DB imported")
except:
    print("Step 5: Supabase DB failed")

try:
    from pipeline.backend.integration.caption_generator import CaptionGenerator
    print("Step 6: Caption Generator imported")
except:
    print("Step 6: Caption Generator failed")

print("Done")
