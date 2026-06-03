"""
Run a small full-architecture report quality probe for local or cloud mode.

The probe intentionally uses one known image plus detector facts, then exercises:
1. caption provider routing,
2. ReportGenerator provider routing,
3. HTML rendering and metadata sidecar writing.

It writes all artifacts under reports/debug so generated files stay out of git.
"""
# Readability: Module overview: keep the main setup, workflow, and fallback paths easy to scan.

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


# Prepare root for the next step.
ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent


# Section: run the load env file workflow with clear inputs and outputs.
def _load_env_file(path: Path) -> None:
    # Choose the correct branch before the workflow continues.
    if not path.exists():
        # Return the prepared result to the caller.
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        # Prepare value for the next step.
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


# Section: run the configure mode workflow with clear inputs and outputs.
def _configure_mode(mode: str) -> None:
    # Prepare values needed by the next step.
    os.environ["STRICT_PROVIDER_MODE_SPLIT"] = "true"
    os.environ["ALLOW_NLP_FALLBACK"] = "false"
    os.environ["STRICT_REPORT_GENERATION"] = "true"
    os.environ["CLOUD_REPORT_FALLBACK_ENABLED"] = "false"

    if mode == "local":
        # Prepare values needed by the next step.
        os.environ["CASM_ROUTING_PROFILE"] = "local"
        os.environ["GEMINI_ENABLED"] = "false"
        os.environ["MODEL_API_ENABLED"] = "false"
        os.environ["VISION_PROVIDER_ORDER"] = "ollama"
        os.environ["NLP_PROVIDER_ORDER"] = "ollama"
        os.environ.setdefault("LOCAL_OLLAMA_UNIFIED_MODEL", "gemma3:4b")
        os.environ.setdefault("OLLAMA_MODEL", os.environ.get("LOCAL_OLLAMA_UNIFIED_MODEL", "gemma3:4b"))
        os.environ.setdefault("LOCAL_OLLAMA_CPU_VISION_READ_TIMEOUT_SECONDS", "210")
        os.environ.setdefault("OLLAMA_FORCE_LOCAL_READ_TIMEOUT_SECONDS", "240")
        # Trigger the side effect required for this stage.
        os.environ.setdefault("OLLAMA_FORCE_LOCAL_MAX_ATTEMPTS", "2")
        os.environ.setdefault("OLLAMA_FORCE_LOCAL_JSON_SCHEMA", "true")
    else:
        os.environ["CASM_ROUTING_PROFILE"] = "cloud"
        os.environ["GEMINI_ENABLED"] = "true"
        os.environ["MODEL_API_ENABLED"] = "false"
        os.environ["VISION_PROVIDER_ORDER"] = "gemini"
        os.environ["NLP_PROVIDER_ORDER"] = "gemini"
        os.environ.setdefault("GEMINI_REPORT_MAX_RETRIES", "1")
        # Trigger the side effect required for this stage.
        os.environ.setdefault("GEMINI_SCHEMA_REGEN_ATTEMPTS", "1")
        os.environ.setdefault("GEMINI_SEMANTIC_REGEN_ATTEMPTS", "1")


# Section: run the strip html text workflow with clear inputs and outputs.
def _strip_html_text(path: Path) -> str:
    # Choose the correct branch before the workflow continues.
    if not path.exists():
        return ""
    raw = path.read_text(encoding="utf-8", errors="ignore")
    raw = re.sub(r"<script.*?</script>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<style.*?</style>", " ", raw, flags=re.I | re.S)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return html.unescape(re.sub(r"\s+", " ", raw)).strip()


# Section: run the quality flags workflow with clear inputs and outputs.
def _quality_flags(text: str, nlp_analysis: Dict[str, Any]) -> Dict[str, Any]:
    # Prepare lower for the next step.
    lower = text.lower()
    hard_fail_terms = [
        "stop work",
        "major (high potential for lta)",
        "critical (immediate danger",
        "fatal:",
        "head injury risk from falling",
        "respiratory exposure risk from dust",
        "struck-by risk due to reduced worker visibility",
    ]
    # Prepare found terms for the next step.
    found_terms = [term for term in hard_fail_terms if term in lower]

    likelihoods: List[str] = []
    for person in nlp_analysis.get("persons") or []:
        # Choose the correct branch before the workflow continues.
        if not isinstance(person, dict):
            continue
        for risk in person.get("risks") or []:
            # Choose the correct branch before the workflow continues.
            if isinstance(risk, dict):
                # Trigger the side effect required for this stage.
                likelihoods.append(str(risk.get("likelihood") or "").strip().upper())

    # Return the prepared result to the caller.
    return {
        "over_escalation_terms": found_terms,
        "likelihoods": likelihoods,
        "all_likelihoods_low_or_review": all(
            value in {"LOW", "REVIEW_REQUIRED", ""} for value in likelihoods
        ),
        "has_supervisor_verification": "supervisor verification" in lower,
        "has_incident_package": "regulatory incident report package" in lower,
    }


# Section: run the default detections workflow with clear inputs and outputs.
def _default_detections() -> List[Dict[str, Any]]:
    # Return the prepared result to the caller.
    return [
        {"class_name": "Person", "confidence": 0.91, "bbox": [0, 0, 1, 1]},
        {"class_name": "NO-Hardhat", "confidence": 0.88, "bbox": [0, 0, 1, 1]},
        {"class_name": "NO-Safety Vest", "confidence": 0.82, "bbox": [0, 0, 1, 1]},
        {"class_name": "NO-Mask", "confidence": 0.79, "bbox": [0, 0, 1, 1]},
    ]


# Section: run the main workflow with clear inputs and outputs.
def main() -> int:
    # Prepare parser for the next step.
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["local", "cloud"], required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--annotated", default="")
    parser.add_argument("--source-report-id", default="")
    parser.add_argument("--severity", default="LOW")
    args = parser.parse_args()

    _load_env_file(ROOT / ".env")
    # Trigger the side effect required for this stage.
    _load_env_file(REPO_ROOT / ".env")
    _configure_mode(args.mode)

    sys.path.insert(0, str(ROOT))

    from caption_image import caption_image_llava, get_runtime_provider_diagnostics
    from pipeline.backend.core.report_generator import ReportGenerator
    from pipeline.config import (
        BRAND_COLORS,
        GEMINI_CONFIG,
        OLLAMA_CONFIG,
        RAG_CONFIG,
        REPORT_CONFIG,
    )

    # Prepare source image for the next step.
    source_image = Path(args.image).resolve()
    if not source_image.exists():
        # Surface the failure with enough context for the caller.
        raise FileNotFoundError(source_image)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_id_seed = args.source_report_id or source_image.stem
    report_id = f"{args.mode}_quality_probe_{report_id_seed}_{timestamp}"
    output_root = ROOT / "reports" / "debug" / report_id
    violation_dir = output_root / "violations" / report_id
    # Prepare reports dir for the next step.
    reports_dir = output_root / "reports"
    violation_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    original_path = violation_dir / "original.jpg"
    annotated_path = violation_dir / "annotated.jpg"
    shutil.copy2(source_image, original_path)
    annotated_source = Path(args.annotated).resolve() if args.annotated else source_image
    shutil.copy2(annotated_source if annotated_source.exists() else source_image, annotated_path)

    timings: Dict[str, float] = {}

    # Prepare caption started for the next step.
    caption_started = time.perf_counter()
    caption = caption_image_llava(str(original_path)) or ""
    timings["caption_generation_seconds"] = round(time.perf_counter() - caption_started, 2)
    caption_diag = get_runtime_provider_diagnostics()

    report_config = dict(REPORT_CONFIG)
    report_config["enable_pdf_generation"] = False
    report_config["generate_pdf"] = False
    config = {
        "OLLAMA_CONFIG": dict(OLLAMA_CONFIG),
        "GEMINI_CONFIG": dict(GEMINI_CONFIG),
        "RAG_CONFIG": dict(RAG_CONFIG),
        "REPORT_CONFIG": report_config,
        "BRAND_COLORS": dict(BRAND_COLORS),
        "REPORTS_DIR": reports_dir,
        "VIOLATIONS_DIR": output_root / "violations",
    }

    # Prepare init started for the next step.
    init_started = time.perf_counter()
    generator = ReportGenerator(config)
    timings["report_generator_init_seconds"] = round(time.perf_counter() - init_started, 2)

    report_data = {
        "report_id": report_id,
        "timestamp": datetime.now().isoformat(),
        "caption": caption,
        "vlm_caption": caption,
        "detections": _default_detections(),
        "violation_summary": "PPE Violation Detected: NO-Hardhat, NO-Safety Vest, NO-Mask",
        "person_count": 1,
        "violation_count": 3,
        "severity": str(args.severity or "LOW").upper(),
        "original_image_path": str(original_path),
        "annotated_image_path": str(annotated_path),
        "force_local_nlp": args.mode == "local",
    }

    # Prepare report started for the next step.
    report_started = time.perf_counter()
    result = generator.generate_report(report_data)
    timings["report_generation_seconds"] = round(time.perf_counter() - report_started, 2)
    timings["end_to_end_seconds"] = round(sum(
        timings.get(key, 0.0)
        for key in ("caption_generation_seconds", "report_generator_init_seconds", "report_generation_seconds")
    ), 2)

    html_path = Path(result.get("html") or "")
    # Prepare nlp analysis for the next step.
    nlp_analysis = result.get("nlp_analysis") or {}
    rendered_text = _strip_html_text(html_path)
    flags = _quality_flags(rendered_text, nlp_analysis if isinstance(nlp_analysis, dict) else {})

    metadata = {
        "success": True,
        "mode": args.mode,
        "report_id": report_id,
        "source_report_id": args.source_report_id,
        "output_root": str(output_root),
        "html_path": str(html_path),
        "timings_seconds": timings,
        "caption": caption,
        "caption_provider": caption_diag.get("last_provider_used"),
        "caption_model": {
            "gemini": caption_diag.get("gemini_model"),
            "ollama": caption_diag.get("ollama_model"),
            "model_api": caption_diag.get("vision_api_model"),
        }.get(str(caption_diag.get("last_provider_used") or "").lower()),
        "caption_diag": caption_diag,
        "report_provider": generator.last_nlp_provider,
        "report_model": generator.last_nlp_model,
        "severity_level": nlp_analysis.get("severity_level") if isinstance(nlp_analysis, dict) else None,
        "environment_type": nlp_analysis.get("environment_type") if isinstance(nlp_analysis, dict) else None,
        "summary": nlp_analysis.get("summary") if isinstance(nlp_analysis, dict) else None,
        "low_context_guard": bool(isinstance(nlp_analysis, dict) and nlp_analysis.get("_low_context_proportionality_guard")),
        "quality_flags": flags,
    }

    # Prepare metadata path for the next step.
    metadata_path = output_root / "probe_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(metadata, indent=2, ensure_ascii=True))
    return 0


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    raise SystemExit(main())
