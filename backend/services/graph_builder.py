"""
VisCode Graph Builder

Transforms analysis results into visualization graph data (nodes + edges)
ready for the D3.js frontend canvas.
"""

from __future__ import annotations

import logging
from models.analysis import (
    FileManifest, FileAnalysis, CrossFileAnalysis, ArchitectureSummary,
    GraphNode, GraphEdge, GraphData, NodeType, EdgeType, LayoutHint, FileStatus,
)

logger = logging.getLogger("viscode.graph")


def build_overview_graph(
    manifest: FileManifest,
    file_analyses: dict[str, FileAnalysis],
    cross_file: CrossFileAnalysis | None,
    architecture: ArchitectureSummary | None,
    failed_files: list[dict[str, str]] | None = None,
) -> GraphData:
    """
    Build the project overview graph: files as nodes, imports as edges.

    Args:
        manifest: Scanned file manifest.
        file_analyses: Per-file AI analysis results.
        cross_file: Cross-file relationship analysis.
        architecture: Architecture summary.
        failed_files: List of {path, error} for failed analyses.

    Returns:
        GraphData ready for frontend rendering.
    """
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    failed_set = {f["path"] for f in (failed_files or [])}
    failed_errors = {f["path"]: f.get("error", "Unknown") for f in (failed_files or [])}

    # --- Create folder nodes ---
    folders_seen: set[str] = set()
    for file_info in manifest.files:
        parts = file_info.path.split("/")
        for depth in range(1, len(parts)):
            folder_path = "/".join(parts[:depth])
            if folder_path not in folders_seen:
                folders_seen.add(folder_path)
                parent_path = "/".join(parts[:depth - 1]) if depth > 1 else None
                nodes.append(GraphNode(
                    id=f"folder:{folder_path}",
                    label=parts[depth - 1],
                    type=NodeType.FOLDER,
                    description=f"Directory: {folder_path}",
                    metadata={"path": folder_path, "depth": depth},
                ))
                # Folder containment edge
                if parent_path:
                    edges.append(GraphEdge(
                        id=f"contains:{parent_path}->{folder_path}",
                        source=f"folder:{parent_path}",
                        target=f"folder:{folder_path}",
                        type=EdgeType.CONTAINS,
                    ))

    # --- Create file nodes ---
    for file_info in manifest.files:
        analysis = file_analyses.get(file_info.path)
        is_failed = file_info.path in failed_set

        metadata = {
            "language": file_info.language,
            "line_count": file_info.line_count,
            "size_bytes": file_info.size_bytes,
        }

        if analysis:
            metadata["role"] = analysis.role_in_project
            metadata["summary"] = analysis.file_summary
            metadata["function_count"] = len(analysis.functions)
            metadata["class_count"] = len(analysis.classes)
            metadata["endpoint_count"] = len(analysis.endpoints)

        if is_failed:
            metadata["error"] = failed_errors.get(file_info.path, "Analysis failed")

        # Determine status
        if is_failed:
            status = FileStatus.FAILED
        elif file_info.is_minified:
            status = FileStatus.SKIPPED
        elif analysis:
            status = FileStatus.COMPLETED
        else:
            status = FileStatus.PENDING

        description = ""
        if analysis:
            description = analysis.file_summary
        elif is_failed:
            description = f"⚠️ Analysis failed: {metadata.get('error', 'Unknown error')}"

        nodes.append(GraphNode(
            id=f"file:{file_info.path}",
            label=file_info.path.split("/")[-1],
            type=NodeType.FILE,
            description=description,
            metadata=metadata,
            file_path=file_info.path,
            status=status,
        ))

        # File → folder containment
        parts = file_info.path.split("/")
        if len(parts) > 1:
            parent_folder = "/".join(parts[:-1])
            edges.append(GraphEdge(
                id=f"contains:{parent_folder}->{file_info.path}",
                source=f"folder:{parent_folder}",
                target=f"file:{file_info.path}",
                type=EdgeType.CONTAINS,
            ))

    # --- Create import edges from cross-file analysis ---
    if cross_file:
        for rel in cross_file.relationships:
            edge_id = f"{rel.relationship_type}:{rel.source_file}->{rel.target_file}"
            edge_type = {
                "imports": EdgeType.IMPORTS,
                "calls": EdgeType.CALLS,
                "extends": EdgeType.EXTENDS,
                "implements": EdgeType.IMPLEMENTS,
            }.get(rel.relationship_type, EdgeType.IMPORTS)

            edges.append(GraphEdge(
                id=edge_id,
                source=f"file:{rel.source_file}",
                target=f"file:{rel.target_file}",
                type=edge_type,
                label=", ".join(rel.details[:3]),  # Show first 3 details
            ))

    return GraphData(
        nodes=nodes,
        edges=edges,
        view_type="overview",
        layout_hint=LayoutHint.DAGRE,
        architecture=architecture,
    )


def build_file_detail_graph(
    file_path: str,
    analysis: FileAnalysis,
) -> GraphData:
    """
    Build a detail graph for a single file: shows internal structure
    (classes, functions, endpoints as nodes).
    """
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    # File root node
    nodes.append(GraphNode(
        id=f"file:{file_path}",
        label=file_path.split("/")[-1],
        type=NodeType.FILE,
        description=analysis.file_summary,
        metadata={"role": analysis.role_in_project, "language": analysis.language},
        file_path=file_path,
    ))

    # Classes
    for cls in analysis.classes:
        cls_id = f"class:{file_path}:{cls.name}"
        nodes.append(GraphNode(
            id=cls_id,
            label=cls.name,
            type=NodeType.CLASS,
            description=cls.description,
            metadata={
                "purpose": cls.purpose,
                "inherits_from": cls.inherits_from,
            },
            file_path=file_path,
            line_start=cls.line_start,
            line_end=cls.line_end,
            confidence=cls.confidence,
        ))
        edges.append(GraphEdge(
            id=f"contains:{file_path}->{cls.name}",
            source=f"file:{file_path}",
            target=cls_id,
            type=EdgeType.CONTAINS,
        ))

        # Methods inside class
        for method in cls.methods:
            method_id = f"method:{file_path}:{cls.name}.{method.name}"
            nodes.append(GraphNode(
                id=method_id,
                label=method.name,
                type=NodeType.METHOD,
                description=method.description,
                metadata={
                    "purpose": method.purpose,
                    "complexity": method.complexity.value if method.complexity else "simple",
                    "side_effects": method.side_effects,
                    "calls": method.calls,
                },
                file_path=file_path,
                line_start=method.line_start,
                line_end=method.line_end,
                confidence=method.confidence,
            ))
            edges.append(GraphEdge(
                id=f"contains:{cls.name}->{method.name}",
                source=cls_id,
                target=method_id,
                type=EdgeType.CONTAINS,
            ))

    # Standalone functions
    for func in analysis.functions:
        func_id = f"func:{file_path}:{func.name}"
        nodes.append(GraphNode(
            id=func_id,
            label=func.name,
            type=NodeType.FUNCTION,
            description=func.description,
            metadata={
                "purpose": func.purpose,
                "complexity": func.complexity.value if func.complexity else "simple",
                "side_effects": func.side_effects,
                "calls": func.calls,
            },
            file_path=file_path,
            line_start=func.line_start,
            line_end=func.line_end,
            confidence=func.confidence,
        ))
        edges.append(GraphEdge(
            id=f"contains:{file_path}->{func.name}",
            source=f"file:{file_path}",
            target=func_id,
            type=EdgeType.CONTAINS,
        ))

    # Endpoints
    for ep in analysis.endpoints:
        ep_id = f"endpoint:{file_path}:{ep.method.value}:{ep.route}"
        nodes.append(GraphNode(
            id=ep_id,
            label=f"{ep.method.value} {ep.route}",
            type=NodeType.ENDPOINT,
            description=ep.description,
            metadata={
                "handler": ep.handler_function,
                "auth_required": ep.auth_required,
                "middleware": ep.middleware,
            },
            file_path=file_path,
        ))
        edges.append(GraphEdge(
            id=f"contains:{file_path}->{ep.route}",
            source=f"file:{file_path}",
            target=ep_id,
            type=EdgeType.CONTAINS,
        ))

    # Data models
    for dm in analysis.data_models:
        dm_id = f"model:{file_path}:{dm.name}"
        nodes.append(GraphNode(
            id=dm_id,
            label=dm.name,
            type=NodeType.MODEL,
            description=dm.description,
            metadata={"fields": [f.model_dump() for f in dm.fields]},
            file_path=file_path,
            line_start=dm.line_start,
            line_end=dm.line_end,
        ))
        edges.append(GraphEdge(
            id=f"contains:{file_path}->{dm.name}",
            source=f"file:{file_path}",
            target=dm_id,
            type=EdgeType.CONTAINS,
        ))

    # Call edges between functions
    all_func_names = {f.name for f in analysis.functions}
    all_method_names = set()
    for cls in analysis.classes:
        for m in cls.methods:
            all_method_names.add(f"{cls.name}.{m.name}")

    for func in analysis.functions:
        for call in func.calls:
            call_name = call.split(".")[-1]
            if call_name in all_func_names:
                edges.append(GraphEdge(
                    id=f"calls:{func.name}->{call_name}",
                    source=f"func:{file_path}:{func.name}",
                    target=f"func:{file_path}:{call_name}",
                    type=EdgeType.CALLS,
                    animated=True,
                ))

    return GraphData(
        nodes=nodes,
        edges=edges,
        view_type="file_detail",
        layout_hint=LayoutHint.DAGRE,
    )
