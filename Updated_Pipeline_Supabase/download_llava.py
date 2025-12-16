"""Download LLaVA Model"""
print("Downloading LLaVA 1.5 7B (~13GB)... This will take 10-30 minutes.")
print("Model will be cached in: ~/.cache/huggingface/")

from transformers import LlavaForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
import torch

print("\n[1/2] Downloading model...")
# Configure quantization for limited GPU RAM
quantization_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16,
    llm_int8_enable_fp32_cpu_offload=True  # Allow CPU offloading
)

model = LlavaForConditionalGeneration.from_pretrained(
    'llava-hf/llava-1.5-7b-hf',
    quantization_config=quantization_config,
    device_map="auto",
    low_cpu_mem_usage=True
)
print("✓ Model downloaded!")

print("\n[2/2] Downloading processor...")
processor = AutoProcessor.from_pretrained('llava-hf/llava-1.5-7b-hf')
print("✓ Processor downloaded!")

print("\n" + "="*80)
print("SUCCESS! LLaVA is ready. Restart LUNA and captions will work.")
print("="*80)
