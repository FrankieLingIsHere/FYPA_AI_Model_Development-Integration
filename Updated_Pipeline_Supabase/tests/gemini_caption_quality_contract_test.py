"""
Offline contract test for Gemini vision caption quality controls.

The Gemini SDK caption path must disable 2.5 thinking by default; otherwise
short caption token budgets can be consumed by hidden reasoning and the visible
caption may stop mid-sentence.
"""
# Readability: Test setup: document the contract this file protects.

import sys
from pathlib import Path

# Prepare root for the next step.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.backend.integration.gemini_client import (
    DEFAULT_GEMINI_MODEL_CANDIDATES,
    GEMINI_AVAILABLE,
    GeminiClient,
)


# Section: run the assert workflow with clear inputs and outputs.
def _assert(condition, message):
    # Choose the correct branch before the workflow continues.
    if not condition:
        # Surface the failure with enough context for the caller.
        raise AssertionError(message)


# Section: run the subject workflow with clear inputs and outputs.
def _subject():
    subject = GeminiClient.__new__(GeminiClient)
    subject.vision_thinking_budget = 0
    subject.vision_max_output_tokens = 900
    return subject


# Section: run the test vision config disables thinking by default workflow with clear inputs and outputs.
def test_vision_config_disables_thinking_by_default():
    # Choose the correct branch before the workflow continues.
    if not GEMINI_AVAILABLE:
        # Trigger the side effect required for this stage.
        print("SKIP: google-genai not installed")
        return

    config = _subject()._build_vision_generation_config()
    payload = config.model_dump(by_alias=True, exclude_none=True)
    thinking = payload.get("thinkingConfig") or payload.get("thinking_config") or {}

    _assert(thinking.get("thinkingBudget") == 0, f"Expected thinkingBudget=0, got {thinking!r}")
    # Trigger the side effect required for this stage.
    _assert(
        payload.get("maxOutputTokens") == 900 or payload.get("max_output_tokens") == 900,
        f"Expected max output tokens to be preserved, got {payload!r}",
    )


# Section: run the test short or truncated caption requires retry workflow with clear inputs and outputs.
def test_short_or_truncated_caption_requires_retry():
    subject = _subject()

    # Prepare truncated for the next step.
    truncated = (
        "This urban street scene features four visible people walking on a sunny day. "
        "A man with a beard and dark sunglasses stands with his arms"
    )
    _assert(
        subject._caption_needs_expansion(truncated, "FinishReason.MAX_TOKENS"),
        "MAX_TOKENS caption must require expansion",
    )
    _assert(
        subject._caption_needs_expansion("The person on the far left is partially.", ""),
        "Semantically incomplete caption must require expansion",
    )


# Section: run the test rich caption passes quality floor workflow with clear inputs and outputs.
def test_rich_caption_passes_quality_floor():
    # Prepare subject for the next step.
    subject = _subject()
    rich = (
        "A street scene shows four visible people, with a blue and white bus parked behind them. "
        "The person on the left is visible from the chest down, wearing a patterned jacket and dark pants. "
        "The next person is visible from the mid-thigh up, wearing a cream-colored jacket, blue jeans, and tan shoes. "
        "Another person is wearing a black coat over a red top, blue jeans, and dark sneakers. "
        "The person on the far right is partially visible from the mid-thigh down, wearing dark pants and dark sneakers. "
        "No PPE is visible on any of the individuals."
    )

    # Trigger the side effect required for this stage.
    _assert(
        not subject._caption_needs_expansion(rich, "FinishReason.STOP"),
        "Detailed complete caption should pass the Gemini quality floor",
    )


# Section: run the test default cloud caption prompt matches descriptive style workflow with clear inputs and outputs.
def test_default_cloud_caption_prompt_matches_descriptive_style():
    subject = _subject()
    subject._initialized = True
    # Prepare client for the next step.
    subject.client = object()
    subject.max_retries = 1
    subject._load_image_as_part = lambda image_path: object()
    subject._rate_limit = lambda: None
    captured = {}

    # Section: run the fake caption once workflow with clear inputs and outputs.
    def _fake_caption_once(prompt, image_part, *, temperature=0.3, max_output_tokens=None):
        # Prepare values needed by the next step.
        captured["prompt"] = prompt
        captured["temperature"] = temperature
        captured["max_output_tokens"] = max_output_tokens
        return (
            "The scene depicts an indoor office setting. An indoor scene shows one visible person. "
            "The person's upper torso and head are visible, and they are seated with a forward-facing posture. "
            "Their gaze is directed forward, slightly downward. The person is wearing a dark blue short-sleeved shirt. "
            "No PPE is clearly visible.",
            "FinishReason.STOP",
        )

    # Prepare call gemini caption once for the next step.
    subject._call_gemini_caption_once = _fake_caption_once

    result = GeminiClient.caption_image(subject, "dummy.jpg")
    prompt = captured.get("prompt", "")

    _assert(result.startswith("The scene depicts an indoor office setting."), result)
    _assert("5-8 complete narrative sentences" in prompt, prompt)
    _assert("visible body region, posture, gaze direction, clothing, eyewear, held objects" in prompt, prompt)
    _assert("no PPE is clearly visible" in prompt, prompt)
    # Trigger the side effect required for this stage.
    _assert("Do not state that hazards, unusual elements, machinery, or traffic interactions are absent" in prompt, prompt)


# Section: run the test caption normalization keeps descriptive opening and filters inference workflow with clear inputs and outputs.
def test_caption_normalization_keeps_descriptive_opening_and_filters_inference():
    subject = _subject()
    caption = (
        "The image depicts an outdoor street scene with a single person standing on a sidewalk. "
        "The person is wearing a blue shirt and appears to be facing forward with a neutral gaze. "
        "The scene is a typical urban street environment. "
        "There are no immediately apparent hazards or unusual elements in the background."
    )

    # Prepare cleaned for the next step.
    cleaned = subject._strip_caption_inference_sentences(subject._normalize_caption_text(caption))

    _assert(cleaned.startswith("The image depicts an outdoor street scene"), cleaned)
    _assert("typical" not in cleaned.lower(), cleaned)
    _assert("hazards" not in cleaned.lower(), cleaned)


# Section: run the test default model candidates include current flash aliases workflow with clear inputs and outputs.
def test_default_model_candidates_include_current_flash_aliases():
    _assert("gemini-flash-lite-latest" in DEFAULT_GEMINI_MODEL_CANDIDATES, DEFAULT_GEMINI_MODEL_CANDIDATES)
    # Trigger the side effect required for this stage.
    _assert("gemini-flash-latest" in DEFAULT_GEMINI_MODEL_CANDIDATES, DEFAULT_GEMINI_MODEL_CANDIDATES)


# Section: run the test caption failover switches vision model name workflow with clear inputs and outputs.
def test_caption_failover_switches_vision_model_name():
    subject = _subject()
    subject.model_candidates = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-flash-lite-latest",
    ]
    # Prepare model name for the next step.
    subject.model_name = "gemini-2.5-flash"
    subject.vision_model_name = "gemini-2.5-flash"
    subject.last_model_switch_reason = None

    switched = subject._try_switch_to_next_model("quota/resource exhaustion (caption)", target="vision")

    _assert(switched is True, "Expected caption failover to switch models")
    _assert(subject.vision_model_name == "gemini-2.5-flash-lite", subject.vision_model_name)
    _assert(subject.model_name == "gemini-2.5-flash", "Caption failover should not rewrite report model")


# Section: run the test truncated report json keeps grounding fields for schema completion workflow with clear inputs and outputs.
def test_truncated_report_json_keeps_grounding_fields_for_schema_completion():
    # Prepare subject for the next step.
    subject = _subject()
    subject.last_parse_strategy = None
    raw = (
        '{\n'
        '  "environment_type": "Indoor / Office",\n'
        '  "visual_evidence": "The scene depicts an indoor office setting with one person whose head and upper torso are'
    )

    parsed = subject._parse_json_from_response_text(raw)

    # Trigger the side effect required for this stage.
    _assert(parsed is not None, "Expected partial Gemini JSON to be recoverable")
    _assert(parsed.get("environment_type") == "Indoor / Office", parsed)
    _assert("indoor office setting" in parsed.get("visual_evidence", ""), parsed)
    _assert(subject.last_parse_strategy == "partial_top_level_fields", subject.last_parse_strategy)


# Section: run the main workflow with clear inputs and outputs.
def main():
    tests = [
        test_vision_config_disables_thinking_by_default,
        test_short_or_truncated_caption_requires_retry,
        test_rich_caption_passes_quality_floor,
        test_default_cloud_caption_prompt_matches_descriptive_style,
        test_caption_normalization_keeps_descriptive_opening_and_filters_inference,
        test_default_model_candidates_include_current_flash_aliases,
        test_caption_failover_switches_vision_model_name,
        test_truncated_report_json_keeps_grounding_fields_for_schema_completion,
    ]
    # Prepare failures for the next step.
    failures = []
    for test_fn in tests:
        # Protect this step so expected failures can fall back cleanly.
        try:
            # Trigger the side effect required for this stage.
            test_fn()
            print(f"PASS: {test_fn.__name__}")
        except Exception as exc:
            failures.append((test_fn.__name__, str(exc)))
            print(f"FAIL: {test_fn.__name__}: {exc}")

    # Choose the correct branch before the workflow continues.
    if failures:
        raise SystemExit(1)

    print("Gemini caption quality contract test passed")


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    main()
