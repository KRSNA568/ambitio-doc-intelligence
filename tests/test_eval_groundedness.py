"""Tests for the eval's sentence handling and groundedness scoring."""

import eval as eval_mod


def test_strips_citation_markers():
    sents = eval_mod.split_sentences("The deal closed in 2021 [E1]. It was signed [E2].")
    assert all("[E" not in s for s in sents)
    assert len(sents) == 2


def test_drops_section_headers_and_short_labels():
    text = "Timeline:\n- A real event happened on this date here.\nDamages:"
    sents = eval_mod.split_sentences(text)
    # Header-only lines like "Timeline:" / "Damages:" must not count as claims.
    assert "Timeline:" not in sents
    assert any("real event happened" in s for s in sents)


def test_abbreviations_do_not_split_sentence():
    sents = eval_mod.split_sentences("Meridian Logistics, Inc. sued the defendant company.")
    assert len(sents) == 1


def test_max_rouge_l_high_for_grounded_sentence():
    chunks = ["The dispute began in March 2021 when deliveries fell short."]
    score = eval_mod.max_rouge_l("The dispute began in March 2021", chunks)
    assert score > 0.5


def test_max_rouge_l_low_for_unsupported_sentence():
    chunks = ["The dispute began in March 2021 when deliveries fell short."]
    # No lexical overlap with the chunk -> should score near zero.
    score = eval_mod.max_rouge_l("Bananas ripen quickly under tropical sunshine", chunks)
    assert score < 0.2


def test_evaluate_reports_unsupported_count():
    chunks = ["Alpha beta gamma delta epsilon zeta eta theta."]
    result = eval_mod.evaluate(
        "Alpha beta gamma delta epsilon zeta. Completely unrelated invented claim here.",
        chunks,
    )
    assert result["num_sentences"] == 2
    assert result["num_unsupported"] >= 1
