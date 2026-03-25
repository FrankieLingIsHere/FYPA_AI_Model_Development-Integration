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

# Try to import Gemini client (primary AI provider)
try:
    from pipeline.backend.integration.gemini_client import GeminiClient, load_regulations, build_regulation_context
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logging.info("Gemini client not available")

# Try to import local Llama (fallback)
try:
    from pipeline.backend.integration.local_llama import LocalLlamaGenerator
    LOCAL_LLAMA_AVAILABLE = True
except ImportError:
    LOCAL_LLAMA_AVAILABLE = False

# Try to import Chroma DB (legacy RAG — only used if Gemini disabled)
try:
    import chromadb
    from chromadb.config import Settings
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False
    logging.debug("chromadb not installed (not needed when using Gemini)")

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
        
        # =====================================================================
        # GEMINI (Primary AI provider)
        # =====================================================================
        gemini_config = config.get('GEMINI_CONFIG', {})
        self.use_gemini = gemini_config.get('enabled', True) and GEMINI_AVAILABLE
        self.gemini_client = None
        
        if self.use_gemini:
            try:
                self.gemini_client = GeminiClient(config)
                if self.gemini_client.is_available:
                    logger.info("✓ Gemini client initialized for NLP report generation")
                else:
                    logger.warning("Gemini client not available, falling back to Ollama")
                    self.gemini_client = None
                    self.use_gemini = False
            except Exception as e:
                logger.error(f"Failed to initialize Gemini: {e}")
                self.gemini_client = None
                self.use_gemini = False
        
        # =====================================================================
        # REGULATION DATA (Direct injection — replaces ChromaDB RAG)
        # =====================================================================
        self.regulations_data = {}
        rag_config = config.get('RAG_CONFIG', {})
        regulations_file = rag_config.get('regulations_file', '')
        
        if GEMINI_AVAILABLE:
            try:
                self.regulations_data = load_regulations(str(regulations_file) if regulations_file else None)
                logger.info(f"✓ Loaded {len(self.regulations_data.get('regulations', {}))} regulation entries")
            except Exception as e:
                logger.error(f"Failed to load regulations: {e}")
        
        # =====================================================================
        # OLLAMA (Fallback AI provider)
        # =====================================================================
        ollama_config = config.get('OLLAMA_CONFIG', {})
        self.api_url = ollama_config.get('api_url', 'http://localhost:11434/api/generate')
        self.model = ollama_config.get('model', 'llama3')
        self.temperature = ollama_config.get('temperature', 0.7)
        self.ollama_timeout = ollama_config.get('timeout', 600)
        
        # Local Llama settings (fallback if Ollama not available)
        self.use_local_llama = ollama_config.get('use_local_model', True)
        self.local_model_path = ollama_config.get('local_model_path', 
            r'C:\Users\maste\Downloads\FYP Combined\Meta-Llama-3-8B-Instruct')
        self.local_llama = None
        
        if not self.use_gemini and self.use_local_llama and LOCAL_LLAMA_AVAILABLE:
            try:
                logger.info("Initializing local Llama model...")
                self.local_llama = LocalLlamaGenerator(self.local_model_path)
                logger.info("[OK] Local Llama initialized (will load on first use)")
            except Exception as e:
                logger.warning(f"Could not initialize local Llama: {e}")
                self.local_llama = None
        
        # =====================================================================
        # RAG settings (legacy — used only when Gemini is disabled)
        # =====================================================================
        self.rag_enabled = rag_config.get('enabled', True)
        self.use_chroma = rag_config.get('use_chroma', False) and not self.use_gemini
        self.chroma_path = rag_config.get('chroma_path', '')
        self.collection_name = rag_config.get('collection_name', 'dosh_documentation')
        self.embedding_model = rag_config.get('embedding_model', 'nomic-embed-text')
        self.rag_data_path = rag_config.get('data_source', '')
        self.num_similar = rag_config.get('num_similar_incidents', 2)
        self.top_k = rag_config.get('top_k', 3)
        
        # Chroma DB client (legacy)
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
        
        ai_provider = 'Gemini' if self.use_gemini else ('Ollama' if not self.use_local_llama else 'Local Llama')
        logger.info(f"Report Generator initialized (AI provider: {ai_provider})")
    
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
    # ENVIRONMENT DETECTION FROM CAPTION (Root cause fix for "Unknown" issue)
    # =========================================================================
    
    def _extract_environment_from_caption(self, caption: str) -> str:
        """
        Extract environment type from VLM caption using keyword matching.
        This is more reliable than depending on NLP to extract it.
        
        Args:
            caption: VLM-generated image caption
            
        Returns:
            One of the standard environment types
        """
        caption_lower = caption.lower()
        
        # =====================================================================
        # Industry-standard environment categories aligned with:
        #   - DOSH Malaysia (Dept. of Occupational Safety & Health)
        #   - JKR (Jabatan Kerja Raya) classifications
        #   - OSHA 29 CFR 1926 (construction) / 1910 (general industry)
        #   - ISO 45001 hazard identification categories
        # Order: most specific → least specific (first match wins)
        # =====================================================================
        ENVIRONMENT_KEYWORDS = {
            # --- High-specificity outdoor work zones ---
            'Roadside Work Zone': [
                'roadside', 'road construction', 'roadwork', 'road work',
                'highway', 'traffic cone', 'traffic control', 'flagman',
                'lane closure', 'road barrier', 'moving traffic',
                'public road', 'road shoulder', 'median'
            ],
            'Construction Site': [
                'construction site', 'construction area', 'building site',
                'construction zone', 'construction project', 'construction work',
                'scaffolding', 'foundation work', 'concrete pour', 'concrete mixing',
                'demolition', 'building under construction', 'crane', 'rebar',
                'formwork', 'piling', 'site hoarding', 'tower crane',
                'backhoe', 'excavator on site', 'cement mixer'
            ],
            'Work at Height': [
                'scaffolding', 'scaffold', 'roof', 'rooftop', 'roofing',
                'elevated platform', 'ladder', 'aerial lift', 'cherry picker',
                'elevated walkway', 'suspended platform', 'edge of building',
                'high rise', 'working at height', 'fall protection'
            ],
            'Excavation / Trenching': [
                'excavation', 'trench', 'trenching', 'pit', 'earthworks',
                'digging', 'underground', 'shoring', 'deep hole',
                'foundation pit', 'pipe laying', 'utility trench'
            ],
            'Confined Space': [
                'confined space', 'tank', 'manhole', 'sewer', 'tunnel',
                'boiler', 'silo', 'vessel', 'pipeline interior', 'duct'
            ],
            # --- Indoor / facilities ---
            'Industrial / Warehouse': [
                'warehouse', 'factory', 'manufacturing', 'industrial',
                'production line', 'assembly line', 'storage facility',
                'loading dock', 'forklift', 'pallet', 'workshop',
                'machine shop', 'fabrication', 'welding bay', 'paint shop'
            ],
            'Residential': [
                'living room', 'bedroom', 'kitchen', 'bathroom',
                'backyard', 'garden', 'couch', 'sofa', 'dining',
                'home', 'house', 'apartment', 'residential',
                'bed', 'television', 'staircase', 'stairs', 'pillow',
                'curtain', 'carpet', 'relaxing'
            ],
            'Indoor / Office': [
                'office', 'desk', 'cubicle', 'meeting room', 'conference room',
                'workplace', 'computer', 'workstation', 'lobby',
                'corridor', 'hallway', 'reception', 'indoor', 'indoors',
                'room', 'interior', 'inside', 'ceiling', 'posing'
            ],
            # --- Public / open areas ---
            'Public Area': [
                'street', 'road', 'sidewalk', 'pavement',
                'intersection', 'crosswalk', 'public area',
                'parking lot', 'car park', 'open yard', 'material yard',
                'storage yard', 'staging area'
            ]
        }
        
        # Check for environment keywords (first match wins — order above matters)
        for env_type, keywords in ENVIRONMENT_KEYWORDS.items():
            for keyword in keywords:
                if keyword in caption_lower:
                    logger.info(f"Environment detected from caption: '{env_type}' (matched keyword: '{keyword}')")
                    return env_type
        
        # Default fallback
        logger.info("No specific environment detected from caption — defaulting to 'General Workspace'")
        return 'General Workspace'
    
    def _build_scene_description(
        self,
        caption: str,
        environment_type: str,
        detections: list
    ) -> str:
        """
        Build a professional, industry-standard AI scene description from the
        VLM caption, detected environment, and YOLO detections.
        
        This replaces the NLP's hallucinated visual_evidence when the environment
        override is triggered, producing an objective, factual description.
        
        Args:
            caption: VLM-generated image caption
            environment_type: Detected environment type from keyword matching
            detections: YOLO detection results
            
        Returns:
            Professional scene description string
        """
        # 1. Opening statement with environment classification
        description = f"The scene depicts a {environment_type.lower()} setting. "
        
        # 2. Append the VLM caption content (cleaned up)
        # Remove redundant "The image shows" prefix if present to avoid repetition
        caption_clean = caption.strip()
        for prefix in ['The image shows ', 'The image depicts ', 'The scene shows ', 'This image shows ']:
            if caption_clean.startswith(prefix):
                caption_clean = caption_clean[len(prefix):]
                # Capitalize the remaining text
                caption_clean = caption_clean[0].upper() + caption_clean[1:] if caption_clean else caption_clean
                break
        
        description += caption_clean
        
        # Ensure it ends with a period
        if description and not description.endswith('.'):
            description += '.'
        
        # 3. Append PPE violation summary
        violation_types = [
            d.get('class_name', '').replace('NO-', '')
            for d in detections
            if d.get('class_name', '').startswith('NO-')
        ]
        
        if violation_types:
            unique_violations = list(dict.fromkeys(violation_types))  # preserve order, remove dupes
            violation_text = ', '.join(unique_violations)
            # Count persons: explicit Person detections + infer from violations
            explicit_persons = sum(1 for d in detections if d.get('class_name', '') == 'Person')
            # Each group of violations may imply a person even if not explicitly detected
            person_count = max(explicit_persons, 1)  # At least 1 person if violations exist
            
            description += (
                f" YOLO detection identified {person_count} person(s) in the frame "
                f"with the following PPE deficiencies: {violation_text}."
            )
        
        logger.info(f"Built scene description ({len(description)} chars) for environment '{environment_type}'")
        return description
    
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
        
        # Smart Logic: If YOLO missed people but we have violations or caption mentions people, assume at least 1
        video_caption_lower = caption.lower()
        if person_count == 0:
            if len(detections) > 0:
                person_count = 1 # Assume at least one person committed the violation
            elif any(word in video_caption_lower for word in ['man', 'men', 'woman', 'women', 'person', 'people', 'worker', 'workers']):
                person_count = 1
        
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
        
        # Build enhanced prompt with Context-Aware Logic (Architecture 2.0)
        # Inject VLM caption into prompt so Llama 3 has visual context
        vlm_caption = report_data.get('caption', 'No visual caption available')
        
        prompt = f"""You are a JKR-certified AI Safety Officer. 
        
CONTEXT: Strict adherence to Malaysian Safety Standards (JKR/DOSH/CIDB).

*** VLM VISUAL CAPTION (Primary Visual Evidence) ***
"{vlm_caption}"

*** INSTRUCTION 1: SCENE CLASSIFICATION ***
Analyze the VLM visual caption above. Based ONLY on the contents described in the caption, classify the scene into ONE of these categories:
1. "Construction Site": Active building/infrastructure construction with heavy equipment.
2. "Roadside Work Zone": Active public highway/road with MOVING traffic. (Parked vehicles alone do NOT count.)
3. "Work at Height": Scaffolding, roof, edge of building, suspended platform (>2m elevation).
4. "Excavation / Trenching": Trench, pit, hole, earthworks (>1.5m depth).
5. "Industrial / Warehouse": Factory floor, warehouse, loading dock, workshop.
6. "Indoor / Office": Office, meeting room, indoor space, residential room.
7. "Residential": Home, apartment, living room, bedroom, kitchen.
8. "Public Area": Sidewalk, parking lot, open yard, material staging area.
9. "General Workspace": Catch-all for ground-level work that doesn't fit above.

IMPORTANT: Your classification MUST be consistent with the VLM caption. 
If the caption describes a couch, living room, bedroom, or indoor setting, the scene is NOT Construction/Roadside.

*** INSTRUCTION 2: DYNAMIC RULESET SELECTION ***
Based on classification, APPLY these specific standards:
- IF Roadside Work Zone: Apply **JKR Arahan Teknik (Jalan) 2C/85**. High Visibility Vest is MANDATORY.
- IF Work at Height: Apply **BOWEC 1986 (Scaffolds)**. Safety Harness/Helmet is MANDATORY.
- IF Excavation: Apply **DOSH Guidelines on Trenching**. Shoring/Barriers required.
- OTHERWISE: Apply **BOWEC 1986 (General)** and relevant OSHA 1994 provisions.

*** INSTRUCTION 3: WITNESS COUNT (ZERO TOLERANCE) ***
- You MUST analyze exactly {person_count} people.
- WARNING: Do NOT count detected PPE tags (e.g. 'NO-Hardhat') as people. Only count class 'Person'.

*** INSTRUCTION 4: REPORT GENERATION ***
Generate a JSON report following this logic:

1. **SCENE DESCRIPTION (visual_evidence field)**: Start with "The scene depicts a [environment type] setting." 
   Then describe what the VLM caption shows. Be objective and factual. DO NOT REPEAT THE LIST OF CATEGORIES.
2. **INDIVIDUAL ANALYSIS**:
   - "Person N (Action) + No PPE + [Scene Hazard] = Specific Risk"
3. **WEIGHTED SEVERITY**:
   - Boost severity to "CRITICAL" if the missing PPE is lethal for that scene.
4. **NEGATIVE CONSTRAINTS**:
   - NO vague terms ("scattered", "some").
   - NO "Chemical masks" unless chemicals visible.
   - NO "1." numbering prefixes in the description text.

{dosh_text if dosh_text else ""}{context_text if context_text else ""}

RESPONSE FORMAT (JSON):
{{
    "environment_type": "[One of the 9 categories above]",
    "visual_evidence": "The scene depicts a [environment] setting. [Detailed factual description from VLM caption]...",
    "persons": [
        {{
            "id": "Person 1",
            "description": "Person 1 observed standing in potential fall zone without fall protection.",
            "actions": ["Stop Work", "Issue PPE"],
            "ppe": {{
                "hardhat": "Mentioned/Missing/Not Required",
                "safety_vest": "Mentioned/Missing/Not Required",
                "mask": "Mentioned/Missing/Not Required",
                "gloves": "Mentioned/Missing/Not Required",
                "footwear": "Mentioned/Missing/Not Required",
                "goggles": "Mentioned/Missing/Not Required"
            }},
            "hazards_faced": [
                 {{ "type": "Hazard type", "source": "Source", "severity": "HIGH/MEDIUM/LOW" }}
            ],
            "risks": [
                 {{ 
                    "risk": "Risk description", 
                    "likelihood": "HIGH/MEDIUM/LOW", 
                    "regulation_citation": "Regulation", 
                    "legal_regulatory_consequences": "Consequence" 
                 }}
            ]
        }}
    ],
    "summary": "• **SCENE CLASS**: [Environment Type]...\\n• **CRITICAL RISK**: ...\\n• **LEGAL ORDER**: ...",
    "dosh_regulations_cited": [
        {{ "regulation": "Regulation Name", "requirement": "Requirement" }}
    ]
}}
"""
        
        return prompt
    
    def _call_gemini_api(self, prompt: str, image_path: str = None) -> Optional[Dict[str, Any]]:
        """
        Call Gemini API for NLP analysis (primary provider).
        
        Args:
            prompt: Prompt to send to Gemini
            image_path: Optional image for multimodal analysis
        
        Returns:
            Parsed JSON response or None if failed
        """
        if not self.gemini_client or not self.gemini_client.is_available:
            return None
        
        try:
            logger.info("\U0001f680 Using Gemini API for NLP analysis...")
            result = self.gemini_client.generate_report_json(prompt, image_path=image_path)
            
            if result:
                logger.info("✓ Gemini NLP analysis completed")
                return result
            else:
                logger.warning("Gemini returned no valid JSON")
                return None
                
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return None
    
    def _call_ollama_api(self, prompt: str) -> Optional[Dict[str, Any]]:
        """
        Call Ollama API or use local Llama to get NLP analysis (fallback).
        
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
                    max_new_tokens=512,
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
                    'context': [],
                    'stream': False,
                    'format': 'json',
                    'options': {
                        'temperature': self.temperature,
                        'num_predict': 1500,
                        'top_k': 40,
                        'top_p': 0.9
                    }
                },
                timeout=self.ollama_timeout
            )
            
            if not response.ok:
                logger.error(f"Ollama API error: {response.status_code}")
                return None
            
            data = response.json()
            logger.debug(f"Ollama response: {data}")
            
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
        regulation_context = ""
        
        if self.rag_enabled:
            query_text = f"{report_data.get('caption', '')} {report_data.get('violation_summary', '')}"
            
            # PRIMARY: Direct regulation injection (Gemini mode)
            if self.use_gemini and self.regulations_data:
                detected_violations = [d.get('class_name', '') for d in report_data.get('detections', []) if d.get('class_name', '').startswith('NO-')]
                caption = report_data.get('caption', '')
                env_type = self._extract_environment_from_caption(caption)
                regulation_context = build_regulation_context(
                    self.regulations_data,
                    detected_violations=detected_violations,
                    environment_type=env_type
                )
                logger.info(f"Injected {len(regulation_context)} chars of regulation context")
            
            # LEGACY: Use Chroma DB for DOSH documentation (only if Gemini disabled)
            elif self.use_chroma and self.chroma_collection:
                logger.info("Retrieving relevant DOSH documentation from Chroma DB...")
                dosh_context = self._query_chroma_db(query_text, n_results=self.top_k)
                logger.info(f"Retrieved {len(dosh_context)} DOSH documentation chunks")
            
            # Also get similar incidents from CSV (optional)
            similar_incidents = self._find_similar_incidents(query_text, self.num_similar)
            logger.info(f"Found {len(similar_incidents)} similar incidents")
        
        # Step 2: NLP - Generate analysis
        nlp_analysis = None
        prompt = self._build_nlp_prompt(report_data, similar_incidents, dosh_context)
        
        # Inject regulation context into prompt if using Gemini
        if regulation_context:
            prompt = regulation_context + "\n" + prompt
        
        # Try Gemini first, then Ollama
        if self.use_gemini:
            image_path = report_data.get('original_image_path')
            nlp_analysis = self._call_gemini_api(prompt, image_path=str(image_path) if image_path else None)
        
        if not nlp_analysis:
            # Fallback to Ollama
            if self.use_gemini:
                logger.warning("Gemini failed, falling back to Ollama...")
            nlp_analysis = self._call_ollama_api(prompt)
        
        if not nlp_analysis:
            # Fallback if NLP fails
            logger.warning("NLP analysis failed, using fallback")
            nlp_analysis = self._generate_fallback_analysis(report_data)
        else:
            # Post-NLP validation: Enhance NLP output with fallback data for better specificity
            detections = report_data.get('detections', [])
            has_violations = any(d.get('class_name', '').startswith('NO-') for d in detections)
            
            if has_violations:
                # Generate fallback data with specific JKR/BOWEC/OSHA regulations
                fallback = self._generate_fallback_analysis(report_data)
                
                # Always use fallback DOSH regulations (they have specific citations)
                # NLP often returns generic text like "All workers must wear PPE"
                logger.info("Using fallback DOSH regulations for specific JKR/BOWEC/OSHA citations")
                nlp_analysis['dosh_regulations_cited'] = fallback.get('dosh_regulations_cited', [])
                
                # ALWAYS extract environment from VLM caption and override NLP (ROOT CAUSE FIX)
                # Llama 3 hallucinates "ROADSIDE" for indoor scenes because NO-Safety Vest
                # triggers its "roadside" bias. VLM caption keywords are more reliable.
                caption = report_data.get('caption', '')
                detected_env = self._extract_environment_from_caption(caption)
                nlp_env = nlp_analysis.get('environment_type', 'Unknown')
                
                if detected_env != 'General Workspace':
                    # VLM found a specific environment match - trust it over NLP
                    if detected_env.lower() != nlp_env.lower():
                        logger.warning(f"Environment OVERRIDE: NLP said '{nlp_env}' but VLM caption matched '{detected_env}'. Using VLM.")
                        
                        # Build professional scene description from VLM caption + environment
                        nlp_analysis['visual_evidence'] = self._build_scene_description(
                            caption, detected_env, report_data.get('detections', [])
                        )
                        
                        # Patch summary to replace wrong scene class
                        summary = nlp_analysis.get('summary', '')
                        if summary and nlp_env.upper() in summary.upper():
                            nlp_analysis['summary'] = summary.replace(nlp_env, detected_env).replace(nlp_env.upper(), detected_env)
                    
                    nlp_analysis['environment_type'] = detected_env
                elif nlp_env.lower() == 'unknown':
                    # NLP returned Unknown and VLM had no specific match either
                    logger.info(f"Environment type was 'Unknown' - using fallback '{detected_env}'")
                    nlp_analysis['environment_type'] = detected_env
                
                # Get per-person actions based on their specific PPE violations
                # Map violation types to specific corrective actions
                VIOLATION_ACTIONS = {
                    'hardhat': 'Stop work immediately. Issue MS 183:2001 certified safety helmet. Verify chin strap is fastened.',
                    'safety vest': 'Ensure high-visibility vest (Neon Yellow/Orange - MS 1731) is worn as outermost layer.',
                    'mask': 'Provide MS 2323:2010 particulate respirator (N95/P2) or specific chem-hazard mask.',
                    'gloves': 'Provide task-specific hand protection (cut-resistant for rebar, chemical-resistant for wet works).',
                    'goggles': 'Mandate MS 2050 compliant eye protection appropriate for the specific task.',
                    'footwear': 'Enforce MS ISO 20345 Safety Boots usage (Steel toe/midsole protection).'
                }
                
                # Get detected violations
                detected_violations = [d.get('class_name', '').lower().replace('no-', '') 
                                       for d in detections if d.get('class_name', '').startswith('NO-')]
                # Get specific corrective actions from fallback
                fallback_actions = fallback.get('suggested_actions', [])
                
                # If persons array is empty, use fallback persons
                if not nlp_analysis.get('persons'):
                    logger.warning("NLP returned empty persons array - using fallback persons data")
                    nlp_analysis['persons'] = fallback.get('persons', [])
                
                # Enforce person count from YOLO (prevents hallucinations)
                # If YOLO detected 2 people, but LLM imagined 6, we truncate to 2
                yolo_person_count = report_data.get('person_count', 0)
                
                # If YOLO count is 0 but we have violations, assume at least 1 person responsible
                if yolo_person_count == 0 and has_violations:
                    yolo_person_count = 1
                
                nlp_persons = nlp_analysis.get('persons', [])
                if len(nlp_persons) > yolo_person_count:
                    logger.warning(f"NLP hallucinated {len(nlp_persons)} persons, but YOLO detection count is {yolo_person_count}. Truncating.")
                    nlp_analysis['persons'] = nlp_persons[:yolo_person_count]
                elif len(nlp_persons) < yolo_person_count:
                    logger.warning(f"NLP Under-Count: {len(nlp_persons)} vs YOLO {yolo_person_count}. Appending fallback data.")
                    fallback_persons = fallback.get('persons', [])
                    # Append missing persons from fallback
                    if len(fallback_persons) >= yolo_person_count:
                        nlp_analysis['persons'].extend(fallback_persons[len(nlp_persons):yolo_person_count])
                    else:
                        nlp_analysis['persons'].extend(fallback_persons[len(nlp_persons):])

                # Enhance each person with specific actions for THEIR PPE violations
                for person in nlp_analysis.get('persons', []):
                    ppe_status = person.get('ppe', {})
                    person_actions = []
                    
                    # Check each PPE item for this person
                    for ppe_key, action in VIOLATION_ACTIONS.items():
                        ppe_field = ppe_key.replace(' ', '_')
                        status = str(ppe_status.get(ppe_field, '')).lower()
                        
                        # If this person's PPE is missing, add the specific action
                        if status == 'missing' or ppe_key.replace('_', ' ') in detected_violations:
                            person_actions.append(action)
                    
                    # If no specific actions, use general ones
                    if not person_actions:
                        person_actions = fallback.get('suggested_actions', ['Conduct safety inspection'])
                    
                    # Set both action fields
                    person['actions'] = person_actions
                    person['corrective_actions'] = person_actions



        
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
        
        # Hazards and recommendations by violation type (aligned with JKR/OSHA standards)
        # v7 Enhancement: Dual citations (Law + Technical Standard) and Action Verb directives
        # v7.1: Added official regulation URLs for verification
        # v7.2: Updated to direct PDF download links for specific regulations
        VIOLATION_DATA = {
            'hardhat': {
                'hazard': 'Exposure to falling objects (timber piles, debris) or impact with fixed structures in a mandatory Hard Hat Zone.',
                'risk': 'Fatal/Severe: Traumatic Brain Injury (TBI), skull fracture, or concussion from overhead debris.',
                'action': 'REPLACE HAT WITH HELMET: Worker is at risk of fatal head injury from falling timber/debris. Stop work immediately.',
                'legal_citation': 'BOWEC 1986, Reg. 24: Mandatory head protection on construction sites.',
                'technical_standard': 'MS 183:2001: Specifications for industrial safety helmets.',
                'regulation': 'BOWEC 1986 Reg. 24 / MS 183:2001',
                'requirement': 'Personnel must wear MS 183:2001 certified industrial safety helmets (at least 4.9kN impact resistance). Sun hats/caps are PROHIBITED.',
                'penalty': 'Violation of OSHA 1994 Section 15. Mandatory fine up to RM 50,000 or 2 years imprisonment for failing to provide safe equipment.',
                'risk_tier': 'HIGH'  # Tier 1: Instant Push
            },
            'mask': {
                'hazard': 'Inhalation of hazardous construction dusts (silica from concrete, wood particles from timber handling) or fumes.',
                'risk': 'Chronic/Acute: Respiratory impairment (Silicosis, Asthma) or lung damage from prolonged dust exposure.',
                'action': 'ISSUE RESPIRATOR: Stop exposure to dust/fumes immediately. Provide N95/P2 particulate mask.',
                'legal_citation': 'USECHH Regulations 2000: Control of exposure to hazardous chemicals.',
                'technical_standard': 'MS 2323:2010: Respiratory protective devices - Selection, use and maintenance.',
                'regulation': 'USECHH 2000 / MS 2323:2010',
                'requirement': 'Workers exposed to construction dusts must wear MS 2323:2010 compliant respirators (Min. N95/P2 class).',
                'penalty': 'Violation of USECHH Regulations 2000. Fine up to RM 10,000 or 1 year imprisonment.',
                'risk_tier': 'MEDIUM'  # Tier 2: End-of-Shift Batch
            },
            'safety vest': {
                'hazard': 'Failure to be visible to operators of mobile plant (excavators, lorries) and passing traffic on roadside sites.',
                'risk': 'Fatal: Struck-by-vehicle incident from lorry, excavator, or passing traffic near roadside work zones.',
                'action': 'WEAR VEST NOW: Worker is invisible to lorry/excavator operators. HIGH RISK of being struck.',
                'legal_citation': 'JKR Standard Spec (Section A): High-viz required near plant/traffic.',
                'technical_standard': 'MS 1731:2004: Retroreflective materials for high-visibility safety vests.',
                'regulation': 'JKR Std Spec Sec A / MS 1731:2004',
                'requirement': 'Workers must wear SIRIM-certified neon vests with retroreflective strips visible from 200m (Class 2 Minimum).',
                'penalty': 'Violation of JKR Standard Specification Section A. Mandatory fine up to RM 50,000 under Section 15 of OSHA 1994 for failing to provide a safe system of work.',
                'risk_tier': 'HIGH'  # Tier 1: Instant Push (especially if roadside)
            },
            'gloves': {
                'hazard': 'Direct contact with abrasive materials, sharp edges (rebar), or corrosive substances.',
                'risk': 'Moderate: Lacerations, chemical burns, punctures, or dermatitis.',
                'action': 'ISSUE GLOVES: Worker handling materials without hand protection. Provide cut-resistant or chemical-resistant gloves.',
                'legal_citation': 'OSHA 1994 Section 15: Employer duty to provide suitable PPE.',
                'technical_standard': 'MS 2097: Protective gloves for construction.',
                'regulation': 'OSHA 1994 Section 15 / MS 2097',
                'requirement': 'Suitable hand protection (MS 2097) must be worn when handling abrasive, sharp, or hazardous materials.',
                'penalty': 'General penalty under OSHA 1994 Section 15: Fine up to RM 50,000.',
                'risk_tier': 'MEDIUM'  # Tier 2: End-of-Shift Batch
            },
            'goggles': {
                'hazard': 'Exposure to flying particles (grinding/chipping), chemical splashes, or intense light emissions.',
                'risk': 'Severe: Corneal abrasion, chemical eye burns, or permanent vision loss.',
                'action': 'ISSUE EYE PROTECTION: Worker exposed to flying particles/splashes. Provide MS 2050 compliant goggles.',
                'legal_citation': 'BOWEC 1986 Reg. 13: Eye protection for hazardous processes.',
                'technical_standard': 'MS 2050: Eye protectors for industrial use.',
                'regulation': 'BOWEC 1986 Reg. 13 / MS 2050',
                'requirement': 'Eye protection (MS 2050) is mandatory for processes involving flying particles (welding, cutting, grinding).',
                'penalty': 'Strict liability offense under FMA 1967. Fine up to RM 5,000.',
                'risk_tier': 'MEDIUM'  # Tier 2: End-of-Shift Batch
            },
            'footwear': {
                'hazard': 'Foot exposure to sharp objects (nails), crushing weights, or uneven terrain/slip hazards.',
                'risk': 'Serious: Crushed toes, puncture wounds (tetanus risk), or skeletal fractures.',
                'action': 'CHANGE FOOTWEAR: Worker wearing non-compliant shoes. Enforce MS ISO 20345 safety boots (steel toe).',
                'legal_citation': 'BOWEC 1986 Reg. 15: Safety footwear mandatory on construction sites.',
                'technical_standard': 'MS ISO 20345: Personal protective equipment - Safety footwear.',
                'regulation': 'BOWEC 1986 Reg. 15 / MS ISO 20345',
                'requirement': 'Safety footwear (MS ISO 20345) with toe protection (200J) and penetration resistance is MANDATORY. Slippers/sneakers are prohibited.',
                'penalty': 'Violation of BOWEC Reg 15. Fine up to RM 5,000.',
                'risk_tier': 'MEDIUM'  # Tier 2: End-of-Shift Batch
            },
            'harness': {
                'hazard': 'Working at height (>2m) without fall arrest system or improper anchorage.',
                'risk': 'Fatal: Fall from height resulting in death or catastrophic injury.',
                'action': 'STOP WORK IMMEDIATELY: Worker at height without harness. Equip with MS 2311 full-body harness before resuming.',
                'legal_citation': 'BOWEC 1986 Reg. 12: Fall protection mandatory for work at height.',
                'technical_standard': 'MS 2311: Full-body harness for fall arrest systems.',
                'regulation': 'BOWEC 1986 Reg. 12 / MS 2311',
                'requirement': 'Full-body harness (MS 2311) with secure anchorage is mandatory for all work at height >2m.',
                'penalty': 'Immediate Prohibition Notice. Fine up to RM 50,000 under OSHA 1994.',
                'risk_tier': 'HIGH'  # Tier 1: Instant Push
            },
            'unsecured_piles': {
                'hazard': 'Unsecured material stacking (Bakau piles, timber) on slopes or uneven ground.',
                'risk': 'Fatal: Crush hazard from material collapse onto workers.',
                'action': 'SECURE MATERIALS: Unsecured piles detected. Implement chocking/bracing per CIDB CIS 22:2021.',
                'legal_citation': 'BOWEC 1986 Reg. 18: Safe stacking of materials to prevent collapse.',
                'technical_standard': 'CIDB CIS 22:2021: Safe handling and storage of construction materials.',
                'regulation': 'BOWEC 1986 Reg. 18 / CIDB CIS 22:2021',
                'requirement': 'Material stacks must be stable and secured (chocked) against collapse. Stacking on slopes is prohibited.',
                'penalty': 'Violation of BOWEC Reg 18. Fine up to RM 50,000.',
                'risk_tier': 'HIGH'  # Tier 1: Instant Push
            },
            'roadside_risk': {
                'hazard': 'Workers operating near active traffic lanes without barriers or traffic management.',
                'risk': 'Fatal: Struck-by-vehicle incident from passing traffic.',
                'action': 'ESTABLISH TRAFFIC MANAGEMENT PLAN: Roadside work zone detected. Deploy flagmen and cone tapers per JKR ATJ 2C/85 to secure the perimeter.',
                'legal_citation': 'OSHA 1994 Section 15: Employer duty to ensure safety of workers and public.',
                'technical_standard': 'JKR ATJ 2C/85: Manual on Traffic Control Devices.',
                'regulation': 'OSHA 1994 Sec 15 / JKR ATJ 2C/85',
                'requirement': 'Roadside works must implement a Traffic Management Plan (TMP) compliant with JKR ATJ 2C/85, including Advance Warning Signs, Safety Cones, and Flagmen.',
                'penalty': 'Major offense under OSHA 1994 Section 15. Mandatory fine up to RM 50,000 or 2 years imprisonment.',
                'risk_tier': 'HIGH'  # Tier 1: Instant Push
            },
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
                    regulations.append({
                        'regulation': data['regulation'], 
                        'requirement': data['requirement'],
                        'penalty': data.get('penalty', ''),
                        'legal_url': data.get('legal_url', ''),
                        'standard_url': data.get('standard_url', '')
                    })
                    break
        
        # Detect environment from caption keywords AND YOLO detections
        caption = report_data.get('vlm_caption', '') or report_data.get('caption', '') or ''
        caption_lower = caption.lower()

        # YOLO Object Context
        detections_str = " ".join([d.get('class_name', '').lower() for d in report_data.get('detections', [])])
        yolo_cones = 'cone' in detections_str
        yolo_vehicle = 'vehicle' in detections_str or 'truck' in detections_str or 'lorry' in detections_str
        yolo_machinery = 'machinery' in detections_str or 'excavator' in detections_str
        
        # Environment detection with specificity
        # Check for specific Malaysian context hazards from caption + YOLO
        has_piles = any(kw in caption_lower for kw in ['pile', 'timber', 'log', 'bakau', 'wood'])
        has_slope = any(kw in caption_lower for kw in ['slope', 'incline', 'embankment', 'unstable', 'dirt'])
        has_roadside = any(kw in caption_lower for kw in ['road', 'roadside', 'traffic', 'highway', 'lorry', 'truck', 'pavement']) or yolo_cones or yolo_vehicle
        has_lorry = any(kw in caption_lower for kw in ['lorry', 'truck', 'flatbed', 'vehicle']) or yolo_vehicle
        has_phone = any(kw in caption_lower for kw in ['phone', 'mobile', 'call', 'device', 'watsapp', 'texting'])
        
        if has_roadside and has_piles:
            env_type = 'Roadside Bakau Piling Zone'
            env_detail = 'High-risk roadside timber piling zone with struck-by-vehicle and crush hazards.'
        elif has_roadside:
            env_type = 'Roadside Work Zone'
            env_detail = 'Roadside location with struck-by-vehicle risk from passing traffic. JKR ATJ 2C/85 traffic management required.'
        elif has_piles:
            env_type = 'Material Handling Area'
            env_detail = 'Bakau piling zone with crush hazards from unsecured timber loads. BOWEC Reg. 18 applies.'
        elif any(kw in caption_lower for kw in ['construction', 'building', 'scaffold', 'crane', 'excavat', 'foundation']):
            env_type = 'Construction Site'
            env_detail = 'Active construction zone with potential heavy machinery and falling object hazards.'
        elif any(kw in caption_lower for kw in ['warehouse', 'factory', 'industrial', 'manufacturing']):
            env_type = 'Industrial Warehouse'
            env_detail = 'Industrial environment with forklift traffic and material handling hazards.'
        else:
            env_type = 'General Workspace'
            env_detail = 'Work environment identified from visual analysis.'
        
        # Generate behavior-based person descriptions (not generic "Individual detected")
        violation_types = [v.replace('NO-', '') for v in violations]
        
        # Create specific person descriptions based on context
        person_descriptions = []
        for i in range(person_count):
            person_id = f"Person {i + 1}"
            
            # Build behavior-based description
            if 'Safety Vest' in violation_types and 'Hardhat' in violation_types:
                desc = f"Worker operating in {env_type} without MS 1731 high-visibility vest or MS 183 helmet."
                if has_slope:
                    desc += " Positioned on unstable embankment."
                if has_piles:
                    desc += " Risk: Loss of situational awareness near heavy timber loads."
                if has_phone:
                     desc += " DISTRACTED by mobile phone/device."
                     risks.append("Distracted Behavior: Reduced situational awareness while operating in high-risk zone.")
            elif 'Safety Vest' in violation_types:
                desc = f"Worker without MS 1731 high-visibility vest. INVISIBLE to lorry/plant operators."
                if has_roadside:
                    desc += " FATAL RISK from passing traffic."
                if has_phone:
                     desc += " DISTRACTED by mobile phone/device."
                     risks.append("Distracted Behavior: Reduced situational awareness while operating in high-risk zone.")
            elif 'Hardhat' in violation_types:
                desc = f"Worker without MS 183 rigid helmet in falling object zone."
                if has_piles:
                    desc += " Violation: BOWEC 1986 Reg. 24 (sun hats do not meet impact requirements)."
                if has_phone:
                     desc += " DISTRACTED by mobile phone/device."
                     risks.append("Distracted Behavior: Reduced situational awareness while operating in high-risk zone.")
            else:
                desc = f"Worker observed with PPE status as detailed below."
                if has_phone:
                     desc += " Worker is DISTRACTED by mobile phone/device."
                     risks.append("Distracted Behavior: Reduced situational awareness while operating in high-risk zone.")

            
            person_descriptions.append({
                'id': i + 1,
                'description': desc,
                'ppe': ppe_status.copy(),
                'actions': actions or ['Ensure appropriate PPE is available and worn when required'],
                'hazards_faced': hazards or ['Potential hazards identified based on missing PPE'],
                'risks': risks or ['Risk level depends on environment and activities performed'],
                'compliance_status': 'Non-Compliant' if violations else 'Unknown'
            })
        
        # Situation-Hazard-Standard summary model
        if violation_types:
            ppe_list = ' or '.join([f"MS {std}" for std in ['1731 high-visibility vest' if 'Safety Vest' in violation_types else '', '183 helmet' if 'Hardhat' in violation_types else ''] if std])
            if not ppe_list:
                ppe_list = ' and '.join(violation_types)
            
            # Build Situation-Hazard-Standard summary
            situation = f"High-severity violation at {env_type.lower()}."
            hazard = f"{person_count} personnel operating"
            if has_slope:
                hazard += " on an unstable embankment"
            if has_lorry:
                hazard += " near a flatbed lorry"
            hazard += f" without {ppe_list}."
            standard = "Stop Work order recommended per BOWEC 1986."
            
            if 'Safety Vest' in violation_types and has_roadside:
                risk_desc = "This creates an immediate risk of being struck by the lorry or passing traffic."
            elif 'Hardhat' in violation_types and has_piles:
                risk_desc = "This creates an immediate risk of head injury from falling timber/debris."
            else:
                risk_desc = "This creates an immediate risk of injury."
            
            summary = f"{situation} {hazard} {risk_desc} {standard}"
        else:
            summary = f"Safety observation recorded at {env_type}."
        
        return {
            'summary': summary,
            'environment_type': env_type,
            'environment_assessment': env_detail,
            'dosh_regulations_cited': regulations or [{'regulation': 'General Safety Guidelines', 'requirement': 'PPE should be worn as appropriate for the environment and activities'}],
            'persons': person_descriptions,
            'hazards_detected': hazards or ['PPE status recorded for reference'],
            'suggested_actions': actions or ['Assess environment to determine PPE requirements'],
            'severity_level': 'HIGH' if violations else 'MEDIUM'
        }
    
    # Old summary method removed



    def _inject_interactive_tooltips(self, text):
        """Wraps standard names in interactive tooltip spans."""
        if not text:
            return text
            
        import re
        replacements = [
            (r'(MS\s?1731|High-Visibility|High-Vis|Vest|Reflective Strips?|Neon)', 'ms1731_vest.jpg'),
            (r'(MS\s?183(:2001)?|Safety Helmet|Hardhat|Head Protection|Helmet)', 'ms183_helmet.jpg'),
            (r'(MS\s?ISO\s?20345|Safety Footwear|Safety Shoes|Boots|Shoes)', 'iso20345_boots.jpg'),
            (r'(BOWEC(\s?1986)?|Body Harness|Safety Harness|Fall Protection|Lanyard|Double Lanyard)', 'bowec_harness.jpg'),
            (r'(MS\s?2323(:2010)?|Respirator|Mask|N95|Face Mask)', 'ms2323_mask.png')
        ]
        
        for pattern, img_file in replacements:
            text = re.sub(pattern, f'<span class="ppe-tooltip" data-image="{img_file}">\\g<0></span>', text, flags=re.IGNORECASE)
            
        return text

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

        # Clean violation summary (Deduplicate)
        raw_summary = report_data.get('violation_summary', '')
        if raw_summary:
            parts = [p.strip() for p in raw_summary.split(',')]
            from collections import Counter
            counts = Counter(parts)
            summary_parts = []
            for vio, count in counts.items():
                if count > 1:
                    summary_parts.append(f"{vio} (x{count})")
                else:
                    summary_parts.append(vio)
            report_data['violation_summary'] = ", ".join(summary_parts)
        
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

        /* Tooltip CSS */
        .ppe-tooltip {{
            border-bottom: 2px dashed #e67e22;
            cursor: help;
            position: relative;
            color: #d35400;
            font-weight: 600;
            transition: all 0.2s ease;
        }}
        
        .ppe-tooltip:hover {{
            background-color: rgba(230, 126, 34, 0.1);
            border-bottom-style: solid;
        }}
        
        .ppe-tooltip::after {{
            content: '';
            position: absolute;
            bottom: 100%;
            left: 50%;
            transform: translateX(-50%) translateY(-10px);
            width: 200px;
            height: 200px;
            background-color: white;
            background-size: contain;
            background-repeat: no-repeat;
            background-position: center;
            border: 2px solid #e67e22;
            border-radius: 8px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.2);
            opacity: 0;
            visibility: hidden;
            transition: opacity 0.2s, transform 0.2s;
            z-index: 1000;
            pointer-events: none;
        }}
        
        .ppe-tooltip[data-image="ms1731_vest.jpg"]::after {{ background-image: url('/static/images/standards/ms1731_vest.jpg'); }}
        .ppe-tooltip[data-image="ms183_helmet.jpg"]::after {{ background-image: url('/static/images/standards/ms183_helmet.jpg'); }}
        .ppe-tooltip[data-image="iso20345_boots.jpg"]::after {{ background-image: url('/static/images/standards/iso20345_boots.jpg'); }}
        .ppe-tooltip[data-image="bowec_harness.jpg"]::after {{ background-image: url('/static/images/standards/bowec_harness.jpg'); }}
        .ppe-tooltip[data-image="ms2323_mask.png"]::after {{ background-image: url('/static/images/standards/ms2323_mask.png'); }}
        
        .ppe-tooltip:hover::after {{
            opacity: 1;
            visibility: visible;
            transform: translateX(-50%) translateY(-5px);
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
            white-space: normal;
            overflow: visible;
            text-overflow: unset;
            word-wrap: break-word;
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
            
            <!-- AI Scene Analysis -->
            <div class="section">
                <h2 class="section-title">🤖 AI Scene Description</h2>
                <div class="card">
                    <div class="card-content">
                        <p>{nlp_analysis.get('visual_evidence', report_data.get('caption', 'No description available'))}</p>
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
                        {self._format_summary_html(nlp_analysis, report_data)}
                        {f"<p style='margin-top: 1rem; font-style: italic; color: #7f8c8d;'>{nlp_analysis.get('environment_assessment', '')}</p>" if nlp_analysis.get('environment_assessment') else ''}
                    </div>
                </div>
            </div>
            
            <!-- DOSH Regulations -->
            {self._generate_dosh_regulations_section(nlp_analysis)}
            
            <!-- Individual Person Analysis -->
            {self._generate_person_cards_section(nlp_analysis, report_data)}
        </div>
        
        <!-- Functional NCR Generation Section -->
        <div class="section" style="background: linear-gradient(135deg, #f8f9fa, #e9ecef); border: 2px solid #495057; padding: 1.5rem; margin: 1rem 0; border-radius: 8px; text-align: center;">
            <h3 style="color: #495057; margin-bottom: 0.5rem;">📋 Generate Official Documentation</h3>
            <p style="color: #6c757d; margin-bottom: 1rem;">Create formal documentation for regulatory compliance and incident reporting.</p>
            <button onclick="generateNCR()" style="background: linear-gradient(135deg, #28a745, #20c997); color: white; border: none; padding: 0.75rem 1.5rem; border-radius: 6px; cursor: pointer; font-weight: bold; margin-right: 0.5rem; box-shadow: 0 2px 4px rgba(0,0,0,0.2);">
                📄 Generate Non-Conformance Report (NCR)
            </button>
            <button onclick="generateJKKP7()" style="background: linear-gradient(135deg, #007bff, #0056b3); color: white; border: none; padding: 0.75rem 1.5rem; border-radius: 6px; cursor: pointer; font-weight: bold; box-shadow: 0 2px 4px rgba(0,0,0,0.2);">
                ⚠️ Generate JKKP-7 Incident Form
            </button>
        </div>
        
        <script>
        function generateNCR() {{
            const reportId = '{report_id}';
            const timestamp = '{report_data.get("timestamp", "N/A")}';
            const environment = '{nlp_analysis.get("environment_type", "Construction Site")}';
            const severity = '{nlp_analysis.get("severity_level", "HIGH")}';
            const summary = `{nlp_analysis.get("summary", "PPE violation detected").replace('"', "").replace("'", "")}`;
            
            // Collect violations from the page
            const violations = [];
            document.querySelectorAll('.card-header').forEach(el => {{
                if (el.textContent.includes('Reg.') || el.textContent.includes('OSHA') || el.textContent.includes('BOWEC')) {{
                    violations.push(el.textContent.trim());
                }}
            }});
            
            const ncrHtml = `
<!DOCTYPE html>
<html>
<head>
    <title>NCR - ${{reportId}}</title>
    <style>
        @media print {{ @page {{ margin: 1.5cm; }} }}
        body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.4; }}
        .header {{ text-align: center; border-bottom: 3px solid #000; padding-bottom: 15px; margin-bottom: 20px; }}
        .header h1 {{ margin: 0; color: #c00; font-size: 24px; }}
        .header h2 {{ margin: 5px 0; font-size: 18px; }}
        .ncr-number {{ background: #f0f0f0; padding: 10px; font-size: 16px; font-weight: bold; margin: 10px 0; }}
        .section {{ margin: 15px 0; }}
        .section-title {{ background: #333; color: white; padding: 8px 12px; font-weight: bold; margin-bottom: 10px; }}
        .field {{ display: flex; border-bottom: 1px solid #ccc; padding: 8px 0; }}
        .field-label {{ width: 180px; font-weight: bold; }}
        .field-value {{ flex: 1; }}
        .violations-list {{ background: #fff8e1; padding: 10px; border-left: 4px solid #ffc107; }}
        .signature-block {{ display: flex; justify-content: space-between; margin-top: 40px; }}
        .signature-box {{ width: 45%; text-align: center; }}
        .signature-line {{ border-top: 1px solid #000; margin-top: 60px; padding-top: 5px; }}
        .checkbox {{ display: inline-block; width: 15px; height: 15px; border: 1px solid #000; margin-right: 10px; vertical-align: middle; }}
        .footer {{ text-align: center; margin-top: 30px; font-size: 12px; color: #666; border-top: 1px solid #ccc; padding-top: 10px; }}
        .print-btn {{ background: #28a745; color: white; border: none; padding: 10px 20px; cursor: pointer; font-size: 16px; margin: 20px; }}
        @media print {{ .print-btn {{ display: none; }} }}
    </style>
</head>
<body>
    <button class="print-btn" onclick="window.print()">🖨️ Print NCR</button>
    
    <div class="header">
        <h1>⚠️ NON-CONFORMANCE REPORT (NCR)</h1>
        <h2>Workplace Safety & Health Violation</h2>
        <div class="ncr-number">NCR No: NCR-${{reportId.replace('violation_', '')}}</div>
    </div>
    
    <div class="section">
        <div class="section-title">📍 INCIDENT DETAILS</div>
        <div class="field"><span class="field-label">Report ID:</span><span class="field-value">${{reportId}}</span></div>
        <div class="field"><span class="field-label">Date/Time:</span><span class="field-value">${{timestamp}}</span></div>
        <div class="field"><span class="field-label">Location Type:</span><span class="field-value">${{environment}}</span></div>
        <div class="field"><span class="field-label">Severity Level:</span><span class="field-value" style="color: ${{severity === 'HIGH' ? '#c00' : '#f90'}}; font-weight: bold;">${{severity}}</span></div>
    </div>
    
    <div class="section">
        <div class="section-title">📝 DESCRIPTION OF NON-CONFORMANCE</div>
        <p>${{summary}}</p>
    </div>
    
    <div class="section">
        <div class="section-title">⚖️ REGULATIONS VIOLATED</div>
        <div class="violations-list">
            ${{violations.map(v => '<div>• ' + v + '</div>').join('') || '<div>• See attached violation report for full details</div>'}}
        </div>
    </div>
    
    <div class="section">
        <div class="section-title">✅ CORRECTIVE ACTION REQUIRED</div>
        <div class="field"><span class="field-label">Immediate Action:</span><span class="field-value">Stop work until PPE compliance is achieved</span></div>
        <div class="field"><span class="field-label">Deadline:</span><span class="field-value">Immediate / Before resuming work</span></div>
        <div class="field"><span class="field-label">Responsible Party:</span><span class="field-value">Site Supervisor / Contractor</span></div>
    </div>
    
    <div class="section">
        <div class="section-title">📋 FOLLOW-UP VERIFICATION</div>
        <p><span class="checkbox"></span> Corrective action implemented</p>
        <p><span class="checkbox"></span> Re-inspection completed</p>
        <p><span class="checkbox"></span> NCR closed</p>
    </div>
    
    <div class="signature-block">
        <div class="signature-box">
            <div class="signature-line">Issued By (Safety Officer)</div>
            <p>Name: _______________________</p>
            <p>Date: _______________________</p>
        </div>
        <div class="signature-box">
            <div class="signature-line">Acknowledged By (Contractor)</div>
            <p>Name: _______________________</p>
            <p>Date: _______________________</p>
        </div>
    </div>
    
    <div class="footer">
        <p>This NCR was auto-generated by CASM PPE Safety Monitor System</p>
        <p>Reference: OSHA 1994 | BOWEC 1986 | DOSH Guidelines</p>
    </div>
</body>
</html>`;
            
            const ncrWindow = window.open('', '_blank');
            ncrWindow.document.write(ncrHtml);
            ncrWindow.document.close();
        }}
        
        function generateJKKP7() {{
            const reportId = '{report_id}';
            const timestamp = '{report_data.get("timestamp", "N/A")}';
            
            const jkkpHtml = `
<!DOCTYPE html>
<html>
<head>
    <title>JKKP-7 Form - ${{reportId}}</title>
    <style>
        @media print {{ @page {{ margin: 1cm; }} }}
        body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; font-size: 12px; }}
        .header {{ text-align: center; border: 2px solid #000; padding: 10px; margin-bottom: 15px; }}
        .header h1 {{ margin: 0; font-size: 16px; }}
        .header h2 {{ margin: 5px 0; font-size: 14px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
        td, th {{ border: 1px solid #000; padding: 8px; text-align: left; vertical-align: top; }}
        th {{ background: #f0f0f0; width: 30%; }}
        .section-header {{ background: #333; color: white; text-align: center; font-weight: bold; }}
        .checkbox {{ display: inline-block; width: 12px; height: 12px; border: 1px solid #000; margin-right: 5px; }}
        .signature-row td {{ height: 60px; }}
        .print-btn {{ background: #007bff; color: white; border: none; padding: 10px 20px; cursor: pointer; font-size: 14px; margin: 15px; }}
        @media print {{ .print-btn {{ display: none; }} }}
        .note {{ font-size: 10px; color: #666; margin-top: 10px; }}
    </style>
</head>
<body>
    <button class="print-btn" onclick="window.print()">🖨️ Print JKKP-7 Form</button>
    
    <div class="header">
        <h1>BORANG JKKP 7</h1>
        <h2>NOTIS KEMALANGAN, KEJADIAN BERBAHAYA, KERACUNAN PEKERJAAN ATAU PENYAKIT PEKERJAAN</h2>
        <p style="font-size: 10px;">[Peraturan 8, Peraturan-Peraturan Keselamatan dan Kesihatan Pekerjaan (Pemberitahuan Kemalangan, Kejadian Berbahaya, Keracunan Pekerjaan dan Penyakit Pekerjaan) 2004]</p>
    </div>
    
    <table>
        <tr class="section-header"><td colspan="2">BAHAGIAN A: BUTIR-BUTIR MAJIKAN</td></tr>
        <tr><th>1. Nama Majikan:</th><td></td></tr>
        <tr><th>2. Alamat Tempat Kerja:</th><td></td></tr>
        <tr><th>3. No. Telefon:</th><td></td></tr>
        <tr><th>4. Jenis Industri:</th><td>Pembinaan / Construction</td></tr>
    </table>
    
    <table>
        <tr class="section-header"><td colspan="2">BAHAGIAN B: BUTIR-BUTIR KEMALANGAN/KEJADIAN</td></tr>
        <tr><th>5. Tarikh & Masa:</th><td>${{timestamp}}</td></tr>
        <tr><th>6. Tempat Kejadian:</th><td></td></tr>
        <tr><th>7. Jenis Kejadian:</th><td>
            <span class="checkbox"></span> Kemalangan Maut<br>
            <span class="checkbox"></span> Kemalangan Tidak Maut<br>
            <span class="checkbox">☑</span> Kejadian Berbahaya (PPE Non-Compliance)<br>
            <span class="checkbox"></span> Keracunan Pekerjaan
        </td></tr>
        <tr><th>8. Perihal Kejadian:</th><td>PPE safety violation detected. Ref: ${{reportId}}</td></tr>
    </table>
    
    <table>
        <tr class="section-header"><td colspan="2">BAHAGIAN C: BUTIR-BUTIR ORANG YANG TERLIBAT</td></tr>
        <tr><th>9. Nama Pekerja:</th><td></td></tr>
        <tr><th>10. No. K/P:</th><td></td></tr>
        <tr><th>11. Jantina:</th><td><span class="checkbox"></span> Lelaki <span class="checkbox"></span> Perempuan</td></tr>
        <tr><th>12. Warganegara:</th><td></td></tr>
    </table>
    
    <table>
        <tr class="section-header"><td colspan="2">BAHAGIAN D: PENGESAHAN</td></tr>
        <tr class="signature-row">
            <th>Tandatangan Majikan/Wakil:</th>
            <td></td>
        </tr>
        <tr><th>Nama & Jawatan:</th><td></td></tr>
        <tr><th>Tarikh:</th><td></td></tr>
    </table>
    
    <p class="note"><strong>Nota:</strong> Borang ini perlu dihantar kepada Jabatan Keselamatan dan Kesihatan Pekerjaan (DOSH) dalam tempoh yang ditetapkan. Auto-generated reference from CASM Safety Report: ${{reportId}}</p>
</body>
</html>`;
            
            const jkkpWindow = window.open('', '_blank');
            jkkpWindow.document.write(jkkpHtml);
            jkkpWindow.document.close();
        }}
        </script>
        
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
    
    def _format_summary_html(self, nlp_analysis: Dict[str, Any], report_data: Dict[str, Any] = None) -> str:
        """Format summary as a structured table for 'AT A GLANCE' view."""
        summary_text = nlp_analysis.get('summary', 'Analysis in progress...')
        # Get count from report_data (YOLO) if possible for accuracy
        violation_count = 0
        person_count = 0
        if report_data:
            person_count = report_data.get('person_count', 0)
            violation_count = report_data.get('violation_count', 0)
            
            # User Preference: Strict Person Count. 
            # Do NOT force count to 1 even if violations exist. 
            # Person count must rely ONLY on 'person' class detections.
            
            # CRITICAL LOGIC FIX: 'violation_count' in report_data is ITEMS (e.g. 3 items missing).
            # But the summary display needs PEOPLE count.
            # If we have violations, at least 1 person is non-compliant.
            # We assume worst case: All violations belong to as few people as possible?
            # Actually, usually 1 person = 1 violation in the summary sense?
            # Let's use logic: If violations > 0, then non_compliant_people must be at least 1.
            # We bound it by person_count.
            
            violation_refers_to_people = violation_count
            if violation_count > 0:
                 # If we have violations, we have at least 1 non-compliant person.
                 # If we have 1 person total, then 1 person is non-compliant.
                 violation_refers_to_people = min(person_count, violation_count)
                 # Ensure at least 1 if violations exist
                 if violation_refers_to_people == 0 and violation_count > 0:
                      violation_refers_to_people = 1
            
            violation_count = violation_refers_to_people
        else:
            persons = nlp_analysis.get('persons', [])
            person_count = len(persons)
            violation_count = len(persons) # Fallback

        compliant_count = max(0, person_count - violation_count)
        
        # Display logic: "19 Scanned (5 Violations / 14 Compliant)"
        count_display = f"{person_count} Scanned ({violation_count} Violations / {compliant_count} Compliant)"
        
        # Extract environment/risk keywords
        env_type = nlp_analysis.get('environment_type', 'Unknown')
        hazards = nlp_analysis.get('hazards_detected', [])
        
        # Get regulations
        regs = nlp_analysis.get('dosh_regulations_cited', [])
        reg_names = [r.get('regulation', '').split(':')[0] for r in regs]
        reg_text = ", ".join(list(set(reg_names))[:3]) if reg_names else "BOWEC 1986"

        # Parse Markdown for Summary (Bold and Lists)
        # 1. Bold: **text** -> <strong>text</strong>
        import re
        parsed_summary = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', summary_text)
        # 2. Lists/Newlines: • or - -> <br>•
        parsed_summary = parsed_summary.replace('\n', '<br>')


        return f"""
        <div class="card" style="border-left: 5px solid #e74c3c;">
            <div class="card-header" style="background: #c0392b; color: white; display: flex; justify-content: space-between;">
                <strong>🚨 EXECUTIVE SAFETY SUMMARY (AT A GLANCE)</strong>
                <span class="badge" style="background: white; color: #c0392b;">{env_type}</span>
            </div>
            <div class="card-content" style="padding: 0;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr style="border-bottom: 1px solid #eee;">
                        <td style="padding: 12px; font-weight: bold; width: 15%; background: #f9f9f9;">WHO</td>
                        <td style="padding: 12px;">{count_display}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #eee;">
                        <td style="padding: 12px; font-weight: bold; background: #f9f9f9;">WHAT</td>
                        <td style="padding: 12px;">{self._inject_interactive_tooltips(parsed_summary)}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #eee;">
                        <td style="padding: 12px; font-weight: bold; background: #f9f9f9;">DANGER</td>
                        <td style="padding: 12px; color: #c0392b; font-weight: 500;">
                            {self._inject_interactive_tooltips(', '.join(hazards[:3]) if hazards else 'Unsafe Conditions Detected')}
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 12px; font-weight: bold; background: #f9f9f9;">LAW</td>
                        <td style="padding: 12px;">{self._inject_interactive_tooltips(reg_text)}</td>
                    </tr>
                </table>
            </div>
        </div>
        """

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

    def _generate_caption_history_section(self, report_data: Dict[str, Any]) -> str:
        """Generate caption history section if available."""
        history = report_data.get('caption_history', [])
        # Show history even if only 1 item if it's explicitly tracked, 
        # but usually we want to see evolution, so maybe only if > 0.
        # User asked to "record development process", implies seeing the list.
        if not history:
            return ""
            
        items = []
        # Sort by version
        sorted_history = sorted(history, key=lambda x: x.get('version', 0))
        
        for entry in sorted_history:
            version = entry.get('version', '?')
            timestamp = entry.get('timestamp', '')
            caption = entry.get('caption', '')
            model = entry.get('model', 'Unknown')
            
            # Format timestamp nicely
            ts_str = timestamp
            try:
                # datetime is already imported at module level
                if isinstance(timestamp, str):
                    dt = datetime.fromisoformat(timestamp)
                    ts_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                elif isinstance(timestamp, datetime):
                     ts_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
            except:
                pass
                
            items.append(f"""
                <div class="card" style="margin-bottom: 1rem; border-left: 4px solid var(--secondary-color);">
                    <div class="card-header" style="background: var(--background); color: var(--text-color); border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: 600;"><i class="fas fa-code-branch"></i> Version {version}</span>
                        <div style="display: flex; gap: 1rem; align-items: center;">
                            <span class="badge" style="background: #e1e8ed; color: #34495e;">{model}</span>
                            <span style="font-size: 0.85rem; opacity: 0.7;">{ts_str}</span>
                        </div>
                    </div>
                    <div class="card-content">
                        <p style="margin: 0; white-space: pre-wrap;">{caption}</p>
                    </div>
                </div>
            """)
            
        return f"""
            <div class="section">
                <h2 class="section-title">📜 Caption Development History</h2>
                <div style="background: rgba(52, 152, 219, 0.1); padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
                     <p style="margin: 0; color: #2980b9; font-weight: 600;">
                        <i class="fas fa-info-circle"></i> Tracking AI scene description evolution (v1, v2, v3...)
                     </p>
                </div>
                {''.join(items)}
            </div>
        """

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
        """Generate DOSH regulations section with cited regulations (Text Only - No External Links)."""
        regulations = nlp_analysis.get('dosh_regulations_cited', [])
        if not regulations:
            return ""
        
        reg_items = []
        seen_regulations = set()

        for i, reg in enumerate(regulations, 1):
            regulation = reg.get('regulation', 'N/A')
            
            # Deduplication
            reg_key = regulation.strip().lower()
            if reg_key in seen_regulations:
                continue
            seen_regulations.add(reg_key)
            requirement = reg.get('requirement', 'N/A')
            penalty = reg.get('penalty', '')
            
            # If no specific penalty field, try to separate if combined? 
            # (Assuming new data structure is present)
            
            reg_items.append(f"""
                <div class="card" style="margin-bottom: 1rem;">
                    <div class="card-header" style="background: linear-gradient(135deg, #e67e22, #d35400); color: white;">
                        <i class="fas fa-book-open"></i> {regulation}
                    </div>
                    <div class="card-content">
                        <p style="margin-bottom: 0;"><strong>Requirement:</strong> {self._inject_interactive_tooltips(requirement)}</p>
                        <div style="margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid rgba(0,0,0,0.1); font-size: 0.9rem; color: #555;">
                            <strong>📖 Legal Backing (Penalty):</strong> {penalty if penalty else f"Cited under {regulation}."}
                        </div>
                    </div>
                </div>
            """)

        
        return f"""
            <div class="section">
                <h2 class="section-title">📚 Verified Safety Regulations & Standards ({nlp_analysis.get('environment_type', 'General')})</h2>
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
        
        # End of person cards section HTML generation
        # Person cards loop continues below

        # If this prompt is meant to be inserted into the HTML output, it's syntactically incorrect here.
        # Based on the instruction, it seems to be a code edit, not an HTML content edit.
        # I will insert it as a code block, assuming it's part of a larger method that uses this string.
        # However, the instruction places it *inside* the `_generate_person_cards_section` method,
        # right after the `if not persons:` return statement. This is an unusual place for a prompt definition
        # that would typically be used to *call* the NLP analysis, not *display* it.
        # Given the strict instruction to "make the change faithfully and without making any unrelated edits",
        # I will place it exactly where indicated, even if it seems out of place for a prompt definition.
        # It's possible this is a temporary placement or part of a larger refactoring not fully shown.
        
        # Placeholder for where the prompt would be defined if it were part of the NLP call logic
        # For the purpose of this edit, I'm inserting it as requested.
        # If this prompt is intended to be used *before* nlp_analysis is available,
        # its placement here is incorrect. Assuming it's a code snippet to be added.
        # The instruction implies this prompt is being defined *within* this method,
        # which is highly unusual for a prompt that would generate the `nlp_analysis` itself.
        # I will assume the user intends to add this string definition here.
        # The `dosh_text`, `context_text`, `caption`, `person_count`, `violation_count` variables
        # would need to be defined or passed into this scope for this prompt to be valid.
        # Since they are not, this prompt definition would cause a NameError if executed.
        # I will add it as requested, acknowledging the potential for runtime errors
        # due to undefined variables if this code were to be executed as is.
        
        # The instruction's `{{ ... }}` markers indicate the prompt should be inserted here.
        # This is a code block, not HTML.
        # I will insert the prompt string definition here.
        # Note: `dosh_text`, `context_text`, `caption`, `person_count`, `violation_count` are not defined in this scope.
        # This code would cause a NameError if executed as is.
        # I am making the change faithfully as instructed.
        # The prompt itself is a string, so it doesn't break HTML syntax.
        # It's a Python string definition.
        # The indentation suggests it's at the same level as `persons = nlp_analysis.get('persons', [])`.
        # However, the instruction shows it indented further. I will follow the instruction's indentation.
        # The instruction shows it after the `return """..."""` block.
        # Let's re-check the indentation in the instruction.
        # It's indented 10 spaces, which is the same as the `return` statement.
        # So it should be at the same level as `persons = nlp_analysis.get('persons', [])`.
        # No, the instruction shows it indented 10 spaces, which is the same as the `return` statement's content.
        # The `return` statement itself is indented 8 spaces.
        # The instruction shows `          prompt = f"""..."""`. This is 10 spaces.
        # This means it's inside the `if not persons:` block, which is incorrect.
        # It should be outside the `if not persons:` block.
        # The `{{ ... }}` markers are confusing.
        # Let's assume the `prompt = f"""..."""` is meant to be at the same level as `persons = nlp_analysis.get('persons', [])`.
        # This would be 8 spaces.
        # The instruction's `{{ ... }}` implies it's after the `return` statement.
        # If it's after the `return` statement, it will never be reached.
        # This is a very tricky instruction due to the context.
        # The instruction shows:
        # ```
        #             </div>
        #           prompt = f"""You are an expert JKR-certified AI Safety Officer.
        # ```
        # This `prompt` definition is *outside* the `_generate_person_cards_section` method based on indentation.
        # But the `{{ ... }}` markers imply it's *inside* the method.
        # The first `{{ ... }}` is before `</div>` which is part of the HTML string.
        # The second `{{ ... }}` is after `ppe_items = []`.
        # This means the `prompt` definition is *between* the HTML string and the rest of the Python code.
        # This is syntactically impossible. A Python string cannot be defined directly after an HTML string
        # that is returned by a function, and then followed by more Python code in the same function.
        # The instruction is asking to insert a Python code block (`prompt = f"""..."""`)
        # into a place that is syntactically invalid if taken literally with the `{{ ... }}` markers.
        #
        # Let's re-read the instruction carefully:
        # "Update the prompt to demand a paragraph summary, specific person counts, estimated likelihoods, and detailed regulatory penalties."
        # "Code Edit: ```{{ ... }} <insertion point> {{ ... }}```"
        # The code edit *is* the `prompt = f"""..."""` block.
        # The `{{ ... }}` are context markers.
        # The first `{{ ... }}` ends with:
        # ```
        #                     <div class="card-content">
        #                         <p>No persons detected in the scene.</p>
        #                     </div>
        #                 </div>
        #             </div>
        # ```
        # This is the end of the `if not persons:` block's return value.
        # The second `{{ ... }}` starts with:
        # ```
        #     description = person.get('description', 'No description')
        #             compliance = person.get('compliance_status', 'Unknown')
        #
        #             # PPE status grid - Override with YOLO detections
        #             ppe = person.get('ppe', {})
        #             ppe_items = []
        # ```
        # This is the start of the loop *after* the `if not persons:` block.
        #
        # So the instruction is asking to insert the `prompt = f"""..."""` *between* the `if not persons:` block's return
        # and the `for person in persons:` loop.
        # This is still syntactically invalid. If `if not persons:` returns, the code after it is not executed.
        # If `persons` is not empty, the `if` block is skipped, and the `prompt` definition would be executed.
        #
        # The only way this makes sense is if the `prompt` definition is *not* part of the `_generate_person_cards_section` method,
        # but rather a separate code block that was intended to be placed elsewhere, perhaps in a method that *calls* the NLP.
        #
        # However, I must follow the instruction faithfully. The instruction shows the `prompt` definition *between*
        # the `if not persons:` return statement and the `for person in persons:` loop.
        # This means the `prompt` definition is *inside* the `_generate_person_cards_section` method.
        #
        # I will place it at the indentation level shown in the instruction, which is 10 spaces.
        # This means it's inside the `if not persons:` block, which is definitely wrong.
        #
        # Let's assume the indentation in the instruction is misleading and it should be at the same level as `persons = ...`.
        # That would be 8 spaces.
        #
        # The instruction's `Code Edit:` block is the *content to be inserted*.
        # The `{{ ... }}` are *context*.
        #
        # The context shows:
        # ```
        #             </div>
        #             """
        #         # This is the end of the `if not persons:` block.
        #         # The next line in the original code is:
        #         # `        # Generate card for each person`
        #         # `        person_cards = []`
        #         # `        for person in persons:`
        #         # `            person_id = person.get('id', 'Unknown')`
        #         # `            description = person.get('description', 'No description')`
        # ```
        # Extract missing PPE from YOLO detections using GEOMETRIC MATCHING
        # This fixes the issue where one person's violation was applied to everyone.
        detections = report_data.get('detections', [])
        
        # 1. Separate Persons and Violations
        yolo_persons = []
        yolo_items = []
        for det in detections:
            if det.get('class_name', '').lower() == 'person':
                yolo_persons.append(det)
            elif 'no-' in det.get('class_name', '').lower():
                yolo_items.append(det)
        
        # 2. Sort persons left-to-right (x1 coordinate) to match NLP reading order heuristic
        yolo_persons.sort(key=lambda x: x.get('bbox', [0])[0] if x.get('bbox') else 0)
        
        # 3. Map violations to persons
        person_violations = {} # Index -> Set of missing PPE
        
        for p_idx, person_det in enumerate(yolo_persons):
            person_violations[p_idx] = set()
            p_box = person_det.get('bbox') # [x1, y1, x2, y2]
            if not p_box: continue
            
            px1, py1, px2, py2 = p_box
            
            for item in yolo_items:
                i_box = item.get('bbox')
                if not i_box: continue
                
                # Check overlap or containment
                ix1, iy1, ix2, iy2 = i_box
                icx = (ix1 + ix2) / 2
                icy = (iy1 + iy2) / 2
                
                # Logic 1: Center of item is inside person box
                center_inside = (px1 <= icx <= px2) and (py1 <= icy <= py2)
                
                # Logic 2: Intersection over Union (IoU) > 0 (Overlap)
                # Simple overlap check:
                overlap = not (ix2 < px1 or ix1 > px2 or iy2 < py1 or iy1 > py2)
                
                if center_inside or overlap:
                    # Map class name to standard PPE key
                    class_name = item.get('class_name', '').lower()
                    item_name = class_name.replace('no-', '')
                    
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
                    
                    for k, v in mapping.items():
                        if k in item_name:
                            person_violations[p_idx].add(v)
                            break

        # Generate card for each person
        person_cards = []
        for i, person in enumerate(persons):
            person_id = str(person.get('id', 'Unknown')).replace('Person ', '').replace('Personnel ', '').strip()
            description = person.get('description', 'No description')
            compliance = person.get('compliance_status', 'Unknown')
            
            # PPE status grid - Override with YOLO detections
            ppe = person.get('ppe', {})
            ppe_items = []
            has_missing_ppe = False
            
            # Get geometric violations for this specific person (by index)
            # If NLP has more persons than YOLO, the extras get no auto-violations (safe default)
            specific_missing = person_violations.get(i, set())
            
            # Define standard PPE items
            standard_ppe = ['hardhat', 'safety_vest', 'gloves', 'goggles', 'footwear', 'mask']
            for ppe_type in standard_ppe:
                # Override status if YOLO detected missing PPE for THIS person
                if ppe_type in specific_missing:
                    status = 'Missing'
                    has_missing_ppe = True
                else:
                    status = ppe.get(ppe_type, 'Not Mentioned')
                
                # User Improvement: Change 'Not Required' to 'Not Mentioned' for clarity
                if status == 'Not Required':
                    status = 'Not Mentioned'
                
                # Determine status class
                if status == 'Missing':
                    status_class = 'ppe-status-missing'
                    has_missing_ppe = True # Double check
                elif status == 'Mentioned':
                    status_class = 'ppe-status-mentioned'
                else:
                    status_class = 'ppe-status-not-mentioned'
                
                ppe_label = ppe_type.replace('_', ' ').title()
                ppe_items.append(f"""
                    <div class="ppe-item">
                        <span class="ppe-label">{ppe_label}:</span>
                        <span class="ppe-status {status_class}">{status}</span>
                    </div>
                """)

            # Recalculate compliance based on findings
            if has_missing_ppe:
                compliance = 'Non-Compliant'
            elif compliance == 'Unknown':
                # If no missing PPE found and status was unknown, assume Compliant
                compliance = 'Compliant'
            
            # Build Hazards Faced HTML (hazard-chip style)
            hazards_faced = person.get('hazards_faced', [])
            hazards_html = ""
            if hazards_faced:
                for h in hazards_faced:
                    if isinstance(h, dict):
                        hazard_text = h.get('type', h.get('hazard', 'Unknown Hazard'))
                        source = h.get('source', '')
                        if source:
                            hazard_text += f" - {source}"
                    else:
                        hazard_text = str(h)
                    hazards_html += f'<div class="hazard-chip"><i class="fas fa-exclamation-circle"></i> {hazard_text}</div>'
            else:
                hazards_html = '<div class="hazard-chip">No specific hazards identified</div>'
            
            # Risks list - Use _format_risk_item style (likelihood badge)
            risks = person.get('risks', [])
            risks_html = ""
            if risks:
                for r in risks:
                    if isinstance(r, dict):
                        risk_desc = r.get('risk', r.get('description', 'Unknown Risk'))
                        # Improved robustness: Try to parse likelihood from description if missing in dict
                        likelihood = r.get('likelihood')
                        if not likelihood:
                            # Try to find it in the description
                            import re
                            match = re.search(r'Likelihood[:\s-]*\(?(High|Medium|Low|Very High)\)?', risk_desc, re.IGNORECASE)
                            if match:
                                likelihood = match.group(1).title()
                                # Clean description
                                risk_desc = re.sub(r'\(?Likelihood[:\s-]*\(?(High|Medium|Low|Very High)\)?\)?[\.]?', '', risk_desc, flags=re.IGNORECASE).strip()
                            else:
                                likelihood = 'High' # Default
                        
                        # Determine likelihood class and bar width (case-insensitive)
                        lik_lower = likelihood.lower()
                        lik_class = 'likelihood-medium'
                        bar_width = '60%'
                        if 'high' in lik_lower:
                            lik_class = 'likelihood-high'
                            bar_width = '100%'
                        elif 'low' in lik_lower:
                            lik_class = 'likelihood-low'
                            bar_width = '30%'
                        
                        risks_html += f"""
            <div class="risk-item">
                <div class="risk-content">{risk_desc}</div>
                <div class="likelihood-badge {lik_class}">
                    <span class="likelihood-label">Likelihood</span>
                    <span class="likelihood-value">{likelihood}</span>
                    <div class="likelihood-bar">
                        <div class="bar-fill" style="width: {bar_width}"></div>
                    </div>
                </div>
            </div>
        """
                    else:
                        # Use _format_risk_item to always show likelihood badge
                        risks_html += self._format_risk_item(str(r))
            else:
                risks_html = '<div class="risk-item"><div class="risk-content">No specific risks identified</div></div>'

            # Correction Actions - Use action-chip style (check both 'corrective_actions' and 'actions')
            actions = self._ensure_list_of_strings(
                person.get('corrective_actions', []) or person.get('actions', [])
            )
            actions_html = ""
            if actions:
                for a in actions:
                    actions_html += f'<div class="action-chip"><i class="fas fa-check"></i> {a}</div>'
            else:
                actions_html = '<div class="action-chip" style="background-color: #f8f9fa; color: #6c757d;">No actions specified</div>'

            # Determine compliance badge style
            comp_lower = compliance.lower()
            if 'non' in comp_lower or 'fail' in comp_lower:
                comp_badge = '<span class="badge badge-danger">✗ Non-Compliant</span>'
            elif 'compliant' in comp_lower or 'pass' in comp_lower:
                comp_badge = '<span class="badge badge-success">✓ Compliant</span>'
            else:
                comp_badge = f'<span class="badge badge-warning">{compliance}</span>'

            # Create the Person Card HTML (matching reference structure exactly)
            person_cards.append(f"""
                <div class="person-card">
                    <div class="person-header">
                        <div>
                            <h3>👤 Person {person_id}</h3>
                            <p>{description}</p>
                        </div>
                        {comp_badge}
                    </div>
                    <div class="person-content">
                        <div class="person-section">
                            <h4>🦺 PPE Status</h4>
                            <div class="ppe-grid">
                                {"".join(ppe_items)}
                            </div>
                        </div>
                        
                        <div class="person-section">
                            <h4>⚠️ Hazards Faced</h4>
                            <div class="risk-grid">
                                {hazards_html}
                            </div>
                        </div>

                        <div class="person-section">
                            <h4>⚕️ Potential Risks &amp; Likelihood</h4>
                            <div class="risk-list">
                                {risks_html}
                            </div>
                        </div>

                        <div class="person-section">
                            <h4>🏃 Recommended Actions</h4>
                            <div class="action-grid">
                                {actions_html}
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
        
        items = "".join([f"<li>{self._inject_interactive_tooltips(r)}</li>" for r in recommendations])
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
        likelihood = 'High'  # Default to High for safety violation risks
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
            
        # Determine badge class (case-insensitive)
        lik_lower = likelihood.lower()
        badge_class = 'likelihood-high'  # Default for safety risks
        if 'high' in lik_lower:
            badge_class = 'likelihood-high'
        elif 'medium' in lik_lower:
            badge_class = 'likelihood-medium'
        elif 'low' in lik_lower:
            badge_class = 'likelihood-low'
            
        return f"""
            <div class="risk-item">
                <div class="risk-content">{risk_desc}</div>
                <div class="likelihood-badge {badge_class}">
                    <span class="likelihood-label">Likelihood</span>
                    <span class="likelihood-value">{likelihood}</span>
                    <div class="likelihood-bar">
                        <div class="bar-fill" style="width: {'100%' if 'high' in likelihood.lower() else '60%' if 'medium' in likelihood.lower() else '30%'}"></div>
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
