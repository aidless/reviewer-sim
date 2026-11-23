STATUS: WORK-IN-PROGRESS — not A yet

Gaps:

- GitHub About is outside git and still says the repository hosts its docs on UNU C3. This pull request cannot edit About. The proposed replacement is in the pull request description.

# reviewer-sim

An LLM can score a paper on named criteria and fold those scores into one recommendation. That number is a model opinion, and this repository does not show that it agrees with human reviewers. What can be checked offline is whether the one stored run obeys the pipeline's own scoring formula.

**Result.** On `my_first_review/` (2026-06-28, model `deepseek-v4-pro` only), `calculate_recommendation` matches the stated overall and the recommendation on 12/12 reviews, and 15/15 consolidated CSV rows match the paired review (paper stem plus the review minute). **Limits.** 8/12 reviews omit at least one criterion; averaging only the criteria that were scored changes the one-decimal overall on those 8. 5/12 reviews give a criterion a score outside the configured scale of 1 to 5 (a 0 on reproducibility). 4/12 filenames are stamped 8 hours ahead of the timestamp inside the file, so a join on the filename clock fails for those four. There is 1 model, so cross-model pairs are 0 and there is no agreement coefficient and no interval. Same-model reruns already disagree with each other: `main.pdf` spans 31.4 to 43.2 (4 reviews), `main_1.pdf` spans 30.4 to 48.6 (4), `main_2.pdf` spans 38.6 to 52.0 (3), and `paper.pdf` is 37.6 once.

The figure 43.2 is the `main.pdf` review at 13:10. The figure 30.4 is the `main_1.pdf` review at 13:12. They are not two scores of one paper. The old "$0.22 per paper" sentence is the two-decimal rounding of one CSV cell, `0.22231965599999998` (four-decimal form 0.2223). It is not a rate. The 12 unique paper-minute rows sum to 3.83812957599999959 (min 0.20203445999999997, max 0.52020303).

`make check` rebuilds the block below from the files. It exits non-zero if that block drifts, or if any numeral outside the block is not a token the recompute emitted. No API key. It does not re-call a model.

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

## Withdrawn

- "3 consolidated CSVs." The directory has 6 files and 5 distinct hashes. `consolidated_reviews_20260628_211215.csv` and `consolidated_reviews_20260628_211226.csv` are byte-identical. `docs/demo.gif` runs `setup_run.py` and then a tail of `ls`, so the frame shows three names and does not list the directory.
- "$0.22 per paper." See the one-cell rounding above.
- A reading of 43.2 and 30.4 as the score of "the" resampling paper. See the two reviews named above. The stored run also contains other scores for those files.

## Provenance

The code is MIT, copyright Dr. Ng Chong, in `LICENSE`. The maintained line of this family is [review-workflow](https://github.com/aidless/review-workflow). The archived full Web+CLI tree is [agentic-paper-review](https://github.com/aidless/agentic-paper-review). This repository is the multi-role simulation variant.

The user guide (https://c3.unu.edu/projects/ai/paperreview/userguide.html) and the blog post (https://c3.unu.edu/blog/from-months-to-days-ai-assisted-peer-review-with-human-oversight) are Ng Chong's UNU C3 pages for the Agentic Academic Review System. This tree does not build those pages. The dashboard screenshot in `docs/dashboard.png` is the UI in `web/static/index.html`: same title, same tabs, and the same footer ("智能论文评审系统 · 联合国大学 C3 中心 · Ng Chong 开发"). The GIF in `docs/demo.gif` is a local terminal capture whose setup lines are the prints in `setup_run.py`.

One ingestion-cache entry stores an absolute Windows path whose project directory is `agentic-paper-review`. The stored run was produced in that tree. The cache has text for `main.pdf` and `main_1.pdf` only. Reviews also name `main_2.pdf` and `paper.pdf`, which are not in `my_first_review/papers/`. `papers/PAPER5_main.pdf` is a different double-blind manuscript (memory architectures for multi-agent systems). It is not an input of the stored run. Neither PDF has a paper license in its metadata. `LICENSE` does not license those manuscripts. Font licenses embedded in the files license the fonts.

`package.json` version 1.0.0 is an npm scaffold (`private`, no `index.js`). It is not a release of the review tool. There is no `pyproject.toml` or `setup.py`. The publish workflow skips the build when those files are absent. This repository is not a PyPI package.

No API key is committed. `.env_example` leaves the key fields empty.

## What the agents do

| Agent | Role |
|-------|------|
| Specialist | Scores the paper once per criterion, with quotes |
| Editor | Writes the review and the weighted overall |
| Judge | Adjudicates conflicting model runs, when more than one run exists |
| Librarian | Optional literature search |
| Fact-Checker | Optional check of claims such as "first study" |
| Critic | Optional novelty-adjusted synthesis |

The stored run exercised Specialist and Editor only, both on `deepseek-v4-pro`. Judge, Librarian, Fact-Checker, and Critic are in the tree and are not in the stored outputs.

Pipeline: ingest a PDF or text file, extract one score per criterion, synthesize with `agents/agent_synthesizer.py`, write a Markdown review and a CSV row. Optional later stages compare two model runs and adjudicate. The stored run has nothing for those stages to compare.

## Check

From a fresh clone, with no API key:

```bash
pip install -r requirements.txt
make check
```

`make check` runs the pytest suite (`repo.pytest_test_functions` in the block), `eval/run_cases.py` (`repo.eval_cases`, including `STORED-01`), the case runner's self-test (it must go red), and `eval/recompute_stored_run.py --selftest` (the real README check must pass, and a doctored score must fail). The case runner's float tolerance is the `1e-9` in the block.

`config/criteria.yaml` is the development-economics default: 8 criteria, weights summing to 100, thresholds 85, 70, 50, 0. The stored run uses `my_first_review/input/criteria.yaml`: 8 criteria, weights summing to 100, thresholds 85, 65, 45, 0, scale 1 to 5. `config/prompts/` has 5 prompt files. The dashboard default port is 8050 (`web_app.py`).

## Run (needs API keys)

Copy `.env_example` to `.env` and set the provider keys and model names there. Then:

```bash
python3 setup_run.py --run-dir my_review_run
python3 web_app.py --port 8050
```

Put PDFs in the run's `papers/` directory before the review command. `run_with_custom_params.py` is the CLI review entry and it calls the network. The dashboard has no authentication; keep it on a machine you control. `compare_reports.py` and `judge_conflicts.py` need two model runs first. Batch distribution is `setup_batch_runs()` in `setup_batch_runs_literature.py` (a function, not a CLI). The batch driver is `run_batch.py`.

Human reviewers make the accept or reject decision. The recommendation strings are the labels in the criterion file, not a decision.

## 族谱

论文评审主线是 [review-workflow](https://github.com/aidless/review-workflow)。已归档的完整 Web+CLI 树是 [agentic-paper-review](https://github.com/aidless/agentic-paper-review)。本仓是多角色模拟变体，上面的离线复算是本仓能对已提交跑次负责的结果。
