"""
Contract tests for the strict-local structured Gemma caption path.

Local Ollama captions should prefer a grounded JSON payload that we render
deterministically into prose, instead of relying on free-form model wording.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import caption_image


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


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

    parsed = caption_image._try_parse_local_caption_json(raw)

    _assert(isinstance(parsed, dict), "Expected fenced JSON payload to parse")
    _assert(parsed.get("people_count") == 3, f"Unexpected parse result: {parsed!r}")


def test_render_local_caption_from_json_is_grounded_and_readable():
    rendered = caption_image._render_local_caption_from_json({
        "scene": "outdoor street scene",
        "people_count": 3,
        "visible_people": ["person in dark jacket and jeans", "person in light-colored jacket and jeans"],
        "major_objects": ["blue bus", "building facade"],
        "ppe_visible": [],
    })

    _assert(rendered.startswith("This is an outdoor street scene with 3 visible people."), rendered)
    _assert("Visible people include person in dark jacket and jeans" in rendered, rendered)
    _assert("Major visible objects include blue bus, building facade." in rendered, rendered)
    _assert(rendered.endswith("No PPE is visible."), rendered)


def test_render_local_caption_from_json_keeps_activity_hints_readable():
    rendered = caption_image._render_local_caption_from_json({
        "scene": "outdoor street scene",
        "people_count": 2,
        "visible_people": ["person on sidewalk wearing dark jacket"],
        "major_objects": ["blue bus", "street bollards"],
        "activity_context": ["traffic_interface", "machinery", "traffic_interface"],
        "ppe_visible": [],
    })

    _assert("Visible activity context includes" not in rendered, rendered)
    _assert("The scene also shows" in rendered, rendered)
    _assert("road, street, bus, or vehicle area near the person" in rendered, rendered)
    _assert("machinery or mobile plant near the person" in rendered, rendered)
    _assert(rendered.endswith("No PPE is visible."), rendered)


def test_caption_image_llava_prefers_structured_local_caption_without_custom_prompt():
    original_generate = caption_image._generate_vision_response
    original_order = list(caption_image.VISION_PROVIDER_ORDER)
    original_strict = caption_image.STRICT_PROVIDER_MODE_SPLIT
    original_profile = os.environ.get("CASM_ROUTING_PROFILE")
    original_order_env = os.environ.get("VISION_PROVIDER_ORDER")

    temp_path = None
    try:
        caption_image.STRICT_PROVIDER_MODE_SPLIT = True
        caption_image.VISION_PROVIDER_ORDER = ["ollama"]
        os.environ["CASM_ROUTING_PROFILE"] = "local"
        os.environ["VISION_PROVIDER_ORDER"] = "ollama"

        def _fake_generate(prompt, image_base64, temperature=0.6, max_tokens=300):
            if "Return strict JSON only" not in prompt:
                raise AssertionError("Expected structured local prompt to be used first")
            if "activity_context" not in prompt or max_tokens != 300:
                raise AssertionError("Expected structured local activity hints without a second vision call")
            return """```json
{
  "scene": "indoor room",
  "people_count": 1,
  "visible_people": ["man wearing a grey shirt"],
  "major_objects": ["couch", "backpack"],
  "activity_context": [],
  "ppe_visible": []
}
```"""

        caption_image._generate_vision_response = _fake_generate

        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as handle:
            handle.write(b"fake-image-bytes")
            temp_path = handle.name

        rendered = caption_image.caption_image_llava(temp_path)

        _assert(rendered.startswith("This is an indoor room with 1 visible person."), rendered)
        _assert("Visible people include man wearing a grey shirt." in rendered, rendered)
        _assert("Major visible objects include couch, backpack." in rendered, rendered)
        _assert(rendered.endswith("No PPE is visible."), rendered)
    finally:
        caption_image._generate_vision_response = original_generate
        caption_image.VISION_PROVIDER_ORDER = original_order
        caption_image.STRICT_PROVIDER_MODE_SPLIT = original_strict
        if original_profile is None:
            os.environ.pop("CASM_ROUTING_PROFILE", None)
        else:
            os.environ["CASM_ROUTING_PROFILE"] = original_profile
        if original_order_env is None:
            os.environ.pop("VISION_PROVIDER_ORDER", None)
        else:
            os.environ["VISION_PROVIDER_ORDER"] = original_order_env
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def main():
    tests = [
        test_parse_local_caption_json_handles_fenced_payload,
        test_render_local_caption_from_json_is_grounded_and_readable,
        test_render_local_caption_from_json_keeps_activity_hints_readable,
        test_caption_image_llava_prefers_structured_local_caption_without_custom_prompt,
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
        raise SystemExit(1)

    print("Local Gemma structured caption contract test passed")


if __name__ == "__main__":
    main()
