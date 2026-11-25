import re
import unicodedata
import urllib.parse

from app.ai.schemas import EditorialPackage


_NUMBER_PATTERN = re.compile(
    r"(?<![\w])(?:[$€£₽]\s*)?[+-]?\d+(?:[.,]\d+)*(?:\s?[%％])?(?![\w])",
    flags=re.UNICODE,
)


def _normalize_number(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _extract_numbers(value: str) -> set[str]:
    return {_normalize_number(item) for item in _NUMBER_PATTERN.findall(value)}


def _normalize_words(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).split())


def _entity_in_source(entity: str, normalized_source: str) -> bool:
    normalized_entity = _normalize_words(entity)
    if not normalized_entity:
        return False
    return f" {normalized_entity} " in f" {normalized_source} "


def validate_editorial_package(
    package: EditorialPackage,
    *,
    source_title: str,
    source_content: str,
    source_url: str,
    max_summary_words: int = 200,
) -> dict[str, object]:
    """Check source consistency and completeness; this is not external fact-checking."""
    source_text = f"{source_title}\n{source_content}"
    source_numbers = _extract_numbers(source_text)
    generated_text = "\n".join(
        [
            package.summary,
            *package.key_points,
            *package.important_numbers,
            *package.caveats,
            *package.channel_variants.model_dump().values(),
        ]
    )
    unsupported_numbers = sorted(_extract_numbers(generated_text) - source_numbers)
    normalized_source = f" {_normalize_words(source_text)} "
    unsupported_entities = sorted(
        entity for entity in package.entities
        if not _entity_in_source(entity, normalized_source)
    )
    try:
        parsed_url = urllib.parse.urlsplit(source_url)
        valid_url = parsed_url.scheme in {"http", "https"} and bool(parsed_url.netloc)
    except ValueError:
        valid_url = False

    summary_word_count = len(package.summary.split())
    checks = [
        {
            "name": "summary_word_limit",
            "passed": summary_word_count <= max_summary_words,
            "severity": "error",
            "details": f"{summary_word_count} words; limit is {max_summary_words}",
        },
        {
            "name": "numeric_consistency",
            "passed": not unsupported_numbers,
            "severity": "error",
            "details": "All generated numeric values appear in the source"
            if not unsupported_numbers
            else "Generated text contains numeric values not found in the source",
            "unsupported_values": unsupported_numbers,
        },
        {
            "name": "entity_grounding",
            "passed": not unsupported_entities,
            "severity": "warning",
            "details": "All extracted entities appear in the source"
            if not unsupported_entities
            else "Some extracted entities could not be matched in the source text",
            "unsupported_entities": unsupported_entities,
        },
        {
            "name": "channel_variants",
            "passed": bool(package.channel_variants.telegram.strip())
            and bool(package.channel_variants.brief.strip()),
            "severity": "error",
            "details": "Telegram and brief variants are present",
        },
        {
            "name": "source_url",
            "passed": valid_url,
            "severity": "error",
            "details": "The source URL is an absolute HTTP(S) URL" if valid_url else "Invalid source URL",
        },
    ]
    return {
        "passed": all(bool(check["passed"]) for check in checks),
        "human_review_required": True,
        "checks": checks,
        "summary_word_count": summary_word_count,
        "unsupported_numbers": unsupported_numbers,
        "unsupported_entities": unsupported_entities,
        "scope_note": (
            "Automated source-consistency checks only. These checks do not verify truth "
            "against external sources; an editor must review the draft before use."
        ),
    }
