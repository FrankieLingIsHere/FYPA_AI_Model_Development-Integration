# Readability: Test setup: document the contract this file protects.
import sys
from pathlib import Path


# Prepare root for the next step.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import caption_image


# Section: run the test environment validation parser handles category prefixes workflow with clear inputs and outputs.
def test_environment_validation_parser_handles_category_prefixes():
    assert caption_image._parse_environment_validation_category("C - person in living room") == "C"
    assert caption_image._parse_environment_validation_category("Category C - home interior") == "C"
    assert caption_image._parse_environment_validation_category("B) office desk area") == "B"
    assert caption_image._parse_environment_validation_category("D: outdoor road") == "D"


# Section: run the test validate work environment invalid residential with provider metadata workflow with clear inputs and outputs.
def test_validate_work_environment_invalid_residential_with_provider_metadata(tmp_path, monkeypatch):
    # Prepare image path for the next step.
    image_path = tmp_path / "scene.jpg"
    image_path.write_bytes(b"not-real-image-but-base64-readable")

    # Section: run the fake generate vision response workflow with clear inputs and outputs.
    def fake_generate_vision_response(**_kwargs):
        # Prepare last provider used for the next step.
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


# Section: run the test validate work environment fails closed on unknown scene workflow with clear inputs and outputs.
def test_validate_work_environment_fails_closed_on_unknown_scene(tmp_path, monkeypatch):
    # Prepare image path for the next step.
    image_path = tmp_path / "unknown.jpg"
    image_path.write_bytes(b"base64-readable")

    # Section: run the fake unparseable response workflow with clear inputs and outputs.
    def fake_unparseable_response(**_kwargs):
        # Prepare last provider used for the next step.
        caption_image._LAST_PROVIDER_USED = "gemini"
        return "This might be a scene, but I cannot classify it."

    monkeypatch.setattr(caption_image, "_generate_vision_response", fake_unparseable_response)
    monkeypatch.setattr(caption_image, "VISION_PROVIDER_ORDER", ["gemini"])

    result = caption_image.validate_work_environment(str(image_path))

    assert result["is_valid"] is False
    assert result["confidence"] == "low"
    assert result["environment_type"] == "unknown"


# Section: run the test validate work environment keeps only construction related scenes valid workflow with clear inputs and outputs.
def test_validate_work_environment_keeps_only_construction_related_scenes_valid(tmp_path, monkeypatch):
    # Prepare image path for the next step.
    image_path = tmp_path / "office.jpg"
    image_path.write_bytes(b"base64-readable")

    # Section: run the fake generate vision response workflow with clear inputs and outputs.
    def fake_generate_vision_response(**_kwargs):
        # Prepare last provider used for the next step.
        caption_image._LAST_PROVIDER_USED = "ollama"
        return "B) office desk area"

    monkeypatch.setattr(caption_image, "_generate_vision_response", fake_generate_vision_response)
    monkeypatch.setattr(caption_image, "VISION_PROVIDER_ORDER", ["ollama"])

    result = caption_image.validate_work_environment(str(image_path))

    assert result["is_valid"] is False
    assert result["confidence"] == "medium"
    assert result["environment_type"] == "office/commercial"
    assert result["provider"] == "ollama"

    # Section: run the fake construction response workflow with clear inputs and outputs.
    def fake_construction_response(**_kwargs):
        # Prepare last provider used for the next step.
        caption_image._LAST_PROVIDER_USED = "ollama"
        return "A - construction site with scaffolding"

    monkeypatch.setattr(caption_image, "_generate_vision_response", fake_construction_response)
    construction_result = caption_image.validate_work_environment(str(image_path))

    assert construction_result["is_valid"] is True
    assert construction_result["confidence"] == "high"
    assert construction_result["environment_type"] == "construction/industrial"

    # Section: run the fake public street response workflow with clear inputs and outputs.
    def fake_public_street_response(**_kwargs):
        # Prepare last provider used for the next step.
        caption_image._LAST_PROVIDER_USED = "ollama"
        return "D - public sidewalk near bus"

    monkeypatch.setattr(caption_image, "_generate_vision_response", fake_public_street_response)
    public_result = caption_image.validate_work_environment(str(image_path))

    assert public_result["is_valid"] is False
    assert public_result["confidence"] == "low"
    assert public_result["environment_type"] == "other"
