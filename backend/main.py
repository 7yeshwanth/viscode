"""
VisCode FastAPI Server

REST API + SSE streaming for the code visualization tool.
"""

from __future__ import annotations

import uuid
import json
import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from config import config
from models.analysis import AnalyzeRequest, HealthResponse, CostEstimate
from services.orchestrator import AnalysisOrchestrator

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("viscode.server")


# ──────────────────────────────────────────────
# App State
# ──────────────────────────────────────────────
orchestrator = AnalysisOrchestrator()
# Store results in memory (keyed by project_id)
# Each entry includes a timestamp for TTL eviction
project_results: dict[str, dict] = {}
# Limit concurrent analyses to prevent overload
_active_analyses = 0
_MAX_CONCURRENT_ANALYSES = 3
_PROJECT_TTL_SECONDS = 3600  # 1 hour


def _evict_stale_results():
    """Remove project results older than TTL to prevent memory leaks."""
    now = time.time()
    stale_ids = [
        pid for pid, data in project_results.items()
        if now - data.get("created_at", now) > _PROJECT_TTL_SECONDS
    ]
    for pid in stale_ids:
        del project_results[pid]
    if stale_ids:
        logger.info(f"Evicted {len(stale_ids)} stale project results")


# ──────────────────────────────────────────────
# Lifespan
# ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    warnings = config.validate()
    for w in warnings:
        logger.warning(f"⚠️  {w}")
    logger.info(f"VisCode server starting on {config.HOST}:{config.PORT}")
    cache_stats = orchestrator.cache.stats()
    logger.info(f"Cache: {cache_stats['entries']} entries, {cache_stats['size_bytes']} bytes")
    yield
    logger.info("VisCode server shutting down")


# ──────────────────────────────────────────────
# App
# ──────────────────────────────────────────────
app = FastAPI(
    title="VisCode API",
    description="AI-powered code visualization backend",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# Middleware: Request ID
# ──────────────────────────────────────────────
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    api_key_valid = bool(
        config.OPENAI_API_KEY
        and config.OPENAI_API_KEY != "sk-your-key-here"
    )
    return HealthResponse(
        status="ok",
        api_key_valid=api_key_valid,
        version="1.0.0",
        cache_dir=str(config.get_cache_path()),
    )


@app.post("/api/analyze")
async def start_analysis(request: AnalyzeRequest):
    """
    Start project analysis. Returns project_id immediately.
    Use the SSE endpoint to stream progress.
    """
    # Evict stale results (older than 1 hour)
    _evict_stale_results()

    # Quick validation
    from services.scanner import validate_project_path
    valid, error = validate_project_path(request.path)
    if not valid:
        raise HTTPException(status_code=400, detail=error)

    # Check concurrent limit
    global _active_analyses
    if _active_analyses >= _MAX_CONCURRENT_ANALYSES:
        raise HTTPException(status_code=429, detail=f"Too many concurrent analyses ({_active_analyses} running). Please wait.")

    project_id = uuid.uuid4().hex[:12]

    # Store initial state
    project_results[project_id] = {
        "status": "queued",
        "path": request.path,
        "model_tier": request.model_tier,
        "ignore_patterns": request.ignore_patterns,
        "created_at": time.time(),
    }

    return {"project_id": project_id, "status": "queued", "message": "Analysis queued. Stream progress via /api/analyze/{project_id}/stream"}


@app.get("/api/analyze/{project_id}/stream")
async def stream_analysis(project_id: str):
    """
    SSE endpoint — starts analysis and streams progress events.
    """
    project_info = project_results.get(project_id)
    if not project_info:
        raise HTTPException(status_code=404, detail="Project not found")

    async def event_generator():
        global _active_analyses
        _active_analyses += 1
        progress_queue: asyncio.Queue = asyncio.Queue()

        def on_progress(phase: str, message: str, percent: float):
            progress_queue.put_nowait({
                "phase": phase,
                "message": message,
                "percent": round(percent, 1),
            })

        # Run analysis in background
        async def run_analysis():
            try:
                _, project, graph = await orchestrator.analyze_project(
                    path=project_info["path"],
                    progress=on_progress,
                    extra_ignore=project_info.get("ignore_patterns"),
                    model_tier=project_info.get("model_tier", "balanced"),
                )
                # Store results but exclude heavy fields to save memory
                project_results[project_id] = {
                    "status": "complete",
                    "created_at": time.time(),
                    "project": project.model_dump(exclude={
                        "manifest": {"files": {"__all__": {"absolute_path"}}}
                    }),
                    "graph": graph.model_dump(),
                }
                progress_queue.put_nowait({"phase": "done", "message": "Analysis complete", "percent": 100})
            except Exception as e:
                logger.error(f"Analysis failed: {e}")
                project_results[project_id] = {"status": "error", "error": str(e), "created_at": time.time()}
                progress_queue.put_nowait({"phase": "error", "message": str(e), "percent": 0})

        task = asyncio.create_task(run_analysis())

        # Stream progress events
        while True:
            try:
                event = await asyncio.wait_for(progress_queue.get(), timeout=120)
                yield {
                    "event": event["phase"],
                    "data": json.dumps(event),
                }
                if event["phase"] in ("done", "error"):
                    break
            except asyncio.TimeoutError:
                yield {"event": "heartbeat", "data": '{"status":"alive"}'}

        _active_analyses = max(0, _active_analyses - 1)
        await task

    return EventSourceResponse(event_generator())


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    """Get complete project analysis results."""
    result = project_results.get(project_id)
    if not result:
        raise HTTPException(status_code=404, detail="Project not found")
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))
    if result.get("status") != "complete":
        return {"status": result.get("status", "pending"), "message": "Analysis still in progress"}
    return result


@app.get("/api/projects/{project_id}/graph")
async def get_project_graph(project_id: str):
    """Get the visualization graph data."""
    result = project_results.get(project_id)
    if not result or result.get("status") != "complete":
        raise HTTPException(status_code=404, detail="Project not found or analysis not complete")
    return result.get("graph", {})


@app.get("/api/projects/{project_id}/file/{file_path:path}")
async def get_file_detail(project_id: str, file_path: str):
    """Get detailed analysis and graph for a specific file."""
    result = project_results.get(project_id)
    if not result or result.get("status") != "complete":
        raise HTTPException(status_code=404, detail="Project not found or not complete")

    project_data = result.get("project", {})
    file_analyses = project_data.get("file_analyses", {})
    analysis = file_analyses.get(file_path)

    if not analysis:
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    # Build file detail graph
    from models.analysis import FileAnalysis
    from services.graph_builder import build_file_detail_graph
    fa = FileAnalysis(**analysis)
    graph = build_file_detail_graph(file_path, fa)

    return {
        "analysis": analysis,
        "graph": graph.model_dump() if graph else None,
    }


@app.post("/api/estimate")
async def estimate_analysis(request: AnalyzeRequest):
    """Estimate cost and time for analyzing a project (no AI calls)."""
    try:
        estimate = orchestrator.get_estimate(request.path, request.model_tier)
        return estimate
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/cache/stats")
async def cache_stats():
    """Get cache statistics."""
    return orchestrator.cache.stats()


@app.delete("/api/cache")
async def clear_cache():
    """Clear the analysis cache."""
    count = orchestrator.cache.clear()
    return {"message": f"Cleared {count} cache entries"}


# ──────────────────────────────────────────────
# Error Handler
# ──────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_error_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__},
    )


# ──────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    import socket

    port = config.PORT
    # Auto-find available port if configured one is in use
    for attempt in range(10):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind((config.HOST, port))
            sock.close()
            break
        except OSError:
            logger.warning(f"Port {port} in use, trying {port + 1}...")
            port += 1

    if port != config.PORT:
        logger.info(f"Using port {port} (configured port {config.PORT} was in use)")

    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=port,
        reload=True,
        log_level="info",
    )
