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
    Detects negations like 'not wearing', 'without', etc.
    """
    ppe_keywords = {
        'hardhat': ['hard hat', 'hardhat', 'helmet', 'hard-hat'],
        'safety_glasses': ['safety glasses', 'goggles', 'eye protection', 'safety goggles', 'glasses'],
        'gloves': ['gloves', 'hand protection', 'glove'],
        'safety_vest': ['safety vest', 'hi-vis', 'high visibility', 'reflective vest', 'vest'],
        'footwear': ['safety boots', 'steel-toe', 'safety shoes', 'protective footwear', 'boots', 'shoes']
    }
    
    detected_ppe = {}
    text_lower = scenario_text.lower()
    
    # For each PPE type, check if mentioned AND check for negation context
    for ppe_type, keywords in ppe_keywords.items():
        for keyword in keywords:
            if keyword in text_lower:
                # Find the position of the keyword
                keyword_pos = text_lower.find(keyword)
                # Get surrounding context (60 chars before the keyword)
                context_before = text_lower[max(0, keyword_pos-60):keyword_pos]
                
                # Negation indicators
                negations = ['not wearing', 'without', 'no ', 'missing', 'not using', 
                            'lacks', 'absent', 'not have', "doesn't have", 'removed',
                            'but not', 'except', 'not a ', "isn't wearing", 'failed to wear']
                
                is_negated = any(neg in context_before for neg in negations)
                
                if is_negated:
                    detected_ppe[ppe_type] = "Missing"
                else:
                    detected_ppe[ppe_type] = "Mentioned"
                break
        
        # If not found at all, mark as "Not Mentioned"
        if ppe_type not in detected_ppe:
            detected_ppe[ppe_type] = "Not Mentioned"
    
    return detected_ppe

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

def generate_rag_response(scenario_text, context):
    """Generate analysis using RAG with Ollama"""
    
    # Build context string from retrieved guidelines
    context_str = ""
    if context.get('guidelines'):
        context_str = "OSHA GUIDELINES:\n"
        for guideline in context['guidelines'][:2]:  # Limit to 2 guidelines
            context_str += f"{guideline['text'][:500]}\n"
    
    prompt = f"""Analyze PPE compliance for this workplace scenario.

Guidelines: {context_str}

Scenario: {scenario_text}

RULES:
1. Check what PPE is mentioned in the scenario
2. ✅ = PPE is mentioned/worn | ❌ = PPE NOT mentioned/missing
3. Each PPE item needs brief explanation (max 30 words)
4. Provide safety recommendations

OUTPUT FORMAT:

RISK LEVEL: [HIGH/MEDIUM/LOW] - [Explanation]

PPE VIOLATIONS:
✅ [PPE Item] - [Reason why compliant]
❌ [PPE Item] - [Reason why violation/missing]

SAFETY RECOMMENDATIONS:
1. Make the recommendations clear and detailed. Use professional language and make sure to give a good recommendations and long

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

3. What should have been done to prevent it?
   - Provide specific corrective actions
   - Reference OSHA compliance requirements

IMPORTANT: For question 1, provide COMPLETE and DETAILED OSHA citations with CFR numbers for every violation. Be specific and comprehensive."""

    try:
        response = ollama.generate(
            model=rag_config['llama_model'],
            prompt=prompt,
            options={
                'num_predict': 800,
                'temperature': 0.2,
                'top_k': 10,
                'top_p': 0.5
            }
        )
        
        analysis_text = response['response']
        print(f"\n📝 Raw LLM Response (first 500 chars):\n{analysis_text[:500]}")
        
        # Parse the structured text response (not JSON)
        parsed_result = parse_ppe_analysis(analysis_text)
        
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

def parse_ppe_analysis(analysis_text):
    """Parse the RAG analysis into structured format"""
    # Initialize all variables
    risk_level = "MEDIUM"
    risk_explanation = "Unable to determine risk level."
    ppe_items = []
    recommendations = []
    osha_rules = []
    why_unsafe = []
    what_should_be_done = []
    
    # Parse risk level
    risk_match = re.search(r'RISK LEVEL:\s*([A-Z]+)\s*-\s*(.+?)(?=\n\n|PPE|$)', analysis_text, re.IGNORECASE | re.DOTALL)
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
        'ppe_items': ppe_items,
        'recommendations': recommendations,
        'osha_rules': osha_rules,
        'why_unsafe': why_unsafe,
        'what_should_be_done': what_should_be_done
    }

def transform_to_frontend_format(analysis_result, scenario_text, risk_level, confidence_score, detected_ppe):
    """
    Transform the backend analysis result to match frontend expected format
    Frontend expects: summary, confidence_score, persons, hazards_detected, suggested_actions
    """
    # Build summary from risk level and explanation
    risk_explanation = analysis_result.get('risk_explanation', '')
    summary = f"Risk Level: {risk_level}. {risk_explanation}"
    
    # Initialize PPE status with all required items (frontend expects these exact keys)
    ppe_status = {
        'hardhat': 'Not Mentioned',
        'safety_glasses': 'Not Mentioned',
        'gloves': 'Not Mentioned',
        'safety_vest': 'Not Mentioned',
        'footwear': 'Not Mentioned'
    }
    
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
    
    # Dynamically build potential risks for all missing PPE
    potential_risks = []
    missing_risk_map = {
        'hardhat': 'Risk of head injuries from falling objects or impacts due to missing head protection.',
        'gloves': 'Risk of hand injuries from cuts, abrasions, or chemicals due to missing gloves.',
        'safety_glasses': 'Risk of eye injuries from flying particles, chemicals, or equipment due to missing safety glasses.',
        'safety_vest': 'Risk of reduced visibility and increased accident risk due to missing safety vest.',
        'footwear': 'Risk of foot injuries from heavy objects, sharp debris, or slips due to missing protective footwear.'
    }
    for ppe_key, status in ppe_status.items():
        if status == 'Missing' and ppe_key in missing_risk_map:
            potential_risks.append(missing_risk_map[ppe_key])
    # Always include general OSHA violation risks
    potential_risks.append('Potential for serious injury or fatality from OSHA violations.')
    potential_risks.append('Legal and compliance risks for employer due to safety violations.')
    potential_risks.append('Increased liability exposure from inadequate PPE compliance.')

    person = {
        'id': 1,
        'description': scenario_text[:100] + ('...' if len(scenario_text) > 100 else ''),
        'actions': filtered_actions[:5],  # Suggested Actions - OSHA citations removed
        'hazards_faced': analysis_result.get('why_unsafe', [])[:5],  # Why unsafe
        'risks': potential_risks[:5],  # Now dynamic based on missing PPE
        'ppe': ppe_status
    }
    
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

    return {
        'summary': summary,
        'confidence_score': str(int(confidence_score)),
        'persons': [person],
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
        
        # Step 1: Extract PPE items from text
        ppe_items = extract_ppe_items(scenario_text)
        print(f"\n🦺 PPE Items Detected:")
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
        analysis_result, analysis_text = generate_rag_response(scenario_text, context)
        
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
