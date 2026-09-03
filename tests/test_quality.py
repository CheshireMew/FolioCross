from foliocross.application.quality import check_translation


def test_empty_and_identical_translations_are_errors():
    assert (
        check_translation("A sufficiently long source paragraph for comparison.", "", [], [])[0][
            "category"
        ]
        == "empty"
    )
    issues = check_translation(
        "A sufficiently long source paragraph for comparison.",
        "A sufficiently long source paragraph for comparison.",
        [],
        [],
    )
    assert any(item["category"] == "untranslated" for item in issues)


def test_missing_term_is_warning():
    issues = check_translation(
        "Alice arrived.",
        "她到了。",
        [],
        [{"source": "Alice", "target": "爱丽丝"}],
    )
    assert issues == [
        {
            "category": "terminology",
            "severity": "warning",
            "message": "未发现约定译名：Alice → 爱丽丝",
        }
    ]


def test_residual_source_repetition_and_punctuation_are_detected():
    issues = check_translation(
        "These source words should all become a complete translated sentence for readers.",
        "这些内容 These source words should all become These source words should all become（",
        [],
        [],
    )
    categories = {item["category"] for item in issues}
    assert "source_residue" in categories
    assert "repetition" in categories
    assert "punctuation" in categories
