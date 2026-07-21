"""
FastAPI Web Application

Serves the dashboard UI and provides REST/SSE API endpoints
for managing and monitoring review runs.
"""

import os
import sys
import json
import time
import asyncio
import argparse
import threading
import glob
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.progress import (
    get_emitter, get_sse_backend, SSEBackend,
    Event, RunStarted, RunCompleted, PaperCompleted, RunProgress,
    StageStarted, StageCompleted, Error, CostUpdate,
    configure_emitter,
)

# Import llm_wrapper early so custom models are registered with litellm
import core.llm_wrapper  # noqa: F401

app = FastAPI(title="Agentic Paper Review System")

# Static files
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(PROJECT_ROOT, "web", "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _resolve_run_path(run_dir: str) -> str:
    """Resolve a run directory name to an absolute path, validating it exists."""
    if os.path.isabs(run_dir):
        full_path = run_dir
    else:
        full_path = os.path.join(PROJECT_ROOT, run_dir)
    resolved = str(Path(full_path).resolve())
    if not resolved.startswith(str(Path(PROJECT_ROOT).resolve())):
        raise HTTPException(status_code=403, detail="访问被拒绝")
    if not os.path.isdir(resolved):
        raise HTTPException(status_code=404, detail=f"目录未找到：{run_dir}")
    return resolved

# ---------------------------------------------------------------------------
# Run state tracking
# ---------------------------------------------------------------------------

_active_runs: Dict[str, Dict[str, Any]] = {}
_run_history: List[Dict[str, Any]] = []
_cancel_flags: Dict[str, bool] = {}
_batch_state: Dict[str, Any] = {}  # {"active": bool, "dirs": [...], "current_index": int, ...}


def _load_progress(progress_file: str, current_config_hash: str, mode: str) -> Dict[str, Dict]:
    """Load progress file, resetting if config or mode changed."""
    if not os.path.exists(progress_file):
        return {"papers": {}}
    try:
        with open(progress_file, "r", encoding='utf-8') as f:
            progress_data = json.load(f)
        stored_mode = progress_data.get("mode", "standard")  # CLI doesn't store mode
        if progress_data.get("config_hash") != current_config_hash or stored_mode != mode:
            return {"papers": {}}
        return progress_data
    except (json.JSONDecodeError, KeyError):
        return {"papers": {}}


def _save_progress(progress_file: str, progress: Dict[str, Dict], config_hash: str, mode: str):
    """Save progress file with config hash and mode."""
    progress_data = {
        "config_hash": config_hash,
        "mode": mode,
        "papers": progress,
        "last_updated": datetime.now().isoformat(),
    }
    with open(progress_file, "w", encoding='utf-8') as f:
        json.dump(progress_data, f, indent=2, default=str)


def _find_run_dirs() -> List[Dict[str, str]]:
    """Scan for run directories at the project root."""
    dirs = []
    for entry in sorted(os.listdir(PROJECT_ROOT)):
        path = os.path.join(PROJECT_ROOT, entry)
        if os.path.isdir(path) and os.path.isdir(os.path.join(path, "papers")):
            # Count papers
            papers = (
                glob.glob(os.path.join(path, "papers", "*.pdf"))
                + glob.glob(os.path.join(path, "papers", "*.md"))
            )
            # Check for outputs
            has_output = os.path.isdir(os.path.join(path, "outputs", "reviews"))
            dirs.append({
                "name": entry,
                "path": path,
                "paper_count": len(papers),
                "has_output": has_output,
            })
    return dirs


def _load_config_safe(run_dir: str) -> Dict[str, Any]:
    """Load config for a run directory, masking API keys."""
    env_path = os.path.join(run_dir, "input", ".env")
    config_data: Dict[str, Any] = {}
    if os.path.exists(env_path):
        with open(env_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    if "KEY" in key.upper() or "SECRET" in key.upper():
                        config_data[key] = "***masked***"
                    else:
                        # Ensure value is always a plain string
                        config_data[key] = str(value)
    return config_data


def _load_criteria(run_dir: str) -> Dict[str, Any]:
    """Load criteria.yaml for a run directory."""
    criteria_path = os.path.join(run_dir, "input", "criteria.yaml")
    if not os.path.exists(criteria_path):
        # Try default
        criteria_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "criteria.yaml")
    if not os.path.exists(criteria_path):
        return {}
    import yaml
    with open(criteria_path, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def _get_reviews(run_dir: str) -> List[Dict[str, Any]]:
    """Get list of review files for a run directory."""
    reviews_dir = os.path.join(run_dir, "outputs", "reviews")
    if not os.path.isdir(reviews_dir):
        return []
    reviews = []
    for f in sorted(glob.glob(os.path.join(reviews_dir, "*.md")), reverse=True):
        reviews.append({
            "filename": os.path.basename(f),
            "path": f,
            "size": os.path.getsize(f),
            "modified": datetime.fromtimestamp(os.path.getmtime(f)).isoformat(),
        })
    return reviews


def _parse_csv_results(run_dir: str) -> List[Dict[str, Any]]:
    """Parse the latest consolidated CSV into JSON."""
    reports_dir = os.path.join(run_dir, "outputs", "reports")
    if not os.path.isdir(reports_dir):
        return []
    # Match both naming conventions: consolidated_reviews_*.csv and report_consolidated_*.csv
    csv_files = (
        sorted(glob.glob(os.path.join(reports_dir, "consolidated_reviews_*.csv")), reverse=True)
        or sorted(glob.glob(os.path.join(reports_dir, "report_consolidated_*.csv")), reverse=True)
    )
    if not csv_files:
        return []
    try:
        import pandas as pd
        df = pd.read_csv(csv_files[0])
        return df.fillna("").to_dict(orient="records")
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Pipeline runner (background thread)
# ---------------------------------------------------------------------------

def _run_pipeline(run_dir: str, run_id: str, mode: str, config_overrides: Dict[str, Any]):
    """Execute the review pipeline in a background thread."""
    from core.config_loader import Config
    from core.paper_ingestor import load_ingestion_cache, save_ingestion_cache, ingest_directory
    from utilities.helpers import setup_logging, get_config_hash

    emitter = get_emitter()
    setup_logging()

    start_time = time.time()
    _cancel_flags[run_id] = False

    try:
        dirs = {
            "run_dir": run_dir,
            "papers_dir": os.path.join(run_dir, "papers"),
            "input_dir": os.path.join(run_dir, "input"),
            "outputs_dir": os.path.join(run_dir, "outputs"),
            "reports_dir": os.path.join(run_dir, "outputs", "reports"),
            "reviews_dir": os.path.join(run_dir, "outputs", "reviews"),
        }
        for d in dirs.values():
            os.makedirs(d, exist_ok=True)

        # Apply config overrides to .env
        if config_overrides:
            env_path = os.path.join(dirs["input_dir"], ".env")
            env_vars = {}
            if os.path.exists(env_path):
                with open(env_path, encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            env_vars[k] = v
            env_vars.update(config_overrides)
            with open(env_path, "w", encoding='utf-8') as f:
                for k, v in env_vars.items():
                    if not k.endswith("_API_KEY"):
                        clean_v = str(v).replace("\n", "").replace("\r", "")
                        f.write(f"{k}={clean_v}\n")

        config = Config(config_path=dirs["input_dir"])
        config_hash = get_config_hash(config)

        # Load progress for idempotent resume
        progress_file = os.path.join(run_dir, "progress.json")
        progress_data = _load_progress(progress_file, config_hash, mode)
        progress_papers = progress_data.get("papers", {})

        # Ingest papers
        cache_file = os.path.join(run_dir, "ingestion_cache.json")
        ingestion_cache = load_ingestion_cache(cache_file)
        papers, cache_was_updated = ingest_directory(dirs["papers_dir"], ingestion_cache, cache_file)
        if cache_was_updated:
            save_ingestion_cache(ingestion_cache, cache_file)

        if not papers:
            emitter.emit(Event(event_type="error", stage_name="ingest", message="未找到论文", recoverable=False))
            return

        emitter.emit(RunStarted(run_dir=run_dir, mode=mode, paper_count=len(papers)))

        # Select pipeline
        if mode == "literature":
            from agents.agent_librarian import create_baseline_reference
            from agents.agent_reader import process_paper_extractions as process_lit
            from agents.agent_fact_checker import run_fact_checks
            from agents.agent_critic import synthesize_grounded_review
            from agents.agent_extractor import process_paper_extractions
            from agents.agent_synthesizer import synthesize_review
            from run_review_with_dir_literature import enhance_review_with_literature
            from utilities.output_generator import save_review_markdown, save_consolidated_csv
            from utilities.helpers import load_yaml_config
            from core.data_models import GroundedReview, LiteratureContext

            literature_config = load_yaml_config("config/literature_sources.yaml")
        else:
            from agents.agent_extractor import process_paper_extractions
            from agents.agent_synthesizer import synthesize_review
            from utilities.output_generator import save_review_markdown, save_consolidated_csv

        final_reviews = []
        total_cost = 0.0

        for i, paper in enumerate(papers, 1):
            if _cancel_flags.get(run_id, False):
                emitter.emit(Event(event_type="error", stage_name="cancel", message="用户取消了运行", recoverable=True))
                break

            # Skip already-processed papers (idempotent resume)
            if paper.filename in progress_papers:
                review_data = progress_papers[paper.filename]["review"]
                if mode == "literature":
                    from core.data_models import GroundedReview
                    review = GroundedReview.model_validate(review_data)
                else:
                    from core.data_models import Review
                    review = Review.model_validate(review_data)
                final_reviews.append(review)
                paper_cost = progress_papers[paper.filename].get("cost", 0.0)
                total_cost += paper_cost

                emitter.emit(PaperCompleted(
                    paper_filename=paper.filename,
                    score=review.overall_score,
                    recommendation=review.recommendation,
                    cost=paper_cost,
                    duration_s=0.0,
                ))
                elapsed = time.time() - start_time
                est_remaining = (elapsed / i * (len(papers) - i)) if i > 0 else 0
                emitter.emit(RunProgress(
                    papers_done=i, papers_total=len(papers),
                    elapsed_s=elapsed, estimated_remaining_s=est_remaining,
                ))
                emitter.emit(CostUpdate(paper_cost=paper_cost, total_cost=total_cost))
                continue

            paper_start = time.time()

            if mode == "literature":
                # Stage 1: Librarian
                emitter.emit(StageStarted(stage_name="Librarian", paper_filename=paper.filename))
                t0 = time.time()
                baseline = None
                try:
                    baseline = create_baseline_reference(paper, config)
                except Exception as e:
                    emitter.emit(Error(stage_name="Librarian", message=str(e)))
                emitter.emit(StageCompleted(stage_name="Librarian", duration_s=time.time()-t0,
                                           result_summary=f"{len(baseline.baseline_papers) if baseline else 0} papers"))

                # Stage 2: Reader/Extractor
                emitter.emit(StageStarted(stage_name="Extraction", paper_filename=paper.filename))
                t0 = time.time()
                if baseline:
                    extractions = process_lit(paper, config, baseline=baseline)
                else:
                    extractions = process_paper_extractions(paper, config)
                emitter.emit(StageCompleted(stage_name="Extraction", duration_s=time.time()-t0,
                                           result_summary=f"{len(extractions)} criteria"))

                if not extractions:
                    emitter.emit(Error(stage_name="Extraction", message=f"论文 {paper.filename} 无评估结果 — 跳过", recoverable=True))
                    continue

                # Stage 3: Fact-Checker
                fact_checks = []
                if baseline:
                    emitter.emit(StageStarted(stage_name="Fact-Check", paper_filename=paper.filename))
                    t0 = time.time()
                    try:
                        fact_checks = run_fact_checks(extractions, config.get_criteria(), config, literature_config) or []
                    except Exception:
                        pass
                    emitter.emit(StageCompleted(stage_name="Fact-Check", duration_s=time.time()-t0,
                                               result_summary=f"{len(fact_checks)} checks"))

                # Stage 4: Two-phase synthesis (standard review + literature enhancement)
                emitter.emit(StageStarted(stage_name="Synthesis", paper_filename=paper.filename))
                t0 = time.time()
                base_review = synthesize_review(paper, extractions, config)
                if base_review:
                    review = enhance_review_with_literature(
                        base_review=base_review, paper=paper, baseline=baseline,
                        fact_checks=fact_checks, extractions=extractions, config=config,
                    )
                else:
                    review = synthesize_grounded_review(paper, extractions, config, baseline=baseline, fact_checks=fact_checks)
                emitter.emit(StageCompleted(stage_name="Synthesis", duration_s=time.time()-t0,
                                           result_summary=f"分数：{review.overall_score:.1f}" if review else "失败"))
            else:
                # Standard pipeline
                emitter.emit(StageStarted(stage_name="Extraction", paper_filename=paper.filename))
                t0 = time.time()
                extractions = process_paper_extractions(paper, config)
                emitter.emit(StageCompleted(stage_name="Extraction", duration_s=time.time()-t0,
                                           result_summary=f"{len(extractions)} criteria"))

                if not extractions:
                    emitter.emit(Error(stage_name="Extraction", message=f"论文 {paper.filename} 无评估结果 — 跳过", recoverable=True))
                    continue

                emitter.emit(StageStarted(stage_name="Synthesis", paper_filename=paper.filename))
                t0 = time.time()
                review = synthesize_review(paper, extractions, config)
                emitter.emit(StageCompleted(stage_name="Synthesis", duration_s=time.time()-t0,
                                           result_summary=f"分数：{review.overall_score:.1f}" if review else "失败"))

            if not review:
                continue

            # Save review
            paper_base = os.path.splitext(paper.filename)[0]
            ext_model = review.extractor_model_used.replace("/", "_")
            syn_model = review.synthesizer_model_used.replace("/", "_")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            review_fn = f"{paper_base}_{ext_model}_{syn_model}_{ts}.md"
            output_path = os.path.join(dirs["reviews_dir"], review_fn)
            save_review_markdown(review=review, output_path=output_path, paper=paper, config=config)

            paper_duration = time.time() - paper_start
            total_cost += review.total_cost

            emitter.emit(PaperCompleted(
                paper_filename=paper.filename,
                score=review.overall_score,
                recommendation=review.recommendation,
                cost=review.total_cost,
                duration_s=paper_duration,
            ))

            elapsed = time.time() - start_time
            avg_per_paper = elapsed / i
            remaining = avg_per_paper * (len(papers) - i)
            emitter.emit(RunProgress(
                papers_done=i, papers_total=len(papers),
                elapsed_s=elapsed, estimated_remaining_s=remaining,
            ))
            emitter.emit(CostUpdate(paper_cost=review.total_cost, total_cost=total_cost))

            final_reviews.append(review)

            # Save progress for idempotent resume
            progress_papers[paper.filename] = {
                "review": review.model_dump(),
                "cost": review.total_cost,
                "timestamp": datetime.now().isoformat(),
            }
            _save_progress(progress_file, progress_papers, config_hash, mode)

        # Save consolidated CSV
        if final_reviews:
            save_consolidated_csv(final_reviews, dirs["reports_dir"])

        total_time = time.time() - start_time
        emitter.emit(RunCompleted(
            total_papers=len(final_reviews),
            total_cost=total_cost,
            total_time_s=total_time,
            output_dir=dirs["outputs_dir"],
        ))

    except Exception as e:
        import traceback
        emitter.emit(Error(stage_name="pipeline", message=f"{e}", recoverable=False))
        traceback.print_exc()
    finally:
        _active_runs.pop(run_id, None)
        _cancel_flags.pop(run_id, None)


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    with open(os.path.join(STATIC_DIR, "index.html"), encoding='utf-8') as f:
        return f.read()


@app.get("/api/runs")
async def list_runs():
    return {"runs": _find_run_dirs()}


@app.post("/api/start")
async def start_run(request: Request):
    body = await request.json()
    run_dir = body.get("run_dir")
    mode = body.get("mode", "standard")
    config_overrides = body.get("config_overrides", {})

    if not run_dir:
        raise HTTPException(status_code=400, detail="缺少 run_dir 参数")

    run_dir = _resolve_run_path(run_dir)

    # Prevent concurrent runs on the same directory
    for rid, info in _active_runs.items():
        if info["run_dir"] == run_dir:
            raise HTTPException(status_code=409, detail=f"该目录上已有运行中的任务（run_id: {rid}）")

    run_id = f"{os.path.basename(run_dir)}_{int(time.time())}"

    # Ensure SSE backend is active
    emitter = get_emitter()
    sse = get_sse_backend()
    if not sse:
        sse = SSEBackend()
        emitter.add_backend(sse)

    _active_runs[run_id] = {
        "run_dir": run_dir,
        "mode": mode,
        "started_at": time.time(),
        "status": "running",
    }

    thread = threading.Thread(
        target=_run_pipeline,
        args=(run_dir, run_id, mode, config_overrides),
        daemon=True,
    )
    thread.start()

    return {"run_id": run_id, "status": "started"}


@app.get("/api/events/{run_id}")
async def event_stream(run_id: str):
    """SSE endpoint for real-time progress."""
    async def event_generator():
        import asyncio as aio
        queue = asyncio.Queue()
        sse = get_sse_backend()
        if not sse:
            sse = SSEBackend()
            get_emitter().add_backend(sse)

        sse.add_listener(queue)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30)
                    yield {"event": "progress", "data": data}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        finally:
            sse.remove_listener(queue)

    return EventSourceResponse(event_generator())


@app.get("/api/status/{run_id}")
async def get_status(run_id: str):
    if run_id in _active_runs:
        return {"status": "running", **_active_runs[run_id]}
    return {"status": "completed"}


@app.post("/api/stop/{run_id}")
async def stop_run(run_id: str):
    if run_id not in _active_runs:
        raise HTTPException(status_code=404, detail="运行未找到")
    _cancel_flags[run_id] = True
    return {"status": "cancelling"}


# ---------------------------------------------------------------------------
# Batch processing — sequential run of all (or selected) run directories
# ---------------------------------------------------------------------------

def _run_batch(dirs: List[str], mode: str):
    """Run pipeline sequentially for each directory."""
    emitter = get_emitter()
    _batch_state.update({
        "active": True,
        "dirs": [os.path.basename(d) for d in dirs],
        "current_index": 0,
        "completed": [],
        "failed": [],
        "cancelled": False,
        "started_at": time.time(),
    })

    sse = get_sse_backend()
    if not sse:
        sse = SSEBackend()
        emitter.add_backend(sse)

    for idx, run_dir in enumerate(dirs):
        if _batch_state.get("cancelled"):
            break

        dir_name = os.path.basename(run_dir)
        _batch_state["current_index"] = idx

        run_id = f"batch_{dir_name}_{int(time.time())}"

        _active_runs[run_id] = {
            "run_dir": run_dir,
            "mode": mode,
            "started_at": time.time(),
            "status": "running",
        }

        if sse:
            batch_evt = json.dumps({
                "event_type": "batch_dir_started",
                "dir_name": dir_name,
                "dir_index": idx,
                "dir_total": len(dirs),
                "timestamp": time.time(),
            })
            with sse._lock:
                for q in list(sse._listeners):
                    try:
                        q.put_nowait(batch_evt)
                    except Exception:
                        pass

        try:
            _run_pipeline(run_dir, run_id, mode, {})
            _batch_state["completed"].append(dir_name)
        except Exception as e:
            _batch_state["failed"].append({"dir": dir_name, "error": str(e)})
            emitter.emit(Error(stage_name="batch", message=f"处理 {dir_name} 失败：{e}", recoverable=True))

    total_time = time.time() - _batch_state["started_at"]
    sse = get_sse_backend()
    if sse:
        batch_evt = json.dumps({
            "event_type": "batch_completed",
            "completed": len(_batch_state["completed"]),
            "failed": len(_batch_state["failed"]),
            "total": len(dirs),
            "total_time_s": total_time,
            "timestamp": time.time(),
        })
        with sse._lock:
            for q in list(sse._listeners):
                try:
                    q.put_nowait(batch_evt)
                except Exception:
                    pass
    _batch_state["active"] = False


@app.post("/api/batch-start")
async def batch_start(request: Request):
    if _batch_state.get("active"):
        raise HTTPException(status_code=409, detail="已有批量任务在运行")
    if _active_runs:
        raise HTTPException(status_code=409, detail="有单目录任务正在运行 — 请先停止")

    body = await request.json()
    mode = body.get("mode", "standard")
    selected_dirs = body.get("dirs")  # optional list of dir names

    all_dirs = _find_run_dirs()
    if selected_dirs:
        dirs = [d["path"] for d in all_dirs if d["name"] in selected_dirs]
    else:
        dirs = [d["path"] for d in all_dirs]

    if not dirs:
        raise HTTPException(status_code=400, detail="未找到任何运行目录")

    emitter = get_emitter()
    sse = get_sse_backend()
    if not sse:
        sse = SSEBackend()
        emitter.add_backend(sse)

    thread = threading.Thread(target=_run_batch, args=(dirs, mode), daemon=True)
    thread.start()

    return {"status": "started", "dirs": [os.path.basename(d) for d in dirs], "total": len(dirs)}


@app.post("/api/batch-stop")
async def batch_stop():
    if not _batch_state.get("active"):
        raise HTTPException(status_code=404, detail="没有正在运行的批量任务")
    _batch_state["cancelled"] = True
    for rid in list(_cancel_flags.keys()):
        _cancel_flags[rid] = True
    return {"status": "cancelling"}


@app.get("/api/batch-status")
async def batch_status():
    if not _batch_state:
        return {"active": False}
    return {
        "active": _batch_state.get("active", False),
        "dirs": _batch_state.get("dirs", []),
        "current_index": _batch_state.get("current_index", 0),
        "completed": _batch_state.get("completed", []),
        "failed": _batch_state.get("failed", []),
    }


@app.get("/api/config/{run_dir:path}")
async def get_config(run_dir: str):
    full_path = _resolve_run_path(run_dir)
    return {"config": _load_config_safe(full_path)}


@app.get("/api/results/{run_dir:path}")
async def get_results(run_dir: str):
    full_path = _resolve_run_path(run_dir)
    return {"results": _parse_csv_results(full_path)}


@app.get("/api/all-reviews/{run_dir:path}")
async def get_all_reviews(run_dir: str):
    """Return ALL review files for a run directory with parsed metadata and scores."""
    import re
    full_path = _resolve_run_path(run_dir)
    reviews_dir = os.path.join(full_path, "outputs", "reviews")
    if not os.path.isdir(reviews_dir):
        return {"reviews": []}

    reviews = []
    for f in sorted(glob.glob(os.path.join(reviews_dir, "*.md")), reverse=True):
        fname = os.path.basename(f)
        # Parse: {paper}_{provider1}_{model1}_{provider2}_{model2}_{YYYYMMDD_HHMMSS}.md
        parts = fname.replace(".md", "").split("_")
        timestamp = ""
        extractor = ""
        synthesizer = ""
        paper = ""

        # Find timestamp pattern (8 digits _ 6 digits)
        ts_idx = None
        for i, p in enumerate(parts):
            if re.match(r"^\d{8}$", p) and i + 1 < len(parts) and re.match(r"^\d{6}$", parts[i + 1]):
                ts_idx = i
                timestamp = f"{p}_{parts[i+1]}"
                break

        if ts_idx is not None:
            paper = "_".join(parts[:ts_idx - 4]) if ts_idx >= 5 else "_".join(parts[:ts_idx])
            extractor = "/".join(parts[ts_idx - 4:ts_idx - 2]) if ts_idx >= 4 else ""
            synthesizer = "/".join(parts[ts_idx - 2:ts_idx]) if ts_idx >= 2 else ""
        else:
            paper = fname.replace(".md", "")

        # Quick-score extraction from file content
        score = None
        recommendation = None
        cost = None
        confidence = None
        try:
            with open(f, encoding='utf-8') as fh:
                head = fh.read(4000)  # Score/rec/confidence are near the top
            with open(f, encoding='utf-8') as fh:
                fh.seek(max(0, os.path.getsize(f) - 1500))
                tail = fh.read()      # Cost is at the bottom
            # Extract score — handles "**Overall Score:** **61.4 / 100**"
            m = re.search(r"Overall Score:.*?(\d+\.?\d*)\s*(?:/\s*100)?", head, re.IGNORECASE)
            if m:
                score = float(m.group(1))
            # Extract recommendation — handles "**Recommendation:** **REVISE AND RESUBMIT**"
            m = re.search(r"Recommendation:.*?((?:Accept|Revise|Reject|Resubmit|Strong|Weak|Minor|Major)[A-Za-z\s&]*?)[\*\n\r]", head, re.IGNORECASE)
            if m:
                recommendation = m.group(1).strip()
            # Extract cost — at bottom of file
            m = re.search(r"(?:Total\s+)?(?:API\s+)?Cost:.*?[\$]?([\d.]+)", tail, re.IGNORECASE)
            if m:
                cost = float(m.group(1))
            # Extract confidence — handles "**Confidence:** 85%" or "**Confidence:** 0.85"
            m = re.search(r"Confidence:\s*\*{0,2}\s*(\d+\.?\d*)\s*%?", head, re.IGNORECASE)
            if m:
                val = float(m.group(1))
                confidence = val if val <= 1.0 else val / 100.0
        except Exception:
            pass

        # Format timestamp for display
        display_date = ""
        if timestamp:
            try:
                display_date = datetime.strptime(timestamp, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M")
            except ValueError:
                display_date = timestamp

        reviews.append({
            "filename": fname,
            "paper": paper,
            "extractor_model": extractor,
            "synthesizer_model": synthesizer,
            "timestamp": timestamp,
            "display_date": display_date,
            "overall_score": score,
            "recommendation": recommendation,
            "total_cost": cost,
            "confidence": confidence,
            "size": os.path.getsize(f),
        })

    return {"reviews": reviews}


@app.get("/api/review/{run_dir:path}/{filename:path}")
async def get_review(run_dir: str, filename: str):
    full_path = _resolve_run_path(run_dir)
    reviews_dir = Path(full_path) / "outputs" / "reviews"
    review_path = (reviews_dir / filename).resolve()
    if not str(review_path).startswith(str(reviews_dir.resolve())):
        raise HTTPException(status_code=403, detail="访问被拒绝")
    if not review_path.exists():
        raise HTTPException(status_code=404, detail="评审未找到")
    return FileResponse(str(review_path), media_type="text/markdown")


@app.get("/api/criteria/{run_dir:path}")
async def get_criteria(run_dir: str):
    full_path = _resolve_run_path(run_dir)
    return {"criteria": _load_criteria(full_path)}


@app.get("/api/criteria-raw/{run_dir:path}")
async def get_criteria_raw(run_dir: str):
    """Return raw YAML text of criteria.yaml for editing."""
    full_path = _resolve_run_path(run_dir)
    criteria_path = os.path.join(full_path, "input", "criteria.yaml")
    if not os.path.exists(criteria_path):
        criteria_path = os.path.join(PROJECT_ROOT, "config", "criteria.yaml")
    if not os.path.exists(criteria_path):
        raise HTTPException(status_code=404, detail="criteria.yaml 未找到")
    with open(criteria_path, encoding='utf-8') as f:
        return {"content": f.read()}


@app.put("/api/criteria/{run_dir:path}")
async def update_criteria(run_dir: str, request: Request):
    """Update criteria.yaml for a run directory."""
    import yaml
    body = await request.json()
    content = body.get("content", "")
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML 格式无效：{e}")

    full_path = _resolve_run_path(run_dir)
    criteria_path = os.path.join(full_path, "input", "criteria.yaml")
    if not os.path.exists(criteria_path):
        os.makedirs(os.path.dirname(criteria_path), exist_ok=True)
    try:
        with open(criteria_path, "w", encoding='utf-8') as f:
            f.write(content)
    except (IOError, OSError) as e:
        raise HTTPException(status_code=500, detail=f"写入评审标准失败：{e}")
    return {"success": True}


@app.put("/api/config/{run_dir:path}")
async def update_config(run_dir: str, request: Request):
    """Update a single key in the run's .env file."""
    ALLOWED_KEYS = {
        "PROVIDER_EXTRACTION", "PROVIDER_SYNTHESIS",
        "EXTRACTOR_MODEL", "SYNTHESIZER_MODEL",
        "MODEL_EXTRACTION", "MODEL_SYNTHESIS",
        "TEMPERATURE", "TEMPERATURE_EXTRACTION", "TEMPERATURE_SYNTHESIS",
        "MAX_TOKENS_EXTRACTION", "MAX_TOKENS_SYNTHESIS", "MAX_TOKENS_JUDGE",
        "TOKEN_LIMIT_DEFAULT",
        "EXTRACTION_BATCH_SIZE", "MAX_PARALLEL_EXTRACTIONS", "CONCURRENCY",
        "DOMAIN", "LANGUAGE",
        "MAX_RETRIES", "JUDGE_PROVIDER", "JUDGE_MODEL", "JUDGE_TEMPERATURE",
        "LITERATURE_GROUNDING_ENABLED",
        "LIBRARIAN_TEMPERATURE", "LIBRARIAN_SUMMARY_TEMPERATURE",
        "FACT_CHECKER_TEMPERATURE", "CRITIC_TEMPERATURE",
        "CRITIC_MAX_JSON_RETRIES", "FACT_CHECKER_MAX_RETRIES",
        "LLM_TIMEOUT", "API_TIMEOUT",
    }
    body = await request.json()
    key = body.get("key", "")
    value = body.get("value", "")

    # Sanitize NaN/Inf from numeric inputs
    if isinstance(value, float) and (value != value or abs(value) == float("inf")):
        raise HTTPException(status_code=400, detail="值必须是有效数字")

    # Prevent newline injection
    if isinstance(value, str):
        value = value.replace("\n", "").replace("\r", "")

    if not key:
        raise HTTPException(status_code=400, detail="缺少 key 参数")
    if "KEY" in key.upper() or "SECRET" in key.upper():
        raise HTTPException(status_code=400, detail="不能通过仪表盘修改 API 密钥")
    if key not in ALLOWED_KEYS:
        raise HTTPException(status_code=400, detail=f"键 '{key}' 不可编辑。允许的键：{sorted(ALLOWED_KEYS)}")

    full_path = _resolve_run_path(run_dir)
    env_path = os.path.join(full_path, "input", ".env")
    if not os.path.exists(env_path):
        raise HTTPException(status_code=404, detail=".env 未找到")

    # Read, update, write back — preserving comments and order
    lines = []
    found = False
    with open(env_path, encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, _ = stripped.split("=", 1)
                if k == key:
                    lines.append(f"{key}={value}\n")
                    found = True
                    continue
            lines.append(line)
    if not found:
        lines.append(f"{key}={value}\n")
    with open(env_path, "w", encoding='utf-8') as f:
        f.writelines(lines)

    return {"config": _load_config_safe(full_path)}


@app.get("/api/prompts")
async def get_prompts():
    """Return all prompt files with their content."""
    prompts_dir = os.path.join(PROJECT_ROOT, "config", "prompts")
    if not os.path.isdir(prompts_dir):
        return {"prompts": []}
    prompts = []
    for fn in sorted(os.listdir(prompts_dir)):
        if fn.endswith(".txt"):
            with open(os.path.join(prompts_dir, fn), encoding='utf-8') as f:
                prompts.append({"filename": fn, "content": f.read()})
    return {"prompts": prompts}


@app.put("/api/prompts/{filename}")
async def update_prompt(filename: str, request: Request):
    """Update a prompt file."""
    ALLOWED_PROMPTS = {
        "extractor_system.txt", "extractor_user.txt",
        "synthesizer_system.txt", "synthesizer_user.txt",
    }
    if filename not in ALLOWED_PROMPTS:
        raise HTTPException(status_code=400, detail=f"未知提示词文件：{filename}")

    body = await request.json()
    content = body.get("content", "")

    prompt_path = os.path.join(PROJECT_ROOT, "config", "prompts", filename)
    try:
        with open(prompt_path, "w", encoding='utf-8') as f:
            f.write(content)
    except (IOError, OSError) as e:
        raise HTTPException(status_code=500, detail=f"写入提示词失败：{e}")
    return {"success": True}


@app.get("/api/literature-sources")
async def get_literature_sources():
    """Return literature_sources.yaml content."""
    path = os.path.join(PROJECT_ROOT, "config", "literature_sources.yaml")
    if not os.path.exists(path):
        return {"content": ""}
    with open(path, encoding='utf-8') as f:
        return {"content": f.read()}


@app.put("/api/literature-sources")
async def update_literature_sources(request: Request):
    """Update literature_sources.yaml."""
    import yaml
    body = await request.json()
    content = body.get("content", "")
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML 格式无效：{e}")

    path = os.path.join(PROJECT_ROOT, "config", "literature_sources.yaml")
    try:
        with open(path, "w", encoding='utf-8') as f:
            f.write(content)
    except (IOError, OSError) as e:
        raise HTTPException(status_code=500, detail=f"写入文献源配置失败：{e}")
    return {"success": True}


@app.get("/api/model-costs")
async def get_model_costs():
    """Return model_costs.yaml content and litellm's known pricing for active models."""
    import yaml
    path = os.path.join(PROJECT_ROOT, "config", "model_costs.yaml")
    yaml_content = ""
    custom_models = {}
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            yaml_content = f.read()
        try:
            data = yaml.safe_load(yaml_content) or {}
            custom_models = data.get("models", {})
        except yaml.YAMLError:
            pass

    # Also return litellm's built-in pricing for commonly used models
    import litellm
    builtin = {}
    for model_key in list(litellm.model_cost.keys()):
        info = litellm.model_cost[model_key]
        inp = info.get("input_cost_per_token", 0)
        out = info.get("output_cost_per_token", 0)
        if inp or out:
            builtin[model_key] = {
                "input_cost_per_million": round(inp * 1_000_000, 4),
                "output_cost_per_million": round(out * 1_000_000, 4),
                "source": "litellm" if model_key not in custom_models else "custom",
            }

    return {"content": yaml_content, "custom_models": custom_models, "builtin_count": len(builtin)}


@app.put("/api/model-costs")
async def update_model_costs(request: Request):
    """Update model_costs.yaml and re-register models with litellm."""
    import yaml
    body = await request.json()
    content = body.get("content", "")
    try:
        data = yaml.safe_load(content)
        if data and "models" in data:
            for name, info in data["models"].items():
                if not isinstance(info, dict):
                    raise ValueError(f"模型 '{name}' 必须是字典格式")
        elif data is not None:
            raise ValueError("YAML 必须包含 'models' 键")
    except (yaml.YAMLError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"YAML 格式无效：{e}")

    path = os.path.join(PROJECT_ROOT, "config", "model_costs.yaml")
    try:
        with open(path, "w", encoding='utf-8') as f:
            f.write(content)
    except (IOError, OSError) as e:
        raise HTTPException(status_code=500, detail=f"写入模型费用失败：{e}")

    # Re-register models with litellm
    from core.llm_wrapper import _load_and_register_custom_models
    _load_and_register_custom_models()

    return {"success": True}


@app.get("/api/model-costs/lookup/{model_name:path}")
async def lookup_model_cost(model_name: str):
    """Look up litellm's pricing for a specific model."""
    import litellm
    info = litellm.model_cost.get(model_name, {})
    if not info:
        raise HTTPException(status_code=404, detail=f"模型 '{model_name}' 在 litellm 注册表中未找到")
    return {
        "model": model_name,
        "input_cost_per_million": round(info.get("input_cost_per_token", 0) * 1_000_000, 4),
        "output_cost_per_million": round(info.get("output_cost_per_token", 0) * 1_000_000, 4),
        "max_input_tokens": info.get("max_input_tokens"),
        "max_output_tokens": info.get("max_output_tokens"),
    }


@app.get("/api/reviews/{run_dir:path}")
async def list_reviews(run_dir: str):
    full_path = _resolve_run_path(run_dir)
    return {"reviews": _get_reviews(full_path)}


# ---------------------------------------------------------------------------
# Judge endpoints
# ---------------------------------------------------------------------------

_active_judges: Dict[str, bool] = {}


def _run_judge_pipeline(run_dir: str, run_id: str):
    """Run compare + judge in a background thread."""
    from compare_reports import find_discrepancies
    from judge_conflicts import adjudicate_conflicts

    emitter = get_emitter()

    try:
        _active_judges[run_id] = True

        # Stage 1: Compare reports
        emitter.emit(StageStarted(stage_name="Judge-Compare", paper_filename=""))
        t0 = time.time()

        # find_discrepancies prints to stdout; we capture the key info ourselves
        reports_dir = os.path.join(run_dir, "outputs", "reports")
        csv_files = sorted(glob.glob(os.path.join(reports_dir, "report_consolidated_*.csv")))
        if len(csv_files) < 2:
            emitter.emit(Error(stage_name="Judge-Compare",
                               message="需要至少 2 份汇总报告才能对比。请先用不同模型运行评审。",
                               recoverable=False))
            return

        find_discrepancies(run_dir)

        discrepancy_files = sorted(glob.glob(os.path.join(reports_dir, "HUMAN_REVIEW_discrepancies_*.csv")))
        if not discrepancy_files:
            emitter.emit(StageCompleted(stage_name="Judge-Compare", duration_s=time.time() - t0,
                                        result_summary="No conflicts found"))
            emitter.emit(RunCompleted(total_papers=0, total_cost=0.0, total_time_s=time.time() - t0,
                                      output_dir=os.path.join(run_dir, "outputs")))
            return

        import pandas as pd
        disc_df = pd.read_csv(discrepancy_files[-1])
        conflict_count = disc_df["paper_filename"].nunique() if "paper_filename" in disc_df.columns else 0
        emitter.emit(StageCompleted(stage_name="Judge-Compare", duration_s=time.time() - t0,
                                    result_summary=f"{conflict_count} conflicts found"))

        # Stage 2: Adjudicate
        emitter.emit(StageStarted(stage_name="Judge-Adjudicate", paper_filename=""))
        t1 = time.time()
        adjudicate_conflicts(run_dir)
        emitter.emit(StageCompleted(stage_name="Judge-Adjudicate", duration_s=time.time() - t1,
                                    result_summary="Done"))

        emitter.emit(RunCompleted(total_papers=conflict_count, total_cost=0.0,
                                  total_time_s=time.time() - t0,
                                  output_dir=os.path.join(run_dir, "outputs")))
    except Exception as e:
        import traceback
        emitter.emit(Error(stage_name="judge", message=str(e), recoverable=False))
        traceback.print_exc()
    finally:
        _active_judges.pop(run_id, None)


@app.post("/api/judge/{run_dir:path}")
async def start_judge(run_dir: str):
    """Start the compare + judge pipeline for a run directory."""
    full_path = _resolve_run_path(run_dir)

    reports_dir = os.path.join(full_path, "outputs", "reports")
    csv_files = glob.glob(os.path.join(reports_dir, "report_consolidated_*.csv"))
    if len(csv_files) < 2:
        raise HTTPException(
            status_code=400,
            detail="需要至少 2 份汇总报告。请先用不同模型运行评审。",
        )

    run_id = f"judge_{os.path.basename(run_dir)}_{int(time.time())}"

    emitter = get_emitter()
    sse = get_sse_backend()
    if not sse:
        sse = SSEBackend()
        emitter.add_backend(sse)

    thread = threading.Thread(target=_run_judge_pipeline, args=(full_path, run_id), daemon=True)
    thread.start()

    return {"run_id": run_id, "status": "started"}


@app.get("/api/judge/results/{run_dir:path}")
async def get_judge_results(run_dir: str):
    """Return the latest judge verdicts CSV as JSON."""
    import pandas as pd
    full_path = _resolve_run_path(run_dir)
    reports_dir = os.path.join(full_path, "outputs", "reports")
    if not os.path.isdir(reports_dir):
        return {"verdicts": []}
    verdict_files = sorted(glob.glob(os.path.join(reports_dir, "JUDGE_VERDICTS_report_*.csv")), reverse=True)
    if not verdict_files:
        return {"verdicts": []}
    try:
        df = pd.read_csv(verdict_files[0])
        return {"verdicts": df.fillna("").to_dict(orient="records")}
    except Exception:
        return {"verdicts": []}


@app.get("/api/judge/status/{run_id}")
async def judge_status(run_id: str):
    if run_id in _active_judges:
        return {"status": "running"}
    return {"status": "completed"}


# ---------------------------------------------------------------------------
# File Upload
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {".pdf", ".md", ".txt", ".docx"}

@app.post("/api/upload/{run_dir:path}")
async def upload_papers(run_dir: str, files: list[UploadFile] = File(...)):
    """Upload one or more papers to a run directory's papers folder."""
    run_path = _resolve_run_path(run_dir)
    papers_dir = os.path.join(run_path, "papers")
    os.makedirs(papers_dir, exist_ok=True)

    uploaded = []
    skipped = []

    for file in files:
        if not file.filename:
            continue

        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            skipped.append({"filename": file.filename, "reason": f"不支持的文件类型 {ext}，仅支持 PDF/MD/TXT/DOCX"})
            continue

        dest = os.path.join(papers_dir, file.filename)
        # If file exists, add suffix to avoid overwriting
        if os.path.exists(dest):
            base = Path(file.filename).stem
            counter = 1
            while os.path.exists(os.path.join(papers_dir, f"{base}_{counter}{ext}")):
                counter += 1
            dest = os.path.join(papers_dir, f"{base}_{counter}{ext}")
            uploaded.append({"filename": os.path.basename(dest), "original": file.filename, "renamed": True})
        else:
            uploaded.append({"filename": file.filename, "original": file.filename, "renamed": False})

        content = await file.read()
        with open(dest, "wb") as f:
            f.write(content)

    return {
        "success": True,
        "uploaded": uploaded,
        "skipped": skipped,
        "papers_dir": papers_dir,
        "total": len(uploaded),
    }

@app.get("/api/papers/{run_dir:path}")
async def list_papers(run_dir: str):
    """List papers currently in a run directory."""
    run_path = _resolve_run_path(run_dir)
    papers_dir = os.path.join(run_path, "papers")
    if not os.path.isdir(papers_dir):
        return {"papers": [], "count": 0}
    papers = sorted(
        [f for f in os.listdir(papers_dir) if Path(f).suffix.lower() in ALLOWED_EXTENSIONS],
        key=lambda f: os.path.getmtime(os.path.join(papers_dir, f)),
        reverse=True,
    )
    return {"papers": papers, "count": len(papers), "papers_dir": papers_dir}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Agentic Paper Review System - Web Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8050, help="Port to bind")
    args = parser.parse_args()

    import uvicorn
    print(f"Starting Agentic Paper Review System dashboard on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
