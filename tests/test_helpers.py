"""Offline tests for utilities/helpers.py.

Covers the pure functions that do not require LLM calls: filename
sanitization, weight-table rendering, config hashing, and the novelty
score adjustment used by the Critic agent and literature pipeline.
"""
import os
import sys
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from utilities.helpers import (
    sanitize_model_name,
    get_weights_table,
    get_config_hash,
    get_judge_config_hash,
    calculate_novelty_adjusted_score,
)


class TestSanitizeModelName:
    def test_slashes_become_underscores(self):
        assert sanitize_model_name("openai/gpt-4o") == "openai_gpt-4o"

    def test_colons_become_underscores(self):
        assert sanitize_model_name("provider:model") == "provider_model"

    def test_backslashes_become_underscores(self):
        assert sanitize_model_name("a\\b") == "a_b"

    def test_windows_forbidden_chars_removed(self):
        out = sanitize_model_name('m<>:"|?*')
        assert not set(out) & set('<>:"|?*')

    def test_empty_stays_empty(self):
        assert sanitize_model_name("") == ""

    def test_roundtrip_common_model(self):
        # The exact format the output generator relies on.
        assert sanitize_model_name("deepseek/deepseek-v4-pro") == "deepseek_deepseek-v4-pro"


class TestWeightsTable:
    def test_renders_header_and_rows(self):
        criteria = [
            {"id": "a", "name": "Alpha", "weight": 60},
            {"id": "b", "name": "Beta", "weight": 40},
        ]
        table = get_weights_table(criteria)
        assert "| Criterion ID | Name | Weight |" in table
        assert "| a | Alpha | 60 |" in table
        assert "| b | Beta | 40 |" in table


class TestConfigHash:
    def test_hash_is_deterministic(self):
        h1 = get_config_hash(_stub_config())
        h2 = get_config_hash(_stub_config())
        assert h1 == h2

    def test_hash_changes_with_criteria(self):
        h1 = get_config_hash(_stub_config())
        c2 = _stub_config()
        c2.criteria_config = {"criteria": [{"id": "x", "weight": 99}]}
        h2 = get_config_hash(c2)
        assert h1 != h2


class TestJudgeConfigHash:
    def test_judge_hash_deterministic(self):
        import os
        old = {k: os.environ.get(k) for k in ("JUDGE_PROVIDER", "JUDGE_MODEL", "JUDGE_TEMPERATURE")}
        try:
            os.environ["JUDGE_PROVIDER"] = "deepseek"
            os.environ["JUDGE_MODEL"] = "deepseek-v4-pro"
            os.environ["JUDGE_TEMPERATURE"] = "0.1"
            assert get_judge_config_hash() == get_judge_config_hash()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class TestNoveltyAdjustedScore:
    """Shared by Critic agent and the literature pipeline wrapper."""

    def _extraction(self, novelty=3, contradicts=False, extends=False):
        import types
        return types.SimpleNamespace(
            novelty_ranking=novelty,
            contradicts_baseline=contradicts,
            extends_baseline=extends,
        )

    def test_no_extractions_returns_base(self):
        assert calculate_novelty_adjusted_score(80.0, []) == 80.0

    def test_neutral_novelty_no_change(self):
        exts = [self._extraction(3)]
        assert calculate_novelty_adjusted_score(80.0, exts) == pytest.approx(80.0)

    def test_high_novelty_boosts(self):
        exts = [self._extraction(5)]
        # (5-3)*0.025 = +0.05 -> 80 * 1.05 = 84
        assert calculate_novelty_adjusted_score(80.0, exts) == pytest.approx(84.0)

    def test_low_novelty_penalizes(self):
        exts = [self._extraction(1)]
        # (1-3)*0.025 = -0.05 -> 80 * 0.95 = 76
        assert calculate_novelty_adjusted_score(80.0, exts) == pytest.approx(76.0)

    def test_contradiction_penalty(self):
        exts = [self._extraction(3, contradicts=True)]
        # -0.05 -> 80 * 0.95 = 76
        assert calculate_novelty_adjusted_score(80.0, exts) == pytest.approx(76.0)

    def test_extension_bonus(self):
        exts = [self._extraction(3, extends=True)]
        # +0.03 -> 80 * 1.03 = 82.4
        assert calculate_novelty_adjusted_score(80.0, exts) == pytest.approx(82.4)

    def test_clamped_at_100(self):
        exts = [self._extraction(5)] * 10
        assert calculate_novelty_adjusted_score(99.0, exts) <= 100.0

    def test_clamped_at_0(self):
        exts = [self._extraction(1, contradicts=True)] * 10
        assert calculate_novelty_adjusted_score(5.0, exts) >= 0.0


def _stub_config():
    """A minimal object with the attributes get_config_hash touches."""
    import types
    cfg = types.SimpleNamespace()
    cfg.get_llm_config = lambda: {
        "extractor_provider": "openai",
        "extractor_model": "gpt-5.4-nano",
        "synthesizer_provider": "openai",
        "synthesizer_model": "gpt-5.4-nano",
        "temperature": 0.2,
        "max_retries": 3,
        "max_parallel": 5,
        "judge_provider": "deepseek",
        "judge_model": "deepseek-v4-pro",
        "judge_temperature": 0.1,
    }
    cfg.criteria_config = {"criteria": [{"id": "a", "weight": 100}]}
    cfg.config_path = os.path.join(REPO_ROOT, "config")
    return cfg
