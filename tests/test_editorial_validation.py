from app.ai.schemas import EditorialPackage
from app.ai.validation import validate_editorial_package


def package(**overrides):
    values = {
        "category": "economy",
        "language": "en",
        "summary": "Gazprom reported a 15% increase in exports in 2024.",
        "key_points": ["Exports increased by 15% in 2024."],
        "entities": ["Gazprom"],
        "important_numbers": ["15%", "2024"],
        "channel_variants": {
            "telegram": "Gazprom reported a 15% increase in exports in 2024.",
            "brief": "Gazprom exports rose 15% in 2024.",
        },
        "caveats": [],
        "confidence": 0.85,
    }
    values.update(overrides)
    return EditorialPackage.model_validate(values)


def test_validation_passes_when_numbers_and_entities_are_in_source():
    result = validate_editorial_package(
        package(),
        source_title="Gazprom exports",
        source_content="Gazprom reported a 15% increase in exports during 2024.",
        source_url="https://example.com/news",
    )
    assert result["passed"] is True
    assert result["human_review_required"] is True


def test_validation_flags_unsupported_numbers_and_entities():
    result = validate_editorial_package(
        package(
            summary="Gazprom reported a 25% increase in exports in 2024.",
            important_numbers=["25%", "2024"],
            entities=["ACME"],
            channel_variants={
                "telegram": "Gazprom reported a 25% increase in exports in 2024.",
                "brief": "Exports rose 25% in 2024.",
            },
        ),
        source_title="Gazprom exports",
        source_content="Gazprom reported a 15% increase in exports during 2024.",
        source_url="https://example.com/news",
    )
    assert result["passed"] is False
    assert result["unsupported_numbers"] == ["25%"]
    assert result["unsupported_entities"] == ["ACME"]
    assert result["human_review_required"] is True


def test_validation_reports_summary_word_limit():
    result = validate_editorial_package(
        package(summary="one two three four five"),
        source_title="Gazprom exports",
        source_content="Gazprom reported 15% growth.",
        source_url="https://example.com/news",
        max_summary_words=3,
    )
    failed = [item for item in result["checks"] if item["name"] == "summary_word_limit"]
    assert failed[0]["passed"] is False
