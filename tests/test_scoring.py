"""Offline tests for agents/agent_synthesizer.calculate_recommendation.

This validates the scoring + recommendation mapping WITHOUT any LLM call.
It reproduces the exact threshold logic: thresholds sorted descending,
first match where score >= threshold wins; otherwise the lowest label.
"""
import os
import sys
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core.data_models import Extraction
from core.config_loader import Config
from agents.agent_synthesizer import calculate_recommendation


@pytest.fixture
def ml_config():
    return Config(config_path=os.path.join(REPO_ROOT, "my_first_review/input"))


@pytest.fixture
def dev_config():
    return Config(config_path=os.path.join(REPO_ROOT, "config"))


def _ext(criterion_id, score):
    return Extraction(
        paper_id="p1",
        criterion_id=criterion_id,
        score=score,
        score_justification="test",
        evidence=[],
        strengths=[],
        weaknesses=[],
        confidence=0.9,
        model_used="test/model",
    )


class TestCalculateRecommendationML:
    """machine_learning thresholds: 85/65/45/0."""

    def test_perfect_score_gives_accept(self, ml_config):
        # All 8 criteria at 5/5 -> 100
        crits = ml_config.criteria
        exts = [_ext(c["id"], 5) for c in crits]
        rec, _rationale, score, _wb = calculate_recommendation(exts, ml_config)
        assert score == pytest.approx(100.0)
        assert rec == "直接接收"

    def test_mid_score_revisions(self, ml_config):
        # All criteria at 4/5 -> 80 -> 修改后接收
        crits = ml_config.criteria
        exts = [_ext(c["id"], 4) for c in crits]
        rec, _r, score, _wb = calculate_recommendation(exts, ml_config)
        assert score == pytest.approx(80.0)
        assert rec == "修改后接收"

    def test_high_65_boundary(self, ml_config):
        # Need exactly >=65: weight mix -> score 65.2 stays 修改后接收
        crits = ml_config.criteria
        # weights: [18,15,16,12,12,10,9,8]
        exts = [_ext(c["id"], s) for c, s in zip(crits, [4,4,4,3,3,3,3,3])]
        rec, _r, score, _wb = calculate_recommendation(exts, ml_config)
        assert 65 <= score < 85
        assert rec == "修改后接收"

    def test_low_score_reject(self, ml_config):
        crits = ml_config.criteria
        exts = [_ext(c["id"], 1) for c in crits]
        rec, _r, score, _wb = calculate_recommendation(exts, ml_config)
        assert score == pytest.approx(20.0)
        assert rec == "拒稿"


class TestCalculateRecommendationDev:
    """development_economics thresholds: 85/70/50/0 (English labels)."""

    def test_accept_boundary(self, dev_config):
        crits = dev_config.criteria
        exts = [_ext(c["id"], 5) for c in crits]
        rec, _r, score, _wb = calculate_recommendation(exts, dev_config)
        assert score == pytest.approx(100.0)
        assert rec == "Accept"

    def test_revisions_band(self, dev_config):
        crits = dev_config.criteria
        exts = [_ext(c["id"], 4) for c in crits]
        rec, _r, score, _wb = calculate_recommendation(exts, dev_config)
        assert rec == "Accept with Revisions"

    def test_resubmit_band(self, dev_config):
        crits = dev_config.criteria
        # score ~50-69
        exts = [_ext(c["id"], s) for c, s in zip(crits, [3,3,3,3,3,2,3,3])]
        rec, _r, score, _wb = calculate_recommendation(exts, dev_config)
        assert rec == "Revise and Resubmit"

    def test_reject_floor(self, dev_config):
        crits = dev_config.criteria
        exts = [_ext(c["id"], 1) for c in crits]
        rec, _r, score, _wb = calculate_recommendation(exts, dev_config)
        assert rec == "Reject"
