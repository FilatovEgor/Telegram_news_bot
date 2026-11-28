from app.sources.urls import (
    canonicalize_url,
    normalize_title,
    normalized_content_hash,
    title_similarity,
)


def test_canonical_url_removes_tracking_and_fragments():
    value = "HTTPS://WWW.Example.COM:443/news?id=7&utm_source=mail&fbclid=click#section"
    assert canonicalize_url(value) == "https://example.com/news?id=7"


def test_canonical_url_preserves_meaningful_query_parameters():
    assert canonicalize_url("http://www.example.org:8080/story?z=2&a=1") == (
        "http://example.org:8080/story?a=1&z=2"
    )


def test_canonical_url_rejects_non_http_urls():
    assert canonicalize_url("javascript:alert(1)") is None
    assert canonicalize_url("/relative/path") is None


def test_content_hash_normalizes_unicode_and_whitespace():
    assert normalized_content_hash("  ＨＥＬＬＯ\nWorld ") == normalized_content_hash("hello world")
    assert normalized_content_hash("  \n ") is None


def test_title_similarity_is_punctuation_and_case_insensitive():
    assert normalize_title("  Oil prices: RISE! ") == "oil prices rise"
    assert title_similarity("Oil prices rise!", "OIL PRICES RISE") == 1.0
    assert title_similarity("Oil prices rise", "Football results") < 0.5


def test_normalized_title_similarity_preserves_sequence_matcher_results():
    from app.sources.urls import normalized_title_similarity

    left = normalize_title("Central bank keeps interest rates steady")
    right = normalize_title("Central bank holds interest rates steady")
    assert normalized_title_similarity(left, right) == title_similarity(
        "Central bank keeps interest rates steady",
        "Central bank holds interest rates steady",
    )


def test_length_bound_skips_pairs_that_cannot_meet_threshold(monkeypatch):
    import app.sources.urls as urls_module

    def unexpected_matcher(*_args, **_kwargs):
        raise AssertionError("SequenceMatcher should not run when the length bound fails")

    monkeypatch.setattr(urls_module.difflib, "SequenceMatcher", unexpected_matcher)
    assert urls_module.normalized_title_similarity("a" * 10, "a" * 100, 0.92) == 0.0
