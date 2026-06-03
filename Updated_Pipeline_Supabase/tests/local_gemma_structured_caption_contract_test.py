"""
Contract tests for the strict-local structured Gemma caption path.

Local Ollama captions should prefer one grounded JSON payload that carries both
a natural caption paragraph and compact activity_context tokens for reporting.
"""
# Readability: Test setup: document the contract this file protects.

import os
import sys
import tempfile
from pathlib import Path

# Prepare root for the next step.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import caption_image


# Section: run the assert workflow with clear inputs and outputs.
def _assert(condition, message):
    # Choose the correct branch before the workflow continues.
    if not condition:
        # Surface the failure with enough context for the caller.
        raise AssertionError(message)


# Section: run the test parse local caption json handles fenced payload workflow with clear inputs and outputs.
def test_parse_local_caption_json_handles_fenced_payload():
    raw = """```json
{
  "scene": "outdoor street scene",
  "people_count": 3,
  "visible_people": ["person in dark jacket", "person in light jacket"],
  "major_objects": ["blue bus", "building"],
  "ppe_visible": []
}
```"""

    # Prepare parsed for the next step.
    parsed = caption_image._try_parse_local_caption_json(raw)

    _assert(isinstance(parsed, dict), "Expected fenced JSON payload to parse")
    _assert(parsed.get("people_count") == 3, f"Unexpected parse result: {parsed!r}")


# Section: run the test render local caption from json is grounded and readable workflow with clear inputs and outputs.
def test_render_local_caption_from_json_is_grounded_and_readable():
    rendered = caption_image._render_local_caption_from_json({
        "scene": "outdoor street scene",
        "people_count": 3,
        "visible_people": ["person in dark jacket and jeans", "person in light-colored jacket and jeans"],
        "major_objects": ["blue bus", "building facade"],
        "ppe_visible": [],
    })

    # Trigger the side effect required for this stage.
    _assert(rendered.startswith("The image shows an outdoor street scene with three visible people"), rendered)
    _assert("including a person in dark jacket and jeans and a person in light-colored jacket and jeans" in rendered, rendered)
    _assert("with a blue bus and a building facade visible nearby" in rendered, rendered)
    _assert("Visible people include" not in rendered, rendered)
    _assert("Major visible objects include" not in rendered, rendered)
    _assert(rendered.endswith("no PPE is clearly visible."), rendered)


# Section: run the test render local caption from json prefers descriptive model caption workflow with clear inputs and outputs.
def test_render_local_caption_from_json_prefers_descriptive_model_caption():
    # Prepare narrative for the next step.
    narrative = (
        "The scene depicts an indoor office setting. An indoor scene shows one visible person. "
        "The person's upper torso and head are visible, and they are seated with a forward-facing posture. "
        "Their gaze is directed forward, slightly downward. The person is wearing a dark blue short-sleeved shirt, "
        "and no eyewear is visible. A thin, light-colored object is held horizontally between their lips. "
        "In the background, there are white wall-mounted shelves with various items, a green wall section, "
        "and a large window with a grid pattern on the right side."
    )
    rendered = caption_image._render_local_caption_from_json({
        "caption": narrative,
        "scene": "indoor office setting",
        "people_count": 1,
        "visible_people": ["person seated in dark blue shirt"],
        "major_objects": ["wall-mounted shelves", "green wall section", "large window"],
        "activity_context": [],
        "ppe_visible": [],
    })

    # Trigger the side effect required for this stage.
    _assert(rendered == narrative, rendered)
    _assert("Visible people include" not in rendered, rendered)
    _assert("surrounding context includes" not in rendered, rendered)


# Section: run the test render local caption from json removes local inference sentences workflow with clear inputs and outputs.
def test_render_local_caption_from_json_removes_local_inference_sentences():
    rendered = caption_image._render_local_caption_from_json({
        "caption": (
            "The image depicts an outdoor street scene with a single person standing on a sidewalk. "
            "The individual is wearing a blue shirt and appears to be looking towards the right. "
            "The scene suggests a typical urban environment with moderate foot traffic. "
            "The overall setting appears safe. "
            "There are no immediately apparent hazards or unusual elements in the background. "
            "The person is not interacting with any machinery or traffic. "
            "The street is a typical urban road."
        ),
        "scene": "outdoor street scene",
        "people_count": 1,
        "visible_people": ["person standing on sidewalk"],
        "major_objects": ["street"],
        "activity_context": ["traffic_interface"],
        "ppe_visible": [],
    })

    # Trigger the side effect required for this stage.
    _assert("single person standing on a sidewalk" in rendered, rendered)
    _assert("appears to be looking towards the right" in rendered, rendered)
    _assert("suggests" not in rendered.lower(), rendered)
    _assert("appears safe" not in rendered.lower(), rendered)
    _assert("hazards" not in rendered.lower(), rendered)
    _assert("unusual elements" not in rendered.lower(), rendered)
    _assert("not interacting" not in rendered.lower(), rendered)
    _assert("typical" not in rendered.lower(), rendered)
    _assert("road or street area" not in rendered, "Traffic evidence already appears in the narrative")


# Section: run the test render local caption from json adds missing no ppe sentence workflow with clear inputs and outputs.
def test_render_local_caption_from_json_adds_missing_no_ppe_sentence():
    # Prepare rendered for the next step.
    rendered = caption_image._render_local_caption_from_json({
        "caption": (
            "A man with dark hair is visible in the frame. "
            "He is wearing a black shirt and a red lanyard. "
            "There is a large plant in the background."
        ),
        "scene": "indoor room",
        "people_count": 1,
        "visible_people": ["man in black shirt"],
        "major_objects": ["large plant"],
        "ppe_visible": "none",
        "activity_context": [],
    })

    # Trigger the side effect required for this stage.
    _assert(rendered.endswith("No PPE is clearly visible."), rendered)


# Section: run the test render local caption from json keeps activity hints readable workflow with clear inputs and outputs.
def test_render_local_caption_from_json_keeps_activity_hints_readable():
    rendered = caption_image._render_local_caption_from_json({
        "scene": "outdoor street scene",
        "people_count": 2,
        "visible_people": ["person on sidewalk wearing dark jacket"],
        "major_objects": ["blue bus", "street bollards"],
        "activity_context": ["traffic_interface", "machinery", "traffic_interface"],
        "ppe_visible": [],
    })

    # Trigger the side effect required for this stage.
    _assert("Visible activity context includes" not in rendered, rendered)
    _assert("The scene also shows" not in rendered, rendered)
    _assert("the surrounding context includes" in rendered, rendered)
    _assert("road or street area with a bus or other vehicle near the person" in rendered, rendered)
    _assert("machinery or mobile plant near the person" in rendered, rendered)
    _assert(rendered.endswith("no PPE is clearly visible."), rendered)


# Section: run the test caption image llava prefers structured local caption without custom prompt workflow with clear inputs and outputs.
def test_caption_image_llava_prefers_structured_local_caption_without_custom_prompt():
    # Prepare original generate for the next step.
    original_generate = caption_image._generate_vision_response
    original_ready = caption_image._ensure_ollama_local_caption_ready
    original_order = list(caption_image.VISION_PROVIDER_ORDER)
    original_strict = caption_image.STRICT_PROVIDER_MODE_SPLIT
    original_profile = os.environ.get("CASM_ROUTING_PROFILE")
    original_order_env = os.environ.get("VISION_PROVIDER_ORDER")

    temp_path = None
    try:
        # Prepare strict provider mode split for the next step.
        caption_image.STRICT_PROVIDER_MODE_SPLIT = True
        caption_image.VISION_PROVIDER_ORDER = ["ollama"]
        os.environ["CASM_ROUTING_PROFILE"] = "local"
        os.environ["VISION_PROVIDER_ORDER"] = "ollama"

        # Section: run the fake generate workflow with clear inputs and outputs.
        def _fake_generate(prompt, image_base64, temperature=0.6, max_tokens=300, **kwargs):
            # Choose the correct branch before the workflow continues.
            if "Return JSON only" not in prompt:
                # Surface the failure with enough context for the caller.
                raise AssertionError("Expected structured local prompt to be used first")
            if "caption" not in prompt or "activity_context" not in prompt or max_tokens != caption_image.LOCAL_OLLAMA_STRUCTURED_CAPTION_MAX_TOKENS:
                raise AssertionError("Expected one structured local caption/activity call")
            if kwargs.get("ollama_format") is not None:
                raise AssertionError("Strict local vision captions should avoid Ollama schema format because it can stall Gemma vision")
            if (kwargs.get("ollama_options") or {}).get("num_ctx") != 1536:
                raise AssertionError("Expected detail-preserving Ollama context for structured local caption")
            return """```json
{
  "caption": "The scene depicts an indoor room. An indoor scene shows one visible person. The person's upper body is visible, and he appears seated while facing forward. He is wearing a grey shirt, and no PPE is clearly visible. A couch and a backpack are visible nearby.",
  "scene": "indoor room",
  "people_count": 1,
  "visible_people": ["man wearing a grey shirt"],
  "major_objects": ["couch", "backpack"],
  "activity_context": [],
  "ppe_visible": []
}
```"""

        # Prepare generate vision response for the next step.
        caption_image._generate_vision_response = _fake_generate
        caption_image._ensure_ollama_local_caption_ready = lambda: {"ready": True}

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as handle:
            # Trigger the side effect required for this stage.
            handle.write(b"fake-image-bytes")
            temp_path = handle.name

        rendered = caption_image.caption_image_llava(temp_path)

        # Trigger the side effect required for this stage.
        _assert(rendered.startswith("The scene depicts an indoor room."), rendered)
        _assert("The person's upper body is visible" in rendered, rendered)
        _assert("A couch and a backpack are visible nearby." in rendered, rendered)
        _assert("no PPE is clearly visible" in rendered, rendered)
    finally:
        caption_image._generate_vision_response = original_generate
        caption_image._ensure_ollama_local_caption_ready = original_ready
        caption_image.VISION_PROVIDER_ORDER = original_order
        caption_image.STRICT_PROVIDER_MODE_SPLIT = original_strict
        # Choose the correct branch before the workflow continues.
        if original_profile is None:
            # Trigger the side effect required for this stage.
            os.environ.pop("CASM_ROUTING_PROFILE", None)
        else:
            os.environ["CASM_ROUTING_PROFILE"] = original_profile
        if original_order_env is None:
            os.environ.pop("VISION_PROVIDER_ORDER", None)
        else:
            os.environ["VISION_PROVIDER_ORDER"] = original_order_env
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


# Section: run the main workflow with clear inputs and outputs.
def main():
    # Prepare tests for the next step.
    tests = [
        test_parse_local_caption_json_handles_fenced_payload,
        test_render_local_caption_from_json_is_grounded_and_readable,
        test_render_local_caption_from_json_prefers_descriptive_model_caption,
        test_render_local_caption_from_json_removes_local_inference_sentences,
        test_render_local_caption_from_json_adds_missing_no_ppe_sentence,
        test_render_local_caption_from_json_keeps_activity_hints_readable,
        test_caption_image_llava_prefers_structured_local_caption_without_custom_prompt,
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

    print("Local Gemma structured caption contract test passed")


# Choose the correct branch before the workflow continues.
if __name__ == "__main__":
    main()
