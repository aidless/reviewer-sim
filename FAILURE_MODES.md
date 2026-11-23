# Failure modes

The stored run can look more consistent than it is. `make check` recomputes the counts in the block. These are the ways the pipeline and the files fail closed, or fail to mean what a casual reading suggests.

**Missing criteria are scored as zero.** `calculate_recommendation` adds nothing for a criterion that is absent from the review, and it still divides by the sum of every weight. The published overall matches that rule on every stored review. It does not match an average that drops the missing weights. That second figure is `reviews_present_denominator_differs` in the block. A reader who averages the criterion lines that are actually printed will not recover the published overall for those reviews.

**A score of 0 is outside the scale and is still accepted.** The run config scale is 1 to 5. `Extraction.score` is an int with no lower bound, so a 0 is stored, printed, and copied into the CSV. It contributes nothing to the numerator, which is a different situation from a missing line only in that the file records a number.

**The filename clock is not the review clock.** Four review filenames are 8 hours ahead of the Review Date in the file and of the CSV timestamp. Joining on the filename clock drops those rows. Joining on the paper stem plus the review minute matches every CSV row (`unpaired_reviews` and `unpaired_csv_rows` in the block).

**The CSV repeats `overall_score`.** Both copies agree on every row. `csv.DictReader` keeps the later copy. Here that does not change the value. Two of the CSV files are byte-identical; the names are in the block. Counting files over-counts snapshots. The demo GIF tails an `ls` listing, so a frame can show three names without the directory containing only those files.

**`progress.json` is a partial latest-run cache.** It matches the latest stored review for the papers it names and omits the other stems and the earlier reruns. The ingestion cache has fewer PDFs than the reviews name, and one `original_path` is an absolute Windows path under `agentic-paper-review`.

**Repeated runs of one model do not repeat the score.** The per-file spans are in the block. That spread is not inter-model agreement. `cross_model_pairs` is 0 because `model_count` is 1. No interval is reported.

**Displayed cost is a rounding of a cell, not a price list.** Markdown prints the CSV cost at four decimal places, and those strings match. The two-decimal form 0.22 is one cell (`cited_main_1_13_12_cost_usd`). The sum of the unique rows is `unique_cost_sum_usd`. Neither is a per-paper rate, and neither will be the cost of the next call.

**The dashboard does not authenticate.** It binds `web_port` from the block. Do not put it on an open network.

**`make check` does not call a model.** An API key is required to produce a new review, and a new review will not reproduce these files. The check recomputes arithmetic, pairings, and file counts only.

**The bundled PDFs are not under the code license.** `LICENSE` is MIT for the software. The run PDF names an author in its metadata and has no license field. `papers/PAPER5_main.pdf` is a different double-blind manuscript and is not an input of the stored run. Embedded font licenses are not a license for the paper text. The cache also contains the author contact lines from the ingested text; they are not credentials.

**Version strings.** `npm_scaffold_version` in the block is `package.json`. That file is a private npm scaffold and is not a release. There is no Python package version. The publish workflow finds no `pyproject.toml`, `setup.py`, or `setup.cfg` and skips the build. This repository is not on PyPI because those files are absent, not because a release was yanked.

**Hosted pages.** The UNU C3 user guide and blog are the author's pages for the Agentic Academic Review System. This commit does not generate them. GitHub About is outside git and is not updated by this change.

**What a matching score is not.** A match means the stored overall is the weighted sum the code defines. It is not calibration, not agreement with a human reviewer, and not a recommendation anyone should treat as the decision.

**The drift check is token-level.** A numeral is accepted outside the block when the recompute already emits that token. Pasting an emitted token onto a different claim does not, by itself, turn the check red. The block is the source of the numerals.

<!-- CHECKED-FACTS:BEGIN -->
```json
{
  "headline": "scores 12/12; recs 12/12; present_denom_differ 8; outside_scale 5; clock_plus_8h 4; csv_files 6; csv_hashes 5; csv_rows 15; csv_rows_match 15; unpaired_reviews 0; unpaired_csv_rows 0; models 1; cross_model_pairs 0",
  "repo": {
    "dev_criteria": 8,
    "dev_thresholds": [
      85,
      70,
      50,
      0
    ],
    "dev_weight_sum": 100,
    "eval_cases": 21,
    "float_abs_tol": "1e-9",
    "npm_scaffold_version": "1.0.0",
    "prompt_files": 5,
    "pytest_test_functions": 38,
    "web_port": 8050
  },
  "stored": {
    "cache_absolute_original_paths": 1,
    "cache_entries": 2,
    "cache_filenames": [
      "main.pdf",
      "main_1.pdf"
    ],
    "cache_paths_mentioning_agentic_paper_review": 1,
    "cited_main_13_10_overall": "43.2",
    "cited_main_1_13_12_cost_2dp": "0.22",
    "cited_main_1_13_12_cost_4dp": "0.2223",
    "cited_main_1_13_12_cost_usd": "0.22231965599999998",
    "cited_main_1_13_12_overall": "30.4",
    "clock_plus_8h_files": [
      "main_1_deepseek_deepseek-v4-pro_deepseek_deepseek-v4-pro_20260628_203726.md",
      "main_1_deepseek_deepseek-v4-pro_deepseek_deepseek-v4-pro_20260628_210006.md",
      "main_2_deepseek_deepseek-v4-pro_deepseek_deepseek-v4-pro_20260628_210451.md",
      "main_deepseek_deepseek-v4-pro_deepseek_deepseek-v4-pro_20260628_205517.md"
    ],
    "cross_model_pairs": 0,
    "csv_byte_identical_groups": [
      [
        "consolidated_reviews_20260628_211215.csv",
        "consolidated_reviews_20260628_211226.csv"
      ]
    ],
    "csv_distinct_sha256": 5,
    "csv_files": 6,
    "csv_rows": 15,
    "csv_rows_duplicate_overall_agrees": 15,
    "csv_rows_match_paired_review": 15,
    "csv_rows_score_match": 15,
    "csv_rows_with_duplicate_overall_column": 15,
    "extra_pdfs_in_papers_dir": [
      "PAPER5_main.pdf"
    ],
    "filename_clock_plus_8h": 4,
    "formula": "calculate_recommendation: sum((score/label_count)*weight) / sum(all criterion weights) * 100; a criterion absent from the review contributes 0 and its weight stays in the denominator",
    "headline": "scores 12/12; recs 12/12; present_denom_differ 8; outside_scale 5; clock_plus_8h 4; csv_files 6; csv_hashes 5; csv_rows 15; csv_rows_match 15; unpaired_reviews 0; unpaired_csv_rows 0; models 1; cross_model_pairs 0",
    "ml_criteria": 8,
    "ml_thresholds": [
      85,
      65,
      45,
      0
    ],
    "ml_weight_sum": 100,
    "model_count": 1,
    "model_ids": [
      "deepseek/deepseek-v4-pro"
    ],
    "paper_spans": {
      "main.pdf": {
        "max": "43.2",
        "min": "31.4",
        "n": 4
      },
      "main_1.pdf": {
        "max": "48.6",
        "min": "30.4",
        "n": 4
      },
      "main_2.pdf": {
        "max": "52.0",
        "min": "38.6",
        "n": 3
      },
      "paper.pdf": {
        "max": "37.6",
        "min": "37.6",
        "n": 1
      }
    },
    "paper_stems_in_reviews": 4,
    "pdfs_in_run_dir": [
      "main.pdf"
    ],
    "pdfs_referenced_missing_from_run_dir": [
      "main_1.pdf",
      "main_2.pdf",
      "paper.pdf"
    ],
    "progress_matches_latest_review": 2,
    "progress_papers": [
      "main.pdf",
      "main_1.pdf"
    ],
    "recommendation_match_reviews": 12,
    "review_files": 12,
    "reviews_missing_a_criterion": 8,
    "reviews_present_denominator_differs": 8,
    "reviews_score_outside_scale": 5,
    "reviews_weight_mismatch": 0,
    "run_minutes_are": [
      "2026-06-28"
    ],
    "scale_max": 5,
    "scale_min": 1,
    "score_match_reviews": 12,
    "score_mismatches": [],
    "unique_cost_conflicts": [],
    "unique_cost_max_usd": "0.52020303",
    "unique_cost_min_usd": "0.20203445999999997",
    "unique_cost_sum_usd": "3.83812957599999959",
    "unique_paper_minutes": 12,
    "unpaired_csv_rows": 0,
    "unpaired_reviews": 0
  }
}
```
<!-- CHECKED-FACTS:END -->
