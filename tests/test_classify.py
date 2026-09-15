"""score_document(): covers the current (as of this session) behaviour of
the relevance-scoring formula, including the threshold defect flagged in
the audit but not yet fixed (the user wants to decide the new formula
themselves). These are characterization tests, not an endorsement of the
formula - if/when `score_document` changes, the marked test below should
be the first thing updated, since it exists specifically to catch that
change.
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


def test_single_hit_out_of_many_keywords_still_clears_the_threshold():
    """Documents the audit's threshold-defect finding: with the current
    formula `score = min(0.95, 0.35 + (hits/len(keywords_any)) * 0.6)`, a
    SINGLE keyword hit out of an arbitrarily long keyword list already
    scores above the default relevance_threshold (0.35) - since even
    hits=1 gives 0.35 + tiny_ratio*0.6 > 0.35. The threshold is close to
    non-functional as a filter. Not fixed in this session; this test just
    pins the current, known-imperfect behaviour so a future formula change
    is a deliberate, visible edit here.
    """
    many_keywords = [f"слово{i}" for i in range(20)]
    profile = _profile(keywords_any=many_keywords)
    text = "документ содержит только слово0 и больше ничего релевантного"
    score, reason = score_document(text, profile)
    assert reason == "keywords"
    assert score > 0.35, "current formula clears the default threshold on a single hit"


def test_all_keywords_hit_caps_at_point95():
    keywords = ["труд", "работник", "увольнение"]
    profile = _profile(keywords_any=keywords)
    text = "труд работник увольнение"
    score, reason = score_document(text, profile)
    assert reason == "keywords"
    assert score == pytest.approx(min(0.95, 0.35 + 1.0 * 0.6))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
