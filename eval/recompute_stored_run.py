#!/usr/bin/env python3
"""Recompute the stored my_first_review run and lock the README to it.

The measurement calls agents.agent_synthesizer.calculate_recommendation,
which is the same function the pipeline uses. A missing criterion adds
nothing to the numerator and stays in the denominator (weight sum from
my_first_review/input/criteria.yaml). That is a different number from
averaging only the criteria that appear in the review.

No network and no API key. `make check` reruns this and exits non-zero
if eval/stored-run-facts.json or the checked block in README.md drifts.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import csv
import hashlib
import io
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FACTS_PATH = REPO_ROOT / "eval" / "stored-run-facts.json"
README_PATH = REPO_ROOT / "README.md"
FAILURES_PATH = REPO_ROOT / "FAILURE_MODES.md"
FACTS_BEGIN = "<!-- CHECKED-FACTS:BEGIN -->"
FACTS_END = "<!-- CHECKED-FACTS:END -->"

CRITERION_RE = re.compile(
    r"^### ([a-z_]+) \(Weight: ([0-9.]+)%, Score: ([0-9.]+)\)", re.M
)
OVERALL_RE = re.compile(r"\*\*Overall Score:\*\* \*\*([0-9.]+) / 100\*\*")
REC_RE = re.compile(r"\*\*Recommendation:\*\* \*\*(.+?)\*\*")
COST_RE = re.compile(r"\*\*Total API Cost:\*\* \$([0-9.]+)")
CONF_RE = re.compile(r"\*\*Confidence:\*\* ([0-9.]+)%")
FILE_RE = re.compile(r"\*\*Filename:\*\* `?([^\s`]+)")
DATE_RE = re.compile(r"\*\*Review Date:\*\* ([0-9]{4}-[0-9]{2}-[0-9]{2}) ([0-9]{2}:[0-9]{2})")
MODEL_RE = re.compile(r"\*\*(Extractor|Synthesizer) Model:\*\* (\S+)")
FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
NUM_RE = re.compile(r"(?<![A-Za-z0-9.])(?:\d+e-\d+|\d+\.\d+|\d+)(?![A-Za-z0-9.])")
IDENT_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+_-]*\d[A-Za-z0-9.+_-]*")
URL_RE = re.compile(r"https?://\S+")


def _imports():
    # llm_wrapper registers model prices and prints to stdout at import.
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        from agents.agent_synthesizer import calculate_recommendation
        from core.config_loader import Config
        from core.data_models import Extraction
    return calculate_recommendation, Config, Extraction


def _load_config(config_dir: Path):
    _, Config, _ = _imports()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return Config(str(config_dir))


def _one_decimal(score: float) -> str:
    return f"{score:.1f}"


def _score_review(scores: dict[str, int], config):
    """Return (recommendation, raw_score, breakdown) from the real function."""
    calculate_recommendation, _, Extraction = _imports()
    extractions = [
        Extraction(
            paper_id="stored",
            criterion_id=cid,
            score=int(score),
            score_justification="stored-run recompute",
            evidence=[],
            strengths=[],
            weaknesses=[],
            confidence=0.0,
            model_used="stored",
        )
        for cid, score in scores.items()
    ]
    rec, _rationale, final, breakdown = calculate_recommendation(extractions, config)
    return rec, float(final), breakdown


def _present_denominator_score(breakdown) -> float | None:
    present = list(breakdown.values())
    if not present:
        return None
    weight = sum(item.weight for item in present)
    if weight <= 0:
        return None
    return (sum(item.weighted_score for item in present) / weight) * 100


def _parse_reviews(root: Path) -> list[dict]:
    rows = []
    for path in sorted((root / "my_first_review" / "outputs" / "reviews").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        date = DATE_RE.search(text)
        filename = FILE_RE.search(text)
        overall = OVERALL_RE.search(text)
        rec = REC_RE.search(text)
        cost = COST_RE.search(text)
        conf = CONF_RE.search(text)
        if not all((date, filename, overall, rec, cost, conf)):
            rows.append({"path": path.name, "parse_error": True})
            continue
        scores = {}
        weights = {}
        for cid, weight, score in CRITERION_RE.findall(text):
            scores[cid] = Decimal(score)
            weights[cid] = Decimal(weight)
        stamp = filename.group(1)
        stem = stamp[:-4] if stamp.endswith(".pdf") else stamp
        clock = re.search(r"_(\d{8})_(\d{6})\.md$", path.name)
        rows.append(
            {
                "path": path.name,
                "parse_error": False,
                "paper": filename.group(1).strip(),
                "stem": stem,
                "minute": f"{date.group(1)} {date.group(2)}",
                "stated_overall": overall.group(1),
                "stated_rec": rec.group(1).strip(),
                "stated_cost": cost.group(1),
                "stated_confidence_pct": conf.group(1),
                "scores": scores,
                "markdown_weights": weights,
                "models": sorted({m for _, m in MODEL_RE.findall(text)}),
                "file_hhmm": clock.group(2)[:4] if clock else "",
                "date_hhmm": date.group(2).replace(":", ""),
            }
        )
    return rows


def _csv_rows(path: Path):
    raw = list(csv.reader(path.open(encoding="utf-8")))
    if not raw:
        return
    header = raw[0]
    for rec in raw[1:]:
        if not any(cell.strip() for cell in rec):
            continue
        first: dict[str, str] = {}
        dups: dict[str, list[str]] = {}
        for idx, name in enumerate(header):
            value = rec[idx] if idx < len(rec) else ""
            if name in first:
                dups.setdefault(name, []).append(value)
            else:
                first[name] = value
        yield first, dups


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _count_tests(root: Path) -> int:
    total = 0
    for path in sorted((root / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        total += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        )
    return total


def _count_cases(root: Path) -> int:
    total = 0
    for line in (root / "eval" / "cases.jsonl").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            total += 1
    return total


def _web_port(root: Path) -> int:
    text = (root / "web_app.py").read_text(encoding="utf-8")
    match = re.search(r'add_argument\(\s*"--port"[^\n]*default\s*=\s*(\d+)', text)
    if not match:
        raise RuntimeError("web_app.py has no --port default")
    return int(match.group(1))


def _float_tol(root: Path) -> str:
    text = (root / "eval" / "run_cases.py").read_text(encoding="utf-8")
    match = re.search(r"\b(1e-9)\b", text)
    if not match:
        raise RuntimeError("run_cases.py has no 1e-9 tolerance")
    return match.group(1)


def _thresholds(config) -> list[int]:
    return [int(item["threshold"]) for item in config.get_recommendation_thresholds()]


def _scale_bounds(config) -> tuple[int, int]:
    lows, highs = [], []
    for criterion in config.get_criteria():
        span = criterion.get("scale", {}).get("range") or []
        if len(span) == 2:
            lows.append(int(span[0]))
            highs.append(int(span[1]))
    if not lows:
        raise RuntimeError("criteria have no scale range")
    return min(lows), max(highs)


def recompute(root: Path | None = None) -> dict:
    root = Path(root) if root else REPO_ROOT
    ml = _load_config(root / "my_first_review" / "input")
    dev = _load_config(root / "config")
    weights = {c["id"]: int(c["weight"]) for c in ml.get_criteria()}
    scale_min, scale_max = _scale_bounds(ml)
    reviews = _parse_reviews(root)

    review_rows = []
    by_key: dict[tuple[str, str], dict] = {}
    models: set[str] = set()
    for row in reviews:
        if row["parse_error"]:
            review_rows.append({"file": row["path"], "parse_error": True})
            continue
        models.update(row["models"])
        integral = all(score == int(score) for score in row["scores"].values())
        score_map = {cid: int(score) for cid, score in row["scores"].items()} if integral else {}
        unknown = sorted(set(score_map) - set(weights))
        weight_mismatch = sorted(
            cid
            for cid, marked in row["markdown_weights"].items()
            if cid in weights and marked != weights[cid]
        )
        outside = sorted(
            cid for cid, score in score_map.items() if score < scale_min or score > scale_max
        )
        if integral and not unknown:
            rec, raw, breakdown = _score_review(score_map, ml)
            one_dp = _one_decimal(raw)
            alt = _present_denominator_score(breakdown)
            alt_dp = _one_decimal(alt) if alt is not None else ""
        else:
            rec, raw, one_dp, alt_dp = "", 0.0, "", ""
        key = (row["stem"], row["minute"])
        item = {
            "file": row["path"],
            "paper": row["paper"],
            "stem": row["stem"],
            "minute": row["minute"],
            "stated_overall": row["stated_overall"],
            "recomputed_overall": one_dp,
            "score_match": one_dp == row["stated_overall"],
            "stated_recommendation": row["stated_rec"],
            "recomputed_recommendation": rec,
            "recommendation_match": rec == row["stated_rec"],
            "criteria_present": len(score_map),
            "criteria_missing": sorted(set(weights) - set(score_map)),
            "present_denominator_overall": alt_dp,
            "present_denominator_differs": bool(alt_dp) and alt_dp != row["stated_overall"],
            "scores_outside_scale": outside,
            "unknown_criteria": unknown,
            "weight_mismatch": weight_mismatch,
            "non_integral_scores": not integral,
            "file_hhmm": row["file_hhmm"],
            "date_hhmm": row["date_hhmm"],
            "clock_plus_8h": _hour_delta(row["file_hhmm"], row["date_hhmm"]) == 8,
            "stated_cost": row["stated_cost"],
            "stated_confidence_pct": row["stated_confidence_pct"],
            "scores": {cid: int(score) for cid, score in score_map.items()},
        }
        review_rows.append(item)
        by_key.setdefault(key, item)

    csv_paths = sorted((root / "my_first_review" / "outputs" / "reports").glob("*.csv"))
    hashes: dict[str, list[str]] = {}
    csv_details = []
    seen_cost: dict[tuple[str, str], str] = {}
    cost_conflict = []
    for path in csv_paths:
        digest = _sha256(path)
        hashes.setdefault(digest, []).append(path.name)
        for first, dups in _csv_rows(path):
            stem = first.get("paper_filename", "")
            minute = (first.get("timestamp") or "")[:16]
            key = (stem, minute)
            cells = {}
            for name, value in first.items():
                if name.endswith("_score") and name != "overall_score":
                    cells[name[: -len("_score")]] = value.strip()
            present = {cid: Decimal(value) for cid, value in cells.items() if value != ""}
            integral = all(value == int(value) for value in present.values())
            unknown = sorted(set(present) - set(weights))
            if integral and not unknown and present:
                rec, raw, _breakdown = _score_review(
                    {cid: int(value) for cid, value in present.items()}, ml
                )
                one_dp = _one_decimal(raw)
            else:
                rec, one_dp = "", ""
            stated = first.get("overall_score", "")
            stated_dp = _one_decimal(float(stated)) if stated else ""
            dup_values = dups.get("overall_score", [])
            dup_agree = all(value == stated for value in dup_values) if dup_values else False
            paired = by_key.get(key)
            cell_match = False
            cost_match = False
            conf_match = False
            rec_match = False
            if paired and not paired.get("parse_error"):
                paired_scores = {cid: str(score) for cid, score in paired["scores"].items()}
                csv_scores = {cid: str(int(value)) for cid, value in present.items()}
                cell_match = csv_scores == paired_scores
                rec_match = first.get("recommendation", "") == paired["stated_recommendation"]
                cost_match = format(float(first.get("total_cost_usd") or "nan"), ".4f") == paired[
                    "stated_cost"
                ]
                conf_match = format(float(first.get("confidence") or "nan"), ".2f") == format(
                    int(paired["stated_confidence_pct"]) / 100, ".2f"
                )
            cost_text = first.get("total_cost_usd", "")
            if key in seen_cost and seen_cost[key] != cost_text:
                cost_conflict.append(
                    {"stem": stem, "minute": minute, "a": seen_cost[key], "b": cost_text}
                )
            elif key not in seen_cost and cost_text:
                seen_cost[key] = cost_text
            csv_details.append(
                {
                    "file": path.name,
                    "stem": stem,
                    "minute": minute,
                    "stated_overall": stated,
                    "recomputed_overall": one_dp,
                    "score_match": bool(one_dp) and one_dp == stated_dp,
                    "recommendation_match": rec == first.get("recommendation", ""),
                    "duplicate_overall_column": bool(dup_values),
                    "duplicate_overall_agrees": dup_agree,
                    "paired_review": paired["file"] if paired else "",
                    "cells_match_review": cell_match,
                    "cost_4dp_matches_review": cost_match,
                    "confidence_matches_review": conf_match,
                    "row_matches_review": bool(paired)
                    and cell_match
                    and rec_match
                    and cost_match
                    and conf_match
                    and one_dp == paired["stated_overall"],
                }
            )

    ok_reviews = [row for row in review_rows if not row.get("parse_error")]
    spans: dict[str, dict] = {}
    for row in ok_reviews:
        bucket = spans.setdefault(row["paper"], [])
        bucket.append(Decimal(row["stated_overall"]))
    paper_spans = {
        paper: {
            "n": len(values),
            "min": format(min(values), "f"),
            "max": format(max(values), "f"),
        }
        for paper, values in sorted(spans.items())
    }
    cited_main = next(
        (row for row in ok_reviews if row["paper"] == "main.pdf" and row["minute"].endswith("13:10")),
        None,
    )
    cited_main_1 = next(
        (
            row
            for row in ok_reviews
            if row["paper"] == "main_1.pdf" and row["minute"].endswith("13:12")
        ),
        None,
    )
    cited_cost = ""
    if cited_main_1:
        cited_cost = seen_cost.get((cited_main_1["stem"], cited_main_1["minute"]), "")
    unique_costs = [Decimal(value) for value in seen_cost.values()]
    cost_sum = sum(unique_costs, Decimal("0")) if unique_costs else Decimal("0")
    review_keys = {(row["stem"], row["minute"]) for row in ok_reviews}
    csv_keys = {(row["stem"], row["minute"]) for row in csv_details}

    cache_path = root / "my_first_review" / "ingestion_cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    cache_names = sorted(entry.get("filename", "") for entry in cache)
    agentic_paths = sum(
        1 for entry in cache if "agentic-paper-review" in str(entry.get("original_path", ""))
    )
    absolute_paths = sum(
        1
        for entry in cache
        if re.match(r"^[A-Za-z]:[\\/]", str(entry.get("original_path", "")))
        or str(entry.get("original_path", "")).startswith("/")
    )

    progress = json.loads((root / "my_first_review" / "progress.json").read_text(encoding="utf-8"))
    progress_match = 0
    progress_papers = sorted(progress.get("papers", {}))
    for name, payload in progress.get("papers", {}).items():
        review = (payload or {}).get("review") or {}
        latest = [
            row
            for row in ok_reviews
            if row["paper"] == name
        ]
        if not latest:
            continue
        latest.sort(key=lambda row: row["minute"])
        chosen = latest[-1]
        if (
            _one_decimal(float(review.get("overall_score"))) == chosen["stated_overall"]
            and review.get("recommendation") == chosen["stated_recommendation"]
        ):
            progress_match += 1

    run_pdfs = sorted(p.name for p in (root / "my_first_review" / "papers").glob("*.pdf"))
    extra_pdfs = sorted(p.name for p in (root / "papers").glob("*.pdf"))
    referenced = sorted({row["paper"] for row in ok_reviews})
    missing_pdfs = sorted(set(referenced) - set(run_pdfs))

    stored = {
        "formula": (
            "calculate_recommendation: sum((score/label_count)*weight) "
            "/ sum(all criterion weights) * 100; a criterion absent from the "
            "review contributes 0 and its weight stays in the denominator"
        ),
        "run_minutes_are": sorted({row["minute"][:10] for row in ok_reviews}),
        "review_files": len(review_rows),
        "score_match_reviews": sum(1 for row in ok_reviews if row["score_match"]),
        "recommendation_match_reviews": sum(
            1 for row in ok_reviews if row["recommendation_match"]
        ),
        "reviews_present_denominator_differs": sum(
            1 for row in ok_reviews if row["present_denominator_differs"]
        ),
        "reviews_score_outside_scale": sum(1 for row in ok_reviews if row["scores_outside_scale"]),
        "reviews_missing_a_criterion": sum(1 for row in ok_reviews if row["criteria_missing"]),
        "reviews_weight_mismatch": sum(1 for row in ok_reviews if row["weight_mismatch"]),
        "filename_clock_plus_8h": sum(1 for row in ok_reviews if row["clock_plus_8h"]),
        "clock_plus_8h_files": sorted(row["file"] for row in ok_reviews if row["clock_plus_8h"]),
        "csv_files": len(csv_paths),
        "csv_distinct_sha256": len(hashes),
        "csv_byte_identical_groups": [
            sorted(names) for names in hashes.values() if len(names) > 1
        ],
        "csv_rows": len(csv_details),
        "csv_rows_score_match": sum(1 for row in csv_details if row["score_match"]),
        "csv_rows_with_duplicate_overall_column": sum(
            1 for row in csv_details if row["duplicate_overall_column"]
        ),
        "csv_rows_duplicate_overall_agrees": sum(
            1 for row in csv_details if row["duplicate_overall_agrees"]
        ),
        "csv_rows_match_paired_review": sum(1 for row in csv_details if row["row_matches_review"]),
        "unpaired_reviews": len(review_keys - csv_keys),
        "unpaired_csv_rows": len(csv_keys - review_keys),
        "unique_paper_minutes": len(seen_cost),
        "unique_cost_sum_usd": format(cost_sum, "f"),
        "unique_cost_min_usd": format(min(unique_costs), "f") if unique_costs else "",
        "unique_cost_max_usd": format(max(unique_costs), "f") if unique_costs else "",
        "unique_cost_conflicts": cost_conflict,
        "model_ids": sorted(models),
        "model_count": len(models),
        "cross_model_pairs": 0 if len(models) < 2 else len(models) * (len(models) - 1) // 2,
        "scale_min": scale_min,
        "scale_max": scale_max,
        "ml_weight_sum": sum(weights.values()),
        "ml_criteria": len(weights),
        "ml_thresholds": _thresholds(ml),
        "paper_stems_in_reviews": len({row["stem"] for row in ok_reviews}),
        "paper_spans": paper_spans,
        "cited_main_13_10_overall": cited_main["stated_overall"] if cited_main else "",
        "cited_main_1_13_12_overall": cited_main_1["stated_overall"] if cited_main_1 else "",
        "cited_main_1_13_12_cost_usd": cited_cost,
        "cited_main_1_13_12_cost_4dp": format(float(cited_cost), ".4f") if cited_cost else "",
        "cited_main_1_13_12_cost_2dp": format(float(cited_cost), ".2f") if cited_cost else "",
        "pdfs_in_run_dir": run_pdfs,
        "pdfs_referenced_missing_from_run_dir": missing_pdfs,
        "extra_pdfs_in_papers_dir": extra_pdfs,
        "cache_entries": len(cache),
        "cache_filenames": cache_names,
        "cache_paths_mentioning_agentic_paper_review": agentic_paths,
        "cache_absolute_original_paths": absolute_paths,
        "progress_papers": progress_papers,
        "progress_matches_latest_review": progress_match,
        "score_mismatches": [
            {
                "file": row["file"],
                "stated": row["stated_overall"],
                "recomputed": row["recomputed_overall"],
            }
            for row in ok_reviews
            if not row["score_match"]
        ],
    }
    stored["headline"] = _headline(stored)
    repo = {
        "pytest_test_functions": _count_tests(root),
        "eval_cases": _count_cases(root),
        "web_port": _web_port(root),
        "dev_weight_sum": sum(int(c["weight"]) for c in dev.get_criteria()),
        "dev_criteria": len(dev.get_criteria()),
        "dev_thresholds": _thresholds(dev),
        "float_abs_tol": _float_tol(root),
        "prompt_files": len(list((root / "config" / "prompts").glob("*.txt"))),
        "npm_scaffold_version": json.loads((root / "package.json").read_text(encoding="utf-8"))[
            "version"
        ],
    }
    return {"stored": stored, "repo": repo}


def _hour_delta(file_hhmm: str, date_hhmm: str) -> int | None:
    if len(file_hhmm) < 4 or len(date_hhmm) < 4:
        return None
    return (int(file_hhmm[:2]) - int(date_hhmm[:2])) % 24


def _headline(stored: dict) -> str:
    return (
        f"scores {stored['score_match_reviews']}/{stored['review_files']}; "
        f"recs {stored['recommendation_match_reviews']}/{stored['review_files']}; "
        f"present_denom_differ {stored['reviews_present_denominator_differs']}; "
        f"outside_scale {stored['reviews_score_outside_scale']}; "
        f"clock_plus_8h {stored['filename_clock_plus_8h']}; "
        f"csv_files {stored['csv_files']}; "
        f"csv_hashes {stored['csv_distinct_sha256']}; "
        f"csv_rows {stored['csv_rows']}; "
        f"csv_rows_match {stored['csv_rows_match_paired_review']}; "
        f"unpaired_reviews {stored['unpaired_reviews']}; "
        f"unpaired_csv_rows {stored['unpaired_csv_rows']}; "
        f"models {stored['model_count']}; "
        f"cross_model_pairs {stored['cross_model_pairs']}"
    )


def public_facts(payload: dict) -> dict:
    """JSON object embedded in README. Every prose number must occur here."""
    stored = payload["stored"]
    return {
        "headline": stored["headline"],
        "stored": stored,
        "repo": payload["repo"],
    }


def render_block(payload: dict) -> str:
    body = json.dumps(public_facts(payload), ensure_ascii=False, indent=2, sort_keys=True)
    return f"{FACTS_BEGIN}\n```json\n{body}\n```\n{FACTS_END}"


def _numbers(text: str) -> set[str]:
    return set(NUM_RE.findall(text))


def _strip_verbatim_fences(text: str, root: Path) -> str:
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".git", "outputs", "__pycache__"} for part in path.parts):
            continue
        if path.suffix.lower() in {".pdf", ".png", ".gif", ".json"}:
            continue
        if path.stat().st_size > 200_000:
            continue
        files.append(path.read_text(encoding="utf-8", errors="ignore"))

    def replace(match: re.Match) -> str:
        body = match.group(1).strip("\n")
        if body and any(body in source for source in files):
            return ""
        return match.group(0)

    return FENCE_RE.sub(replace, text)


def check_document(text: str, payload: dict, root: Path, label: str) -> list[str]:
    errors = []
    if FACTS_BEGIN not in text or FACTS_END not in text:
        return [f"{label} is missing the checked-facts block"]
    block = text.split(FACTS_BEGIN, 1)[1].split(FACTS_END, 1)[0]
    expected = render_block(payload).split(FACTS_BEGIN, 1)[1].split(FACTS_END, 1)[0]
    if block.strip() != expected.strip():
        errors.append(f"{label} checked-facts block does not match a fresh recompute")
    allowed = _numbers(render_block(payload))
    outside = text.split(FACTS_BEGIN, 1)[0] + text.split(FACTS_END, 1)[1]
    outside = _strip_verbatim_fences(outside, root)
    outside = URL_RE.sub(" ", outside)
    outside = IDENT_RE.sub(" ", outside)
    stray = sorted(_numbers(outside) - allowed)
    if stray:
        errors.append(f"{label} has numbers that are not in the checked block: {', '.join(stray)}")
    return errors


def check_all(payload: dict, root: Path) -> list[str]:
    errors = []
    frozen = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    if frozen != payload["stored"]:
        errors.append("eval/stored-run-facts.json does not match a fresh recompute of the stored run")
    errors.extend(check_document(README_PATH.read_text(encoding="utf-8"), payload, root, "README.md"))
    errors.extend(
        check_document(FAILURES_PATH.read_text(encoding="utf-8"), payload, root, "FAILURE_MODES.md")
    )
    return errors


def _write_frozen(payload: dict) -> None:
    FACTS_PATH.write_text(
        json.dumps(payload["stored"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-frozen", action="store_true")
    parser.add_argument("--print-block", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Require the real check to pass, then require a tampered count to fail",
    )
    args = parser.parse_args(argv)
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):
        payload = recompute(REPO_ROOT)
    if args.write_frozen:
        _write_frozen(payload)
        print(f"wrote {FACTS_PATH.relative_to(REPO_ROOT)}", file=sys.stderr)
    if args.print_block:
        print(render_block(payload))
        return 0
    if args.selftest:
        errors = check_all(payload, REPO_ROOT)
        if errors:
            print("SELFTEST invalid; real check failed:", file=sys.stderr)
            for err in errors:
                print(f"- {err}", file=sys.stderr)
            return 1
        tampered = json.loads(json.dumps(payload))
        tampered["stored"]["score_match_reviews"] = payload["stored"]["score_match_reviews"] + 1
        tampered["stored"]["headline"] = _headline(tampered["stored"])
        if not check_all(tampered, REPO_ROOT):
            print("SELFTEST failed: tampered score count was accepted", file=sys.stderr)
            return 1
        doctored = README_PATH.read_text(encoding="utf-8").replace(
            f'"score_match_reviews": {payload["stored"]["score_match_reviews"]}',
            f'"score_match_reviews": {payload["stored"]["score_match_reviews"] + 1}',
            1,
        )
        if not check_document(doctored, payload, REPO_ROOT, "README.md"):
            print("SELFTEST failed: doctored README number was accepted", file=sys.stderr)
            return 1
        print("SELFTEST ok: tampered score count and doctored README were rejected")
        return 0
    if args.check:
        errors = check_all(payload, REPO_ROOT)
        if errors:
            for err in errors:
                print(f"FAIL {err}", file=sys.stderr)
            return 1
        print(payload["stored"]["headline"])
        return 0
    print(json.dumps(public_facts(payload), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
