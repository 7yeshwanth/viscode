"""
VisCode Analysis Orchestrator

Coordinates the full analysis pipeline:
Scan → Extract → Chunk → AI Analyze → Validate → Cache → Build Graph

Handles partial failures gracefully — never aborts the full pipeline.
Reports progress via callback for SSE streaming.
"""

from __future__ import annotations

import json
import uuid
import asyncio
import logging
from typing import Callable, Any

from config import config
from models.analysis import (
    FileManifest, FileAnalysis, ProjectAnalysis,
    CrossFileAnalysis, ArchitectureSummary, GraphData, FileStatus,
)
from services.scanner import scan_project, validate_project_path, estimate_cost
from services.extractor import extract_ground_truth
from services.chunker import chunk_file
from services.analyzer import AIAnalyzer
from services.validator import validate_analysis
from services.graph_builder import build_overview_graph, build_file_detail_graph
from cache.analysis_cache import AnalysisCache

logger = logging.getLogger("viscode.orchestrator")

# Type for progress callbacks
ProgressCallback = Callable[[str, str, float], Any]  # (phase, message, percent)


def _noop_progress(phase: str, message: str, percent: float) -> None:
    """Default no-op progress callback."""
    pass


class AnalysisOrchestrator:
    """Orchestrates the full code analysis pipeline."""

    def __init__(self):
        self.analyzer = AIAnalyzer()
        self.cache = AnalysisCache()
        self._active_projects: dict[str, dict] = {}

    def get_project_status(self, project_id: str) -> dict | None:
        """Get current status of a project analysis."""
        return self._active_projects.get(project_id)

    async def analyze_project(
        self,
        path: str,
        progress: ProgressCallback | None = None,
        extra_ignore: list[str] | None = None,
        model_tier: str = "balanced",
    ) -> tuple[str, ProjectAnalysis, GraphData]:
        """
        Run the full analysis pipeline on a project.

        Args:
            path: Absolute path to the project directory.
            progress: Callback for progress updates.
            extra_ignore: Additional glob patterns to ignore.
            model_tier: "fast", "balanced", or "deep".

        Returns:
            (project_id, ProjectAnalysis, GraphData)
        """
        cb = progress or _noop_progress
        project_id = uuid.uuid4().hex[:12]

        self._active_projects[project_id] = {
            "status": "starting", "percent": 0, "message": "",
        }

        try:
            # ── Step 1: Validate Path ──
            cb("validating", "Validating project path...", 2)
            valid, error = validate_project_path(path)
            if not valid:
                raise ValueError(f"Invalid project path: {error}")

            # ── Step 2: Scan ──
            cb("scanning", "Scanning project files...", 5)
            manifest = scan_project(path, extra_ignore)
            skipped_count = len(manifest.skipped)
            cb("scanning", f"Found {manifest.total_files} code files ({skipped_count} skipped)", 8)

            if manifest.total_files == 0:
                raise ValueError(
                    f"No supported code files found in {path}. "
                    f"Supported languages: {', '.join(sorted(config.LANGUAGE_MAP.values()))}"
                )

            # ── Step 3: Check Cache ──
            cb("cache_check", "Checking cache...", 10)
            file_analyses: dict[str, FileAnalysis] = {}
            uncached_files = []

            for file_info in manifest.files:
                if file_info.is_generated or file_info.is_minified:
                    file_info.status = FileStatus.SKIPPED
                    continue

                cached = self.cache.get(file_info.content_hash)
                if cached:
                    file_analyses[file_info.path] = cached
                    file_info.status = FileStatus.CACHED
                else:
                    uncached_files.append(file_info)

            cached_count = len(file_analyses)
            cb("cache_check", f"{cached_count} files cached, {len(uncached_files)} to analyze", 12)

            # ── Step 4: Extract + Analyze uncached files ──
            failed_files: list[dict[str, str]] = []
            total_to_analyze = len(uncached_files)

            for idx, file_info in enumerate(uncached_files):
                percent = 15 + (idx / max(1, total_to_analyze)) * 70  # 15% → 85%
                file_info.status = FileStatus.ANALYZING

                try:
                    cb("analyzing", f"[{idx + 1}/{total_to_analyze}] {file_info.path}", percent)

                    # Read file content
                    with open(file_info.absolute_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()

                    # Extract ground truth
                    ground_truth = extract_ground_truth(
                        file_info.path, content, file_info.language
                    )

                    # Chunk if needed
                    chunks = chunk_file(file_info.path, content, ground_truth)

                    # AI analysis for each chunk
                    gt_json = json.dumps([
                        {"name": i.name, "kind": i.kind.value,
                         "line_start": i.line_start, "line_end": i.line_end,
                         "parent": i.parent, "params": i.params}
                        for i in ground_truth.identifiers
                    ], indent=2)

                    chunk_results: list[dict] = []
                    for chunk in chunks:
                        raw = await self.analyzer.analyze_file(
                            chunk, gt_json, file_info.language, model_tier
                        )
                        chunk_results.append(raw)

                    # Merge chunk results (use first chunk as base, extend lists)
                    merged = chunk_results[0] if chunk_results else {}
                    for cr in chunk_results[1:]:
                        for key in ("functions", "classes", "endpoints", "data_models",
                                    "variables", "key_logic", "error_handling", "imports_analysis"):
                            if key in cr:
                                merged.setdefault(key, []).extend(cr[key])

                    # Parse into model
                    file_analysis = self.analyzer.parse_pass1_result(
                        merged, file_info.path, file_info.language
                    )

                    # Validate against ground truth
                    file_analysis, corrections = validate_analysis(file_analysis, ground_truth)

                    if corrections:
                        logger.info(f"  {len(corrections)} corrections for {file_info.path}")

                    # Cache the result
                    self.cache.put(file_info.content_hash, file_analysis)

                    file_analyses[file_info.path] = file_analysis
                    file_info.status = FileStatus.COMPLETED

                except Exception as e:
                    logger.error(f"Failed to analyze {file_info.path}: {e}")
                    failed_files.append({"path": file_info.path, "error": str(e)})
                    file_info.status = FileStatus.FAILED
                    file_info.error = str(e)
                    cb("warning", f"Failed: {file_info.path} — {e}", percent)

            # ── Step 5: Pass 2 — Cross-File Analysis ──
            cross_file: CrossFileAnalysis | None = None
            if file_analyses:
                try:
                    cb("cross_analysis", "Analyzing cross-file relationships...", 87)
                    file_summaries = {
                        path: a.file_summary for path, a in file_analyses.items()
                    }
                    import_map = {
                        path: [{"name": imp.name, "source": imp.source} for imp in a.imports]
                        for path, a in file_analyses.items()
                    }
                    cross_file = await self.analyzer.analyze_cross_file(
                        file_summaries, import_map, manifest.languages, model_tier
                    )
                except Exception as e:
                    logger.error(f"Cross-file analysis failed: {e}")
                    cb("warning", f"Cross-file analysis unavailable: {e}", 90)

            # ── Step 6: Pass 3 — Architecture Summary ──
            architecture: ArchitectureSummary | None = None
            if file_analyses and cross_file:
                try:
                    cb("architecture", "Generating architecture overview...", 92)
                    file_summaries = {
                        path: a.file_summary for path, a in file_analyses.items()
                    }
                    architecture = await self.analyzer.analyze_architecture(
                        file_summaries, cross_file,
                        manifest.total_files, manifest.total_lines,
                        manifest.languages, model_tier
                    )
                except Exception as e:
                    logger.error(f"Architecture analysis failed: {e}")
                    cb("warning", f"Architecture overview unavailable: {e}", 95)

            # ── Step 7: Build Graph ──
            cb("building_graph", "Creating visualization...", 96)
            graph = build_overview_graph(
                manifest, file_analyses, cross_file, architecture, failed_files
            )

            # ── Step 8: Assemble result ──
            project = ProjectAnalysis(
                project_id=project_id,
                project_root=path,
                manifest=manifest,
                file_analyses=file_analyses,
                cross_file=cross_file,
                architecture=architecture,
                failed_files=failed_files,
            )

            stats = self.analyzer.get_stats()
            cache_stats = self.cache.stats()
            cb("complete",
               f"Done! {len(file_analyses)} analyzed, {len(failed_files)} failed, "
               f"{cached_count} cached. API calls: {stats['api_calls']}",
               100)

            self._active_projects[project_id] = {
                "status": "complete", "percent": 100,
                "message": f"{len(file_analyses)} files analyzed",
            }

            return project_id, project, graph

        except Exception as e:
            self._active_projects[project_id] = {
                "status": "error", "percent": 0, "message": str(e),
            }
            raise

    def get_file_detail(
        self,
        project: ProjectAnalysis,
        file_path: str,
    ) -> GraphData | None:
        """Get detailed graph for a specific file."""
        analysis = project.file_analyses.get(file_path)
        if not analysis:
            return None
        return build_file_detail_graph(file_path, analysis)

    def get_estimate(self, path: str, model_tier: str = "balanced") -> dict:
        """Get cost/time estimate for a project without running analysis."""
        valid, error = validate_project_path(path)
        if not valid:
            raise ValueError(error)
        manifest = scan_project(path)
        return estimate_cost(manifest, model_tier)
