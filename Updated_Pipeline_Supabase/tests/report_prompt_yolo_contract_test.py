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


def test_person_cards_are_grounded_to_detector_ppe_and_summary_counts():
    subject = ReportGenerator.__new__(ReportGenerator)
    analysis = subject._sanitize_nlp_analysis({
        "summary": "Two workers require PPE follow-up.",
        "environment_type": "Construction Site",
        "persons": [
            {
                "id": "Person 1",
                "description": "Worker near the platform without mask.",
                "ppe": {"hardhat": "Mentioned", "mask": "Missing"},
                "risks": [{"risk": "PPE exposure risk.", "likelihood": "MEDIUM"}],
                "corrective_actions": ["Check PPE"],
            }
        ],
    })
    report_data = {
        "caption": "Two workers are visible in a construction site.",
        "violation_summary": "PPE Violation Detected: NO-Hardhat, NO-Safety Vest",
        "person_count": 2,
        "violation_count": 99,
        "missing_ppe": ["Hardhat", "Safety Vest"],
        "detections": [
            {"class_name": "Person"},
            {"class_name": "Person"},
            {"class_name": "NO-Hardhat"},
            {"class_name": "NO-Safety Vest"},
        ],
    }

    rendered = subject._generate_person_cards_section(analysis, report_data)
    summary = subject._format_summary_html(analysis, report_data)

    _assert(rendered.count('<details class="person-card') == 2, "Person card count must match detected/caption count")
    _assert(
        rendered.count("Detector-confirmed PPE conditions: missing Hardhat and Safety Vest.") == 2,
        "Each person card description must name the exact detector-confirmed PPE gaps",
    )
    _assert(
        rendered.count('ppe-status-missing">Missing</span>') == 4,
        "Only Hardhat and Safety Vest should be marked missing on two person cards",
    )
    _assert("missing mask" not in rendered.lower(), "Unsupported model PPE gap should not survive reconciliation")
    _assert(report_data["violation_count"] == 2, "Violation count should tally with distinct detector-confirmed PPE gaps")
    _assert(
        "Report lists 2 person(s); 2 with detector-confirmed PPE conditions: Hardhat, Safety Vest." in summary,
        "Summary WHO row must tally with the normalized person cards",
    )
    _assert('class="summary-table"' in summary, "Executive summary should use the breathable summary table layout")
    _assert('class="summary-label">WHAT</td>' in summary, "Executive summary WHAT label should use layout class")
    _assert('class="summary-cell-copy"' in summary, "Executive summary cells should wrap copy for readable spacing")


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

    _assert("Return schema keys: environment_type, visual_evidence, persons" in compact, "Compact prompt missing required schema keys")
    _assert("YOLO missing PPE: Hardhat, Safety Vest" in compact, "Compact prompt did not preserve YOLO PPE gaps")
    _assert("No empty object" in compact, "Compact prompt must reject empty JSON")
    _assert("Observed non-PPE activity categories: restricted_area, machinery" in compact, "Compact prompt missing observed local activity categories")
    _assert("risk_category, risk, likelihood, evidence" in compact, "Compact prompt missing structured risk fields")
    _assert('Do not invent unlisted activity risks' in compact, "Compact prompt missing anti-invention rule")
    _assert("Generate the regulatory incident report package" in compact, "Compact prompt missing regulatory report package action")
    _assert('Do not write "(inferred)" in likelihood' in compact, "Compact prompt should block inferred labels")
    _assert(len(compact) < 3500, f"Compact prompt too large for local Gemma: {len(compact)} chars")

    schema = subject._build_ollama_report_json_schema({
        "person_count": 2,
    })
    _assert(schema["required"] == [
        "environment_type",
        "visual_evidence",
        "persons",
        "summary",
        "severity_level",
        "dosh_regulations_cited",
    ], "Ollama JSON schema must require top-level report keys")
    _assert("minItems" not in schema["properties"]["persons"], "Ollama schema should not over-constrain slow local generation")

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
    _assert('Person 1, Person 2' in compact_two_people, "Compact prompt did not preserve multi-person ids")


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

    _assert("Observed non-PPE activity categories: traffic_interface" in compact, "Local caption activity hint should mark traffic observed")
    _assert('Observed non-PPE activity categories: traffic_interface' in compact, "Compact prompt missing traffic_interface requirement")


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


def test_fallback_office_ppe_gaps_do_not_invent_construction_hazards():
    subject = ReportGenerator.__new__(ReportGenerator)
    caption = (
        "An indoor office scene shows one person standing near a desk, chairs, and a computer monitor. "
        "No road, vehicle traffic, cones, machinery, dust, fumes, or overhead construction work are visible."
    )
    report_data = {
        "caption": caption,
        "vlm_caption": caption,
        "detections": [
            {"class_name": "Person", "confidence": 0.91},
            {"class_name": "NO-Hardhat", "confidence": 0.82},
            {"class_name": "NO-Safety Vest", "confidence": 0.79},
            {"class_name": "NO-Mask", "confidence": 0.75},
        ],
        "violation_summary": "PPE Violation Detected: NO-Hardhat, NO-Safety Vest, NO-Mask",
        "person_count": 1,
        "severity": "HIGH",
    }

    analysis = subject._generate_fallback_analysis(report_data)
    risks = analysis["persons"][0]["risks"]
    combined_text = " ".join([
        analysis.get("summary", ""),
        " ".join(analysis.get("hazards_detected", [])),
        " ".join(analysis.get("suggested_actions", [])),
        " ".join(str(risk.get("risk", "")) + " " + str(risk.get("evidence", "")) for risk in risks),
    ]).lower()

    _assert(analysis["environment_type"] == "Indoor / Office", analysis["environment_type"])
    _assert(analysis["severity_level"] == "MEDIUM", analysis["severity_level"])
    _assert(report_data["severity"] == "MEDIUM", report_data["severity"])
    _assert(all(risk.get("likelihood") != "HIGH" for risk in risks), f"Unexpected high likelihood risk: {risks!r}")
    _assert("falling timber" not in combined_text, "Office fallback should not invent falling timber hazard")
    _assert("lorry" not in combined_text and "excavator" not in combined_text, "Office fallback should not invent vehicle/plant hazard")
    _assert("silica" not in combined_text, "Office fallback should not invent construction dust hazard")
    _assert("stop work" not in combined_text, "Office fallback should request review before stop-work escalation")


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


def test_executive_summary_formats_labeled_what_and_danger_as_bullets():
    subject = ReportGenerator.__new__(ReportGenerator)
    analysis = {
        "summary": (
            "SCENE CLASS: Indoor / Office CRITICAL RISK: **Direct exposure to potential respiratory hazards** "
            "Core Violation: Non-compliance with respiratory protection requirements "
            "Immediate Risk: The individual faces immediate health risks from inhaling contaminants "
            "Critical Action**: Stop work until PPE is worn. "
            "LEGAL ORDER: Verify whether OSHA 1994 Section 15 controls apply before enforcement action."
        ),
        "visual_evidence": "One worker is visible indoors with missing mask and safety vest.",
        "environment_type": "Indoor / Office",
        "hazards_detected": [
            "Struck-by risk due to reduced worker visibility",
            "Respiratory exposure risk from dust or airborne contaminants",
        ],
        "dosh_regulations_cited": [
            {"regulation": "USECHH Regulations 2000"},
            {"regulation": "JKR Standard Specification Section A"},
        ],
        "persons": [],
    }
    report_data = {
        "caption": "One worker is visible indoors with missing mask and safety vest.",
        "violation_summary": "Missing Mask, Missing Safety Vest",
        "person_count": 1,
        "violation_count": 2,
        "detections": [
            {"class_name": "Person"},
            {"class_name": "NO-Mask"},
            {"class_name": "NO-Safety Vest"},
        ],
    }

    summary = subject._format_summary_html(analysis, report_data)

    _assert(summary.count('class="summary-bullet-list"') >= 3, "WHAT/DANGER/LAW should render as bullet lists")
    _assert('<strong class="summary-item-label">Scene class:</strong>' in summary, "WHAT row should expose labeled line items")
    _assert('<strong class="summary-item-label">Critical risk:</strong>' in summary, "Critical risk should be a line-item label")
    what_segment = summary.split('<td class="summary-label">WHAT</td>', 1)[1].split('<td class="summary-label">DANGER</td>', 1)[0]
    law_segment = summary.split('<td class="summary-label">LAW</td>', 1)[1]
    _assert("Legal order:" not in what_segment, "Legal order should not be merged into WHAT")
    _assert("Legal order:" in law_segment, "Legal order should be rendered in LAW")
    _assert("**" not in summary, "Markdown bold markers must not leak into executive summary")
    _assert("summary-value-danger" in summary, "DANGER row should keep danger styling without bolding all copy")
    _assert("Respirator</span>y" not in summary, "Tooltip injection must not split the word respiratory")


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
        test_fallback_office_ppe_gaps_do_not_invent_construction_hazards,
        test_local_activity_augmentation_adds_observed_caption_hint_when_model_omits_it,
        test_environment_detection_does_not_treat_restricted_work_area_as_office,
        test_executive_summary_formats_labeled_what_and_danger_as_bullets,
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
