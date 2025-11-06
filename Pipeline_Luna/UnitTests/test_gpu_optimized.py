"""
Quick GPU optimization test
"""
import sys
from pathlib import Path
import logging
import torch
import time

sys.path.insert(0, str(Path(__file__).parent))
from pipeline.backend.integration.local_llama import LocalLlamaGenerator

logging.basicConfig(level=logging.INFO, format='%(message)s')

print("=" * 80)
print("OPTIMIZED GPU TEST - RTX 5070")
print("=" * 80)

# Check GPU
print(f"\n✅ GPU: {torch.cuda.get_device_name(0)}")
print(f"✅ Memory: {torch.cuda.get_device_properties(0).total_memory / (1024**3):.1f} GB")

# Initialize
model_path = r"C:\Users\maste\Downloads\FYP Combined\Meta-Llama-3-8B-Instruct"
generator = LocalLlamaGenerator(model_path)

# Optimized prompt (shorter)
test_prompt = """Analyze this scene and respond with JSON only:

Scene: Construction worker on ladder without hard hat. Wearing safety vest.
Objects: person, NO-Hardhat, safety_vest
People: 1

JSON format:
{
  "summary": "Brief summary",
  "environment_type": "Construction Site|Office|etc",
  "environment_assessment": "Why this type",
  "persons": [{
    "id": 1,
    "description": "role",
    "ppe": {
      "hardhat": "Missing|Mentioned|Not Required",
      "safety_vest": "Missing|Mentioned|Not Required",
      "gloves": "Missing|Mentioned|Not Required",
      "goggles": "Missing|Mentioned|Not Required",
      "footwear": "Missing|Mentioned|Not Required"
    },
    "actions": ["actions"],
    "hazards_faced": ["hazards"],
    "risks": ["risks"],
    "compliance_status": "Non-Compliant|Compliant|Partially Compliant"
  }],
  "hazards_detected": ["hazards"],
  "suggested_actions": ["actions"],
  "severity_level": "CRITICAL|HIGH|MEDIUM|LOW"
}

JSON:"""

print("\n⏱️  Starting generation...")
start = time.time()

if torch.cuda.is_available():
    torch.cuda.reset_peak_memory_stats()

result = generator.generate_json(test_prompt, max_new_tokens=512, temperature=0.7)

elapsed = time.time() - start

print(f"\n⏱️  Time: {elapsed:.2f} seconds")

if torch.cuda.is_available():
    peak_mem = torch.cuda.max_memory_allocated(0) / (1024**3)
    print(f"📊 Peak GPU Memory: {peak_mem:.2f} GB")

if result:
    import json
    print("\n✅ JSON Generated Successfully!")
    print(json.dumps(result, indent=2))
else:
    print("\n❌ Failed to generate JSON")

print("\n" + "=" * 80)
print(f"SPEED: {elapsed:.1f}s | MEMORY: {peak_mem:.2f}GB")
print("=" * 80)
