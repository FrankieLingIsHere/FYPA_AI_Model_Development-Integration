"""
Report Generator - NLP-powered report generation with RAG
==========================================================

Generates comprehensive safety violation reports combining:
1. YOLO detection data (hard metrics)
2. Image caption from LLaVA  
3. RAG retrieval from incident database (Trim1.csv)
4. NLP analysis from Llama3 8b (soft reporting)
5. HTML report generation
6. PDF conversion

Based on NLP_Luna/llama3_variant implementation.
"""

import logging
import json
import csv
import requests
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from datetime import datetime
import sys

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.absolute()))

# Try to import local Llama
try:
    from pipeline.backend.integration.local_llama import LocalLlamaGenerator
    LOCAL_LLAMA_AVAILABLE = True
except ImportError:
    LOCAL_LLAMA_AVAILABLE = False

# Try to import Chroma DB
try:
    import chromadb
    from chromadb.config import Settings
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False
    logging.warning("chromadb not installed. Install with: pip install chromadb")

logger = logging.getLogger(__name__)


class ReportGenerator:
    """
    Generates safety violation reports with NLP analysis.
    
    Uses RAG (Retrieval-Augmented Generation) with historical incident data
    and Llama3 via Ollama for intelligent report generation.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize report generator.
        
        Args:
            config: Configuration dictionary from config.py
        """
        self.config = config
        
        # Ollama settings
        ollama_config = config.get('OLLAMA_CONFIG', {})
        self.api_url = ollama_config.get('api_url', 'http://localhost:11434/api/generate')
        self.model = ollama_config.get('model', 'llama3')
        self.temperature = ollama_config.get('temperature', 0.7)
        self.ollama_timeout = ollama_config.get('timeout', 600)  # Default 10 minutes for detailed analysis
        
        # Local Llama settings (fallback if Ollama not available)
        self.use_local_llama = ollama_config.get('use_local_model', True)
        self.local_model_path = ollama_config.get('local_model_path', 
            r'C:\Users\maste\Downloads\FYP Combined\Meta-Llama-3-8B-Instruct')
        self.local_llama = None
        
        # Initialize local Llama if configured
        if self.use_local_llama and LOCAL_LLAMA_AVAILABLE:
            try:
                logger.info("Initializing local Llama model...")
                self.local_llama = LocalLlamaGenerator(self.local_model_path)
                logger.info("[OK] Local Llama initialized (will load on first use)")
            except Exception as e:
                logger.warning(f"Could not initialize local Llama: {e}")
                self.local_llama = None
        
        # RAG settings
        rag_config = config.get('RAG_CONFIG', {})
        self.rag_enabled = rag_config.get('enabled', True)
        self.use_chroma = rag_config.get('use_chroma', False)
        self.chroma_path = rag_config.get('chroma_path', '')
        self.collection_name = rag_config.get('collection_name', 'dosh_documentation')
        self.embedding_model = rag_config.get('embedding_model', 'nomic-embed-text')
        self.rag_data_path = rag_config.get('data_source', '')
        self.num_similar = rag_config.get('num_similar_incidents', 2)
        self.top_k = rag_config.get('top_k', 3)
        
        # Chroma DB client
        self.chroma_client = None
        self.chroma_collection = None
        if self.rag_enabled and self.use_chroma:
            self._initialize_chroma()
        
        # Report settings
        report_config = config.get('REPORT_CONFIG', {})
        self.reports_dir = config.get('REPORTS_DIR', Path('reports'))
        self.violations_dir = config.get('VIOLATIONS_DIR', Path('violations'))
        self.format = report_config.get('format', 'both')
        self.enable_pdf = report_config.get('enable_pdf_generation', True)
        
        # Brand colors
        self.colors = config.get('BRAND_COLORS', {
            'primary': '#E67E22',
            'secondary': '#5B7A9E',
            'success': '#2ECC71',
            'warning': '#F39C12',
            'danger': '#E74C3C'
        })
        
        # Load RAG incident database
        self.incident_data = []
        if self.rag_enabled:
            self._load_incident_database()
        
        logger.info("Report Generator initialized")
    
    # =========================================================================
    # RAG - INCIDENT DATABASE
    # =========================================================================
    
    def _load_incident_database(self):
        """Load incident database from CSV for RAG."""
        try:
            rag_path = Path(self.rag_data_path)
            if not rag_path.exists():
                logger.warning(f"RAG data file not found: {rag_path}")
                return
            
            with open(rag_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                self.incident_data = list(reader)
            
            logger.info(f"[OK] Loaded {len(self.incident_data)} incident records for RAG")
            
        except Exception as e:
            logger.error(f"Error loading incident database: {e}")
            self.incident_data = []
    
    def _initialize_chroma(self):
        """Initialize Chroma DB client and collection."""
        if not CHROMA_AVAILABLE:
            logger.error("Chroma DB not available. Install with: pip install chromadb")
            self.use_chroma = False
            return
        
        try:
            logger.info(f"Initializing Chroma DB from: {self.chroma_path}")
            
            # Initialize client with persistent storage
            self.chroma_client = chromadb.PersistentClient(
                path=str(self.chroma_path),
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=False
                )
            )
            
            # Get existing collection
            self.chroma_collection = self.chroma_client.get_collection(
                name=self.collection_name
            )
            
            # Get collection info
            count = self.chroma_collection.count()
            logger.info(f"[OK] Chroma DB connected: {count} documents in '{self.collection_name}' collection")
            logger.info(f"Using embedding model: {self.embedding_model}")
            
        except Exception as e:
            logger.error(f"Failed to initialize Chroma DB: {e}")
            logger.warning("Falling back to CSV-based RAG")
            self.use_chroma = False
            self.chroma_client = None
            self.chroma_collection = None
    
    def _get_ollama_embeddings(self, text: str) -> Optional[List[float]]:
        """Get embeddings from Ollama using nomic-embed-text."""
        try:
            response = requests.post(
                'http://localhost:11434/api/embeddings',
                json={
                    'model': self.embedding_model,
                    'prompt': text
                },
                timeout=30
            )
            
            if response.ok:
                data = response.json()
                return data.get('embedding')
            else:
                logger.error(f"Ollama embeddings error: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting Ollama embeddings: {e}")
            return None
    
    def _query_chroma_db(
        self,
        query_text: str,
        n_results: int = 3
    ) -> List[Dict[str, Any]]:
        """Query Chroma DB for relevant DOSH documentation."""
        if not self.chroma_collection:
            return []
        
        try:
            # Get embeddings for query
            query_embedding = self._get_ollama_embeddings(query_text)
            
            if not query_embedding:
                logger.warning("Could not generate query embeddings, skipping Chroma search")
                return []
            
            # Query collection
            results = self.chroma_collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                include=['documents', 'metadatas', 'distances']
            )
            
            # Format results
            formatted_results = []
            if results['documents'] and len(results['documents']) > 0:
                for i, doc in enumerate(results['documents'][0]):
                    metadata = results['metadatas'][0][i] if results['metadatas'] else {}
                    distance = results['distances'][0][i] if results['distances'] else 0.0
                    
                    formatted_results.append({
                        'content': doc,
                        'metadata': metadata,
                        'relevance_score': 1.0 - distance,  # Convert distance to similarity
                        'source': 'DOSH Documentation'
                    })
            
            logger.info(f"Found {len(formatted_results)} relevant DOSH chunks")
            return formatted_results
            
        except Exception as e:
            logger.error(f"Error querying Chroma DB: {e}")
            return []
    
    def _find_similar_incidents(
        self,
        description: str,
        count: int = 2
    ) -> List[Dict[str, str]]:
        """
        Find similar incidents using keyword matching (basic RAG).
        
        Args:
            description: Description to match against
            count: Number of similar incidents to return
        
        Returns:
            List of similar incident dictionaries
        """
        if not self.incident_data:
            return []
        
        # Extract keywords from description
        description_words = set(description.lower().split())
        
        # Score incidents by keyword overlap
        scored = []
        for incident in self.incident_data:
            abstract = incident.get('Abstract', '')
            abstract_words = set(abstract.lower().split())
            
            # Calculate overlap score
            overlap = len(description_words & abstract_words)
            scored.append((overlap, incident))
        
        # Sort by score and return top N
        scored.sort(reverse=True, key=lambda x: x[0])
        return [incident for score, incident in scored[:count] if score > 0]
    
    # =========================================================================
    # NLP - OLLAMA INTEGRATION
    # =========================================================================
    
    def _build_nlp_prompt(
        self,
        report_data: Dict[str, Any],
        similar_incidents: List[Dict[str, str]],
        dosh_context: List[Dict[str, Any]] = None
    ) -> str:
        """
        Build enhanced prompt for Llama based on NLP_Luna template.
        Includes environment-aware analysis and objective/subjective metrics.
        Now includes DOSH documentation context from Chroma DB.
        
        Args:
            report_data: Report data including caption, detections, etc.
            similar_incidents: Similar incidents from CSV RAG
            dosh_context: Relevant DOSH documentation chunks from Chroma DB
        
        Returns:
            Formatted prompt string
        """
        # Extract data
        caption = report_data.get('caption', 'No caption available')
        detections = report_data.get('detections', [])
        violation_summary = report_data.get('violation_summary', '')
        person_count = report_data.get('person_count', 0)
        
        # Build detection description and identify missing PPE
        detection_desc = []
        missing_ppe = []
        for det in detections:
            # Handle both 'confidence' and 'score' keys
            conf_value = det.get('confidence', det.get('score', 0.0))
            class_name = det['class_name']
            detection_desc.append(
                f"- {class_name} (confidence: {conf_value:.2f})"
            )
            
            # Identify missing PPE from NO-X detections
            if class_name.startswith('NO-'):
                ppe_item = class_name.replace('NO-', '').replace('Hardhat', 'Safety Helmet').replace('Safety Vest', 'High-Visibility Vest')
                missing_ppe.append(ppe_item)
        
        # Also parse caption for missing PPE keywords
        caption_lower = caption.lower()
        ppe_keywords = {
            'hardhat': ['hardhat', 'hard hat', 'safety helmet', 'helmet'],
            'safety_vest': ['vest', 'high-visibility', 'hi-vis', 'safety vest'],
            'gloves': ['gloves', 'hand protection'],
            'goggles': ['goggles', 'eye protection', 'safety glasses'],
            'footwear': ['boots', 'safety boots', 'footwear', 'safety shoes'],
            'mask': ['mask', 'respirator', 'face mask']
        }
        
        caption_missing = []
        for ppe_type, keywords in ppe_keywords.items():
            for keyword in keywords:
                # Check if caption mentions NOT wearing this PPE
                if any(phrase in caption_lower for phrase in [
                    f'not wearing {keyword}',
                    f'without {keyword}',
                    f'no {keyword}',
                    f'absence of {keyword}',
                    f'lack of {keyword}',
                    f'missing {keyword}'
                ]):
                    caption_missing.append(ppe_type.replace('_', ' ').title())
                    break
        
        # Combine detected and caption-identified missing PPE
        all_missing = list(set(missing_ppe + caption_missing))
        missing_ppe_text = f"**CONFIRMED MISSING PPE**: {', '.join(all_missing)} (Mark these as 'Missing' in PPE status)" if all_missing else "All required PPE present"
        
        # Build context from DOSH documentation (primary source)
        dosh_text = ""
        if dosh_context and len(dosh_context) > 0:
            dosh_text = "=== DOSH SAFETY REGULATIONS (Authoritative Source) ===\n\n"
            for i, chunk in enumerate(dosh_context, 1):
                content = chunk.get('content', '')
                source = chunk.get('metadata', {}).get('source', 'DOSH Documentation')
                dosh_text += f"[Regulation {i}]\n{content}\n\n"
            dosh_text += "=== END DOSH REGULATIONS ===\n\n"
        
        # Build context from similar incidents (secondary source)
        context_text = ""
        if similar_incidents:
            context_text = "=== HISTORICAL INCIDENTS (For Reference) ===\n\n"
            for i, inc in enumerate(similar_incidents, 1):
                context_text += f"Incident {i}:\n{inc.get('Abstract', 'N/A')}\n\n"
            context_text += "=== END HISTORICAL INCIDENTS ===\n\n"
        
        # Build enhanced prompt with environment awareness and DOSH regulations
        prompt = f"""You are an expert AI safety inspector with access to DOSH (Department of Occupational Safety and Health) regulations. Analyze this workplace scene and respond with ONLY a valid JSON object.

{dosh_text if dosh_text else ""}{context_text if context_text else ""}
---
SCENE ANALYSIS:
Caption: {caption}
Detected Objects: {chr(10).join(detection_desc) if detection_desc else 'None'}
{missing_ppe_text}
Violation Summary: {violation_summary}
People Count: {person_count}

---
CRITICAL INSTRUCTIONS FOR PROFESSIONAL SAFETY ANALYSIS:

1. PPE STATUS - IGNORE THIS FIELD:
   - PPE status is AUTOMATICALLY determined by the YOLO detection system
   - If "NO-Hardhat" is detected, system marks hardhat as Missing
   - If "NO-Mask" is detected, system marks mask as Missing
   - You do NOT need to fill in the "ppe" field in your response
   - You can set all PPE items to "Not Mentioned" - the system will override them
   - Focus instead on: person description, actions, hazards_faced, and risks
   - "Mentioned" = PPE is present and worn properly
   - "Not Mentioned" = Cannot determine from available data
   - "Not Required" = Environment/task does not mandate this PPE

2. ACTIONS - Corrective and Preventive Measures:
   - These are NOT descriptions of what the worker is currently doing wrong
   - These ARE the corrective actions needed to prevent the identified risks
   - Describe specific steps to address each safety violation and hazard
   - Include: immediate actions required, PPE that must be worn, procedural changes needed
   - Reference relevant safety protocols, equipment requirements, and work practices
   - Be specific about implementation: what needs to be done, how, and by whom
   - Use professional safety management terminology and action-oriented language

3. HAZARDS FACED - Detailed Technical Analysis:
   - Provide detailed descriptions of each hazard (2-3 sentences per hazard)
   - Include: hazard type (mechanical/electrical/chemical/ergonomic/environmental), source, exposure mechanism
   - Specify affected body parts and severity rating with justification
   - Reference specific site conditions from caption and connect to DOSH regulations

4. POTENTIAL RISKS - Medical and Regulatory Analysis:
   - For each hazard, provide comprehensive risk assessment (3-4 sentences per risk)
   - Medical component: injury types with proper medical terminology, affected anatomical structures and body systems, severity classification
   - Mechanism: describe how injury would occur and contributing factors
   - Regulatory: cite specific DOSH section numbers from provided context, legal consequences, regulatory penalties
   - Include likelihood assessment (low/medium/high/very high) with justification
   - END each risk with exact string: "Likelihood: High", "Likelihood: Medium", or "Likelihood: Low"
   - Example: "Risk of Traumatic Brain Injury (TBI) due to potential falling objects or head impact in construction environment. Without proper head protection, impacts to the cranium can cause concussion, intracranial hemorrhage, or skull fracture. This constitutes a serious violation of DOSH safety helmet requirements. Likelihood: High"

5. DOSH CITATIONS:
   - Extract specific regulation section numbers from the DOSH context provided (e.g., Section 21.5.1, Section 15.3)
   - Format regulation field as: "DOSH Section [number] - [brief description]"
   - Example: "DOSH Section 21.5.1 - Safety helmet of approved type must be worn at all times on construction sites"
   - Quote relevant requirements verbatim when possible

JSON structure:
{{
  "summary": "Brief summary with environment and main concerns",
  "environment_type": "Construction Site|Residential Area|Office|Warehouse|Manufacturing|Laboratory|Public Road|Other",
  "environment_assessment": "Why this environment type? SELECT ONE FROM LIST ABOVE. DO NOT INVENT NEW TYPES.",

  "dosh_regulations_cited": [
    {{
      "regulation": "DOSH Section [number] - [brief description of regulation]",
      "requirement": "What the regulation specifically requires"
    }}
  ],
  "persons": [
    {{
      "id": 1,
      "description": "Describe ACTIONS (activity: welding, walking, etc.) and POSITIONING (on ladder, near edge). Be specific.",
      "ppe": {{
        "hardhat": "Missing|Mentioned|Not Mentioned|Not Required",
        "safety_vest": "Missing|Mentioned|Not Mentioned|Not Required",
        "gloves": "Missing|Mentioned|Not Mentioned|Not Required",
        "goggles": "Missing|Mentioned|Not Mentioned|Not Required",
        "footwear": "Missing|Mentioned|Not Mentioned|Not Required"
      }},
      "actions": [
        "Specific corrective action to address identified violations and prevent risks",
        "Another preventive measure with implementation details",
        "Additional safety protocol or procedural requirement"
      ],
      "hazards_faced": [
        "Comprehensive hazard description with classification, source, mechanism, affected body parts, severity, and environmental context (2-3 detailed sentences)",
        "Another detailed hazard if present"
      ],
      "risks": [
        "Extensive risk analysis with medical terminology, injury mechanisms, body systems, severity/likelihood assessment, DOSH citations, and legal consequences (3-4 detailed sentences)",
        "Another comprehensive risk assessment"
      ],
      "compliance_status": "Compliant|Non-Compliant|Partially Compliant"
    }}
  ],
  "hazards_detected": ["scene hazards"],
  "suggested_actions": ["corrective actions - adapt to environment!"],
  "severity_level": "CRITICAL|HIGH|MEDIUM|LOW"
}}

Respond with JSON only:"""
        
        return prompt
    
    def _call_ollama_api(self, prompt: str) -> Optional[Dict[str, Any]]:
        """
        Call Ollama API or use local Llama to get NLP analysis.
        
        Args:
            prompt: Prompt to send to Ollama/Llama
        
        Returns:
            Parsed JSON response or None if failed
        """
        # Try local Llama first if available
        if self.local_llama is not None:
            try:
                logger.info("Using local Llama model for NLP analysis...")
                response = self.local_llama.generate_json(
                    prompt,
                    max_new_tokens=512,  # Reduced for faster generation
                    temperature=self.temperature
                )
                
                if response:
                    logger.info("[OK] Local Llama NLP analysis completed")
                    return response
                else:
                    logger.warning("Local Llama returned no valid JSON, trying Ollama...")
                    
            except Exception as e:
                logger.error(f"Local Llama generation failed: {e}")
                logger.info("Falling back to Ollama API...")
        
        # Fall back to Ollama API
        try:
            logger.info("Calling Ollama API for NLP analysis...")
            
            response = requests.post(
                self.api_url,
                json={
                    'model': self.model,
                    'prompt': prompt,
                    'context': [],  # FORCE STATELESS: Empty context prevents caching of previous conversations
                    'stream': False,
                    'format': 'json',
                    'options': {
                        'temperature': self.temperature
                    }
                },
                timeout=self.ollama_timeout
            )
            
            if not response.ok:
                logger.error(f"Ollama API error: {response.status_code}")
                return None
            
            data = response.json()
            logger.debug(f"Ollama response: {data}")
            
            # Parse the JSON response from the model
            nlp_response = json.loads(data['response'])
            logger.info("[OK] NLP analysis completed")
            
            return nlp_response
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Ollama JSON response: {e}")
            logger.debug(f"Raw response: {data.get('response', 'N/A')}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama API request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Error calling Ollama API: {e}", exc_info=True)
            return None
    
    # =========================================================================
    # REPORT GENERATION
    # =========================================================================
    
    def generate_report(self, report_data: Dict[str, Any]) -> Dict[str, Optional[Path]]:
        """
        Generate complete violation report.
        
        Args:
            report_data: Dictionary containing:
                - report_id: Unique identifier
                - timestamp: Datetime of violation
                - caption: Image caption from LLaVA
                - detections: List of YOLO detections
                - violation_summary: Summary of violations
                - person_count: Number of people detected
                - violation_count: Number of violations
                - severity: Violation severity
                - original_image_path: Path to original image
                - annotated_image_path: Path to annotated image
        
        Returns:
            Dictionary with paths:
                - html: Path to HTML report
                - pdf: Path to PDF report (if enabled)
                - nlp_analysis: NLP analysis data
        """
        logger.info(f"Generating report: {report_data.get('report_id')}")
        
        # Step 1: RAG - Retrieve relevant context
        similar_incidents = []
        dosh_context = []
        
        if self.rag_enabled:
            query_text = f"{report_data.get('caption', '')} {report_data.get('violation_summary', '')}"
            
            # Use Chroma DB for DOSH documentation
            if self.use_chroma and self.chroma_collection:
                logger.info("Retrieving relevant DOSH documentation from Chroma DB...")
                dosh_context = self._query_chroma_db(query_text, n_results=self.top_k)
                logger.info(f"Retrieved {len(dosh_context)} DOSH documentation chunks")
            
            # Also get similar incidents from CSV (optional fallback)
            similar_incidents = self._find_similar_incidents(query_text, self.num_similar)
            logger.info(f"Found {len(similar_incidents)} similar incidents")
        
        # Step 2: NLP - Generate analysis with Ollama
        nlp_analysis = None
        prompt = self._build_nlp_prompt(report_data, similar_incidents, dosh_context)
        nlp_analysis = self._call_ollama_api(prompt)
        
        if not nlp_analysis:
            # Fallback if NLP fails
            logger.warning("NLP analysis failed, using fallback")
            nlp_analysis = self._generate_fallback_analysis(report_data)
        
        # Step 3: Generate HTML report
        html_path = self._generate_html_report(report_data, nlp_analysis)
        
        # Step 4: Generate PDF (if enabled)
        pdf_path = None
        if self.enable_pdf and self.format in ['pdf', 'both']:
            pdf_path = self._generate_pdf_report(html_path, report_data.get('report_id'))
        
        logger.info(f"[OK] Report generated: {report_data.get('report_id')}")
        
        return {
            'html': html_path,
            'pdf': pdf_path,
            'nlp_analysis': nlp_analysis
        }
    
    def _generate_fallback_analysis(self, report_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate comprehensive fallback analysis from YOLO detections when NLP fails.
        Creates person entries with PPE status, hazards, and recommendations.
        Note: Without VLM/NLP, we cannot determine actual environment type.
        """
        detections = report_data.get('detections', [])
        
        # Hazards and recommendations by violation type (with full acronym expansions)
        VIOLATION_DATA = {
            'hardhat': {
                'hazard': 'Head injury risk from falling objects or overhead impact',
                'risk': 'Potential traumatic brain injury or skull fractures',
                'action': 'Provide appropriate safety helmet. Enforce head protection in designated areas.',
                'regulation': 'OSHA 1994 (Occupational Safety and Health Act) Section 15 - Employer Duties',
                'regulation_full': 'OSHA 1994 Section 15 requires employers to ensure the safety and health of employees at work'
            },
            'mask': {
                'hazard': 'Respiratory hazard from dust, fumes, or airborne particles',
                'risk': 'Respiratory diseases such as silicosis or occupational asthma',
                'action': 'Provide appropriate respiratory protective equipment. Conduct exposure assessment.',
                'regulation': 'USECHH Regulations 2000 (Use and Standards of Exposure of Chemicals Hazardous to Health)',
                'regulation_full': 'USECHH 2000 requires employers to assess and control exposure to hazardous chemicals'
            },
            'safety vest': {
                'hazard': 'Visibility hazard in areas with moving vehicles or equipment',
                'risk': 'Struck-by incidents that could cause serious injury',
                'action': 'Issue high-visibility vest for areas with vehicle or equipment movement.',
                'regulation': 'Construction Industry Safety Guidelines',
                'regulation_full': 'High-visibility clothing required in areas where vehicles or mobile equipment operate'
            },
            'gloves': {
                'hazard': 'Hand injury risk from sharp edges or hazardous materials',
                'risk': 'Lacerations, chemical burns, or crush injuries to hands',
                'action': 'Provide appropriate hand protection based on hazard assessment.',
                'regulation': 'OSHA 1994 Section 15 - Personal Protective Equipment',
                'regulation_full': 'Employers must provide suitable protective equipment for identified hazards'
            },
            'goggles': {
                'hazard': 'Eye injury risk from flying particles or splashes',
                'risk': 'Corneal abrasion or permanent vision impairment',
                'action': 'Provide safety eyewear appropriate for the identified hazards.',
                'regulation': 'OSHA 1994 Section 15 - Eye Protection',
                'regulation_full': 'Eye protection required where there is risk of injury from flying particles or liquids'
            }
        }
        
        # Extract violations from detections
        violations = [d.get('class_name', '') for d in detections if d.get('class_name', '').startswith('NO-')]
        person_count = max(1, sum(1 for d in detections if 'person' in d.get('class_name', '').lower()))
        
        # Build PPE status and collect data
        ppe_status = {k: 'Not Mentioned' for k in ['hardhat', 'safety_vest', 'gloves', 'goggles', 'footwear', 'mask']}
        hazards, risks, actions, regulations = [], [], [], []
        
        for v in violations:
            v_lower = v.lower().replace('no-', '')
            for key in VIOLATION_DATA:
                if key.replace(' ', '') in v_lower.replace(' ', '') or key in v_lower:
                    ppe_field = key.replace(' ', '_')
                    ppe_status[ppe_field] = 'Missing'
                    data = VIOLATION_DATA[key]
                    hazards.append(data['hazard'])
                    risks.append(data['risk'])
                    actions.append(data['action'])
                    regulations.append({'regulation': data['regulation'], 'requirement': data['regulation_full']})
                    break
        
        # Create person entries
        persons = [{
            'id': i + 1,
            'description': 'Individual detected with PPE status as shown below',
            'ppe': ppe_status.copy(),
            'actions': actions or ['Ensure appropriate PPE is available and worn when required'],
            'hazards_faced': hazards or ['Potential hazards identified based on missing PPE'],
            'risks': risks or ['Risk level depends on environment and activities performed'],
            'compliance_status': 'Non-Compliant' if violations else 'Unknown'
        } for i in range(person_count)]
        
        violation_types = [v.replace('NO-', '') for v in violations]
        summary = f"PPE issue detected: {', '.join(violation_types)} not worn." if violation_types else "Safety observation recorded."
        
        return {
            'summary': summary,
            'environment_type': 'Detected Location',
            'environment_assessment': 'Environment type could not be determined automatically. PPE requirements depend on actual location and activities.',
            'dosh_regulations_cited': regulations or [{'regulation': 'General Safety Guidelines', 'requirement': 'PPE should be worn as appropriate for the environment and activities'}],
            'persons': persons,
            'hazards_detected': hazards or ['PPE status recorded for reference'],
            'suggested_actions': actions or ['Assess environment to determine PPE requirements'],
            'severity_level': 'HIGH' if violations else 'MEDIUM'
        }
    
    def _generate_html_report(
        self,
        report_data: Dict[str, Any],
        nlp_analysis: Dict[str, Any]
    ) -> Path:
        """
        Generate HTML report with full styling.
        
        Returns:
            Path to HTML report
        """
        report_id = report_data.get('report_id')
        timestamp = report_data.get('timestamp', datetime.now())
        
        # Get image paths (relative to violations dir for web viewing)
        original_img = f"/image/{report_id}/original.jpg"
        annotated_img = f"/image/{report_id}/annotated.jpg"
        
        # Build HTML content
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Safety Violation Report - {report_id}</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        
        :root {{
            --primary-color: #2c3e50;
            --secondary-color: #3498db;
            --danger-color: #e74c3c;
            --warning-color: #f39c12;
            --success-color: #2ecc71;
            --text-color: #34495e;
            --border-color: #dfe6e9;
            --background: #ecf0f1;
        }}
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Inter', sans-serif;
            background: var(--background);
            color: var(--text-color);
            line-height: 1.6;
            padding: 2rem;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        
        .header {{
            background: linear-gradient(135deg, var(--danger-color), #c0392b);
            color: white;
            padding: 2rem;
            text-align: center;
        }}
        
        .header h1 {{
            font-size: 2rem;
            margin-bottom: 0.5rem;
        }}
        
        .header .report-id {{
            font-size: 1.1rem;
            opacity: 0.9;
        }}
        
        .content {{
            padding: 2rem;
        }}
        
        .section {{
            margin-bottom: 2rem;
        }}
        
        .section-title {{
            font-size: 1.5rem;
            color: var(--primary-color);
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid var(--border-color);
        }}
        
        .grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
            margin-bottom: 1.5rem;
        }}
        
        .card {{
            border: 1px solid var(--border-color);
            border-radius: 8px;
            overflow: hidden;
        }}
        
        .card-header {{
            background: var(--primary-color);
            color: white;
            padding: 1rem;
            font-weight: 600;
        }}
        
        .card-content {{
            padding: 1rem;
        }}
        
        .image-container {{
            width: 100%;
            max-height: 400px;
            overflow: hidden;
            background: #000;
        }}
        
        .image-container img {{
            width: 100%;
            height: auto;
            display: block;
        }}
        
        .info-grid {{
            display: grid;
            gap: 0.75rem;
        }}
        
        .info-item {{
            display: flex;
            padding: 0.75rem;
            background: var(--background);
            border-radius: 6px;
        }}
        
        .info-label {{
            font-weight: 600;
            color: var(--primary-color);
            min-width: 150px;
        }}
        
        .info-value {{
            flex: 1;
        }}
        
        .badge {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 12px;
            font-size: 0.85rem;
            font-weight: 500;
        }}
        
        .badge-danger {{
            background: rgba(231,76,60,0.1);
            color: var(--danger-color);
        }}
        
        .badge-warning {{
            background: rgba(243,156,18,0.1);
            color: var(--warning-color);
        }}
        
        .badge-success {{
            background: rgba(46,204,113,0.1);
            color: var(--success-color);
        }}
        
        /* Person Cards */
        .persons-grid {{
            display: grid;
            gap: 1.5rem;
        }}
        
        .person-card {{
            border: 2px solid var(--border-color);
            border-radius: 12px;
            overflow: hidden;
            background: white;
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }}
        
        .person-card:hover {{
            transform: translateY(-4px);
            box-shadow: 0 8px 24px rgba(0,0,0,0.15);
        }}
        
        .person-header {{
            background: linear-gradient(135deg, var(--primary-color), #34495e);
            color: white;
            padding: 1.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        
        .person-header h3 {{
            font-size: 1.25rem;
            margin-bottom: 0.25rem;
        }}
        
        .person-header p {{
            font-size: 0.9rem;
            opacity: 0.9;
        }}
        
        .person-content {{
            padding: 1.5rem;
            display: grid;
            gap: 1.25rem;
        }}
        
        .person-section h4 {{
            color: var(--primary-color);
            font-size: 1rem;
            margin-bottom: 0.75rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid var(--border-color);
        }}
        
        .ppe-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 0.75rem;
        }}
        
        .ppe-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem;
            background: var(--background);
            border-radius: 6px;
        }}
        
        .ppe-label {{
            font-weight: 600;
            color: var(--text-color);
            font-size: 0.9rem;
        }}
        
        .ppe-status {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 12px;
            font-size: 0.85rem;
            font-weight: 500;
        }}
        
        .ppe-status-mentioned {{
            background: rgba(46,204,113,0.1);
            color: var(--success-color);
        }}
        
        .ppe-status-missing {{
            background: rgba(231,76,60,0.1);
            color: var(--danger-color);
        }}
        
        .ppe-status-not-mentioned {{
            background: rgba(149,165,166,0.1);
            color: #7f8c8d;
        }}
        
        .ppe-status-not-required {{
            background: rgba(52,152,219,0.1);
            color: var(--secondary-color);
        }}
        
        .list-compact {{
            list-style: none;
            padding: 0;
        }}
        

        
        /* Environment Badge */
        .environment-badge {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.75rem 1.25rem;
            background: linear-gradient(135deg, var(--secondary-color), #2980b9);
            color: white;
            border-radius: 8px;
            font-weight: 600;
            margin-bottom: 1rem;
        }}
        
        .confidence-indicator {{
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 1rem;
            background: var(--background);
            border-radius: 8px;
            margin-top: 1rem;
        }}
        
        .confidence-bar {{
            flex: 1;
            height: 12px;
            background: #dfe6e9;
            border-radius: 6px;
            overflow: hidden;
        }}
        
        .confidence-fill {{
            height: 100%;
            background: linear-gradient(90deg, var(--success-color), var(--warning-color), var(--danger-color));
            transition: width 0.3s ease;
        }}
        
        .list {{
            list-style: none;
            padding: 0;
        }}
        
        .list li {{
            padding: 0.75rem;
            margin-bottom: 0.5rem;
            background: var(--background);
            border-left: 3px solid var(--secondary-color);
            border-radius: 4px;
        }}
        
        .footer {{
            background: var(--primary-color);
            color: white;
            padding: 1.5rem;
            text-align: center;
        }}
        
        /* Chips and Badges */
        .hazard-chip, .action-chip {{
            display: inline-block;
            padding: 0.5rem 1rem;
            margin: 0.25rem 0.5rem 0.25rem 0;
            border-radius: 20px;
            font-size: 0.9rem;
            line-height: 1.4;
        }}

        .hazard-chip {{
            background-color: #fff3cd;
            color: #856404;
            border: 1px solid #ffeeba;
        }}

        .action-chip {{
            background-color: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }}
        
        /* Likelihood Badge */
        .likelihood-badge {{
            display: inline-flex;
            flex-direction: column;
            align-items: flex-start;
            padding: 0.5rem 1rem;
            border-radius: 8px;
            min-width: 120px;
            border: 1px solid rgba(0,0,0,0.1);
        }}
        
        .likelihood-label {{
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            opacity: 0.8;
            margin-bottom: 0.25rem;
        }}
        
        .likelihood-value {{
            font-weight: bold;
            font-size: 1.1rem;
            margin-bottom: 0.5rem;
        }}
        
        .likelihood-bar {{
            width: 100%;
            height: 6px;
            background: rgba(0,0,0,0.1);
            border-radius: 3px;
            overflow: hidden;
        }}
        
        .bar-fill {{
            height: 100%;
            border-radius: 3px;
        }}
        
        .likelihood-high {{
            background-color: #f8d7da;
            color: #721c24;
            border-color: #f5c6cb;
        }}
        
        .likelihood-high .bar-fill {{
            background-color: #dc3545;
        }}

        .likelihood-medium {{
             background-color: #fff3cd;
             color: #856404;
             border-color: #ffeeba;
        }}
        .likelihood-medium .bar-fill {{
            background-color: #ffc107;
        }}
        
        .risk-grid, .action-grid {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
        }}

        @media (max-width: 768px) {{
            .grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚠️ PPE Safety Violation Report</h1>
            <p class="report-id">Report ID: {report_id}</p>
            <p>Generated: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        
        <div class="content">
            <!-- Images Section -->
            <div class="section">
                <h2 class="section-title">📸 Visual Evidence</h2>
                <div class="grid">
                    <div class="card">
                        <div class="card-header">Original Image (1920x1080)</div>
                        <div class="image-container">
                            <img src="{original_img}" alt="Original Image">
                        </div>
                    </div>
                    <div class="card">
                        <div class="card-header">Annotated Image (Detections)</div>
                        <div class="image-container">
                            <img src="{annotated_img}" alt="Annotated Image">
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Violation Details -->
            <div class="section">
                <h2 class="section-title">📋 Violation Details</h2>
                <div class="info-grid">
                    <div class="info-item">
                        <span class="info-label">Report ID:</span>
                        <span class="info-value">{report_id}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Timestamp:</span>
                        <span class="info-value">{timestamp.strftime('%Y-%m-%d %H:%M:%S')}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Violation Type:</span>
                        <span class="info-value">{report_data.get('violation_summary', 'PPE Violation')}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Severity:</span>
                        <span class="info-value"><span class="badge badge-danger">{report_data.get('severity', 'HIGH')}</span></span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">Violation Count:</span>
                        <span class="info-value">{report_data.get('violation_count', 1)}</span>
                    </div>
                </div>
            </div>
            
            <!-- AI Caption -->
            <div class="section">
                <h2 class="section-title">🤖 AI Scene Description</h2>
                <div class="card">
                    <div class="card-content">
                        <p>{report_data.get('caption', 'No caption available')}</p>
                    </div>
                </div>
            </div>
            
            <!-- NLP Analysis -->
            <div class="section">
                <h2 class="section-title">📊 Safety Analysis</h2>
                
                <!-- Environment Type -->
                <div class="environment-badge">
                    <span>🏗️</span>
                    <span>Environment: {nlp_analysis.get('environment_type', 'Unknown')}</span>
                </div>
                
                <!-- Summary -->
                <div class="card">
                    <div class="card-header">Summary</div>
                    <div class="card-content">
                        <p>{nlp_analysis.get('summary', 'Analysis in progress...')}</p>
                        {f"<p style='margin-top: 1rem; font-style: italic; color: #7f8c8d;'>{nlp_analysis.get('environment_assessment', '')}</p>" if nlp_analysis.get('environment_assessment') else ''}
                    </div>
                </div>
            </div>
            
            <!-- DOSH Regulations -->
            {self._generate_dosh_regulations_section(nlp_analysis)}
            
            <!-- Individual Person Analysis -->
            {self._generate_person_cards_section(nlp_analysis, report_data)}
        </div>
        
        <div class="footer">
            <p>PPE Safety Monitor - AI-Powered Workplace Safety System</p>
            <p style="font-size: 0.9rem; opacity: 0.8; margin-top: 0.5rem;">
                Powered by YOLOv8 • LLaVA • Llama3 • Computer Vision
            </p>
        </div>
    </div>
</body>
</html>"""
        
        # Save to both reports directory and violations directory
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        html_path = self.reports_dir / f'violation_{report_id}.html'
        
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        # Also save to violations directory for web UI
        violations_report_path = self.violations_dir / report_id / 'report.html'
        violations_report_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(violations_report_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"HTML report saved to: {html_path}")
        logger.info(f"HTML report copied to: {violations_report_path}")
        
        return html_path
    
    def _ensure_list_of_strings(self, data: Any) -> List[str]:
        """Helper to ensure data is a list of strings, handling parsing of limiters."""
        if not data:
            return []
        
        if isinstance(data, list):
            return data
            
        if isinstance(data, str):
            # Try splitting by common delimiters
            if ';' in data:
                return [item.strip() for item in data.split(';') if item.strip()]
            if '\n' in data:
                return [item.strip() for item in data.split('\n') if item.strip()]
            return [data]
            
        return [str(data)]

    def _generate_hazards_section(self, nlp_analysis: Dict[str, Any]) -> str:
        """Generate hazards HTML section."""
        hazards = self._ensure_list_of_strings(nlp_analysis.get('hazards_detected', []))
        if not hazards:
            return ""
        
        items = "".join([f"<li>{h}</li>" for h in hazards])
        return f"""
            <div class="section">
                <h2 class="section-title">⚠️ Hazards Detected</h2>
                <ul class="list">
                    {items}
                </ul>
            </div>
        """
    
    def _generate_dosh_regulations_section(self, nlp_analysis: Dict[str, Any]) -> str:
        """Generate DOSH regulations section with cited regulations."""
        regulations = nlp_analysis.get('dosh_regulations_cited', [])
        if not regulations:
            return ""
        
        reg_items = []
        for i, reg in enumerate(regulations, 1):
            regulation = reg.get('regulation', 'N/A')
            requirement = reg.get('requirement', 'N/A')
            
            reg_items.append(f"""
                <div class="card" style="margin-bottom: 1rem;">
                    <div class="card-header" style="background: linear-gradient(135deg, #e67e22, #d35400); color: white;">
                        <i class="fas fa-book-open"></i> {regulation}
                    </div>
                    <div class="card-content">
                        <p style="margin-bottom: 0;"><strong>Requirement:</strong> {requirement}</p>
                    </div>
                </div>
            """)
        
        return f"""
            <div class="section">
                <h2 class="section-title">📚 Applicable DOSH Regulations</h2>
                <div style="background: rgba(230, 126, 34, 0.1); padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
                    <p style="margin: 0; color: #e67e22; font-weight: 600;">
                        <i class="fas fa-info-circle"></i> The following DOSH (Department of Occupational Safety and Health) regulations apply to this violation:
                    </p>
                </div>
                {''.join(reg_items)}
            </div>
        """
    
    def _generate_person_cards_section(self, nlp_analysis: Dict[str, Any], report_data: Dict[str, Any]) -> str:
        """Generate per-person analysis cards (inspired by NLP_Luna)."""
        persons = nlp_analysis.get('persons', [])
        if not persons:
            return """
            <div class="section">
                <h2 class="section-title">👥 Individual Analysis</h2>
                <div class="card">
                    <div class="card-content">
                        <p>No persons detected in the scene.</p>
                    </div>
                </div>
            </div>
            """
        
        # Extract missing PPE from YOLO detections (NO-Hardhat, NO-Mask, etc.)
        detections = report_data.get('detections', [])
        yolo_missing_ppe = set()
        for det in detections:
            class_name = det.get('class_name', det.get('class', ''))
            if class_name.startswith('NO-'):
                ppe_item = class_name.replace('NO-', '').lower()
                # Map YOLO class names to PPE field names
                mapping = {
                    'hardhat': 'hardhat',
                    'mask': 'mask',
                    'safety vest': 'safety_vest',
                    'vest': 'safety_vest',
                    'gloves': 'gloves',
                    'safety shoes': 'footwear',
                    'shoes': 'footwear',
                    'goggles': 'goggles'
                }
                for key, value in mapping.items():
                    if key in ppe_item:
                        yolo_missing_ppe.add(value)
                        break
        
        # Generate card for each person
        person_cards = []
        for person in persons:
            person_id = person.get('id', 'Unknown')
            description = person.get('description', 'No description')
            compliance = person.get('compliance_status', 'Unknown')
            
            # PPE status grid - Override with YOLO detections
            ppe = person.get('ppe', {})
            ppe_items = []
            
            # Define standard PPE items
            standard_ppe = ['hardhat', 'safety_vest', 'gloves', 'goggles', 'footwear', 'mask']
            for ppe_type in standard_ppe:
                # Override status if YOLO detected missing PPE
                if ppe_type in yolo_missing_ppe:
                    status = 'Missing'
                else:
                    status = ppe.get(ppe_type, 'Not Mentioned')
                
                # Determine status class
                # Determine status class
                if status == 'Missing':
                    status_class = 'ppe-status-missing'
                elif status == 'Mentioned':
                    status_class = 'ppe-status-mentioned'
                elif status == 'Not Required':
                    status_class = 'ppe-status-not-required'
                else:
                    status_class = 'ppe-status-not-mentioned'
                
                ppe_label = ppe_type.replace('_', ' ').title()
                ppe_items.append(f"""
                    <div class="ppe-item">
                        <span class="ppe-label">{ppe_label}:</span>
                        <span class="ppe-status {status_class}">{status}</span>
                    </div>
                """)
            
            # Actions list
            actions = self._ensure_list_of_strings(person.get('actions', []))
            actions_html = ''.join([f"<li>{a}</li>" for a in actions]) if actions else '<li>No actions specified</li>'
            
            # Hazards list - handle both string and dict formats
            hazards = self._ensure_list_of_strings(person.get('hazards_faced', []))
            hazards_formatted = []
            for h in hazards:
                if isinstance(h, dict):
                    # Format dict as readable text
                    parts = []
                    if 'type' in h:
                        parts.append(f"{h['type']}")
                    if 'source' in h:
                        parts.append(f"Source: {h['source']}")
                    if 'mechanism' in h:
                        parts.append(f"Mechanism: {h['mechanism']}")
                    if 'affected_body_part' in h:
                        parts.append(f"Affected: {h['affected_body_part']}")
                    if 'severity' in h:
                        parts.append(f"Severity: {h['severity']}")
                    hazards_formatted.append(' - '.join(parts))
                else:
                    hazards_formatted.append(str(h))
            hazards_html = ''.join([f"<li>{h}</li>" for h in hazards_formatted]) if hazards_formatted else '<li>No hazards identified</li>'
            
            # Risks list - handle both string and dict formats
            risks = self._ensure_list_of_strings(person.get('risks', []))
            risks_formatted = []
            for r in risks:
                if isinstance(r, dict):
                    # Format dict as readable text
                    parts = []
                    if 'injury_type' in r:
                        parts.append(f"{r['injury_type']}")
                    if 'medical_terminology' in r:
                        parts.append(f"Medical: {r['medical_terminology']}")
                    if 'body_systems_affected' in r:
                        parts.append(f"Body systems: {r['body_systems_affected']}")
                    if 'severity_classification' in r:
                        parts.append(f"Severity: {r['severity_classification']}")
                    if 'regulation_citation' in r:
                        parts.append(f"Regulation: {r['regulation_citation']}")
                    if 'legal_regulatory_consequences' in r:
                        parts.append(f"Legal consequences: {r['legal_regulatory_consequences']}")
                    # Try to extract text from common keys if specific ones fail
                    if not parts:
                        for key in ['description', 'risk', 'text', 'content', 'details', 'summary']:
                            if key in r:
                                parts.append(str(r[key]))
                                break
                    
                    # Fallback: if still empty, use values or string representation
                    if not parts:
                        parts = [str(v) for v in r.values() if isinstance(v, (str, int, float))]
                        
                    if not parts:
                        parts.append(str(r))
                        
                    risks_formatted.append(' | '.join(parts))
                else:
                    risks_formatted.append(str(r))
            risks_html = ''.join([f"<li>{r}</li>" for r in risks_formatted]) if risks_formatted else '<li>No risks identified</li>'
            
            # Compliance badge
            if compliance == 'Compliant':
                compliance_badge = '<span class="badge badge-success">✓ Compliant</span>'
            elif compliance == 'Non-Compliant':
                compliance_badge = '<span class="badge badge-danger">✗ Non-Compliant</span>'
            else:
                compliance_badge = '<span class="badge badge-warning">⚠ Partially Compliant</span>'
            
            # Build person card
            person_cards.append(f"""
                <div class="person-card">
                    <div class="person-header">
                        <div>
                            <h3>👤 Person {person_id}</h3>
                            <p>{description}</p>
                        </div>
                        {compliance_badge}
                    </div>
                    <div class="person-content">
                        <div class="person-section">
                            <h4>🦺 PPE Status</h4>
                            <div class="ppe-grid">
                                {''.join(ppe_items)}
                            </div>
                        </div>
                        
                        <div class="person-section">
                            <h4>⚠️ Hazards Faced</h4>
                            <div class="risk-grid">
                                {''.join([f'<div class="hazard-chip"><i class="fas fa-exclamation-circle"></i> {h}</div>' for h in hazards_formatted]) if hazards_formatted else '<div class="text-muted">No hazards identified</div>'}
                            </div>
                        </div>

                        <div class="person-section">
                            <h4>⚕️ Potential Risks & Likelihood</h4>
                            <div class="risk-list">
                                {''.join([self._format_risk_item(r) for r in risks_formatted]) if risks_formatted else '<div class="text-muted">No risks identified</div>'}
                            </div>
                        </div>

                        <div class="person-section">
                            <h4>🏃 Recommended Actions</h4>
                            <div class="action-grid">
                                {''.join([f'<div class="action-chip"><i class="fas fa-check"></i> {a}</div>' for a in actions]) if actions else '<div class="text-muted">No actions specified</div>'}
                            </div>
                        </div>
                    </div>
                </div>
            """)
        
        return f"""
            <div class="section">
                <h2 class="section-title">👥 Individual Analysis ({len(persons)} Person{'s' if len(persons) > 1 else ''})</h2>
                <div class="persons-grid">
                    {''.join(person_cards)}
                </div>
            </div>
        """
    
    def _generate_recommendations_section(self, nlp_analysis: Dict[str, Any]) -> str:
        """Generate recommendations HTML section."""
        recommendations = self._ensure_list_of_strings(nlp_analysis.get('suggested_actions', []))
        if not recommendations:
            return ""
        
        items = "".join([f"<li>{r}</li>" for r in recommendations])
        return f"""
            <div class="section">
                <h2 class="section-title">✅ Recommended Actions</h2>
                <ul class="list">
                    {items}
                </ul>
            </div>
        """
    
    def _format_risk_item(self, risk_text: str) -> str:
        """
        Format a risk item with visual likelihood badge.
        Parses 'Likelihood: High/Medium/Low' from the text.
        """
        likelihood = 'Unknown'
        risk_desc = risk_text
        
        # Parse likelihood
        # Parse likelihood
        import re
        # Match 'Likelihood: High', '(Likelihood: High)', 'Likelihood - High', etc.
        match = re.search(r'Likelihood[:\s-]*\(?(High|Medium|Low|Very High)\)?', risk_text, re.IGNORECASE)
        if match:
            likelihood = match.group(1).title()
            # Remove the likelihood text from description
            risk_desc = re.sub(r'\(?Likelihood[:\s-]*\(?(High|Medium|Low|Very High)\)?\)?[\.]?', '', risk_text, flags=re.IGNORECASE).strip()
            # Clean up trailing punctuation
            if risk_desc.endswith(','): risk_desc = risk_desc[:-1]
            
        # Determine badge class
        badge_class = 'bg-gray-200 text-gray-800'
        if 'High' in likelihood:
            badge_class = 'likelihood-high'
        elif 'Medium' in likelihood:
            badge_class = 'likelihood-medium'
        elif 'Low' in likelihood:
            badge_class = 'likelihood-low'
            
        return f"""
            <div class="risk-item">
                <div class="risk-content">{risk_desc}</div>
                <div class="likelihood-badge {badge_class}">
                    <span class="likelihood-label">Likelihood</span>
                    <span class="likelihood-value">{likelihood}</span>
                    <div class="likelihood-bar">
                        <div class="bar-fill" style="width: {'100%' if 'High' in likelihood else '60%' if 'Medium' in likelihood else '30%'}"></div>
                    </div>
                </div>
            </div>
        """

    def _generate_pdf_report(self, html_path: Path, report_id: str) -> Optional[Path]:
        """
        Generate PDF from HTML report (to be implemented).
        
        Returns:
            Path to PDF report or None if failed
        """
        # Will use WeasyPrint or ReportLab
        pdf_path = self.reports_dir / f'violation_{report_id}.pdf'
        logger.info(f"PDF report path: {pdf_path}")
        return pdf_path


# =============================================================================
# TESTING
# =============================================================================

if __name__ == '__main__':
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.absolute()))
    from config import OLLAMA_CONFIG, RAG_CONFIG, REPORT_CONFIG, BRAND_COLORS, REPORTS_DIR, VIOLATIONS_DIR
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 70)
    print("REPORT GENERATOR TEST")
    print("=" * 70)
    
    # Create config
    config = {
        'OLLAMA_CONFIG': OLLAMA_CONFIG,
        'RAG_CONFIG': RAG_CONFIG,
        'REPORT_CONFIG': REPORT_CONFIG,
        'BRAND_COLORS': BRAND_COLORS,
        'REPORTS_DIR': REPORTS_DIR,
        'VIOLATIONS_DIR': VIOLATIONS_DIR
    }
    
    # Create generator
    generator = ReportGenerator(config)
    
    print(f"\n[OK] Report Generator initialized")
    print(f"Ollama URL: {generator.api_url}")
    print(f"Model: {generator.model}")
    print(f"RAG enabled: {generator.rag_enabled}")
    print(f"RAG data loaded: {len(generator.incident_data)} incidents")
    print(f"Report format: {generator.format}")
    
    # Test RAG
    print("\n--- Testing RAG ---")
    test_desc = "worker fell from ladder without safety harness"
    similar = generator._find_similar_incidents(test_desc, 2)
    print(f"Similar incidents found: {len(similar)}")
    if similar:
        print(f"First incident keywords: {similar[0].get('Keywords', 'N/A')[:100]}...")
    
    print("\n[OK] All tests completed!")
    print("=" * 70)
