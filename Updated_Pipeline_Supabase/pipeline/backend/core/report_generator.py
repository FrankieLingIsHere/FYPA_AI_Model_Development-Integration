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
import os
import html
import requests
import threading
import time
import re
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
        self.last_nlp_error = None
        self.last_nlp_provider = None
        self.last_nlp_model = None
        self.last_nlp_fallback_reason = None
        self.last_nlp_completed_at = None
        self.sticky_nlp_provider = None
        self.sticky_nlp_provider_until_epoch = 0.0
        self.last_gemini_budget_block_reason = None
        self.strict_report_generation = os.getenv('STRICT_REPORT_GENERATION', 'true').lower() == 'true'
        self.gemini_schema_regen_attempts = int(os.getenv('GEMINI_SCHEMA_REGEN_ATTEMPTS', '1') or 1)
        self.sticky_nlp_provider_enabled = os.getenv('STICKY_NLP_PROVIDER_ENABLED', 'true').lower() in ('1', 'true', 'yes', 'on')
        self.sticky_nlp_provider_ttl_seconds = int(os.getenv('STICKY_NLP_PROVIDER_TTL_SECONDS', '900') or 900)

        # Gemini spend guardrails (all USD values; set to 0 to disable a limit)
        self.gemini_daily_budget_usd = float(os.getenv('GEMINI_DAILY_BUDGET_USD', '0') or 0)
        self.gemini_monthly_budget_usd = float(os.getenv('GEMINI_MONTHLY_BUDGET_USD', '0') or 0)
        self.gemini_cost_per_1m_input_tokens = float(os.getenv('GEMINI_COST_PER_1M_INPUT_TOKENS', '0.30') or 0.30)
        self.gemini_cost_per_1m_output_tokens = float(os.getenv('GEMINI_COST_PER_1M_OUTPUT_TOKENS', '2.50') or 2.50)
        self.gemini_est_output_tokens_per_report = int(os.getenv('GEMINI_EST_OUTPUT_TOKENS_PER_REPORT', '900') or 900)
        self.gemini_max_output_tokens_per_report = int(os.getenv('GEMINI_MAX_OUTPUT_TOKENS_PER_REPORT', '900') or 900)
        self.gemini_budget_state_path = Path(
            os.getenv(
                'GEMINI_BUDGET_STATE_PATH',
                str(Path(__file__).resolve().parents[3] / 'pipeline' / 'backend' / 'data' / 'gemini_budget_state.json')
            )
        )
        self._gemini_budget_lock = threading.Lock()
        self._gemini_budget_state = self._load_gemini_budget_state()
        
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
                    if self.gemini_max_output_tokens_per_report > 0:
                        self.gemini_client.max_tokens = min(
                            self.gemini_client.max_tokens,
                            self.gemini_max_output_tokens_per_report
                        )
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
        self.embeddings_url = ollama_config.get('embeddings_url', 'http://localhost:11434/api/embeddings')
        self.model = ollama_config.get('model', 'llama3')
        self.temperature = ollama_config.get('temperature', 0.7)
        self.ollama_timeout = ollama_config.get('timeout', 600)

        # =====================================================================
        # MODEL API ROUTING (primary when configured)
        # =====================================================================
        model_api_config = config.get('MODEL_API_CONFIG', {})
        self.model_api_enabled = model_api_config.get('enabled', False)
        self.nlp_provider_order = model_api_config.get(
            'nlp_provider_order', ['model_api', 'gemini', 'ollama', 'local']
        )
        self.embedding_provider_order = model_api_config.get(
            'embedding_provider_order', ['model_api', 'ollama']
        )

        self.nlp_api_url = model_api_config.get('nlp_api_url', '')
        self.nlp_api_key = model_api_config.get('nlp_api_key', '')
        self.nlp_model = model_api_config.get('nlp_model', self.model)

        self.embedding_api_url = model_api_config.get('embedding_api_url', '')
        self.embedding_api_key = model_api_config.get('embedding_api_key', '')
        self.embedding_api_model = model_api_config.get('embedding_model', 'nomic-ai/nomic-embed-text-v1.5')
        
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
        
        ai_provider = ' -> '.join(self.nlp_provider_order)
        logger.info(f"Report Generator initialized (NLP provider order: {ai_provider})")

    def get_runtime_provider_diagnostics(self) -> Dict[str, Any]:
        """Expose NLP routing runtime details for operator visibility."""
        with self._gemini_budget_lock:
            self._rotate_gemini_budget_windows_locked()
            state = dict(self._gemini_budget_state)

        budget_enabled = self.gemini_daily_budget_usd > 0 or self.gemini_monthly_budget_usd > 0
        return {
            'provider_order': list(self.nlp_provider_order or []),
            'last_provider': self.last_nlp_provider,
            'last_model': self.last_nlp_model,
            'last_error': self.last_nlp_error,
            'last_fallback_reason': self.last_nlp_fallback_reason,
            'last_completed_at': self.last_nlp_completed_at,
            'sticky_provider': self.sticky_nlp_provider,
            'sticky_provider_remaining_s': max(0, int(self.sticky_nlp_provider_until_epoch - time.time())),
            'gemini_budget': {
                'enabled': budget_enabled,
                'daily_limit_usd': self.gemini_daily_budget_usd,
                'monthly_limit_usd': self.gemini_monthly_budget_usd,
                'daily_spend_usd': round(float(state.get('daily_spend_usd', 0.0) or 0.0), 6),
                'monthly_spend_usd': round(float(state.get('monthly_spend_usd', 0.0) or 0.0), 6),
                'daily_calls': int(state.get('daily_calls', 0) or 0),
                'monthly_calls': int(state.get('monthly_calls', 0) or 0),
                'last_block_reason': self.last_gemini_budget_block_reason,
                'enforced_max_output_tokens': self.gemini_max_output_tokens_per_report,
            },
        }

    def _utc_day_key(self, now: Optional[datetime] = None) -> str:
        dt = now or datetime.utcnow()
        return dt.strftime('%Y-%m-%d')

    def _utc_month_key(self, now: Optional[datetime] = None) -> str:
        dt = now or datetime.utcnow()
        return dt.strftime('%Y-%m')

    def _default_gemini_budget_state(self) -> Dict[str, Any]:
        return {
            'day_key': self._utc_day_key(),
            'month_key': self._utc_month_key(),
            'daily_spend_usd': 0.0,
            'monthly_spend_usd': 0.0,
            'daily_calls': 0,
            'monthly_calls': 0,
            'updated_at': datetime.utcnow().isoformat() + 'Z',
        }

    def _load_gemini_budget_state(self) -> Dict[str, Any]:
        state = self._default_gemini_budget_state()
        try:
            if self.gemini_budget_state_path.exists():
                loaded = json.loads(self.gemini_budget_state_path.read_text(encoding='utf-8'))
                if isinstance(loaded, dict):
                    state.update(loaded)
        except Exception as e:
            logger.warning(f"Could not load Gemini budget state: {e}")
        return state

    def _save_gemini_budget_state_locked(self):
        try:
            self.gemini_budget_state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = dict(self._gemini_budget_state)
            payload['updated_at'] = datetime.utcnow().isoformat() + 'Z'
            tmp_path = self.gemini_budget_state_path.with_suffix('.tmp')
            tmp_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
            tmp_path.replace(self.gemini_budget_state_path)
        except Exception as e:
            logger.warning(f"Could not persist Gemini budget state: {e}")

    def _rotate_gemini_budget_windows_locked(self):
        current_day = self._utc_day_key()
        current_month = self._utc_month_key()
        changed = False

        if self._gemini_budget_state.get('day_key') != current_day:
            self._gemini_budget_state['day_key'] = current_day
            self._gemini_budget_state['daily_spend_usd'] = 0.0
            self._gemini_budget_state['daily_calls'] = 0
            changed = True

        if self._gemini_budget_state.get('month_key') != current_month:
            self._gemini_budget_state['month_key'] = current_month
            self._gemini_budget_state['monthly_spend_usd'] = 0.0
            self._gemini_budget_state['monthly_calls'] = 0
            changed = True

        if changed:
            self._save_gemini_budget_state_locked()

    def _estimate_text_tokens(self, text: str) -> int:
        # Simple approximation: ~4 chars/token for English text.
        return max(1, int(len(text or '') / 4))

    def _estimate_gemini_call_cost_usd(self, prompt: str) -> Tuple[float, int, int]:
        input_tokens = self._estimate_text_tokens(prompt)
        output_tokens = max(1, int(self.gemini_est_output_tokens_per_report))
        in_cost = (input_tokens / 1_000_000.0) * self.gemini_cost_per_1m_input_tokens
        out_cost = (output_tokens / 1_000_000.0) * self.gemini_cost_per_1m_output_tokens
        return in_cost + out_cost, input_tokens, output_tokens

    def _can_spend_gemini_budget(self, estimated_cost_usd: float) -> Tuple[bool, Optional[str]]:
        if estimated_cost_usd <= 0:
            return True, None

        with self._gemini_budget_lock:
            self._rotate_gemini_budget_windows_locked()
            day_spend = float(self._gemini_budget_state.get('daily_spend_usd', 0.0) or 0.0)
            month_spend = float(self._gemini_budget_state.get('monthly_spend_usd', 0.0) or 0.0)

            if self.gemini_daily_budget_usd > 0 and day_spend + estimated_cost_usd > self.gemini_daily_budget_usd:
                reason = (
                    f"Gemini daily budget guardrail hit ({day_spend:.4f}/{self.gemini_daily_budget_usd:.4f} USD used). "
                    "Falling back to next provider."
                )
                self.last_gemini_budget_block_reason = reason
                return False, reason

            if self.gemini_monthly_budget_usd > 0 and month_spend + estimated_cost_usd > self.gemini_monthly_budget_usd:
                reason = (
                    f"Gemini monthly budget guardrail hit ({month_spend:.4f}/{self.gemini_monthly_budget_usd:.4f} USD used). "
                    "Falling back to next provider."
                )
                self.last_gemini_budget_block_reason = reason
                return False, reason

        return True, None

    def _record_gemini_spend(self, estimated_cost_usd: float):
        if estimated_cost_usd <= 0:
            return
        with self._gemini_budget_lock:
            self._rotate_gemini_budget_windows_locked()
            self._gemini_budget_state['daily_spend_usd'] = float(self._gemini_budget_state.get('daily_spend_usd', 0.0) or 0.0) + estimated_cost_usd
            self._gemini_budget_state['monthly_spend_usd'] = float(self._gemini_budget_state.get('monthly_spend_usd', 0.0) or 0.0) + estimated_cost_usd
            self._gemini_budget_state['daily_calls'] = int(self._gemini_budget_state.get('daily_calls', 0) or 0) + 1
            self._gemini_budget_state['monthly_calls'] = int(self._gemini_budget_state.get('monthly_calls', 0) or 0) + 1
            self._save_gemini_budget_state_locked()

    def _normalize_openai_base_url(self, raw_url: str, endpoint_suffix: str) -> str:
        """Normalize OpenAI-compatible base URL so callers can pass either base URL or full endpoint."""
        if not raw_url:
            return ''
        url = raw_url.rstrip('/')
        if url.endswith(endpoint_suffix):
            return url
        if url.endswith('/v1'):
            return f"{url}{endpoint_suffix}"
        return f"{url}/v1{endpoint_suffix}"

    def _build_auth_headers(self, api_key: str) -> Dict[str, str]:
        """Build headers for provider API calls."""
        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f"Bearer {api_key}"
        return headers

    def _call_model_api_nlp(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Call a model-specific cloud API (OpenAI-compatible chat/completions) for NLP JSON output."""
        if not self.model_api_enabled:
            return None
        if not self.nlp_api_url or not self.nlp_model:
            return None

        endpoint = self._normalize_openai_base_url(self.nlp_api_url, '/chat/completions')

        try:
            response = requests.post(
                endpoint,
                headers=self._build_auth_headers(self.nlp_api_key),
                json={
                    'model': self.nlp_model,
                    'messages': [
                        {
                            'role': 'user',
                            'content': prompt
                        }
                    ],
                    'temperature': self.temperature,
                    'max_tokens': 1600,
                    'response_format': {'type': 'json_object'}
                },
                timeout=self.ollama_timeout
            )

            if not response.ok:
                logger.warning(f"Model API NLP call failed: {response.status_code}")
                return None

            data = response.json()
            choices = data.get('choices', [])
            if not choices:
                logger.warning("Model API NLP returned no choices")
                return None

            content = choices[0].get('message', {}).get('content', '')
            if not content:
                logger.warning("Model API NLP returned empty content")
                return None

            return json.loads(content)

        except Exception as e:
            logger.warning(f"Model API NLP error: {e}")
            return None

    def _get_model_api_embeddings(self, text: str) -> Optional[List[float]]:
        """Call a model-specific cloud API (OpenAI-compatible embeddings) for vector search."""
        if not self.model_api_enabled:
            return None
        if not self.embedding_api_url or not self.embedding_api_model:
            return None

        endpoint = self._normalize_openai_base_url(self.embedding_api_url, '/embeddings')

        try:
            response = requests.post(
                endpoint,
                headers=self._build_auth_headers(self.embedding_api_key),
                json={
                    'model': self.embedding_api_model,
                    'input': text
                },
                timeout=45
            )

            if not response.ok:
                logger.warning(f"Model API embeddings call failed: {response.status_code}")
                return None

            data = response.json()
            vectors = data.get('data', [])
            if not vectors:
                return None
            return vectors[0].get('embedding')

        except Exception as e:
            logger.warning(f"Model API embeddings error: {e}")
            return None
    
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
        if os.getenv('DISABLE_OLLAMA_EMBEDDINGS', 'false').lower() == 'true':
            logger.info("Skipping Ollama embeddings because DISABLE_OLLAMA_EMBEDDINGS=true")
            return None

        # Try model-specific cloud embedding API first (if enabled)
        for provider in self.embedding_provider_order:
            if provider == 'model_api':
                cloud_embedding = self._get_model_api_embeddings(text)
                if cloud_embedding:
                    return cloud_embedding

        try:
            response = requests.post(
                self.embeddings_url,
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
    - For each risk, include the most relevant regulation citation from official JKR/DOSH standards in context.
    - Do NOT limit citations to PPE-only rules; include non-PPE breaches (e.g., traffic control, fall protection, unsafe stacking, excavation controls) when evidenced by caption/detections.
3. **WEIGHTED SEVERITY**:
   - Boost severity to "CRITICAL" if the missing PPE is lethal for that scene.
4. **NEGATIVE CONSTRAINTS**:
   - NO vague terms ("scattered", "some").
   - NO "Chemical masks" unless chemicals visible.
   - NO "1." numbering prefixes in the description text.
    - ONLY cite regulations from the provided JKR/DOSH regulation context. Do not invent regulation titles.

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
                    "regulation_citation": "Most relevant official regulation for this risk (PPE or non-PPE)", 
                    "legal_regulatory_consequences": "Consequence" 
                 }}
            ]
        }}
    ],
    "summary": "• **SCENE CLASS**: [Environment Type]...\\n• **CRITICAL RISK**: ...\\n• **LEGAL ORDER**: ...",
    "dosh_regulations_cited": [
        {{ "regulation": "Official JKR/DOSH regulation name", "requirement": "Specific breached requirement in this scene" }}
    ]
}}
"""
        
        return prompt
    
    def _call_gemini_api(self, prompt: str, image_path: str = None, report_id: str = None) -> Optional[Dict[str, Any]]:
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
            result = self.gemini_client.generate_report_json(prompt, image_path=image_path, report_id=report_id)
            
            if result:
                missing_fields = self._missing_required_nlp_fields(result)
                if missing_fields:
                    logger.warning(
                        "Gemini NLP output missing required fields %s for report %s; attempting schema regeneration",
                        missing_fields,
                        report_id or 'unknown',
                    )

                    regen_prompt = self._build_schema_regen_prompt(prompt, missing_fields)
                    attempts = max(0, self.gemini_schema_regen_attempts)
                    repaired_result = None
                    repaired_missing = list(missing_fields)

                    for attempt_idx in range(attempts):
                        candidate = self.gemini_client.generate_report_json(
                            regen_prompt,
                            image_path=image_path,
                            report_id=report_id,
                        )
                        if not candidate:
                            continue

                        candidate_missing = self._missing_required_nlp_fields(candidate)
                        if not candidate_missing:
                            repaired_result = candidate
                            repaired_missing = []
                            logger.info(
                                "Gemini schema regeneration succeeded on attempt %s for report %s",
                                attempt_idx + 1,
                                report_id or 'unknown',
                            )
                            break

                        repaired_missing = candidate_missing

                    if repaired_result is not None:
                        result = repaired_result
                    else:
                        detail = (
                            "Gemini output missing required fields after regeneration: "
                            + ", ".join(repaired_missing)
                        )
                        self.last_nlp_error = detail
                        logger.warning(detail)
                        return None

                logger.info("✓ Gemini NLP analysis completed")
                self.last_nlp_error = None
                return result
            else:
                detail = getattr(self.gemini_client, 'last_error', None) or 'Gemini returned no valid JSON'
                self.last_nlp_error = detail
                logger.warning(f"Gemini NLP failed: {detail}")
                return None
                
        except Exception as e:
            self.last_nlp_error = f"Gemini API error: {e}"
            logger.error(f"Gemini API error: {e}")
            return None

    def _missing_required_nlp_fields(self, nlp_analysis: Optional[Dict[str, Any]]) -> List[str]:
        """Return list of missing/empty required NLP fields for strict schema gating."""
        if not isinstance(nlp_analysis, dict):
            return ['environment_type', 'visual_evidence', 'persons', 'summary', 'dosh_regulations_cited']

        missing = []
        if not str(nlp_analysis.get('environment_type', '') or '').strip():
            missing.append('environment_type')
        if not str(nlp_analysis.get('visual_evidence', '') or '').strip():
            missing.append('visual_evidence')
        if not isinstance(nlp_analysis.get('persons'), list) or len(nlp_analysis.get('persons', [])) == 0:
            missing.append('persons')
        if not str(nlp_analysis.get('summary', '') or '').strip():
            missing.append('summary')
        if not isinstance(nlp_analysis.get('dosh_regulations_cited'), list) or len(nlp_analysis.get('dosh_regulations_cited', [])) == 0:
            missing.append('dosh_regulations_cited')
        return missing

    def _build_schema_regen_prompt(self, prompt: str, missing_fields: List[str]) -> str:
        """Append strict schema reminder to force required fields in regenerated output."""
        fields_text = ', '.join(missing_fields)
        return (
            str(prompt or '')
            + "\n\nSCHEMA REGENERATION REQUIREMENT:\n"
            + f"Your previous response was missing required fields: {fields_text}.\n"
            + "Return exactly one valid JSON object with ALL required fields present and non-empty:\n"
            + "environment_type, visual_evidence, persons, summary, dosh_regulations_cited.\n"
            + "No markdown fences. No extra text."
        )
    
    def _call_ollama_api(self, prompt: str, allow_local_fallback: bool = True) -> Optional[Dict[str, Any]]:
        """
        Call Ollama API or use local Llama to get NLP analysis (fallback).
        
        Args:
            prompt: Prompt to send to Ollama/Llama
        
        Returns:
            Parsed JSON response or None if failed
        """
        # Try local Llama first if available
        if allow_local_fallback and self.local_llama is not None:
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
        
        # Try NLP providers in configured order.
        image_path = report_data.get('original_image_path')
        image_path_str = str(image_path) if image_path else None

        self.last_nlp_error = None
        self.last_nlp_provider = None
        self.last_nlp_model = None
        self.last_nlp_fallback_reason = None
        self.last_gemini_budget_block_reason = None

        effective_provider_order = list(self.nlp_provider_order or [])
        sticky_active = (
            self.sticky_nlp_provider_enabled
            and self.sticky_nlp_provider
            and self.sticky_nlp_provider_until_epoch > time.time()
            and self.sticky_nlp_provider in effective_provider_order
        )
        if sticky_active:
            effective_provider_order = [
                self.sticky_nlp_provider,
                *[p for p in effective_provider_order if p != self.sticky_nlp_provider]
            ]

        for provider in effective_provider_order:
            if nlp_analysis:
                break

            provider_name = provider.strip().lower()
            if provider_name == 'model_api':
                logger.info("Trying model-specific cloud NLP API...")
                nlp_analysis = self._call_model_api_nlp(prompt)
                self.last_nlp_model = self.nlp_model
                if not nlp_analysis:
                    self.last_nlp_error = self.last_nlp_error or 'model_api did not return valid NLP JSON'
            elif provider_name == 'gemini':
                if self.use_gemini:
                    est_cost, _, _ = self._estimate_gemini_call_cost_usd(prompt)
                    allowed, guardrail_reason = self._can_spend_gemini_budget(est_cost)
                    if not allowed:
                        logger.warning(guardrail_reason)
                        self.last_nlp_error = guardrail_reason
                        self.last_nlp_fallback_reason = guardrail_reason
                        continue

                    logger.info("Trying Gemini NLP API...")
                    nlp_analysis = self._call_gemini_api(
                        prompt,
                        image_path=image_path_str,
                        report_id=str(report_data.get('report_id') or ''),
                    )
                    if self.gemini_client is not None:
                        self.last_nlp_model = getattr(self.gemini_client, 'model_name', None)
                    if not nlp_analysis:
                        self.last_nlp_error = self.last_nlp_error or 'Gemini NLP provider failed'
                    else:
                        self._record_gemini_spend(est_cost)
            elif provider_name == 'ollama':
                logger.info("Trying Ollama NLP API...")
                nlp_analysis = self._call_ollama_api(prompt, allow_local_fallback=False)
                self.last_nlp_model = self.model
                if not nlp_analysis:
                    self.last_nlp_error = self.last_nlp_error or 'Ollama NLP provider failed'
            elif provider_name == 'local':
                logger.info("Trying local Llama fallback...")
                nlp_analysis = self._call_ollama_api(prompt, allow_local_fallback=True)
                self.last_nlp_model = self.model if self.local_llama is None else 'local-llama'
                if not nlp_analysis:
                    self.last_nlp_error = self.last_nlp_error or 'Local NLP provider failed'

            if nlp_analysis:
                self.last_nlp_provider = provider_name
                self.last_nlp_fallback_reason = None
                self.last_nlp_completed_at = datetime.utcnow().isoformat() + 'Z'
                if self.sticky_nlp_provider_enabled:
                    self.sticky_nlp_provider = provider_name
                    self.sticky_nlp_provider_until_epoch = time.time() + max(30, self.sticky_nlp_provider_ttl_seconds)
                logger.info(f"NLP analysis succeeded with provider: {provider_name}")
                break
        
        if not nlp_analysis:
            detail = self.last_nlp_error or 'NLP analysis failed with no provider detail'
            allow_fallback = str(os.getenv('ALLOW_NLP_FALLBACK', 'true')).strip().lower() in ('1', 'true', 'yes', 'on')
            if self.strict_report_generation and not allow_fallback:
                raise RuntimeError(f"NLP analysis failed: {detail}")
            logger.warning(f"NLP analysis failed ({detail}), using fallback")
            nlp_analysis = self._generate_fallback_analysis(report_data)
            self.last_nlp_provider = 'fallback'
            self.last_nlp_model = 'rule-based-fallback'
            self.last_nlp_fallback_reason = detail
            self.last_nlp_completed_at = datetime.utcnow().isoformat() + 'Z'
        else:
            # Model-first policy: only patch critical missing fields, avoid broad deterministic overrides.
            detections = report_data.get('detections', [])
            has_violations = any(d.get('class_name', '').startswith('NO-') for d in detections)

            fallback = None
            if has_violations:
                needs_persons = not isinstance(nlp_analysis.get('persons'), list) or len(nlp_analysis.get('persons', [])) == 0
                needs_regulation = not isinstance(nlp_analysis.get('dosh_regulations_cited'), list) or len(nlp_analysis.get('dosh_regulations_cited', [])) == 0
                needs_environment = not str(nlp_analysis.get('environment_type', '')).strip()

                if needs_persons or needs_regulation or needs_environment:
                    fallback = self._generate_fallback_analysis(report_data)

                if needs_regulation and fallback is not None:
                    logger.info("NLP output missing regulation citations; injecting fallback citations only")
                    nlp_analysis['dosh_regulations_cited'] = fallback.get('dosh_regulations_cited', [])

                if needs_environment and fallback is not None:
                    caption = report_data.get('caption', '')
                    detected_env = self._extract_environment_from_caption(caption)
                    nlp_analysis['environment_type'] = detected_env if detected_env else fallback.get('environment_type', 'General Workspace')

                if needs_persons and fallback is not None:
                    logger.warning("NLP output missing persons; injecting fallback person entries")
                    nlp_analysis['persons'] = fallback.get('persons', [])

        if isinstance(nlp_analysis, dict):
            if self.last_nlp_provider and not nlp_analysis.get('provider'):
                nlp_analysis['provider'] = self.last_nlp_provider
            if self.last_nlp_model and not nlp_analysis.get('model'):
                nlp_analysis['model'] = self.last_nlp_model

        # Normalize structure once so all sections (including hidden expanded parts)
        # consume consistent model-aligned data shapes.
        raw_nlp_analysis = json.loads(json.dumps(nlp_analysis)) if isinstance(nlp_analysis, (dict, list)) else nlp_analysis
        nlp_analysis = self._sanitize_nlp_analysis(nlp_analysis)

        caption_for_quality = str(report_data.get('caption', '') or '').strip()
        visual_evidence = str(nlp_analysis.get('visual_evidence', '') or '').strip()
        generic_markers = (
            'person is visible',
            'people are visible',
            'indoor environment',
            'outdoor environment',
        )
        should_rebuild_visual_evidence = (
            not visual_evidence
            or len(visual_evidence) < 120
            or any(marker in visual_evidence.lower() for marker in generic_markers)
        )
        if not should_rebuild_visual_evidence and caption_for_quality:
            # If model scene text is long but semantically unrelated to caption, rebuild from caption+detections.
            if not self._has_grounding_overlap(visual_evidence, caption_for_quality, min_overlap=3, min_ratio=0.08):
                should_rebuild_visual_evidence = True

        if should_rebuild_visual_evidence and caption_for_quality:
            rebuilt = self._build_scene_description(
                caption_for_quality,
                nlp_analysis.get('environment_type', 'General Workspace'),
                report_data.get('detections', []),
            )
            if rebuilt and len(rebuilt) > len(visual_evidence):
                nlp_analysis['visual_evidence'] = rebuilt

        summary_text = str(nlp_analysis.get('summary', '') or '').strip()
        violation_summary_text = str(report_data.get('violation_summary', '') or '').strip()
        detection_terms = ' '.join(
            str(d.get('class_name') or d.get('class') or '').replace('NO-', 'No ')
            for d in (report_data.get('detections', []) or [])
            if isinstance(d, dict)
        )
        grounding_reference = ' '.join(
            part for part in [
                caption_for_quality,
                str(nlp_analysis.get('visual_evidence', '') or '').strip(),
                violation_summary_text,
                detection_terms,
            ] if part
        )

        if summary_text and not self._has_grounding_overlap(summary_text, grounding_reference, min_overlap=2, min_ratio=0.08):
            logger.warning(
                "NLP summary appears ungrounded for report %s; replacing with grounded summary",
                report_data.get('report_id')
            )
            nlp_analysis['summary'] = self._build_grounded_summary_text(report_data, nlp_analysis)

        nlp_integrity = self._build_nlp_integrity_snapshot(raw_nlp_analysis, nlp_analysis)


        
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
            'nlp_analysis': nlp_analysis,
            'nlp_analysis_raw': raw_nlp_analysis,
            'nlp_integrity': nlp_integrity,
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

        def _add_violation_signal(key: str, ppe_field: Optional[str] = None) -> None:
            data = VIOLATION_DATA.get(key)
            if not data:
                return
            if ppe_field:
                ppe_status[ppe_field] = 'Missing'
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
        
        for v in violations:
            v_lower = v.lower().replace('no-', '')
            for key in VIOLATION_DATA:
                if key.replace(' ', '') in v_lower.replace(' ', '') or key in v_lower:
                    ppe_field = key.replace(' ', '_')
                    _add_violation_signal(key, ppe_field=ppe_field)
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
        has_work_height = any(kw in caption_lower for kw in ['scaffold', 'ladder', 'roof', 'height', 'elevated', 'platform'])

        # Add non-PPE regulatory signals from scene context when evidenced.
        if has_roadside:
            _add_violation_signal('roadside_risk')
        if has_piles and has_slope:
            _add_violation_signal('unsecured_piles')
        if has_work_height and 'NO-Harness' in violations:
            _add_violation_signal('harness', ppe_field='harness')
        
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
        timestamp_raw = report_data.get('timestamp', datetime.now())
        timestamp = timestamp_raw
        if isinstance(timestamp_raw, str):
            try:
                timestamp = datetime.fromisoformat(timestamp_raw.replace('Z', '+00:00'))
            except Exception:
                timestamp = datetime.now()
        elif not isinstance(timestamp_raw, datetime):
            timestamp = datetime.now()

        timestamp_display = timestamp.strftime('%Y-%m-%d %H:%M:%S')

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
        safe_report_id_js = json.dumps(str(report_id))
        safe_timestamp_js = json.dumps(str(report_data.get('timestamp', 'N/A')))
        safe_environment_js = json.dumps(str(nlp_analysis.get('environment_type', 'Construction Site')))
        safe_severity_js = json.dumps(str(nlp_analysis.get('severity_level', 'HIGH')))
        safe_summary_js = json.dumps(str(nlp_analysis.get('summary', 'PPE violation detected')))

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

        .likelihood-low {{
             background-color: #d1ecf1;
             color: #0c5460;
             border-color: #bee5eb;
        }}
        .likelihood-low .bar-fill {{
            background-color: #17a2b8;
        }}
        
        .risk-grid, .action-grid {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
        }}

        .report-split-card {{
            border: 1px solid var(--border-color);
            border-radius: 12px;
            background: #ffffff;
            overflow: hidden;
        }}

        .report-split-top,
        .report-split-bottom {{
            transition: transform 0.22s ease;
        }}

        .report-split-middle {{
            max-height: 0;
            overflow: hidden;
            opacity: 0;
            transform: scaleY(0.94);
            transform-origin: top center;
            transition: max-height 0.24s ease, opacity 0.18s ease, transform 0.24s ease;
            border-top: 1px solid transparent;
        }}

        .report-split-card.expanded .report-split-top {{
            transform: translateY(-6px);
        }}

        .report-split-card.expanded .report-split-bottom {{
            transform: translateY(6px);
        }}

        .report-split-card.expanded .report-split-middle {{
            max-height: 9000px;
            opacity: 1;
            transform: scaleY(1);
            border-top-color: var(--border-color);
        }}

        .report-expand-toggle-wrap {{
            padding: 1rem 0 0;
            display: flex;
            justify-content: center;
        }}

        .report-expand-toggle {{
            background: linear-gradient(135deg, #1f2937, #374151);
            color: #ffffff;
            border: none;
            border-radius: 999px;
            padding: 0.65rem 1.25rem;
            font-weight: 600;
            cursor: pointer;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.18);
        }}

        .report-expand-toggle:hover {{
            filter: brightness(1.06);
        }}

        @media (max-width: 768px) {{
            .grid {{
                grid-template-columns: 1fr;
            }}

            .content {{
                padding: 1rem;
            }}

            .report-split-card.expanded .report-split-top,
            .report-split-card.expanded .report-split-bottom {{
                transform: none;
            }}
        }}

        @media (max-width: 560px), (max-height: 430px) and (orientation: landscape) {{
            body {{
                padding: 0.6rem;
                line-height: 1.45;
            }}

            .header {{
                padding: 1rem;
            }}

            .header h1 {{
                font-size: 1.35rem;
            }}

            .content {{
                padding: 0.75rem;
            }}

            .section {{
                margin-bottom: 1rem;
            }}

            .section-title {{
                font-size: 1.05rem;
            }}

            .info-item {{
                flex-direction: column;
                align-items: flex-start;
                gap: 0.25rem;
            }}

            .info-label {{
                min-width: 0;
            }}

            .person-header {{
                padding: 1rem;
                flex-direction: column;
                align-items: flex-start;
                gap: 0.4rem;
            }}

            .person-content {{
                padding: 1rem;
                gap: 0.9rem;
            }}

            .ppe-grid {{
                grid-template-columns: 1fr;
            }}

            .report-expand-toggle {{
                width: 100%;
                max-width: 100%;
            }}
        }}

        @media (prefers-reduced-motion: reduce) {{
            .report-split-top,
            .report-split-bottom,
            .report-split-middle {{
                transition: none;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚠️ PPE Safety Violation Report</h1>
            <p class="report-id">Report ID: {report_id}</p>
            <p>Generated: {timestamp_display}</p>
        </div>
        
        <div class="content">
            <div id="reportSplitCard" class="report-split-card">
                <div class="report-split-top">
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
                                <span class="info-value">{timestamp_display}</span>
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
                                <p>{nlp_analysis.get('visual_evidence') or report_data.get('caption') or 'No description available'}</p>
                            </div>
                        </div>
                    </div>

                    <!-- NLP Analysis -->
                    <div class="section" style="margin-bottom: 1rem;">
                        <h2 class="section-title">📊 Safety Analysis</h2>

                        <div class="environment-badge">
                            <span>🏗️</span>
                            <span>Environment: {nlp_analysis.get('environment_type', 'Unknown')}</span>
                        </div>

                        <div class="card">
                            <div class="card-header">Summary</div>
                            <div class="card-content">
                                {self._format_summary_html(nlp_analysis, report_data)}
                                {f"<p style='margin-top: 1rem; font-style: italic; color: #7f8c8d;'>{nlp_analysis.get('environment_assessment', '')}</p>" if nlp_analysis.get('environment_assessment') else ''}
                            </div>
                        </div>
                    </div>
                </div>

                <div class="report-split-middle" id="reportExpandedContext" aria-hidden="true">
                    <!-- DOSH Regulations -->
                    {self._generate_dosh_regulations_section(nlp_analysis)}

                    <!-- Individual Person Analysis -->
                    {self._generate_person_cards_section(nlp_analysis, report_data)}

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
                </div>

                <div class="report-split-bottom">
                    <div class="report-expand-toggle-wrap">
                        <button id="reportExpandToggle" class="report-expand-toggle" type="button" aria-expanded="false" aria-controls="reportExpandedContext">
                            Show Full Report Context
                        </button>
                    </div>
                </div>
            </div>
        </div>
        
        <script>
        function generateNCR() {{
            const reportId = {safe_report_id_js};
            const timestamp = {safe_timestamp_js};
            const environment = {safe_environment_js};
            const severity = {safe_severity_js};
            const summary = {safe_summary_js};
            
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
            const reportId = {safe_report_id_js};
            const timestamp = {safe_timestamp_js};
            
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

        (function initReportExpandToggle() {{
            const splitCard = document.getElementById('reportSplitCard');
            const toggle = document.getElementById('reportExpandToggle');
            const expandedContext = document.getElementById('reportExpandedContext');

            if (!splitCard || !toggle || !expandedContext) return;

            const setExpanded = (expanded) => {{
                splitCard.classList.toggle('expanded', expanded);
                toggle.setAttribute('aria-expanded', String(expanded));
                expandedContext.setAttribute('aria-hidden', String(!expanded));
                toggle.textContent = expanded ? 'Collapse Full Report Context' : 'Show Full Report Context';
            }};

            setExpanded(false);
            toggle.addEventListener('click', () => setExpanded(!splitCard.classList.contains('expanded')));
        }})();
        </script>
        
        <div class="footer">
            <p>CASM PPE Safety Monitor - FYPA AI Model Development & Integration</p>
            <p style="font-size: 0.9rem; opacity: 0.8; margin-top: 0.5rem;">
                Powered by YOLO PPE Detection • Local + Cloud AI Routing • Supabase-backed Report Pipeline
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
        import re

        summary_text = str(nlp_analysis.get('summary') or '').strip()
        persons = nlp_analysis.get('persons', [])
        if not isinstance(persons, list):
            persons = []

        report_data = report_data or {}
        violation_summary = str(report_data.get('violation_summary') or '').strip()
        caption_text = str(report_data.get('caption') or '').strip()
        visual_evidence_text = str(nlp_analysis.get('visual_evidence') or '').strip()

        placeholder_markers = (
            'analysis in progress',
            'no summary available',
            'summary unavailable',
            'not enough information',
            'pending analysis',
            'processing',
        )

        def _is_meaningful_summary(text: str) -> bool:
            clean = str(text or '').strip()
            if len(clean) < 24:
                return False
            lower = clean.lower()
            return not any(marker in lower for marker in placeholder_markers)

        def _clean_sentence(text: str, max_len: int = 190) -> str:
            clean = re.sub(r'\s+', ' ', str(text or '')).strip()
            if not clean:
                return ''
            first = re.split(r'(?<=[.!?])\s+', clean)[0].strip()
            if not first:
                first = clean
            if len(first) <= max_len:
                return first
            return first[: max_len - 3].rstrip(' ,;') + '...'

        # WHO should reflect model output first; detector stats are context only.
        model_person_rows: List[str] = []
        model_non_compliant_count = 0
        detected_missing_labels: List[str] = []

        for idx, person in enumerate(persons):
            if not isinstance(person, dict):
                continue

            person_id = str(person.get('id') or f'Person {idx + 1}').strip()
            person_desc = str(person.get('description') or '').strip()

            ppe = person.get('ppe', {})
            missing_items: List[str] = []
            if isinstance(ppe, dict):
                for item_name, status in ppe.items():
                    status_text = str(status or '').strip().lower()
                    if 'missing' in status_text or status_text.startswith('no '):
                        pretty_item = str(item_name).replace('_', ' ').strip().title()
                        missing_items.append(pretty_item)
                        if pretty_item and pretty_item not in detected_missing_labels:
                            detected_missing_labels.append(pretty_item)

            hazards = person.get('hazards_faced', [])
            risks = person.get('risks', [])
            has_risk_signal = bool(missing_items) or bool(hazards) or bool(risks)
            if has_risk_signal:
                model_non_compliant_count += 1

            if missing_items:
                detail = f"missing {', '.join(missing_items[:3])}"
                if len(missing_items) > 3:
                    detail += f" +{len(missing_items) - 3} more"
            elif person_desc:
                detail = person_desc.split('. ')[0]
            else:
                detail = 'PPE/risk observation recorded by model'

            model_person_rows.append(f"• {person_id}: {detail}")

        model_person_count = len(model_person_rows)

        detected_person_count = int((report_data or {}).get('person_count', 0) or 0)
        detected_violation_items = int((report_data or {}).get('violation_count', 0) or 0)

        def _infer_people_count_from_text(*texts: str) -> int:
            combined = " ".join(str(t or "") for t in texts)
            lower = combined.lower()

            # Prefer explicit numeric phrases like "6 people".
            digit_hits = [
                int(m.group(1))
                for m in re.finditer(r"\b(\d{1,2})\s+(?:people|persons?|workers?|individuals?|men|women)\b", lower)
            ]

            number_words = {
                "one": 1,
                "two": 2,
                "three": 3,
                "four": 4,
                "five": 5,
                "six": 6,
                "seven": 7,
                "eight": 8,
                "nine": 9,
                "ten": 10,
                "eleven": 11,
                "twelve": 12,
            }
            word_hits = []
            for word, value in number_words.items():
                if re.search(rf"\b{word}\s+(?:people|persons?|workers?|individuals?|men|women)\b", lower):
                    word_hits.append(value)

            candidates = digit_hits + word_hits
            if candidates:
                return max(candidates)

            # Last-resort heuristic: count ordinal-person mentions (e.g., "first person", "second person").
            ordinal_hits = re.findall(
                r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+person\b",
                lower,
            )
            if ordinal_hits:
                return len(set(ordinal_hits))

            return 0

        inferred_person_count = 0
        if model_person_count == 0 and detected_person_count == 0:
            inferred_person_count = _infer_people_count_from_text(
                summary_text,
                visual_evidence_text,
                caption_text,
                violation_summary,
            )

        if model_person_count > 0:
            preview_rows = model_person_rows[:4]
            if model_person_count > 4:
                preview_rows.append(f"• +{model_person_count - 4} more model-identified person entries")

            who_header = (
                f"Model identified {model_person_count} person(s), "
                f"{model_non_compliant_count} with non-compliance signals."
            )
            detector_context = (
                f"Detector context: {detected_person_count} persons scanned, "
                f"{detected_violation_items} violation item(s)."
            )
            count_display = f"{who_header}<br>{'<br>'.join(preview_rows)}<br><span style='color:#7f8c8d;'>{detector_context}</span>"
        else:
            people_count_for_display = detected_person_count if detected_person_count > 0 else inferred_person_count
            compliant_count = max(
                0,
                people_count_for_display - min(people_count_for_display, detected_violation_items),
            )
            people_prefix = (
                f"{people_count_for_display} Scanned"
                if detected_person_count > 0
                else f"{people_count_for_display} Estimated From Scene Text"
            )
            count_display = (
                f"{people_prefix} "
                f"({detected_violation_items} Violation Items / {compliant_count} Compliant)"
            )

        # Derive additional missing PPE clues from detector summary/caption text.
        source_text = f"{violation_summary} {caption_text}".lower()
        missing_keyword_map = {
            'hard hat': 'Hard Hat',
            'hardhat': 'Hard Hat',
            'helmet': 'Helmet',
            'safety vest': 'Safety Vest',
            'high visibility vest': 'Safety Vest',
            'reflective vest': 'Safety Vest',
            'mask': 'Mask',
            'respirator': 'Respirator',
            'glove': 'Gloves',
            'goggle': 'Safety Goggles',
            'eye protection': 'Safety Goggles',
            'boot': 'Safety Boots',
        }
        for keyword, label in missing_keyword_map.items():
            if keyword in source_text and label not in detected_missing_labels:
                detected_missing_labels.append(label)

        # WHAT: use model summary when meaningful, otherwise synthesize from evidence.
        caption_lower = caption_text.lower()
        caption_safety_neutral = any(
            marker in caption_lower for marker in (
                'no immediate safety concerns',
                'no ppe is visible',
                'ppe visibility is not applicable',
            )
        )
        no_concrete_ppe_evidence = (
            len(detected_missing_labels) == 0
            and model_non_compliant_count == 0
            and detected_violation_items > 0
        )

        if _is_meaningful_summary(summary_text):
            what_text = summary_text
        else:
            if no_concrete_ppe_evidence and caption_safety_neutral:
                what_text = (
                    'No explicit PPE non-compliance could be confirmed from current visual evidence. '
                    'This event is flagged for manual review before enforcement action.'
                )
            elif detected_missing_labels:
                what_text = (
                    "PPE non-compliance detected involving missing "
                    + ", ".join(detected_missing_labels[:5])
                    + "."
                )
            elif violation_summary:
                what_text = _clean_sentence(violation_summary)
            else:
                what_text = "PPE non-compliance detected from analyzed scene evidence."

            context_sentence = _clean_sentence(visual_evidence_text or caption_text)
            if context_sentence:
                what_text += f" Scene context: {context_sentence}"
        
        # Extract environment/risk keywords
        env_type = nlp_analysis.get('environment_type', 'Unknown')
        hazards = self._ensure_list_of_strings(nlp_analysis.get('hazards_detected', []))
        
        # Get regulations
        regs = nlp_analysis.get('dosh_regulations_cited', [])
        reg_names = []
        if isinstance(regs, list):
            for entry in regs:
                if isinstance(entry, dict):
                    reg_name = str(entry.get('regulation') or entry.get('technical_standard') or '').strip()
                    if reg_name:
                        reg_names.append(reg_name)
                elif isinstance(entry, str):
                    clean_entry = entry.strip()
                    if clean_entry:
                        reg_names.append(clean_entry)
        elif isinstance(regs, str):
            reg_names = [item.strip() for item in re.split(r'[\n;]+', regs) if item.strip()]

        # Preserve order while removing duplicates.
        reg_names = list(dict.fromkeys(reg_names))
        hazard_items = [item.strip() for item in hazards if str(item).strip()]
        hazard_items = list(dict.fromkeys(hazard_items))

        if not hazard_items:
            inferred_hazards: List[str] = []
            risk_map = {
                'Hard Hat': 'Head injury risk from falling or struck-by objects',
                'Helmet': 'Head injury risk from falling or struck-by objects',
                'Safety Vest': 'Struck-by risk due to reduced worker visibility',
                'Mask': 'Respiratory exposure risk from dust or airborne contaminants',
                'Respirator': 'Respiratory exposure risk from hazardous airborne particles',
                'Gloves': 'Hand injury risk from abrasion, sharp edges, or tool contact',
                'Safety Goggles': 'Eye injury risk from dust, particles, or debris',
                'Safety Boots': 'Foot injury risk from impact, puncture, or slip hazards',
            }
            for item in detected_missing_labels:
                mapped = risk_map.get(item)
                if mapped and mapped not in inferred_hazards:
                    inferred_hazards.append(mapped)
            if inferred_hazards:
                hazard_items = inferred_hazards
            elif detected_violation_items > 0:
                hazard_items = ['Increased injury/exposure risk due to observed PPE non-compliance']

        if no_concrete_ppe_evidence and caption_safety_neutral:
            hazard_text = 'Manual verification required; no concrete PPE hazard could be confirmed from current evidence.'
        else:
            hazard_text = '<br>'.join(f"• {self._inject_interactive_tooltips(item)}" for item in hazard_items) if hazard_items else 'Unsafe conditions identified; detailed hazard profile unavailable'

        if not reg_names:
            inferred_regs: List[str] = []
            reg_map = {
                'Hard Hat': 'BOWEC 1986 (Safety Helmets) - Head protection in construction zones',
                'Helmet': 'BOWEC 1986 (Safety Helmets) - Head protection in construction zones',
                'Safety Vest': 'BOWEC 1986 (Visibility and site traffic safety requirements)',
                'Mask': 'USECHH Regulations 2000 - Respiratory protection for airborne hazards',
                'Respirator': 'USECHH Regulations 2000 - Respiratory protection for airborne hazards',
                'Gloves': 'OSHA 1994 Section 15 - Duty to provide suitable protective equipment',
                'Safety Goggles': 'OSHA 1994 Section 15 - Eye and face protection obligations',
                'Safety Boots': 'OSHA 1994 Section 15 - Foot protection obligations',
            }
            for item in detected_missing_labels:
                mapped = reg_map.get(item)
                if mapped and mapped not in inferred_regs:
                    inferred_regs.append(mapped)
            reg_names = inferred_regs or ['BOWEC 1986 - General PPE compliance requirements for construction operations']

        if no_concrete_ppe_evidence and caption_safety_neutral:
            reg_text = 'No specific citation asserted automatically pending manual verification of PPE non-compliance.'
        else:
            reg_text = '<br>'.join(f"• {self._inject_interactive_tooltips(name)}" for name in reg_names)

        # Parse Markdown for Summary (Bold and Lists)
        # 1. Bold: **text** -> <strong>text</strong>
        parsed_summary = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', what_text)
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
                        <td style="padding: 12px; white-space: normal; word-break: break-word;">{count_display}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #eee;">
                        <td style="padding: 12px; font-weight: bold; background: #f9f9f9;">WHAT</td>
                        <td style="padding: 12px; white-space: normal; word-break: break-word;">{self._inject_interactive_tooltips(parsed_summary)}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #eee;">
                        <td style="padding: 12px; font-weight: bold; background: #f9f9f9;">DANGER</td>
                        <td style="padding: 12px; color: #c0392b; font-weight: 500; white-space: normal; word-break: break-word;">
                            {hazard_text}
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 12px; font-weight: bold; background: #f9f9f9;">LAW</td>
                        <td style="padding: 12px; white-space: normal; word-break: break-word;">{reg_text}</td>
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

    def _sanitize_nlp_analysis(self, nlp_analysis: Any) -> Dict[str, Any]:
        """Normalize model output into a stable schema for robust rendering."""
        if not isinstance(nlp_analysis, dict):
            nlp_analysis = {}

        def _as_clean_str(value: Any) -> str:
            return str(value or '').strip()

        def _as_list(value: Any) -> List[Any]:
            if value is None:
                return []
            if isinstance(value, list):
                return value
            return [value]

        normalized: Dict[str, Any] = dict(nlp_analysis)
        normalized['summary'] = _as_clean_str(nlp_analysis.get('summary'))
        normalized['visual_evidence'] = _as_clean_str(nlp_analysis.get('visual_evidence'))
        normalized['environment_type'] = _as_clean_str(nlp_analysis.get('environment_type'))
        normalized['environment_assessment'] = _as_clean_str(nlp_analysis.get('environment_assessment'))
        normalized['hazards_detected'] = [
            _as_clean_str(item) for item in self._ensure_list_of_strings(nlp_analysis.get('hazards_detected', [])) if _as_clean_str(item)
        ]
        normalized['suggested_actions'] = [
            _as_clean_str(item) for item in self._ensure_list_of_strings(nlp_analysis.get('suggested_actions', [])) if _as_clean_str(item)
        ]

        # Regulations: list[dict|str] with consistent string fields.
        regs_out: List[Any] = []
        seen_regs = set()
        for reg in _as_list(nlp_analysis.get('dosh_regulations_cited', [])):
            if isinstance(reg, dict):
                reg_obj = {
                    'regulation': _as_clean_str(reg.get('regulation') or reg.get('technical_standard')),
                    'requirement': _as_clean_str(reg.get('requirement')),
                    'penalty': _as_clean_str(reg.get('penalty') or reg.get('legal_regulatory_consequences')),
                    'technical_standard': _as_clean_str(reg.get('technical_standard')),
                    'legal_regulatory_consequences': _as_clean_str(reg.get('legal_regulatory_consequences')),
                }
                reg_key = reg_obj['regulation'].lower()
                if reg_obj['regulation'] and reg_key not in seen_regs:
                    seen_regs.add(reg_key)
                    regs_out.append(reg_obj)
            else:
                reg_text = _as_clean_str(reg)
                reg_key = reg_text.lower()
                if reg_text and reg_key not in seen_regs:
                    seen_regs.add(reg_key)
                    regs_out.append(reg_text)
        normalized['dosh_regulations_cited'] = regs_out

        # Persons: enforce list[dict] and normalize nested structures used by hidden sections.
        persons_out: List[Dict[str, Any]] = []
        for idx, person in enumerate(_as_list(nlp_analysis.get('persons', []))):
            if not isinstance(person, dict):
                continue

            person_id = _as_clean_str(person.get('id')) or f'Person {idx + 1}'
            person_desc = _as_clean_str(person.get('description'))
            person_compliance = _as_clean_str(person.get('compliance_status'))

            ppe_obj: Dict[str, str] = {}
            ppe_raw = person.get('ppe', {})
            if isinstance(ppe_raw, dict):
                for key, value in ppe_raw.items():
                    key_str = _as_clean_str(key)
                    val_str = _as_clean_str(value)
                    if key_str and val_str:
                        ppe_obj[key_str] = val_str

            hazards_out: List[Any] = []
            for hazard in _as_list(person.get('hazards_faced', [])):
                if isinstance(hazard, dict):
                    hz_type = _as_clean_str(hazard.get('type') or hazard.get('hazard'))
                    hz_source = _as_clean_str(hazard.get('source'))
                    hz_severity = _as_clean_str(hazard.get('severity'))
                    if hz_type or hz_source or hz_severity:
                        hazards_out.append({
                            'type': hz_type,
                            'source': hz_source,
                            'severity': hz_severity,
                        })
                else:
                    hz_text = _as_clean_str(hazard)
                    if hz_text:
                        hazards_out.append(hz_text)

            risks_out: List[Any] = []
            for risk in _as_list(person.get('risks', [])):
                if isinstance(risk, dict):
                    risk_text = _as_clean_str(risk.get('risk') or risk.get('description'))
                    likelihood_text = _as_clean_str(risk.get('likelihood'))
                    if not likelihood_text:
                        risk_l = risk_text.lower()
                        if any(tok in risk_l for tok in ('fatal', 'death', 'catastrophic', 'severe', 'immediate')):
                            likelihood_text = 'High (inferred)'
                        elif any(tok in risk_l for tok in ('minor', 'unlikely', 'low probability')):
                            likelihood_text = 'Low (inferred)'
                        else:
                            likelihood_text = 'Medium (inferred)'
                    risk_obj = {
                        'risk': risk_text,
                        'likelihood': likelihood_text,
                        'regulation_citation': _as_clean_str(risk.get('regulation_citation')),
                        'legal_regulatory_consequences': _as_clean_str(risk.get('legal_regulatory_consequences')),
                    }
                    if any(risk_obj.values()):
                        risks_out.append(risk_obj)
                else:
                    risk_text = _as_clean_str(risk)
                    if risk_text:
                        risks_out.append(risk_text)

            actions_source = person.get('corrective_actions', []) or person.get('actions', [])
            actions_out = [_as_clean_str(a) for a in self._ensure_list_of_strings(actions_source) if _as_clean_str(a)]

            persons_out.append({
                'id': person_id,
                'description': person_desc,
                'compliance_status': person_compliance,
                'ppe': ppe_obj,
                'hazards_faced': hazards_out,
                'risks': risks_out,
                'corrective_actions': actions_out,
                'actions': actions_out,
            })

        normalized['persons'] = persons_out
        return normalized

    def _content_tokens(self, text: str) -> List[str]:
        """Extract lightweight content tokens for lexical grounding checks."""
        text = str(text or '').lower()
        if not text:
            return []

        tokens = re.findall(r'[a-z0-9]+', text)
        stopwords = {
            'the', 'and', 'with', 'from', 'this', 'that', 'were', 'was', 'are', 'for', 'into',
            'onto', 'over', 'under', 'near', 'then', 'than', 'have', 'has', 'had', 'into', 'while',
            'person', 'persons', 'worker', 'workers', 'scene', 'setting', 'report', 'analysis',
            'observed', 'detected', 'safety', 'risk', 'risks', 'hazard', 'hazards', 'summary', 'law',
            'what', 'who', 'danger', 'compliance', 'non', 'ppe'
        }
        return [tok for tok in tokens if len(tok) >= 3 and tok not in stopwords]

    def _has_grounding_overlap(
        self,
        candidate_text: str,
        reference_text: str,
        min_overlap: int = 2,
        min_ratio: float = 0.1,
    ) -> bool:
        """Check whether candidate text is grounded in reference evidence using token overlap."""
        candidate_tokens = set(self._content_tokens(candidate_text))
        reference_tokens = set(self._content_tokens(reference_text))

        if not candidate_tokens:
            return False
        if not reference_tokens:
            return True

        overlap = candidate_tokens & reference_tokens
        overlap_count = len(overlap)
        overlap_ratio = overlap_count / max(1, len(candidate_tokens))
        return overlap_count >= min_overlap or (overlap_count >= 1 and overlap_ratio >= min_ratio)

    def _build_grounded_summary_text(self, report_data: Dict[str, Any], nlp_analysis: Dict[str, Any]) -> str:
        """Build concise grounded summary when model summary is unrelated to visual evidence."""
        detections = report_data.get('detections', []) if isinstance(report_data.get('detections', []), list) else []
        missing_items: List[str] = []
        for det in detections:
            if not isinstance(det, dict):
                continue
            cls = str(det.get('class_name') or det.get('class') or '').strip()
            if cls.startswith('NO-'):
                pretty = cls.replace('NO-', '').replace('_', ' ').strip()
                if pretty and pretty not in missing_items:
                    missing_items.append(pretty)

        env = str(nlp_analysis.get('environment_type') or 'General Workspace').strip() or 'General Workspace'
        context_source = str(nlp_analysis.get('visual_evidence') or report_data.get('caption') or '').strip()
        context_sentence = ''
        if context_source:
            context_sentence = re.split(r'(?<=[.!?])\s+', context_source)[0].strip()
            if len(context_sentence) > 180:
                context_sentence = context_sentence[:177].rstrip(' ,;') + '...'

        if missing_items:
            issue_text = f"missing {', '.join(missing_items[:4])}"
            if len(missing_items) > 4:
                issue_text += f" (+{len(missing_items) - 4} more)"
        else:
            issue_text = str(report_data.get('violation_summary') or 'observed PPE non-compliance').strip()

        summary_parts = [
            f"• **SCENE CLASS**: {env}",
            f"• **CRITICAL OBSERVATION**: {issue_text}",
        ]
        if context_sentence:
            summary_parts.append(f"• **VISUAL CONTEXT**: {context_sentence}")
        summary_parts.append("• **LEGAL ORDER**: enforce compliant PPE before work resumes")
        return '\n'.join(summary_parts)

    def _build_nlp_integrity_snapshot(self, raw_nlp: Any, sanitized_nlp: Dict[str, Any]) -> Dict[str, Any]:
        """Build compact diagnostics comparing raw model payload and sanitized structure."""
        raw_dict = raw_nlp if isinstance(raw_nlp, dict) else {}
        sanitized_dict = sanitized_nlp if isinstance(sanitized_nlp, dict) else {}

        raw_keys = set(raw_dict.keys())
        sanitized_keys = set(sanitized_dict.keys())

        def _safe_len_list(value: Any) -> int:
            return len(value) if isinstance(value, list) else 0

        raw_person_count = _safe_len_list(raw_dict.get('persons'))
        sanitized_person_count = _safe_len_list(sanitized_dict.get('persons'))
        raw_reg_count = _safe_len_list(raw_dict.get('dosh_regulations_cited'))
        sanitized_reg_count = _safe_len_list(sanitized_dict.get('dosh_regulations_cited'))

        return {
            'sanitizer_version': 'v1',
            'raw_top_level_key_count': len(raw_keys),
            'sanitized_top_level_key_count': len(sanitized_keys),
            'dropped_top_level_keys': sorted(list(raw_keys - sanitized_keys)),
            'added_top_level_keys': sorted(list(sanitized_keys - raw_keys)),
            'raw_person_count': raw_person_count,
            'sanitized_person_count': sanitized_person_count,
            'raw_regulation_count': raw_reg_count,
            'sanitized_regulation_count': sanitized_reg_count,
            'person_count_delta': sanitized_person_count - raw_person_count,
            'regulation_count_delta': sanitized_reg_count - raw_reg_count,
            'summary_length_raw': len(str(raw_dict.get('summary') or '')),
            'summary_length_sanitized': len(str(sanitized_dict.get('summary') or '')),
            'visual_evidence_length_raw': len(str(raw_dict.get('visual_evidence') or '')),
            'visual_evidence_length_sanitized': len(str(sanitized_dict.get('visual_evidence') or '')),
        }

    def _to_safe_html_text(self, value: Any) -> str:
        """Escape user/model text for safe HTML rendering and preserve line breaks."""
        if value is None:
            return ""
        return html.escape(str(value), quote=True).replace('\n', '<br>')

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
                        <span style="font-weight: 600;"><i class="fas fa-code-branch"></i> Version {self._to_safe_html_text(version)}</span>
                        <div style="display: flex; gap: 1rem; align-items: center;">
                            <span class="badge" style="background: #e1e8ed; color: #34495e;">{self._to_safe_html_text(model)}</span>
                            <span style="font-size: 0.85rem; opacity: 0.7;">{self._to_safe_html_text(ts_str)}</span>
                        </div>
                    </div>
                    <div class="card-content">
                        <p style="margin: 0; white-space: pre-wrap; word-break: break-word;">{self._to_safe_html_text(caption)}</p>
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
        
        items = "".join([f"<li style=\"white-space: normal; word-break: break-word;\">{self._to_safe_html_text(h)}</li>" for h in hazards if str(h).strip()])
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
        regulations_raw = nlp_analysis.get('dosh_regulations_cited', [])
        if not regulations_raw:
            return ""

        regulations = regulations_raw if isinstance(regulations_raw, list) else [regulations_raw]
        
        reg_items = []
        seen_regulations = set()

        for reg in regulations:
            if isinstance(reg, dict):
                regulation = str(reg.get('regulation') or reg.get('technical_standard') or '').strip()
                requirement = str(reg.get('requirement') or '').strip()
                penalty = str(reg.get('penalty') or reg.get('legal_regulatory_consequences') or '').strip()
            else:
                regulation = str(reg).strip()
                requirement = ""
                penalty = ""

            if not regulation:
                continue
            
            # Deduplication
            reg_key = regulation.strip().lower()
            if reg_key in seen_regulations:
                continue
            seen_regulations.add(reg_key)

            safe_regulation = self._inject_interactive_tooltips(self._to_safe_html_text(regulation))
            safe_requirement = self._inject_interactive_tooltips(self._to_safe_html_text(requirement))
            safe_penalty = self._to_safe_html_text(penalty)
            
            reg_items.append(f"""
                <div class="card" style="margin-bottom: 1rem;">
                    <div class="card-header" style="background: linear-gradient(135deg, #e67e22, #d35400); color: white;">
                        <i class="fas fa-book-open"></i> {safe_regulation}
                    </div>
                    <div class="card-content">
                        {f'<p style="margin-bottom: 0; white-space: normal; word-break: break-word;"><strong>Requirement:</strong> {safe_requirement}</p>' if safe_requirement else ''}
                        {f'<div style="margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid rgba(0,0,0,0.1); font-size: 0.9rem; color: #555; white-space: normal; word-break: break-word;"><strong>📖 Legal Backing (Penalty):</strong> {safe_penalty}</div>' if safe_penalty else ''}
                    </div>
                </div>
            """)

        
        return f"""
            <div class="section">
                <h2 class="section-title">📚 Verified Safety Regulations & Standards ({nlp_analysis.get('environment_type', 'General')})</h2>
                <div style="background: rgba(230, 126, 34, 0.1); padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
                    <p style="margin: 0; color: #e67e22; font-weight: 600;">
                        <i class="fas fa-info-circle"></i> The following official JKR/DOSH regulations may apply to observed scene violations (PPE and non-PPE):
                    </p>
                </div>
                {''.join(reg_items)}
            </div>
        """
    
    def _generate_person_cards_section(self, nlp_analysis: Dict[str, Any], report_data: Dict[str, Any]) -> str:
        """Generate per-person analysis cards (inspired by NLP_Luna)."""
        persons = nlp_analysis.get('persons', [])
        if not isinstance(persons, list):
            persons = []
        persons = [p for p in persons if isinstance(p, dict)]

        if not persons:
            return """
            <div class="section">
                <h2 class="section-title">👥 Individual Analysis</h2>
                <div class="card">
                    <div class="card-content">
                        <p>No person-level analysis returned by model.</p>
                    </div>
                </div>
            </div>
            """

        # Generate card for each person
        person_cards = []
        for i, person in enumerate(persons):
            person_id_raw = str(person.get('id') or f'Person {i + 1}').strip()
            description = self._to_safe_html_text(person.get('description') or '')
            compliance = str(person.get('compliance_status') or '').strip()

            # PPE status grid from model output only (no detector override).
            ppe = person.get('ppe', {})
            if not isinstance(ppe, dict):
                ppe = {}
            ppe_items = []
            has_missing_ppe = False

            ppe_keys_order = ['hardhat', 'safety_vest', 'gloves', 'goggles', 'footwear', 'mask']
            ppe_keys = [k for k in ppe_keys_order if k in ppe] + [k for k in ppe.keys() if k not in ppe_keys_order]

            for ppe_type in ppe_keys:
                status = str(ppe.get(ppe_type, '') or '').strip() or 'Not specified'
                status_lower = status.lower()

                if 'missing' in status_lower or status_lower.startswith('no '):
                    status_class = 'ppe-status-missing'
                    has_missing_ppe = True
                elif 'mention' in status_lower or 'present' in status_lower or 'wear' in status_lower:
                    status_class = 'ppe-status-mentioned'
                else:
                    status_class = 'ppe-status-not-mentioned'
                    
                ppe_label = ppe_type.replace('_', ' ').title()
                ppe_items.append(f"""
                    <div class="ppe-item">
                        <span class="ppe-label">{self._to_safe_html_text(ppe_label)}:</span>
                        <span class="ppe-status {status_class}">{self._to_safe_html_text(status)}</span>
                    </div>
                """)

            if not ppe_items:
                ppe_items.append("""
                    <div class="ppe-item">
                        <span class="ppe-label">PPE:</span>
                        <span class="ppe-status ppe-status-not-mentioned">No PPE status provided by model</span>
                    </div>
                """)

            # Keep model compliance when provided; infer only when absent.
            if not compliance and has_missing_ppe:
                compliance = 'Non-Compliant'
            elif not compliance:
                compliance = 'Not Specified'
            
            # Build Hazards Faced HTML (hazard-chip style)
            hazards_faced = person.get('hazards_faced', [])
            if not isinstance(hazards_faced, list):
                hazards_faced = [hazards_faced]
            hazards_html = ""
            if hazards_faced:
                for h in hazards_faced:
                    if isinstance(h, dict):
                        hazard_text = str(h.get('type') or h.get('hazard') or '').strip()
                        source = str(h.get('source') or '').strip()
                        if source:
                            hazard_text += f" - {source}"
                    else:
                        hazard_text = str(h).strip()
                    if hazard_text:
                        hazards_html += f'<div class="hazard-chip"><i class="fas fa-exclamation-circle"></i> {self._to_safe_html_text(hazard_text)}</div>'
            else:
                hazards_html = '<div class="hazard-chip">No hazards provided by model</div>'
            
            # Risks list - Use _format_risk_item style (likelihood badge)
            risks = person.get('risks', [])
            if not isinstance(risks, list):
                risks = [risks]
            risks_html = ""
            if risks:
                for r in risks:
                    if isinstance(r, dict):
                        risk_desc = str(r.get('risk') or r.get('description') or '').strip()
                        likelihood = str(r.get('likelihood') or '').strip()
                        regulation_citation = str(r.get('regulation_citation') or '').strip()
                        legal_consequence = str(r.get('legal_regulatory_consequences') or r.get('penalty') or '').strip()
                        if not likelihood:
                            risk_l = risk_desc.lower()
                            if any(tok in risk_l for tok in ('fatal', 'death', 'catastrophic', 'severe', 'immediate')):
                                likelihood = 'High (inferred)'
                            elif any(tok in risk_l for tok in ('minor', 'unlikely', 'low probability')):
                                likelihood = 'Low (inferred)'
                            else:
                                likelihood = 'Medium (inferred)'

                        lik_lower = likelihood.lower()
                        lik_class = 'likelihood-medium'
                        bar_width = '60%'
                        if 'very high' in lik_lower or lik_lower == 'high':
                            lik_class = 'likelihood-high'
                            bar_width = '100%'
                        elif lik_lower == 'low':
                            lik_class = 'likelihood-low'
                            bar_width = '30%'
                        elif 'not specified' in lik_lower:
                            lik_class = 'likelihood-medium'
                            bar_width = '45%'
                        
                        risks_html += f"""
            <div class="risk-item">
                <div class="risk-content">{self._to_safe_html_text(risk_desc or 'Risk detail not provided by model')}</div>
                {f'<div class="risk-meta" style="margin-top: 0.4rem; font-size: 0.9rem; color: #555;"><strong>Regulation:</strong> {self._to_safe_html_text(regulation_citation)}</div>' if regulation_citation else ''}
                {f'<div class="risk-meta" style="margin-top: 0.25rem; font-size: 0.88rem; color: #666;"><strong>Legal consequence:</strong> {self._to_safe_html_text(legal_consequence)}</div>' if legal_consequence else ''}
                <div class="likelihood-badge {lik_class}">
                    <span class="likelihood-label">Likelihood</span>
                    <span class="likelihood-value">{self._to_safe_html_text(likelihood)}</span>
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
                risks_html = '<div class="risk-item"><div class="risk-content">No risks provided by model</div></div>'

            # Correction Actions - Use action-chip style (check both 'corrective_actions' and 'actions')
            actions = self._ensure_list_of_strings(
                person.get('corrective_actions', []) or person.get('actions', [])
            )
            actions_html = ""
            if actions:
                for a in actions:
                    actions_html += f'<div class="action-chip"><i class="fas fa-check"></i> {self._to_safe_html_text(a)}</div>'
            else:
                actions_html = '<div class="action-chip" style="background-color: #f8f9fa; color: #6c757d;">No actions provided by model</div>'

            # Determine compliance badge style
            comp_lower = compliance.lower()
            if 'non' in comp_lower or 'fail' in comp_lower:
                comp_badge = '<span class="badge badge-danger">✗ Non-Compliant</span>'
            elif 'compliant' in comp_lower or 'pass' in comp_lower:
                comp_badge = '<span class="badge badge-success">✓ Compliant</span>'
            else:
                comp_badge = f'<span class="badge badge-warning">{self._to_safe_html_text(compliance)}</span>'

            # Create the Person Card HTML (matching reference structure exactly)
            person_id_display = self._to_safe_html_text(
                person_id_raw.replace('Person ', '').replace('Personnel ', '').strip() or str(i + 1)
            )
            person_cards.append(f"""
                <div class="person-card">
                    <div class="person-header">
                        <div>
                            <h3>👤 Person {person_id_display}</h3>
                            <p style="white-space: normal; word-break: break-word;">{description or 'No description provided by model'}</p>
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
        
        items = "".join([
            f"<li style=\"white-space: normal; word-break: break-word;\">{self._inject_interactive_tooltips(self._to_safe_html_text(r))}</li>"
            for r in recommendations if str(r).strip()
        ])
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
        likelihood = 'Medium (inferred)'
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
                <div class="risk-content">{self._to_safe_html_text(risk_desc or 'Risk detail not provided by model')}</div>
                <div class="likelihood-badge {badge_class}">
                    <span class="likelihood-label">Likelihood</span>
                    <span class="likelihood-value">{self._to_safe_html_text(likelihood)}</span>
                    <div class="likelihood-bar">
                        <div class="bar-fill" style="width: {'100%' if 'high' in likelihood.lower() else '60%' if 'medium' in likelihood.lower() else '30%' if 'low' in likelihood.lower() else '45%'}"></div>
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
