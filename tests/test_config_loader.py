"""Offline tests for core/config_loader.py.

These tests exercise the configuration loading logic WITHOUT any API keys,
network, or LLM calls. They validate the invariant that matters most for a
scoring system: criteria weights sum to 100 and recommendation thresholds
sort correctly (highest first).
"""
import os
import sys
import pytest

# Ensure repo root is importable when running `pytest` from the repo root.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core.config_loader import Config, MODEL_DEFAULTS, DEFAULT_THRESHOLDS


def _config_for(dirname):
    return Config(config_path=os.path.join(REPO_ROOT, dirname))


class TestConfigGlobal:
    """Global config/criteria.yaml (development_economics)."""

    def test_global_criteria_weights_sum_to_100(self):
        cfg = _config_for("config")
        weights = [c["weight"] for c in cfg.criteria]
        assert sum(weights) == 100, f"weights sum to {sum(weights)}, expected 100"

    def test_global_criteria_nonempty(self):
        cfg = _config_for("config")
        assert len(cfg.criteria) >= 1

    def test_global_domain(self):
        cfg = _config_for("config")
        assert cfg.domain == "development_economics"

    def test_global_default_thresholds_present(self):
        cfg = _config_for("config")
        assert cfg.recommendation_thresholds


class TestConfigRunDir:
    """my_first_review/input/criteria.yaml (machine_learning run)."""

    def test_run_criteria_weights_sum_to_100(self):
        cfg = _config_for("my_first_review/input")
        weights = [c["weight"] for c in cfg.criteria]
        assert sum(weights) == 100, f"weights sum to {sum(weights)}, expected 100"

    def test_run_criteria_count(self):
        cfg = _config_for("my_first_review/input")
        assert len(cfg.criteria) == 8

    def test_run_domain(self):
        cfg = _config_for("my_first_review/input")
        assert cfg.domain == "machine_learning"

    def test_run_thresholds_sorted_desc(self):
        cfg = _config_for("my_first_review/input")
        thr = [t["threshold"] for t in cfg.recommendation_thresholds]
        assert thr == sorted(thr, reverse=True), f"thresholds not sorted desc: {thr}"

    def test_threshold_contains_reject_floor(self):
        cfg = _config_for("my_first_review/input")
        assert any(t["threshold"] == 0 for t in cfg.recommendation_thresholds)


class TestDefaults:
    """DEFAULT_THRESHOLDS must be a sane fallback."""

    def test_default_thresholds_sort_desc(self):
        thr = [t["threshold"] for t in DEFAULT_THRESHOLDS]
        assert thr == sorted(thr, reverse=True)

    def test_default_thresholds_have_reject_floor(self):
        assert any(t["threshold"] == 0 for t in DEFAULT_THRESHOLDS)

    def test_model_defaults_keys(self):
        for key in (
            "extractor_provider",
            "extractor_model",
            "synthesizer_provider",
            "synthesizer_model",
            "judge_provider",
            "judge_model",
        ):
            assert key in MODEL_DEFAULTS
