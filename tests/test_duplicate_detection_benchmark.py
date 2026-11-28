from scripts.benchmark_duplicate_detection import make_pairs


def test_duplicate_benchmark_pairs_are_deterministic_and_labelled():
    first = make_pairs(100)
    second = make_pairs(100)

    assert first == second
    assert len(first) == 100
    assert all(pair.incoming and pair.candidate for pair in first)
    assert any(pair.is_duplicate for pair in first)
    assert any(not pair.is_duplicate for pair in first)


def test_duplicate_benchmark_covers_english_and_russian_headlines():
    pairs = make_pairs(100)

    assert any("Central bank" in pair.candidate for pair in pairs)
    assert any("Центральный банк" in pair.candidate for pair in pairs)
