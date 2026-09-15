"""score_document(): the relevance-scoring formula that decides which
documents surface in the shortlist. Replaces the formula redesigned this
session - the old one (`min(0.95, 0.35 + (hits/len(keywords_any)) * 0.6)`)
had a base constant that happened to equal the default
`relevance_threshold` (0.35), so a SINGLE keyword hit out of any
keyword list already cleared the threshold and the filter did almost
nothing (see the superseded characterization test this file used to
carry). The new formula scores on the absolute count of distinct keyword
hits, with diminishing returns, independent of how many keywords a
profile's list happens to contain - see score_document()'s docstring for
the full reasoning.
"""
from __future__ import annotations

import pytest

from legal_monitor.config import Profile, ProfileRules
from legal_monitor.pipeline.classify import score_document


def _profile(keywords_any, keywords_exclude=()):
    return Profile(
        id="test",
        name="Test",
        enabled=True,
        description="",
        rules=ProfileRules(keywords_any=list(keywords_any), keywords_exclude=list(keywords_exclude)),
    )


def test_excluded_keyword_wins_over_any_match():
    profile = _profile(keywords_any=["труд"], keywords_exclude=["черновик"])
    score, reason = score_document("трудовой договор, черновик документа", profile)
    assert (score, reason) == (0.0, "excluded")


def test_no_rules_scores_zero():
    profile = _profile(keywords_any=[])
    score, reason = score_document("любой текст", profile)
    assert (score, reason) == (0.0, "no_rules")


def test_no_match_scores_zero():
    profile = _profile(keywords_any=["налог", "пошлина"])
    score, reason = score_document("текст про трудовые отношения", profile)
    assert (score, reason) == (0.0, "no_match")


def test_single_hit_out_of_many_keywords_no_longer_clears_default_threshold():
    """The regression this fix targets: a lone, possibly coincidental
    keyword hit out of a large keyword list must NOT automatically clear
    the default relevance_threshold (0.35) any more.
    """
    many_keywords = [f"слово{i}" for i in range(20)]
    profile = _profile(keywords_any=many_keywords)
    text = "документ содержит только слово0 и больше ничего релевантного"
    score, reason = score_document(text, profile)
    assert reason == "keywords"
    assert score == pytest.approx(0.3)
    assert score < 0.35, "a single hit must no longer clear the default threshold"


def test_single_hit_score_is_independent_of_keyword_list_size():
    """The old ratio-based formula scored a hit differently depending on
    how many keywords the profile's list happened to contain (profiles in
    this project range from 3 to 34 keywords, often just stem variants of
    the same word, with no real connection to topic specificity). The new
    formula scores purely on hit count, so a single hit scores the same
    whether the list has 3 keywords or 30.
    """
    small_profile = _profile(keywords_any=["мрот", "труд", "отпуск"])
    large_profile = _profile(keywords_any=[f"слово{i}" for i in range(30)] + ["труд"])

    small_score, _ = score_document("документ про труд", small_profile)
    large_score, _ = score_document("документ про труд", large_profile)

    assert small_score == large_score == pytest.approx(0.3)


def test_two_hits_clear_the_default_threshold():
    profile = _profile(keywords_any=["труд", "работник", "увольнение", "отпуск"])
    score, reason = score_document("труд и работник упомянуты в тексте", profile)
    assert reason == "keywords"
    assert score == pytest.approx(0.51)
    assert score >= 0.35


def test_score_has_diminishing_returns_per_additional_hit():
    keywords = ["труд", "работник", "увольнение", "отпуск", "мрот"]
    profile = _profile(keywords_any=keywords)

    one_hit, _ = score_document("труд", profile)
    two_hits, _ = score_document("труд работник", profile)
    three_hits, _ = score_document("труд работник увольнение", profile)

    gain_1_to_2 = two_hits - one_hit
    gain_2_to_3 = three_hits - two_hits
    assert 0 < gain_2_to_3 < gain_1_to_2, "each additional hit should add less than the previous one"


def test_many_hits_cap_at_point95():
    keywords = [f"слово{i}" for i in range(15)]
    profile = _profile(keywords_any=keywords)
    text = " ".join(keywords)
    score, reason = score_document(text, profile)
    assert reason == "keywords"
    assert score == 0.95


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
