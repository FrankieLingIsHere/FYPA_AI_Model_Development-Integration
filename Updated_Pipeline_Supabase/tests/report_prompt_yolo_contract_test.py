"""
Offline contract test for NLP report prompt grounding.

The report prompt must carry the raw YOLO detection payload, not only the VLM
caption, so Gemini/Ollama cannot miss PPE classifier evidence.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.backend.core.report_generator import ReportGenerator


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def test_nlp_prompt_injects_yolo_payload():
    subject = ReportGenerator.__new__(ReportGenerator)
    report_data = {
        "caption": (
            "One worker is standing near construction materials in an active work area, "
            "leaning into a cordoned zone while an excavator operates nearby."
        ),
        "detections": [
            {
                "class_name": "Person",
                "confidence": 0.91,
                "bbox": [12, 34, 120, 240],
            },
            {
                "class_name": "NO-Hardhat",
                "score": 0.83,
                "bbox": [22, 40, 90, 110],
            },
            {
                "class_name": "NO-Safety Vest",
                "confidence": 0.76,
                "bbox": [18, 90, 118, 210],
            },
            {
                "class_name": "machinery",
                "confidence": 0.71,
                "bbox": [320, 40, 520, 300],
            },
            {
                "class_name": "Safety Cone",
                "confidence": 0.67,
                "bbox": [250, 300, 280, 360],
            },
        ],
        "violation_summary": "PPE Violation Detected: NO-Hardhat, NO-Safety Vest",
        "person_count": 1,
    }

    prompt = subject._build_nlp_prompt(report_data, similar_incidents=[], dosh_context=[])

    _assert("*** YOLO DETECTION PAYLOAD" in prompt, "Prompt missing YOLO payload section")
    _assert("- Person (confidence: 0.91" in prompt, "Prompt missing person detection")
    _assert("- NO-Hardhat (confidence: 0.83" in prompt, "Prompt missing hardhat violation")
    _assert("- NO-Safety Vest (confidence: 0.76" in prompt, "Prompt missing vest violation")
    _assert("YOLO violation classes: NO-Hardhat, NO-Safety Vest" in prompt, "Prompt missing YOLO violation summary")
    _assert("CONFIRMED MISSING PPE" in prompt, "Prompt missing missing-PPE directive")
    _assert("prefer YOLO for PPE status" in prompt, "Prompt missing conflict-resolution rule")
    _assert("ACTIVITY RISK SIGNALS" in prompt, "Prompt missing activity risk signal block")
    _assert("restricted-area entry / exclusion-zone breach: observed=true" in prompt, "Prompt missing restricted-area coverage")
    _assert("unsafe posture / manual-handling strain: observed=true" in prompt, "Prompt missing unsafe-posture coverage")
    _assert("machinery-related struck-by / caught-between exposure: observed=true" in prompt, "Prompt missing machinery-risk coverage")
    _assert("regulatory report generation / evidence-pack follow-up: observed=true" in prompt, "Prompt missing regulatory report action coverage")
    _assert("Do not copy this block into the caption or visual_evidence" in prompt, "Activity risks must stay out of captions")
    _assert('without the word "inferred"' in prompt, "Prompt must block inferred likelihood labels")
    _assert("Generate the regulatory incident report package" in prompt, "Prompt missing regulatory report package action")


def test_report_text_cleaning_does_not_split_characters():
    subject = ReportGenerator.__new__(ReportGenerator)

    cleaned = subject._to_safe_html_text("Worker -> helmet \u2022 vest")

    _assert(cleaned == "Worker to helmet, vest", f"Unexpected cleaned text: {cleaned!r}")
    _assert("to , to" not in cleaned, "Report text cleaner split text into character fragments")


def test_sanitized_report_fields_stay_word_level():
    subject = ReportGenerator.__new__(ReportGenerator)
    analysis = subject._sanitize_nlp_analysis({
        "summary": "General Workspace safety violation.",
        "hazards_detected": "Falling objects",
        "persons": [
            {
                "id": "Person 1",
                "description": "Worker missing hard hat.",
                "ppe": {"Hard Hat": "Missing"},
                "hazards_faced": ["Falling debris"],
                "risks": [{"risk": "Head injury from debris", "likelihood": "High"}],
                "corrective_actions": ["Replace hat with helmet"],
            }
        ],
    })

    rendered = subject._generate_person_cards_section(analysis, {
        "caption": "One worker is missing required PPE.",
        "violation_summary": "PPE Violation Detected: NO-Hardhat",
        "person_count": 1,
        "detections": [{"class_name": "Person"}],
    })

    _assert("Worker missing hard hat." in rendered, "Person description was not preserved")
    _assert("Falling debris" in rendered, "Hazard text was not preserved")
    _assert("to , to" not in rendered, "Rendered person HTML contains character-split text")


def test_scene_description_does_not_duplicate_caption_yolo_addendum():
    subject = ReportGenerator.__new__(ReportGenerator)
    caption = (
        "One individual is present in an indoor office setting. "
        "YOLO detection identified 1 person(s) in the frame with the following PPE deficiencies: "
        "Missing Hard Hat, Missing Mask, Missing Safety Vest."
    )

    visual = subject._build_scene_description(
        caption,
        "Indoor / Office",
        [
            {"class_name": "Person", "confidence": 0.91},
            {"class_name": "NO-Hardhat", "confidence": 0.83},
            {"class_name": "NO-Mask", "confidence": 0.74},
            {"class_name": "NO-Safety Vest", "confidence": 0.76},
        ],
    )

    _assert(visual.count("YOLO detection identified") == 1, "Scene description duplicated YOLO context")
    _assert("Hardhat, Mask, Safety Vest." not in visual, "Scene description appended raw duplicate labels")


def test_scene_description_preserves_cloud_caption_opening():
    subject = ReportGenerator.__new__(ReportGenerator)
    caption = (
        "The scene depicts an indoor office setting. An indoor scene shows one visible person. "
        "The person's upper torso and head are visible, and they are seated with a forward-facing posture. "
        "Their gaze is directed forward, slightly downward. The person is wearing a dark blue short-sleeved shirt, "
        "and no eyewear is visible. In the background, there are white wall-mounted shelves and a large window."
    )

    visual = subject._build_scene_description(
        caption,
        "Indoor / Office",
        [{"class_name": "Person", "confidence": 0.91}],
    )

    _assert(visual.startswith("The scene depicts an indoor office setting."), visual)
    _assert(visual.count("The scene depicts") == 1, visual)
    _assert("upper torso and head are visible" in visual, visual)


def test_ollama_compact_prompt_keeps_required_schema_and_yolo_ppe():
    subject = ReportGenerator.__new__(ReportGenerator)

    compact = subject._build_ollama_compact_report_prompt({
        "caption": "One worker is standing in a restricted work area beside machinery.",
        "violation_summary": "Missing Hard Hat, Missing Safety Vest",
        "person_count": 1,
        "severity": "HIGH",
        "detections": [
            {"class_name": "Person", "confidence": 0.91},
            {"class_name": "NO-Hardhat", "confidence": 0.83},
            {"class_name": "NO-Safety Vest", "confidence": 0.76},
            {"class_name": "machinery", "confidence": 0.64},
        ],
    }, "original long prompt")

    _assert('"environment_type"' in compact, "Compact prompt missing environment_type schema")
    _assert('"persons"' in compact, "Compact prompt missing persons schema")
    _assert('"dosh_regulations_cited"' in compact, "Compact prompt missing regulation schema")
    _assert('"hardhat": "Missing"' in compact, "Compact prompt did not preserve YOLO hardhat gap")
    _assert('"safety_vest": "Missing"' in compact, "Compact prompt did not preserve YOLO vest gap")
    _assert("Do not return an empty object" in compact, "Compact prompt must reject empty JSON")
    _assert("ACTIVITY RISK SIGNALS" in compact, "Compact prompt missing activity-risk signal block")
    _assert("restricted-area entry / exclusion-zone breach: observed=true" in compact, "Compact prompt missing restricted-area signal")
    _assert("machinery-related struck-by / caught-between exposure: observed=true" in compact, "Compact prompt missing machinery signal")
    _assert('"risk_category": "PPE"' in compact, "Compact prompt missing PPE risk_category schema")
    _assert('Observed non-PPE activity categories from local caption/YOLO: restricted_area, machinery' in compact, "Compact prompt missing observed local activity categories")
    _assert('Do not invent unlisted activity risks' in compact, "Compact prompt missing anti-invention rule")
    _assert("Generate the regulatory incident report package" in compact, "Compact prompt missing regulatory report package action")
    _assert('Do not write "(inferred)" in likelihood' in compact, "Compact prompt should block inferred labels")

    compact_two_people = subject._build_ollama_compact_report_prompt({
        "caption": "Two workers are standing in a work area.",
        "violation_summary": "Missing Hard Hat",
        "person_count": 2,
        "severity": "HIGH",
        "detections": [
            {"class_name": "Person"},
            {"class_name": "Person"},
            {"class_name": "NO-Hardhat"},
        ],
    }, "original long prompt")
    _assert('"id": "Person 2"' in compact_two_people, "Compact prompt did not preserve multi-person schema")


def test_activity_signals_ignore_negated_caption_terms():
    subject = ReportGenerator.__new__(ReportGenerator)
    block = subject._build_activity_risk_signal_block({
        "caption": (
            "A person is seated indoors. There are no visible workplace-specific "
            "hazards like machinery, vehicles, or tools, and no visible barriers."
        ),
        "violation_summary": "PPE Violation Detected: Missing PPE Violation",
        "detections": [],
    })

    _assert("machinery-related struck-by / caught-between exposure: observed=false" in block, "Negated machinery text should not create machinery risk")
    _assert("restricted-area entry / exclusion-zone breach: observed=false" in block, "Negated barrier text should not create restricted-area risk")
    _assert("traffic-interface exposure: observed=false" in block, "Negated vehicle text should not create traffic-interface risk")
    _assert("regulatory report generation / evidence-pack follow-up: observed=true" in block, "Violation summary should still trigger regulatory follow-up")


def test_caption_bus_or_street_creates_traffic_signal():
    subject = ReportGenerator.__new__(ReportGenerator)
    block = subject._build_activity_risk_signal_block({
        "caption": "There are four visible people in an urban street scene featuring a bus.",
        "detections": [],
    })

    _assert("traffic-interface exposure: observed=true" in block, "Street/bus caption should create traffic-interface coverage")


def test_ollama_compact_prompt_expands_local_caption_activity_context():
    subject = ReportGenerator.__new__(ReportGenerator)
    compact = subject._build_ollama_compact_report_prompt({
        "caption": (
            "The image shows an outdoor street scene where one visible person is standing "
            "near a bus, while the surrounding "
            "context includes a road or street area with a bus or other vehicle near the person; "
            "no PPE is clearly visible."
        ),
        "violation_summary": "Missing Hard Hat",
        "person_count": 1,
        "severity": "HIGH",
        "detections": [
            {"class_name": "Person", "confidence": 0.91},
            {"class_name": "NO-Hardhat", "confidence": 0.83},
        ],
    }, "original long prompt")

    _assert("traffic-interface exposure: observed=true" in compact, "Local caption activity hint should mark traffic observed")
    _assert('Observed non-PPE activity categories from local caption/YOLO: traffic_interface' in compact, "Compact prompt missing traffic_interface requirement")


def test_cloud_activity_block_allows_clear_direct_image_override():
    subject = ReportGenerator.__new__(ReportGenerator)
    block = subject._build_activity_risk_signal_block(
        {
            "caption": "Auto-generated safety summary with PPE non-compliance indicators.",
            "detections": [{"class_name": "NO-Hardhat"}],
        },
        direct_image_available=True,
    )

    _assert("attached original image clearly shows that risk" in block, "Cloud image-aware prompt should allow direct image evidence")
    _assert("Only include categories marked observed=true" not in block, "Cloud image-aware prompt should not be text-only strict")


def test_rendered_activity_risk_fields_are_model_json_cells():
    subject = ReportGenerator.__new__(ReportGenerator)
    analysis = subject._sanitize_nlp_analysis({
        "summary": "Restricted area and machinery exposure observed.",
        "environment_type": "Construction Site",
        "persons": [
            {
                "id": "Person 1",
                "description": "Worker is inside a restricted machinery zone without required PPE.",
                "ppe": {"hardhat": "Missing", "safety_vest": "Missing"},
                "hazards_faced": [
                    {"type": "Restricted-area entry", "source": "Caption states restricted work area", "severity": "HIGH"}
                ],
                "risks": [
                    {
                        "risk_category": "machinery",
                        "risk": "The worker could be struck by moving plant because the scene places them inside the operating envelope. The missing helmet and vest reduce both impact protection and visibility.",
                        "likelihood": "HIGH",
                        "evidence": "caption: restricted work area beside machinery; YOLO: machinery and missing PPE",
                        "regulation_citation": "OSHA 1994 Section 15",
                        "legal_regulatory_consequences": "DOSH may issue enforcement action.",
                        "mitigation_steps": [
                            "Stop machinery movement until the exclusion zone is cleared.",
                            "Re-establish barricades and assign a spotter before restart.",
                            "Record the correction in the regulatory evidence pack."
                        ],
                    }
                ],
                "corrective_actions": [
                    "Generate the regulatory incident report package with image evidence and supervisor sign-off before closure.",
                    "Brief the worker on restricted-zone access controls before re-entry.",
                    "Verify PPE fit and high-visibility controls before the task restarts.",
                ],
            }
        ],
    })

    rendered = subject._generate_person_cards_section(analysis, {
        "caption": "One worker is in a restricted work area beside machinery.",
        "violation_summary": "PPE Violation Detected: NO-Hardhat, NO-Safety Vest",
        "person_count": 1,
        "detections": [{"class_name": "Person"}, {"class_name": "NO-Hardhat"}, {"class_name": "machinery"}],
    })

    _assert("Category:" in rendered and "machinery" in rendered, "Rendered risk category missing")
    _assert("Evidence:" in rendered and "restricted work area beside machinery" in rendered, "Rendered risk evidence missing")
    _assert("Mitigation steps" in rendered, "Rendered mitigation steps missing")
    _assert("regulatory incident report package" in rendered, "Regulatory report action missing")
    _assert("(inferred)" not in rendered.lower(), "Rendered model cells should not display inferred likelihood labels")


def test_fallback_report_risks_have_concrete_likelihood_badges():
    subject = ReportGenerator.__new__(ReportGenerator)
    report_data = {
        "caption": (
            "An outdoor street scene shows a person near a bus or vehicle while holding a phone. "
            "No PPE is clearly visible."
        ),
        "vlm_caption": (
            "An outdoor street scene shows a person near a bus or vehicle while holding a phone. "
            "No PPE is clearly visible."
        ),
        "detections": [
            {"class_name": "Person", "confidence": 0.91},
            {"class_name": "NO-Hardhat", "confidence": 0.82},
            {"class_name": "NO-Safety Vest", "confidence": 0.79},
            {"class_name": "vehicle", "confidence": 0.86},
        ],
        "violation_summary": "PPE Violation Detected: NO-Hardhat, NO-Safety Vest",
        "person_count": 1,
    }

    analysis = subject._generate_fallback_analysis(report_data)
    allowed = {"HIGH", "MEDIUM", "LOW", "REVIEW_REQUIRED"}

    risks = analysis["persons"][0]["risks"]
    _assert(risks, "Fallback analysis should emit risk rows")
    _assert(all(isinstance(risk, dict) for risk in risks), f"Fallback risks should be structured dicts: {risks!r}")
    _assert(
        all(str(risk.get("likelihood") or "").strip() in allowed for risk in risks),
        f"Fallback risks must use concrete likelihood values: {risks!r}",
    )

    rendered = subject._generate_person_cards_section(analysis, report_data)
    _assert("Not specified by model" not in rendered, "Fallback report should not render unspecified likelihood badges")
    _assert("REVIEW REQUIRED (Model Likelihood Not Specified)" not in rendered, "Fallback severity footer should not blame model omission")


def test_local_activity_augmentation_adds_observed_caption_hint_when_model_omits_it():
    subject = ReportGenerator.__new__(ReportGenerator)
    subject.enforce_strict_provider_split = True
    subject.routing_profile = "local"
    analysis = {
        "persons": [
            {
                "id": "Person 1",
                "ppe": {"hardhat": "Missing"},
                "risks": [
                    {
                        "risk_category": "PPE",
                        "risk": "The worker could sustain head injury because the hardhat is missing in a traffic environment.",
                        "likelihood": "HIGH",
                        "evidence": "YOLO detected missing Hardhat.",
                    }
                ],
                "corrective_actions": ["Provide hardhat before work restarts."],
            }
        ]
    }
    report_data = {
        "caption": (
            "The image shows an outdoor street scene where one visible person is standing "
            "near a bus, while the surrounding "
            "context includes a road or street area with a bus or other vehicle near the person; "
            "no PPE is clearly visible."
        ),
        "detections": [{"class_name": "Person"}, {"class_name": "NO-Hardhat"}],
        "violation_summary": "PPE Violation Detected: NO-Hardhat",
    }

    subject._augment_local_observed_activity_risks(analysis, report_data, force_local_nlp=True)

    risks = analysis["persons"][0]["risks"]
    categories = [risk.get("risk_category") for risk in risks if isinstance(risk, dict)]
    _assert("traffic_interface" in categories, f"Missing augmented traffic risk: {risks!r}")
    traffic_risk = next(risk for risk in risks if isinstance(risk, dict) and risk.get("risk_category") == "traffic_interface")
    _assert("road or street area with a bus or other vehicle" in traffic_risk.get("evidence", ""), "Augmented risk should cite local caption evidence")
    _assert("(inferred)" not in str(traffic_risk).lower(), "Augmented risk must not use inferred likelihood labels")


def test_environment_detection_does_not_treat_restricted_work_area_as_office():
    subject = ReportGenerator.__new__(ReportGenerator)
    caption = (
        "One construction worker is leaning forward inside a cordoned restricted work area "
        "beside an operating excavator and stacked timber."
    )

    stable = subject._resolve_stable_environment_type(
        caption,
        detections=[{"class_name": "machinery"}],
        model_environment="Construction Site",
    )

    _assert(stable == "Construction Site", f"Expected construction environment, got {stable!r}")


def main():
    tests = [
        test_nlp_prompt_injects_yolo_payload,
        test_report_text_cleaning_does_not_split_characters,
        test_sanitized_report_fields_stay_word_level,
        test_scene_description_does_not_duplicate_caption_yolo_addendum,
        test_scene_description_preserves_cloud_caption_opening,
        test_ollama_compact_prompt_keeps_required_schema_and_yolo_ppe,
        test_activity_signals_ignore_negated_caption_terms,
        test_caption_bus_or_street_creates_traffic_signal,
        test_ollama_compact_prompt_expands_local_caption_activity_context,
        test_cloud_activity_block_allows_clear_direct_image_override,
        test_rendered_activity_risk_fields_are_model_json_cells,
        test_fallback_report_risks_have_concrete_likelihood_badges,
        test_local_activity_augmentation_adds_observed_caption_hint_when_model_omits_it,
        test_environment_detection_does_not_treat_restricted_work_area_as_office,
    ]
    failures = []
    for test_fn in tests:
        try:
            test_fn()
            print(f"PASS: {test_fn.__name__}")
        except Exception as exc:
            failures.append((test_fn.__name__, str(exc)))
            print(f"FAIL: {test_fn.__name__}: {exc}")

    if failures:
        print("Report prompt YOLO contract test failed")
        raise SystemExit(1)

    print("Report prompt YOLO contract test passed")


if __name__ == "__main__":
    main()
