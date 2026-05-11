"""
Offline contract test for Gemini vision caption quality controls.

The Gemini SDK caption path must disable 2.5 thinking by default; otherwise
short caption token budgets can be consumed by hidden reasoning and the visible
caption may stop mid-sentence.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.backend.integration.gemini_client import GEMINI_AVAILABLE, GeminiClient


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def _subject():
    subject = GeminiClient.__new__(GeminiClient)
    subject.vision_thinking_budget = 0
    subject.vision_max_output_tokens = 900
    return subject


def test_vision_config_disables_thinking_by_default():
    if not GEMINI_AVAILABLE:
        print("SKIP: google-genai not installed")
        return

    config = _subject()._build_vision_generation_config()
    payload = config.model_dump(by_alias=True, exclude_none=True)
    thinking = payload.get("thinkingConfig") or payload.get("thinking_config") or {}

    _assert(thinking.get("thinkingBudget") == 0, f"Expected thinkingBudget=0, got {thinking!r}")
    _assert(
        payload.get("maxOutputTokens") == 900 or payload.get("max_output_tokens") == 900,
        f"Expected max output tokens to be preserved, got {payload!r}",
    )


def test_short_or_truncated_caption_requires_retry():
    subject = _subject()

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


def test_rich_caption_passes_quality_floor():
    subject = _subject()
    rich = (
        "A street scene shows four visible people, with a blue and white bus parked behind them. "
        "The person on the left is visible from the chest down, wearing a patterned jacket and dark pants. "
        "The next person is visible from the mid-thigh up, wearing a cream-colored jacket, blue jeans, and tan shoes. "
        "Another person is wearing a black coat over a red top, blue jeans, and dark sneakers. "
        "The person on the far right is partially visible from the mid-thigh down, wearing dark pants and dark sneakers. "
        "No PPE is visible on any of the individuals."
    )

    _assert(
        not subject._caption_needs_expansion(rich, "FinishReason.STOP"),
        "Detailed complete caption should pass the Gemini quality floor",
    )


def main():
    tests = [
        test_vision_config_disables_thinking_by_default,
        test_short_or_truncated_caption_requires_retry,
        test_rich_caption_passes_quality_floor,
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

    print("Gemini caption quality contract test passed")


if __name__ == "__main__":
    main()
