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
        self.rag_data_path = rag_config.get('data_source', '')
        self.num_similar = rag_config.get('num_similar_incidents', 2)
        
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
        similar_incidents: List[Dict[str, str]]
    ) -> str:
        """
        Build enhanced prompt for Llama based on NLP_Luna template.
        Includes environment-aware analysis and objective/subjective metrics.
        
        Args:
            report_data: Report data including caption, detections, etc.
            similar_incidents: Similar incidents from RAG
        
        Returns:
            Formatted prompt string
        """
        # Extract data
        caption = report_data.get('caption', 'No caption available')
        detections = report_data.get('detections', [])
        violation_summary = report_data.get('violation_summary', '')
        person_count = report_data.get('person_count', 0)
        
        # Build detection description
        detection_desc = []
        for det in detections:
            detection_desc.append(
                f"- {det['class_name']} (confidence: {det['confidence']:.2f})"
            )
        
        # Build context from similar incidents
        context_text = ""
        if similar_incidents:
            context_text = "Here are some similar incidents for context:\n\n"
            for i, inc in enumerate(similar_incidents, 1):
                context_text += f"Incident {i}:\n{inc.get('Abstract', 'N/A')}\n\n"
        
        # Build enhanced prompt with environment awareness
        prompt = f"""You are an expert AI safety inspector. Analyze this workplace scene and respond with ONLY a valid JSON object.

{context_text if context_text else ""}
---
SCENE:
Caption: {caption}
Objects: {chr(10).join(detection_desc) if detection_desc else 'None'}
Violation: {violation_summary}
People: {person_count}

---
RULES:
1. Detect environment: Construction Site, Office, Warehouse, Manufacturing, Laboratory, Other
2. Construction/Warehouse/Manufacturing require: Hardhat, vest, footwear
3. Office environments: PPE NOT needed
4. PPE status: "Mentioned", "Not Mentioned", "Missing", or "Not Required"
5. Create one person block per detected person
6. Fall detection = CRITICAL severity

JSON structure:
{{
  "summary": "Brief summary with environment and main concerns",
  "environment_type": "Construction Site|Office|Warehouse|Manufacturing|Laboratory|Other",
  "environment_assessment": "Why this environment type and what standards apply",
  "persons": [
    {{
      "id": 1,
      "description": "Person's role/actions",
      "ppe": {{
        "hardhat": "Mentioned|Not Mentioned|Missing|Not Required",
        "safety_vest": "Mentioned|Not Mentioned|Missing|Not Required",
        "gloves": "Mentioned|Not Mentioned|Missing|Not Required",
        "goggles": "Mentioned|Not Mentioned|Missing|Not Required",
        "footwear": "Mentioned|Not Mentioned|Missing|Not Required"
      }},
      "actions": ["actions list"],
      "hazards_faced": ["hazards list"],
      "risks": ["risks list"],
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
                    'stream': False,
                    'format': 'json',
                    'options': {
                        'temperature': self.temperature
                    }
                },
                timeout=120  # 2 minute timeout
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
        
        # Step 1: RAG - Find similar incidents
        similar_incidents = []
        if self.rag_enabled:
            description = f"{report_data.get('caption', '')} {report_data.get('violation_summary', '')}"
            similar_incidents = self._find_similar_incidents(description, self.num_similar)
            logger.info(f"Found {len(similar_incidents)} similar incidents")
        
        # Step 2: NLP - Generate analysis with Ollama
        nlp_analysis = None
        prompt = self._build_nlp_prompt(report_data, similar_incidents)
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
        """Generate basic fallback analysis if NLP fails."""
        return {
            'summary': report_data.get('violation_summary', 'Safety violation detected'),
            'environment_type': 'Unknown',
            'environment_assessment': 'Unable to determine environment type from available data',
            'persons': [],
            'hazards_detected': ['Violation detected by automated system'],
            'suggested_actions': [
                'Review the annotated image for specific violations',
                'Ensure all workers are wearing required PPE',
                'Investigate the cause of the violation'
            ],
            'severity_level': report_data.get('severity', 'HIGH')
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
        
        .list-compact li {{
            padding: 0.5rem;
            margin-bottom: 0.35rem;
            background: rgba(52,152,219,0.05);
            border-left: 3px solid var(--secondary-color);
            border-radius: 4px;
            font-size: 0.9rem;
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
            
            <!-- Individual Person Analysis -->
            {self._generate_person_cards_section(nlp_analysis)}
            
            <!-- Hazards -->
            {self._generate_hazards_section(nlp_analysis)}
            
            <!-- Recommendations -->
            {self._generate_recommendations_section(nlp_analysis)}
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
    
    def _generate_hazards_section(self, nlp_analysis: Dict[str, Any]) -> str:
        """Generate hazards HTML section."""
        hazards = nlp_analysis.get('hazards_detected', [])
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
    
    def _generate_person_cards_section(self, nlp_analysis: Dict[str, Any]) -> str:
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
        
        # Generate card for each person
        person_cards = []
        for person in persons:
            person_id = person.get('id', 'Unknown')
            description = person.get('description', 'No description')
            compliance = person.get('compliance_status', 'Unknown')
            
            # PPE status grid
            ppe = person.get('ppe', {})
            ppe_items = []
            for ppe_type, status in ppe.items():
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
            actions = person.get('actions', [])
            actions_html = ''.join([f"<li>{a}</li>" for a in actions]) if actions else '<li>No actions specified</li>'
            
            # Hazards list
            hazards = person.get('hazards_faced', [])
            hazards_html = ''.join([f"<li>{h}</li>" for h in hazards]) if hazards else '<li>No hazards identified</li>'
            
            # Risks list
            risks = person.get('risks', [])
            risks_html = ''.join([f"<li>{r}</li>" for r in risks]) if risks else '<li>No risks identified</li>'
            
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
                            <h4>🏃 Actions</h4>
                            <ul class="list-compact">{actions_html}</ul>
                        </div>
                        <div class="person-section">
                            <h4>⚠️ Hazards Faced</h4>
                            <ul class="list-compact">{hazards_html}</ul>
                        </div>
                        <div class="person-section">
                            <h4>⚕️ Potential Risks</h4>
                            <ul class="list-compact">{risks_html}</ul>
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
        recommendations = nlp_analysis.get('suggested_actions', [])
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
