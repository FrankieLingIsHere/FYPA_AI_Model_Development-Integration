import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import caption_image


def test_environment_validation_parser_handles_category_prefixes():
    assert caption_image._parse_environment_validation_category("C - person in living room") == "C"
    assert caption_image._parse_environment_validation_category("Category C - home interior") == "C"
    assert caption_image._parse_environment_validation_category("B) office desk area") == "B"
    assert caption_image._parse_environment_validation_category("D: outdoor road") == "D"


def test_validate_work_environment_invalid_residential_with_provider_metadata(tmp_path, monkeypatch):
    image_path = tmp_path / "scene.jpg"
    image_path.write_bytes(b"not-real-image-but-base64-readable")

    def fake_generate_vision_response(**_kwargs):
        caption_image._LAST_PROVIDER_USED = "gemini"
        return "Category C - person in living room"

    monkeypatch.setattr(caption_image, "_generate_vision_response", fake_generate_vision_response)
    monkeypatch.setattr(caption_image, "VISION_PROVIDER_ORDER", ["gemini"])

    result = caption_image.validate_work_environment(str(image_path))

    assert result["is_valid"] is False
    assert result["confidence"] == "high"
    assert result["environment_type"] == "residential/casual"
    assert result["provider"] == "gemini"
    assert result["vision_provider_order"] == ["gemini"]


def test_validate_work_environment_fails_closed_on_unknown_scene(tmp_path, monkeypatch):
    image_path = tmp_path / "unknown.jpg"
    image_path.write_bytes(b"base64-readable")

    def fake_unparseable_response(**_kwargs):
        caption_image._LAST_PROVIDER_USED = "gemini"
        return "This might be a scene, but I cannot classify it."

    monkeypatch.setattr(caption_image, "_generate_vision_response", fake_unparseable_response)
    monkeypatch.setattr(caption_image, "VISION_PROVIDER_ORDER", ["gemini"])

    result = caption_image.validate_work_environment(str(image_path))

    assert result["is_valid"] is False
    assert result["confidence"] == "low"
    assert result["environment_type"] == "unknown"


def test_validate_work_environment_keeps_only_construction_related_scenes_valid(tmp_path, monkeypatch):
    image_path = tmp_path / "office.jpg"
    image_path.write_bytes(b"base64-readable")

    def fake_generate_vision_response(**_kwargs):
        caption_image._LAST_PROVIDER_USED = "ollama"
        return "B) office desk area"

    monkeypatch.setattr(caption_image, "_generate_vision_response", fake_generate_vision_response)
    monkeypatch.setattr(caption_image, "VISION_PROVIDER_ORDER", ["ollama"])

    result = caption_image.validate_work_environment(str(image_path))

    assert result["is_valid"] is False
    assert result["confidence"] == "medium"
    assert result["environment_type"] == "office/commercial"
    assert result["provider"] == "ollama"

    def fake_construction_response(**_kwargs):
        caption_image._LAST_PROVIDER_USED = "ollama"
        return "A - construction site with scaffolding"

    monkeypatch.setattr(caption_image, "_generate_vision_response", fake_construction_response)
    construction_result = caption_image.validate_work_environment(str(image_path))

    assert construction_result["is_valid"] is True
    assert construction_result["confidence"] == "high"
    assert construction_result["environment_type"] == "construction/industrial"

    def fake_public_street_response(**_kwargs):
        caption_image._LAST_PROVIDER_USED = "ollama"
        return "D - public sidewalk near bus"

    monkeypatch.setattr(caption_image, "_generate_vision_response", fake_public_street_response)
    public_result = caption_image.validate_work_environment(str(image_path))

    assert public_result["is_valid"] is False
    assert public_result["confidence"] == "low"
    assert public_result["environment_type"] == "other"
