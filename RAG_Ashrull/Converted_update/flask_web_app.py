"""
Flask Web Application for AI Safety Inspector
Serves the updated User Interface and provides RAG-based PPE violation detection
"""

from flask import Flask, request, jsonify, send_from_directory, render_template_string
from flask_cors import CORS
import joblib
import json
import chromadb
from chromadb.config import Settings
import ollama
from pathlib import Path
import re
import os
from email_notifier import send_notification, load_email_config

app = Flask(__name__)
CORS(app)

# ============================================================================
# Load Models and Initialize Systems
# ============================================================================
print("="*80)
print("🦺 LOADING AI SAFETY INSPECTOR")
print("="*80)

# Load saved models
print("\n📦 Loading saved models...")
models_path = Path("./saved_models")
risk_classifier = joblib.load(models_path / "risk_classifier.pkl")
tfidf_vectorizer = joblib.load(models_path / "tfidf_vectorizer.pkl")
label_encoder = joblib.load(models_path / "label_encoder.pkl")
print("  ✅ Models loaded")

# Load configurations
with open(models_path / "model_metrics.json", "r") as f:
    metrics = json.load(f)
with open(models_path / "rag_config.json", "r") as f:
    rag_config = json.load(f)
print("  ✅ Configurations loaded")

# Load email configuration
email_config = load_email_config()
if email_config.get('enabled'):
    print(f"  ✅ Email notifications enabled → {email_config.get('recipient_email')}")
else:
    print("  ℹ️ Email notifications disabled (update email_config.json to enable)")

# Initialize ChromaDB
class OllamaEmbeddingFunction:
    def __init__(self, model_name="nomic-embed-text"):
        self.model_name = model_name
    
    def name(self):
        return self.model_name
    
    def __call__(self, input):
        embeddings = []
        texts = input if isinstance(input, list) else [input]
        for text in texts:
            response = ollama.embeddings(model=self.model_name, prompt=text)
            embeddings.append(response["embedding"])
        return embeddings

print("\n🔗 Initializing ChromaDB...")
chroma_client = chromadb.PersistentClient(
    path=rag_config.get('chroma_db_path', './chroma_db'),
    settings=Settings(anonymized_telemetry=False)
)

embedding_function = OllamaEmbeddingFunction(rag_config['embedding_model'])

ppe_collection = chroma_client.get_collection(
    name=rag_config['ppe_collection'],
    embedding_function=embedding_function
)
scenarios_collection = chroma_client.get_collection(
    name=rag_config['scenarios_collection'],
    embedding_function=embedding_function
)
print("  ✅ ChromaDB initialized")
print("="*80)

# ============================================================================
# Helper Functions
# ============================================================================

def calculate_confidence_score(scenario_text, ppe_items, context, risk_proba, llm_analysis):
    """
    Calculate hybrid confidence score combining formula-based metrics with LLM contextual analysis
    """
    
    # ========== FORMULA-BASED CALCULATION (80%) ==========
    
    # 1. Scenario Quality (25%)
    length_score = min(len(scenario_text.split()) / 50, 1.0) * 0.6
    keywords = ['worker', 'construction', 'site', 'wearing', 'equipment', 'helmet', 'vest', 'gloves']
    keyword_count = sum(1 for kw in keywords if kw.lower() in scenario_text.lower())
    keyword_score = min(keyword_count / 5, 1.0) * 0.4
    scenario_quality = (length_score + keyword_score) * 25
    
    # 2. PPE Detection (25%)
    if len(ppe_items) == 0:
        ppe_score = 0.3
    elif len(ppe_items) < 3:
        ppe_score = 0.5
    elif len(ppe_items) < 5:
        ppe_score = 0.8
    else:
        ppe_score = 1.0
    ppe_detection = ppe_score * 25
    
    # 3. Context Quality (25%)
    guideline_quality = len(context.get('guidelines', [])) / 3 if context.get('guidelines') else 0
    scenario_quality_metric = len(context.get('similar_scenarios', [])) / 3 if context.get('similar_scenarios') else 0
    context_quality = (min(guideline_quality, 1.0) * 0.5 + min(scenario_quality_metric, 1.0) * 0.5) * 25
    
    # 4. Classifier Confidence (25%)
    classifier_confidence = (max(risk_proba[0]) if len(risk_proba) > 0 else 0.5) * 25
    
    base_confidence = scenario_quality + ppe_detection + context_quality + classifier_confidence
    
    # ========== LLM CONTEXTUAL ADJUSTMENT (20%) ==========
    
    llm_confidence_boost = 0
    
    if llm_analysis:
        analysis_lower = llm_analysis.lower()
        
        positive_phrases = {
            'clearly': 3, 'definitely': 5, 'certainly': 4, 'obvious': 3,
            'evident': 3, 'confirmed': 4, 'precise': 3, 'exactly': 4, 'specific': 2
        }
        
        negative_phrases = {
            'might': -3, 'possibly': -2, 'perhaps': -2, 'unclear': -5,
            'uncertain': -5, 'vague': -4, 'ambiguous': -4, 'incomplete': -6,
            'insufficient information': -8, 'cannot determine': -7, 'difficult to': -4
        }
        
        for phrase, weight in positive_phrases.items():
            if phrase in analysis_lower:
                llm_confidence_boost += weight
        
        for phrase, weight in negative_phrases.items():
            if phrase in analysis_lower:
                llm_confidence_boost += weight
    
    llm_adjustment = llm_confidence_boost * 0.2
    final_confidence = base_confidence + llm_adjustment
    final_confidence = max(0, min(100, final_confidence))
    
    print(f"\n📊 CONFIDENCE CALCULATION:")
    print(f"  Scenario Quality: {scenario_quality:.1f}%")
    print(f"  PPE Detection: {ppe_detection:.1f}%")
    print(f"  Context Quality: {context_quality:.1f}%")
    print(f"  Classifier Confidence: {classifier_confidence:.1f}%")
    print(f"  Base (formula): {base_confidence:.1f}%")
    print(f"  LLM adjustment: {llm_confidence_boost:+.1f} → {llm_adjustment:+.1f}%")
    print(f"  Final: {final_confidence:.1f}%")
    
    return round(final_confidence, 1)

def extract_ppe_items(scenario_text):
    """
    Extract PPE items mentioned in the scenario with context awareness
    Detects negations like 'not wearing', 'without', 'neither', etc.
    """
    ppe_keywords = {
        'hardhat': ['hard hat', 'hardhat', 'helmet', 'hard-hat'],
        'safety_glasses': ['safety glasses', 'goggles', 'eye protection', 'safety goggles', 'glasses', 'eyewear'],
        'gloves': ['gloves', 'hand protection', 'glove'],
        'safety_vest': ['safety vest', 'hi-vis', 'high visibility', 'reflective vest', 'vest'],
        'footwear': ['safety boots', 'steel-toe', 'safety shoes', 'protective footwear', 'boots', 'shoes']
    }
    
    detected_ppe = {}
    text_lower = scenario_text.lower()
    
    # Enhanced negation patterns - now includes "neither"
    negation_patterns = [
        'not wearing', 'without', 'no ', 'missing', 'not using',
        'lacks', 'absent', 'not have', "doesn't have", 'removed',
        'but not', 'except', 'not a ', "isn't wearing", 'failed to wear',
        'neither', 'nor', 'not equipped', 'lacking', 'fails to wear',
        'does not have', 'do not have', 'not provided', 'not visible',
        'appears to be without', 'appear to be without', 'not appear to'
    ]
    
    # Check for broad negations that affect multiple PPE items
    # E.g., "Neither worker appears to be wearing respiratory protection, safety glasses, or hard hats"
    broad_negation_phrases = [
        'neither worker appears to be wearing',
        'neither worker is wearing',
        'both workers are not wearing',
        'no workers are wearing',
        'workers are not wearing',
        'none of the workers'
    ]
    
    has_broad_negation = any(phrase in text_lower for phrase in broad_negation_phrases)
    
    # For each PPE type, check if mentioned AND check for negation context
    for ppe_type, keywords in ppe_keywords.items():
        found = False
        for keyword in keywords:
            if keyword in text_lower:
                found = True
                # Find all occurrences of the keyword
                keyword_pos = text_lower.find(keyword)
                
                # Get surrounding context (100 chars before and 20 chars after)
                context_before = text_lower[max(0, keyword_pos-100):keyword_pos]
                context_after = text_lower[keyword_pos:min(len(text_lower), keyword_pos + len(keyword) + 20)]
                full_context = context_before + context_after
                
                # Check for negation in context
                is_negated = any(neg in full_context for neg in negation_patterns)
                
                # Also check if this PPE is in a broad negation phrase
                if has_broad_negation:
                    # If we found a broad negation, check if this PPE is mentioned after it
                    for phrase in broad_negation_phrases:
                        phrase_pos = text_lower.find(phrase)
                        if phrase_pos != -1 and keyword_pos > phrase_pos:
                            # Check if keyword is within 200 chars of the broad negation
                            if keyword_pos - phrase_pos < 200:
                                is_negated = True
                                break
                
                if is_negated:
                    detected_ppe[ppe_type] = "Missing"
                    print(f"  🔴 {ppe_type}: MISSING (negation detected)")
                else:
                    detected_ppe[ppe_type] = "Mentioned"
                    print(f"  🟢 {ppe_type}: MENTIONED (present)")
                break
        
        # If not found at all, mark as "Not Mentioned"
        if not found:
            detected_ppe[ppe_type] = "Not Mentioned"
            print(f"  ⚪ {ppe_type}: NOT MENTIONED (not in text)")
    
    return detected_ppe

def extract_worker_count(scenario_text):
    """Extract the number of workers mentioned in the scenario"""
    text_lower = scenario_text.lower()
    
    # Pattern matching for explicit numbers
    patterns = [
        (r'(\d+)\s+workers?', 1),
        (r'two workers?', 2),
        (r'three workers?', 3),
        (r'four workers?', 4),
        (r'five workers?', 5),
        (r'both workers?', 2),
        (r'neither worker', 2),
        (r'multiple workers?', 2),  # Default to 2 for "multiple"
        (r'several workers?', 3),   # Default to 3 for "several"
    ]
    
    for pattern, count in patterns:
        match = re.search(pattern, text_lower)
        if match:
            if isinstance(count, int):
                return count
            else:
                return int(match.group(count))
    
    # Default to 1 worker
    return 1

def extract_worker_descriptions(scenario_text, worker_count):
    """
    Extract individual worker descriptions from scenario text
    Looks for patterns like "one is...", "the other...", "another..."
    Returns list of (description, text_segment) tuples
    """
    text_lower = scenario_text.lower()
    descriptions = []
    
    if worker_count == 1:
        return [(scenario_text[:100] + ('...' if len(scenario_text) > 100 else ''), scenario_text)]
    
    # Patterns for identifying individual workers with their context
    worker_patterns = [
        (r'one\s+(?:is|was|has|worker)\s+([^,\.]+(?:[^\.]*?)(?:,|\.|\s+while|\s+and))', 'one'),
        (r'the\s+other\s+(?:is|was|has|worker)?\s*([^,\.]+(?:[^\.]*?)(?:,|\.))', 'other'),
        (r'another\s+(?:is|was|has|worker)?\s*([^,\.]+)', 'another'),
        (r'first\s+worker\s+(?:is|was|has)\s+([^,\.]+)', 'first'),
        (r'second\s+worker\s+(?:is|was|has)\s+([^,\.]+)', 'second'),
        (r'third\s+worker\s+(?:is|was|has)\s+([^,\.]+)', 'third'),
    ]
    
    for pattern, worker_type in worker_patterns:
        matches = re.finditer(pattern, text_lower)
        for match in matches:
            full_text = match.group(1).strip()
            desc = full_text[:80] if len(full_text) > 80 else full_text
            if desc and len(desc) > 5:  # Valid description
                # Store both description and the full segment for PPE analysis
                descriptions.append((desc, full_text))
    
    # If we found descriptions, use them
    if descriptions:
        # Pad with generic descriptions if needed
        while len(descriptions) < worker_count:
            descriptions.append((f"Worker {len(descriptions) + 1} from the scenario", ""))
        return descriptions[:worker_count]
    
    # Fallback: generic descriptions
    return [(f"Worker {i} from the scenario", "") for i in range(1, worker_count + 1)]

def extract_individual_worker_ppe(worker_text, global_ppe_status):
    """
    Extract PPE status for a specific worker based on their text segment
    Returns PPE status dict for that worker
    """
    worker_ppe = global_ppe_status.copy()
    
    if not worker_text:
        return worker_ppe
    
    text_lower = worker_text.lower()
    
    # PPE keywords
    ppe_keywords = {
        'hardhat': ['hard hat', 'hardhat', 'helmet', 'hard-hat'],
        'safety_glasses': ['safety glasses', 'goggles', 'eye protection', 'safety goggles', 'glasses', 'eyewear'],
        'gloves': ['gloves', 'hand protection', 'glove'],
        'safety_vest': ['safety vest', 'hi-vis', 'high visibility', 'reflective vest', 'vest'],
        'footwear': ['safety boots', 'steel-toe', 'safety shoes', 'protective footwear', 'boots', 'shoes']
    }
    
    # Check if this worker specifically mentions PPE
    for ppe_type, keywords in ppe_keywords.items():
        for keyword in keywords:
            if keyword in text_lower:
                # Check if it's positive (wearing) or negative (not wearing)
                keyword_pos = text_lower.find(keyword)
                context = text_lower[max(0, keyword_pos-50):keyword_pos]
                
                # Positive indicators
                if any(word in context or word in text_lower[keyword_pos:keyword_pos+20] 
                       for word in ['wearing', 'has', 'with', 'using', 'equipped']):
                    worker_ppe[ppe_type] = "Mentioned"
                    print(f"    🟢 {ppe_type}: MENTIONED (found '{keyword}' with positive context)")
                    break
    
    return worker_ppe

def create_fallback_response(scenario_text):
    """Create a basic response when LLM parsing fails"""
    return {
        "summary": f"Analysis of scenario: {scenario_text[:100]}... Basic safety assessment indicates potential hazards present.",
        "persons": [],
        "hazards_detected": [
            "Unable to perform detailed analysis",
            "Please check scenario description clarity"
        ],
        "suggested_actions": [
            "Verify all workers are wearing appropriate PPE",
            "Conduct hazard assessment",
            "Review OSHA guidelines for the work area"
        ],
        "confidence_score": "30"
    }

def generate_rag_response(scenario_text, context, scenario_worker_count=None):
    """Generate analysis using RAG with Ollama"""
    
    # Build context string from retrieved guidelines
    context_str = ""
    if context.get('guidelines'):
        context_str = "OSHA GUIDELINES:\n"
        for guideline in context['guidelines'][:2]:  # Limit to 2 guidelines
            context_str += f"{guideline['text'][:500]}\n"
    
    prompt = f"""You are a workplace safety expert analyzing PPE compliance. Read the scenario VERY CAREFULLY and analyze EACH WORKER INDIVIDUALLY.

OSHA Guidelines: {context_str}

Scenario to Analyze:
{scenario_text}

CRITICAL INSTRUCTIONS - READ CAREFULLY:

1. COUNT WORKERS FIRST: Identify how many workers are in the scenario.

2. ANALYZE EACH WORKER SEPARATELY: If there are multiple workers, track what EACH individual worker is wearing or not wearing.
   - Example: "one is bending down" → Worker 1
   - Example: "the other stands nearby wearing gloves" → Worker 2 has gloves

3. PAY ATTENTION TO INDIVIDUAL DESCRIPTIONS:
   - "one worker is wearing X" → Only that worker has X
   - "the other worker has Y" → Only that worker has Y
   - "neither worker has Z" → Both workers missing Z
   - "both workers have W" → Both workers have W

4. PPE STATUS MEANINGS:
   ✅ = PPE is BEING WORN (compliant) - Only if explicitly stated for THAT worker
   ❌ = PPE is NOT BEING WORN (violation) - If stated "not wearing", "without", "missing"
   ⚠️ = UNCLEAR (if not mentioned for that specific worker but might have it)

5. NEGATION PHRASES: "NOT wearing", "without", "missing", "neither worker", "lacks", etc. → ❌

OUTPUT FORMAT (FOLLOW EXACTLY):

WORKER COUNT: [number]

RISK LEVEL: [HIGH/MEDIUM/LOW] - [Brief explanation]

--- FOR EACH WORKER, CREATE A SECTION LIKE THIS ---

WORKER 1:
Description: [What is this worker doing? e.g., "bending down cutting concrete blocks"]

PPE Status:
✅/❌ Hardhat - [Reason specific to this worker]
✅/❌ Safety Glasses - [Reason specific to this worker]
✅/❌ Gloves - [Reason specific to this worker]
✅/❌ Safety Vest - [Reason specific to this worker]
✅/❌ Boots - [Reason specific to this worker]

Hazards Faced by This Worker:
- [Specific hazard 1 that THIS worker faces based on their activity/location]
- [Specific hazard 2 that THIS worker faces]
- [Specific hazard 3 that THIS worker faces]

Potential Risks for This Worker:
- [Specific risk 1 for THIS worker based on their missing PPE]
- [Specific risk 2 for THIS worker]
- [Specific risk 3 for THIS worker]

Suggested Actions for This Worker:
- [Specific action 1 for THIS worker]
- [Specific action 2 for THIS worker]
- [Specific action 3 for THIS worker]

---

WORKER 2:
Description: [What is this worker doing? e.g., "standing nearby"]

PPE Status:
✅/❌ Hardhat - [Reason specific to this worker]
✅/❌ Safety Glasses - [Reason specific to this worker]
✅/❌ Gloves - [Reason specific to this worker]
✅/❌ Safety Vest - [Reason specific to this worker]
✅/❌ Boots - [Reason specific to this worker]

Hazards Faced by This Worker:
- [Specific hazard 1 that THIS worker faces based on their activity/location]
- [Specific hazard 2 that THIS worker faces]
- [Specific hazard 3 that THIS worker faces]

Potential Risks for This Worker:
- [Specific risk 1 for THIS worker based on their missing PPE]
- [Specific risk 2 for THIS worker]
- [Specific risk 3 for THIS worker]

Suggested Actions for This Worker:
- [Specific action 1 for THIS worker]
- [Specific action 2 for THIS worker]
- [Specific action 3 for THIS worker]

---

[Continue for Worker 3, 4, etc. if more workers]

--- END INDIVIDUAL WORKER SECTIONS ---

GENERAL SAFETY RECOMMENDATIONS (for all workers):
1. [Overall site-wide recommendation]
2. [Another general recommendation]
3. [etc.]

Please explain:
1. What OSHA rules may have been violated? 
   - For EACH violation, provide the COMPLETE OSHA citation including:
     * The specific OSHA standard (e.g., "29 CFR 1926.100" or "29 CFR 1910.135")
     * The full regulation name (e.g., "OSHA's Construction Standard" or "Head Protection Standard")
     * A detailed explanation of what the standard requires
   - Example format: "According to OSHA's Construction Standard (29 CFR 1926.100), employees must be protected from head injuries by wearing hard hats when there is a possibility of head injury from impact, flying debris, or projectile objects."
   
2. Why the situation was unsafe?
   - Explain the specific hazards present
   - Describe potential consequences
   - If multiple workers, mention all of them

3. What should have been done to prevent it?
   - Provide specific corrective actions
   - Reference OSHA compliance requirements

IMPORTANT: 
- For question 1, provide COMPLETE and DETAILED OSHA citations with CFR numbers for every violation
- Pay careful attention to negation words (not, without, neither, etc.)
- If multiple workers are mentioned, address all of them"""

    try:
        response = ollama.generate(
            model=rag_config['llama_model'],
            prompt=prompt,
            options={
                'num_predict': 2000,  # Increased to 2000 for detailed per-worker analysis
                'temperature': 0.1,    # Lower for more deterministic/accurate responses
                'top_k': 5,            # More focused on top choices
                'top_p': 0.3           # More conservative sampling
            }
        )
        
        analysis_text = response['response']
        print(f"\n📝 Raw LLM Response (first 800 chars):\n{analysis_text[:800]}")
        print(f"\n📝 Full response length: {len(analysis_text)} characters")
        
        # Check if response contains worker sections
        if 'WORKER 1:' in analysis_text or 'Worker 1:' in analysis_text:
            print("  ✅ LLM generated individual worker sections")
        else:
            print("  ⚠️ LLM did NOT generate individual worker sections - will use fallback")
        
        # Parse the structured text response (not JSON) - pass scenario worker count
        parsed_result = parse_ppe_analysis(analysis_text, scenario_worker_count)
        
        print(f"\n📋 Parsed Result Structure:")
        print(f"  - risk_level: {parsed_result.get('risk_level', 'N/A')}")
        print(f"  - ppe_items count: {len(parsed_result.get('ppe_items', []))}")
        print(f"  - recommendations count: {len(parsed_result.get('recommendations', []))}")
        print(f"  - osha_rules count: {len(parsed_result.get('osha_rules', []))}")
        
        return parsed_result, analysis_text
            
    except Exception as e:
        print(f"❌ Error generating RAG response: {e}")
        import traceback
        traceback.print_exc()
        return create_fallback_response(scenario_text), ""

def parse_ppe_analysis(analysis_text, scenario_worker_count=None):
    """Parse the RAG analysis into structured format with individual worker tracking"""
    # Initialize all variables
    risk_level = "MEDIUM"
    risk_explanation = "Unable to determine risk level."
    ppe_items = []  # Legacy format - will be deprecated
    recommendations = []
    osha_rules = []
    why_unsafe = []
    what_should_be_done = []
    worker_count = scenario_worker_count if scenario_worker_count else 1  # Use scenario count as default
    workers_data = []  # NEW: Individual worker data
    
    # Parse worker count from LLM response (but don't override if scenario count is higher)
    worker_count_match = re.search(r'WORKER COUNT:\s*(\d+)', analysis_text, re.IGNORECASE)
    if worker_count_match:
        llm_worker_count = int(worker_count_match.group(1))
        if scenario_worker_count and llm_worker_count < scenario_worker_count:
            print(f"  ⚠️ LLM said {llm_worker_count} but scenario has {scenario_worker_count} - using {scenario_worker_count}")
            worker_count = scenario_worker_count
        else:
            worker_count = llm_worker_count
            print(f"  📊 Detected {worker_count} worker(s) in LLM response")
    
    # Parse individual worker sections with ALL their data
    worker_pattern = r'WORKER (\d+):\s*Description:\s*(.+?)\s*PPE Status:\s*(.+?)\s*Hazards Faced by This Worker:\s*(.+?)\s*Potential Risks for This Worker:\s*(.+?)\s*Suggested Actions for This Worker:\s*(.+?)(?=---|\nWORKER \d+:|$)'
    worker_matches = re.finditer(worker_pattern, analysis_text, re.IGNORECASE | re.DOTALL)
    
    for match in worker_matches:
        worker_id = int(match.group(1))
        worker_description = match.group(2).strip()
        ppe_section = match.group(3).strip()
        hazards_section = match.group(4).strip()
        risks_section = match.group(5).strip()
        actions_section = match.group(6).strip()
        
        # Parse PPE items for this specific worker
        worker_ppe = {
            'hardhat': 'Not Mentioned',
            'safety_glasses': 'Not Mentioned',
            'gloves': 'Not Mentioned',
            'safety_vest': 'Not Mentioned',
            'footwear': 'Not Mentioned'
        }
        
        # Parse each PPE line
        ppe_lines = ppe_section.split('\n')
        for line in ppe_lines:
            line = line.strip()
            if '✅' in line or '❌' in line or '⚠️' in line:
                status = 'Mentioned' if '✅' in line else ('Missing' if '❌' in line else 'Not Mentioned')
                
                # Extract PPE type and reason
                ppe_match = re.match(r'[✅❌⚠️]\s*(.+?)\s*-\s*(.+)', line)
                if ppe_match:
                    ppe_name = ppe_match.group(1).strip().lower()
                    reason = ppe_match.group(2).strip()
                    
                    # Map to standard keys
                    if 'hardhat' in ppe_name or 'helmet' in ppe_name or 'hard hat' in ppe_name:
                        worker_ppe['hardhat'] = status
                    elif 'glasses' in ppe_name or 'goggles' in ppe_name or 'eye' in ppe_name:
                        worker_ppe['safety_glasses'] = status
                    elif 'glove' in ppe_name:
                        worker_ppe['gloves'] = status
                    elif 'vest' in ppe_name:
                        worker_ppe['safety_vest'] = status
                    elif 'boot' in ppe_name or 'shoe' in ppe_name or 'footwear' in ppe_name:
                        worker_ppe['footwear'] = status
        
        # Parse hazards for this worker
        worker_hazards = []
        for line in hazards_section.split('\n'):
            line = line.strip()
            if line and (line.startswith('-') or line.startswith('•')):
                clean_line = re.sub(r'^[•\-\*]+\s*', '', line).strip()
                if clean_line:
                    worker_hazards.append(clean_line)
        
        # Parse risks for this worker
        worker_risks = []
        for line in risks_section.split('\n'):
            line = line.strip()
            if line and (line.startswith('-') or line.startswith('•')):
                clean_line = re.sub(r'^[•\-\*]+\s*', '', line).strip()
                if clean_line:
                    worker_risks.append(clean_line)
        
        # Parse actions for this worker
        worker_actions = []
        for line in actions_section.split('\n'):
            line = line.strip()
            if line and (line.startswith('-') or line.startswith('•')):
                clean_line = re.sub(r'^[•\-\*]+\s*', '', line).strip()
                if clean_line:
                    worker_actions.append(clean_line)
        
        workers_data.append({
            'id': worker_id,
            'description': worker_description,
            'ppe': worker_ppe,
            'hazards': worker_hazards,
            'risks': worker_risks,
            'actions': worker_actions
        })
        
        print(f"  👤 Worker {worker_id}: {worker_description[:50]}...")
        for ppe_type, status in worker_ppe.items():
            emoji = "🔴" if status == "Missing" else ("🟢" if status == "Mentioned" else "⚪")
            print(f"     {emoji} {ppe_type}: {status}")
        print(f"     📋 {len(worker_hazards)} hazards, {len(worker_risks)} risks, {len(worker_actions)} actions")
    
    # If no individual worker sections found but we have multiple workers, create them manually
    if not workers_data and worker_count > 1:
        print(f"  ⚠️ No individual worker sections found in LLM response")
        print(f"  🔧 Creating {worker_count} individual worker data structures manually...")
        
        # This function needs scenario_text, which we need to pass through
        # For now, create basic worker data - will be enhanced in transform function
        workers_data = []
        for i in range(1, worker_count + 1):
            # Each worker gets base data - will be populated with extracted info later
            workers_data.append({
                'id': i,
                'description': f"Worker {i}",  # Will be enhanced later
                'ppe': {
                    'hardhat': 'Not Mentioned',
                    'safety_glasses': 'Not Mentioned',
                    'gloves': 'Not Mentioned',
                    'safety_vest': 'Not Mentioned',
                    'footwear': 'Not Mentioned'
                },
                'hazards': [],
                'risks': [],
                'actions': []
            })
        print(f"  ✅ Created {len(workers_data)} worker data structures (will be enhanced with scenario data)")
    elif not workers_data:
        print("  ⚠️ No individual worker sections found, using legacy parsing for single worker")
        workers_data = None  # Signal to use old method
    
    # Parse risk level
    risk_match = re.search(r'RISK LEVEL:\s*([A-Z]+)\s*-\s*(.+?)(?=\n\n|WORKER|---)', analysis_text, re.IGNORECASE | re.DOTALL)
    if risk_match:
        risk_level = risk_match.group(1).upper()
        risk_explanation = risk_match.group(2).strip()
    else:
        # Fallback: try to infer from text
        if 'high risk' in analysis_text.lower() or 'severe' in analysis_text.lower():
            risk_level = "HIGH"
        elif 'low risk' in analysis_text.lower() or 'minimal' in analysis_text.lower():
            risk_level = "LOW"
        risk_explanation = "Risk level inferred from analysis context."
    
    # Parse PPE violations
    ppe_section = re.search(r'PPE VIOLATIONS?:(.+?)(?=SAFETY RECOMMENDATIONS?:|Please explain|$)', analysis_text, re.DOTALL | re.IGNORECASE)
    if ppe_section:
        ppe_text = ppe_section.group(1)
        for line in ppe_text.split('\n'):
            line = line.strip()
            if '✅' in line or '❌' in line:
                status = 'Mentioned' if '✅' in line else 'Missing'
                parts = line.split('-', 1)
                if len(parts) == 2:
                    item_name = parts[0].replace('✅', '').replace('❌', '').strip()
                    reason = parts[1].strip()
                    ppe_items.append({
                        'item': item_name,
                        'status': status,
                        'reason': reason
                    })
    else:
        # Fallback: look for common PPE items mentioned
        ppe_keywords = {
            'helmet': 'hardhat',
            'hardhat': 'hardhat',
            'hard hat': 'hardhat',
            'safety glasses': 'safety_glasses',
            'goggles': 'safety_glasses',
            'gloves': 'gloves',
            'vest': 'safety_vest',
            'safety vest': 'safety_vest',
            'boots': 'footwear',
            'shoes': 'footwear'
        }
        
        text_lower = analysis_text.lower()
        for keyword, ppe_type in ppe_keywords.items():
            if keyword in text_lower:
                if 'not wearing' in text_lower or 'without' in text_lower or 'missing' in text_lower:
                    status = 'Missing'
                    reason = f"Required {ppe_type} not detected in scenario"
                else:
                    status = 'Mentioned'
                    reason = f"{ppe_type} mentioned in scenario"
                
                # Avoid duplicates
                if not any(item['item'] == ppe_type for item in ppe_items):
                    ppe_items.append({
                        'item': ppe_type,
                        'status': status,
                        'reason': reason
                    })
    
    # Parse recommendations
    rec_section = re.search(r'SAFETY RECOMMENDATIONS?:(.+?)(?=Please explain|What OSHA|$)', analysis_text, re.DOTALL | re.IGNORECASE)
    if rec_section:
        rec_text = rec_section.group(1)
        for line in rec_text.split('\n'):
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith('•') or line.startswith('-')):
                clean_line = re.sub(r'^[•\-\d\.]+\s*', '', line).strip()
                if clean_line:
                    recommendations.append(clean_line)
    
    # Parse OSHA rules - look for numbered points or OSHA mentions with CFR citations
    osha_patterns = [
        r'(?:What OSHA rules|OSHA RULES)[\s\S]*?violated\??:?\s*(.+?)(?=Why the situation|What should|$)',
        r'\d+\.\s*[^.]*?(?:OSHA|CFR\s+\d+)[^.]+\.',
        r'(?:According to|violate|violation of|Violates?)\s+OSHA[^.]+\.',
        r'(?:29\s+CFR\s+\d+)[^.]*\.[^.]*\.'
    ]
    
    for pattern in osha_patterns:
        osha_matches = re.finditer(pattern, analysis_text, re.DOTALL | re.IGNORECASE)
        for match in osha_matches:
            osha_text = match.group(0) if len(match.groups()) == 0 else match.group(1)
            
            # If it's a multi-line section, split by lines
            if '\n' in osha_text:
                for line in osha_text.split('\n'):
                    line = line.strip()
                    if line and len(line) > 30 and ('osha' in line.lower() or 'cfr' in line.lower()):
                        clean_line = re.sub(r'^[•\-\*\d\.]+\s*', '', line).strip()
                        if clean_line and not clean_line.lower().startswith(('why', 'what', 'please', 'the situation')):
                            if clean_line not in osha_rules:  # Avoid duplicates
                                osha_rules.append(clean_line)
            else:
                # Single sentence match
                clean = osha_text.strip()
                if clean and len(clean) > 30:
                    if clean not in osha_rules:
                        osha_rules.append(clean)
    
    # If no OSHA rules found, extract sentences mentioning OSHA or CFR standards
    if not osha_rules:
        # Split by sentences more carefully
        sentences = re.split(r'(?<=[.!?])\s+', analysis_text)
        for sentence in sentences:
            sentence = sentence.strip()
            # Look for OSHA or CFR citations
            if ('osha' in sentence.lower() or 'cfr' in sentence.lower()) and len(sentence) > 30:
                # Make sure it ends with punctuation
                if not sentence.endswith(('.', '!', '?')):
                    sentence += '.'
                if sentence not in osha_rules:
                    osha_rules.append(sentence)
    
    # Parse "Why the situation was unsafe"
    unsafe_section = re.search(r'(?:Why|why)[\s\S]*?(?:situation was unsafe|unsafe)\??:?\s*(.+?)(?=What should|$)', analysis_text, re.DOTALL | re.IGNORECASE)
    if unsafe_section:
        unsafe_text = unsafe_section.group(1)
        for line in unsafe_text.split('\n'):
            line = line.strip()
            if line and len(line) > 10:
                clean_line = re.sub(r'^[•\-\*\d\.]+\s*', '', line).strip()
                if clean_line and not clean_line.lower().startswith(('what', 'please')):
                    why_unsafe.append(clean_line)
    else:
        # Fallback: extract sentences about unsafe conditions
        unsafe_keywords = ['unsafe', 'dangerous', 'hazard', 'risk']
        sentences = analysis_text.split('.')
        for sentence in sentences:
            if any(kw in sentence.lower() for kw in unsafe_keywords) and len(sentence.strip()) > 30:
                clean = sentence.strip() + '.'
                if clean not in why_unsafe:
                    why_unsafe.append(clean)
    
    # Parse "What should have been done"
    should_section = re.search(r'(?:What should|should have been done)[\s\S]*?(?:prevent it|prevent)\??:?\s*(.+?)$', analysis_text, re.DOTALL | re.IGNORECASE)
    if should_section:
        should_text = should_section.group(1)
        for line in should_text.split('\n'):
            line = line.strip()
            if line and len(line) > 10:
                clean_line = re.sub(r'^[•\-\*\d\.]+\s*', '', line).strip()
                if clean_line and not clean_line.lower().startswith('provide your'):
                    what_should_be_done.append(clean_line)
    else:
        # Fallback: look for prevention/mitigation suggestions
        prevent_keywords = ['should', 'must', 'require', 'need to', 'recommend']
        sentences = analysis_text.split('.')
        for sentence in sentences:
            if any(kw in sentence.lower() for kw in prevent_keywords) and len(sentence.strip()) > 30:
                clean = sentence.strip() + '.'
                if clean not in what_should_be_done:
                    what_should_be_done.append(clean)
    
    return {
        'risk_level': risk_level,
        'risk_explanation': risk_explanation,
        'ppe_items': ppe_items,  # Legacy - kept for backward compatibility
        'recommendations': recommendations,
        'osha_rules': osha_rules,
        'why_unsafe': why_unsafe,
        'what_should_be_done': what_should_be_done,
        'worker_count': worker_count,
        'workers_data': workers_data  # NEW: Individual worker data with their own PPE status
    }

def transform_to_frontend_format(analysis_result, scenario_text, risk_level, confidence_score, detected_ppe):
    """
    Transform the backend analysis result to match frontend expected format
    Frontend expects: summary, confidence_score, persons, hazards_detected, suggested_actions
    
    NEW: Handles individual worker data when available
    """
    # Get worker count from analysis or extract from scenario
    worker_count = analysis_result.get('worker_count', extract_worker_count(scenario_text))
    
    # Build summary from risk level and explanation
    risk_explanation = analysis_result.get('risk_explanation', '')
    worker_text = f"{worker_count} worker(s) identified. " if worker_count > 1 else ""
    summary = f"{worker_text}Risk Level: {risk_level}. {risk_explanation}"
    
    # Check if we have individual worker data from LLM
    workers_data = analysis_result.get('workers_data', None)
    use_individual_tracking = workers_data is not None and len(workers_data) > 0
    
    if use_individual_tracking:
        print(f"\n✅ Using individual worker tracking for {len(workers_data)} worker(s)")
    else:
        print(f"\n⚠️ Using unified PPE status for all workers")
    
    # Initialize default PPE status (used if no individual data)
    default_ppe_status = {
        'hardhat': 'Not Mentioned',
        'safety_glasses': 'Not Mentioned',
        'gloves': 'Not Mentioned',
        'safety_vest': 'Not Mentioned',
        'footwear': 'Not Mentioned'
    }
    
    # If no individual worker data, build unified PPE status (legacy method)
    if not use_individual_tracking:
        ppe_status = default_ppe_status.copy()
        
        # Map common PPE names to frontend keys
        ppe_mapping = {
            'helmet': 'hardhat',
            'hard hat': 'hardhat',
            'hardhat': 'hardhat',
            'hat': 'hardhat',
            'safety glasses': 'safety_glasses',
            'glasses': 'safety_glasses',
            'goggles': 'safety_glasses',
            'safety_glasses': 'safety_glasses',
            'glove': 'gloves',
            'gloves': 'gloves',
            'vest': 'safety_vest',
            'safety vest': 'safety_vest',
            'safety_vest': 'safety_vest',
            'high visibility vest': 'safety_vest',
            'boot': 'footwear',
            'boots': 'footwear',
            'shoes': 'footwear',
            'footwear': 'footwear',
            'safety shoes': 'footwear'
        }
        
        # Update PPE status from analysis result
        for item in analysis_result.get('ppe_items', []):
            item_name = item.get('item', '').lower()
            status = item.get('status', 'Not Mentioned')
            
            # Map to frontend key
            frontend_key = ppe_mapping.get(item_name, None)
            if frontend_key:
                # Convert status to frontend format
                if status == 'Mentioned':
                    ppe_status[frontend_key] = "Mentioned"
                elif status == 'Missing':
                    ppe_status[frontend_key] = "Missing"
                else:
                    ppe_status[frontend_key] = "Not Mentioned"
        
        # Override with detected PPE items from scenario text (more reliable)
        for ppe_item, status in detected_ppe.items():
            if ppe_item in ppe_status:
                # Use the detected status (which includes negation detection)
                ppe_status[ppe_item] = status
    
    # Build person object (single person from scenario)
    # Actions renamed to "Suggested Actions"
    # Hazards Faced remains for unsafe conditions
    # Risks now focuses ONLY on potential risks of violating OSHA guidelines
    
    # Include all actionable recommendations (do not strip OSHA citation lines)
    all_actions = analysis_result.get('what_should_be_done', []) + analysis_result.get('recommendations', [])
    # Keep everything as-is — user requested OSHA citation lines remain available in suggested actions
    filtered_actions = list(all_actions)
    
    # Dynamically build potential risks for all missing PPE (use detected_ppe which is always available)
    potential_risks = []
    missing_risk_map = {
        'hardhat': 'Risk of head injuries from falling objects or impacts due to missing head protection.',
        'gloves': 'Risk of hand injuries from cuts, abrasions, or chemicals due to missing gloves.',
        'safety_glasses': 'Risk of eye injuries from flying particles, chemicals, or equipment due to missing safety glasses.',
        'safety_vest': 'Risk of reduced visibility and increased accident risk due to missing safety vest.',
        'footwear': 'Risk of foot injuries from heavy objects, sharp debris, or slips due to missing protective footwear.'
    }
    for ppe_key, status in detected_ppe.items():
        if status == 'Missing' and ppe_key in missing_risk_map:
            potential_risks.append(missing_risk_map[ppe_key])
    # Always include general OSHA violation risks
    potential_risks.append('Potential for serious injury or fatality from OSHA violations.')
    potential_risks.append('Legal and compliance risks for employer due to safety violations.')
    potential_risks.append('Increased liability exposure from inadequate PPE compliance.')

    # Create person objects - one for each worker mentioned
    persons = []
    
    if use_individual_tracking:
        # Extract worker descriptions from scenario if needed
        worker_descriptions_data = extract_worker_descriptions(scenario_text, len(workers_data))
        
        # USE INDIVIDUAL WORKER DATA - Each worker has their own everything
        for idx, worker_data in enumerate(workers_data):
            worker_id = worker_data['id']
            worker_description = worker_data['description']
            worker_text_segment = ""
            
            # Enhance description if it's generic
            if worker_description == f"Worker {worker_id}":
                if idx < len(worker_descriptions_data):
                    worker_description, worker_text_segment = worker_descriptions_data[idx]
            
            worker_ppe = worker_data['ppe'].copy()
            
            # If PPE status is all "Not Mentioned" (fallback mode), analyze individual worker
            if all(status == "Not Mentioned" for status in worker_ppe.values()):
                print(f"  🔧 Analyzing individual PPE for Worker {worker_id}")
                # First, apply global detected PPE as baseline
                for ppe_key, status in detected_ppe.items():
                    if ppe_key in worker_ppe:
                        worker_ppe[ppe_key] = status
                
                # Then, override with worker-specific PPE if found in their text segment
                if worker_text_segment:
                    print(f"    📝 Worker {worker_id} segment: '{worker_text_segment[:60]}...'")
                    worker_ppe = extract_individual_worker_ppe(worker_text_segment, worker_ppe)
            
            # Get individual data from LLM response (if available)
            worker_hazards = worker_data.get('hazards', [])
            worker_risks = worker_data.get('risks', [])
            worker_actions = worker_data.get('actions', [])
            
            # Fallback: If LLM didn't provide individual sections, calculate them
            if not worker_hazards:
                worker_hazards = analysis_result.get('why_unsafe', [])[:5]
            
            if not worker_risks:
                # Calculate individual risks based on THIS worker's missing PPE
                individual_risks = []
                missing_risk_map = {
                    'hardhat': 'Risk of head injuries from falling objects or impacts due to missing head protection.',
                    'gloves': 'Risk of hand injuries from cuts, abrasions, or chemicals due to missing gloves.',
                    'safety_glasses': 'Risk of eye injuries from flying particles, chemicals, or equipment due to missing safety glasses.',
                    'safety_vest': 'Risk of reduced visibility and increased accident risk due to missing safety vest.',
                    'footwear': 'Risk of foot injuries from heavy objects, sharp debris, or slips due to missing protective footwear.'
                }
                
                for ppe_key, status in worker_ppe.items():
                    if status == 'Missing' and ppe_key in missing_risk_map:
                        individual_risks.append(missing_risk_map[ppe_key])
                
                # Always include general OSHA violation risks
                if len(individual_risks) > 0:
                    individual_risks.append('Potential for serious injury or fatality from OSHA violations.')
                    individual_risks.append('Legal and compliance risks for employer due to safety violations.')
                
                worker_risks = individual_risks
            
            if not worker_actions:
                worker_actions = filtered_actions[:5]
            
            person = {
                'id': worker_id,
                'description': worker_description,
                'actions': worker_actions[:5],  # INDIVIDUAL Suggested Actions for this worker
                'hazards_faced': worker_hazards[:5],  # INDIVIDUAL Hazards for this worker
                'risks': worker_risks[:5],  # INDIVIDUAL Risks for this worker
                'ppe': worker_ppe  # INDIVIDUAL PPE status for this worker
            }
            persons.append(person)
            
            print(f"  ✅ Worker {worker_id}: {len(worker_actions)} actions, {len(worker_hazards)} hazards, {len(worker_risks)} risks")
    
    else:
        # LEGACY METHOD - All workers have same PPE status
        for worker_id in range(1, worker_count + 1):
            # Create description based on worker count
            if worker_count > 1:
                worker_description = f"Worker {worker_id}: {scenario_text[:80]}..." if len(scenario_text) > 80 else f"Worker {worker_id}: {scenario_text}"
            else:
                worker_description = scenario_text[:100] + ('...' if len(scenario_text) > 100 else '')
            
            person = {
                'id': worker_id,
                'description': worker_description,
                'actions': filtered_actions[:5],  # Suggested Actions
                'hazards_faced': analysis_result.get('why_unsafe', [])[:5],  # Why unsafe
                'risks': potential_risks[:5],  # General risks
                'ppe': ppe_status.copy()  # Same PPE status for all workers
            }
            persons.append(person)
            
            print(f"  ⚠️ Created person card for Worker {worker_id} with unified PPE status")
    
    # Previously we placed OSHA citations in hazards_detected; per user request,
    # move OSHA citation content into the bottom "Suggested Actions" section
    # and leave the OSHA Violation Guidelines (hazards_detected) empty.
    osha_rules = analysis_result.get('osha_rules', [])

    # Bottom suggested actions will contain the OSHA citations first (detailed),
    # followed by the filtered actionable recommendations.
    suggested_actions = []
    # Add OSHA citation lines (keep as-is so they include "According to..." phrasing)
    for rule in osha_rules:
        suggested_actions.append(rule)
    # Then add the filtered actionable suggestions (non-OSHA text)
    suggested_actions.extend(filtered_actions)

    hazards_detected = []  # keep empty as OSHA citations moved to suggested_actions

    tracking_method = "individual PPE tracking" if use_individual_tracking else "unified PPE status"
    print(f"\n👥 Created {len(persons)} person card(s) for {worker_count} worker(s) using {tracking_method}")

    return {
        'summary': summary,
        'confidence_score': str(int(confidence_score)),
        'persons': persons,
        'hazards_detected': hazards_detected[:5],  # intentionally empty
        'suggested_actions': suggested_actions[:8]  # show top items (citations + actions)
    }

# ============================================================================
# Routes
# ============================================================================

@app.route('/')
def index():
    """Serve the main HTML page from User interface folder"""
    html_path = Path("User interface/index.html")
    with open(html_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    return render_template_string(html_content)

@app.route('/style.css')
def serve_css():
    """Serve CSS file from User interface folder"""
    return send_from_directory('User interface', 'style.css')

@app.route('/api/analyze', methods=['POST'])
def analyze_scene():
    """
    Main API endpoint for scene analysis
    Accepts JSON with 'scene_description'
    Returns structured analysis with PPE violations, hazards, and recommendations
    """
    try:
        data = request.get_json()
        
        if not data or 'scene_description' not in data:
            return jsonify({'error': 'No scene description provided'}), 400
        
        scenario_text = data['scene_description']
        
        print("\n" + "="*80)
        print("🔍 NEW ANALYSIS REQUEST")
        print("="*80)
        print(f"Scenario: {scenario_text[:100]}...")
        
        # Step 1: Extract worker count
        worker_count = extract_worker_count(scenario_text)
        print(f"\n👥 Worker Count: {worker_count}")
        
        # Step 2: Extract PPE items from text with negation detection
        print(f"\n🦺 Extracting PPE Items with Negation Detection:")
        ppe_items = extract_ppe_items(scenario_text)
        print(f"\n📊 PPE Detection Summary:")
        for ppe, status in ppe_items.items():
            print(f"  - {ppe}: {status}")
        
        # Step 2: Retrieve relevant context from ChromaDB
        print("\n📚 Retrieving context from knowledge base...")
        
        top_k_guidelines = rag_config.get('top_k_guidelines', 3)
        guidelines_results = ppe_collection.query(
            query_texts=[scenario_text],
            n_results=top_k_guidelines
        )
        
        top_k_scenarios = rag_config.get('top_k_scenarios', 5)
        scenarios_results = scenarios_collection.query(
            query_texts=[scenario_text],
            n_results=top_k_scenarios
        )
        
        context = {
            'guidelines': [
                {
                    'text': doc,
                    'distance': dist
                }
                for doc, dist in zip(
                    guidelines_results['documents'][0],
                    guidelines_results['distances'][0]
                )
            ],
            'similar_scenarios': [
                {
                    'text': doc,
                    'risk_level': meta.get('risk_level', 'Unknown'),
                    'ppe_required': meta.get('ppe_required', 'Not specified'),
                    'distance': dist
                }
                for doc, meta, dist in zip(
                    scenarios_results['documents'][0],
                    scenarios_results['metadatas'][0],
                    scenarios_results['distances'][0]
                )
            ]
        }
        
        print(f"  ✅ Retrieved {len(context['guidelines'])} guidelines")
        print(f"  ✅ Retrieved {len(context['similar_scenarios'])} similar scenarios")
        
        # Step 3: Generate RAG-based analysis
        print("\n🤖 Generating AI analysis...")
        analysis_result, analysis_text = generate_rag_response(scenario_text, context, worker_count)
        
        # CRITICAL FIX: Override worker_count if LLM didn't detect it properly
        llm_worker_count = analysis_result.get('worker_count', 1)
        if llm_worker_count != worker_count:
            print(f"  ⚠️ LLM detected {llm_worker_count} worker(s), but scenario has {worker_count} worker(s)")
            print(f"  🔧 Using scenario-extracted count: {worker_count}")
            analysis_result['worker_count'] = worker_count
        
        # Step 4: Get risk classification from ML model
        print("\n⚠️  Classifying risk level...")
        scenario_vectorized = tfidf_vectorizer.transform([scenario_text])
        risk_proba = risk_classifier.predict_proba(scenario_vectorized)
        risk_class = risk_classifier.predict(scenario_vectorized)[0]
        risk_level = label_encoder.inverse_transform([risk_class])[0]
        
        print(f"  Risk Level: {risk_level}")
        print(f"  Confidence: {max(risk_proba[0])*100:.1f}%")
        
        # Step 5: Calculate hybrid confidence score
        confidence_score = calculate_confidence_score(
            scenario_text,
            ppe_items,
            context,
            risk_proba,
            analysis_text
        )
        
        # Override the confidence score in analysis result with our calculated one
        analysis_result['confidence_score'] = str(int(confidence_score))
        
        # Add risk level to response
        analysis_result['risk_level'] = risk_level
        analysis_result['risk_probability'] = {
            label_encoder.inverse_transform([i])[0]: float(prob)
            for i, prob in enumerate(risk_proba[0])
        }
        
        # Transform to frontend format
        frontend_response = transform_to_frontend_format(
            analysis_result, 
            scenario_text, 
            risk_level, 
            confidence_score,
            ppe_items
        )
        
        print("\n📤 Frontend Response:")
        print(f"  Summary: {frontend_response['summary'][:80]}...")
        print(f"  Confidence: {frontend_response['confidence_score']}%")
        print(f"  Persons: {len(frontend_response['persons'])}")
        print(f"  Hazards: {len(frontend_response['hazards_detected'])}")
        print(f"  Actions: {len(frontend_response['suggested_actions'])}")
        
        print("\n✅ Analysis complete!")
        print("="*80)
        
        # Send email notification if enabled
        if email_config.get('enabled', False):
            # Check if we should send for this risk level (case-insensitive)
            send_on_levels = [level.upper() for level in email_config.get('send_on_risk_levels', ['HIGH', 'MEDIUM', 'LOW'])]
            if risk_level.upper() in send_on_levels:
                print("\n📧 Sending email notification...")
                try:
                    send_notification(
                        analysis_data={
                            'risk_level': risk_level,
                            'confidence_score': str(int(confidence_score)),
                            'persons': frontend_response['persons'],
                            'summary': frontend_response['summary']
                        },
                        scenario_text=scenario_text,
                        config=email_config
                    )
                except Exception as e:
                    print(f"⚠️ Email notification failed: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"ℹ️ Risk level {risk_level} not in notification list {send_on_levels}, skipping email")
        
        return jsonify(frontend_response)
        
    except Exception as e:
        print(f"\n❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'model_loaded': risk_classifier is not None,
        'chroma_connected': ppe_collection is not None,
        'llm_model': rag_config['llama_model']
    })

# ============================================================================
# Main
# ============================================================================

if __name__ == '__main__':
    print("\n" + "="*80)
    print("🚀 STARTING AI SAFETY INSPECTOR WEB APP")
    print("="*80)
    print("\n📍 Server will be available at: http://localhost:5000")
    print("📍 API endpoint: http://localhost:5000/api/analyze")
    print("\n💡 Make sure Ollama is running with the model:", rag_config['llama_model'])
    print("="*80 + "\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
