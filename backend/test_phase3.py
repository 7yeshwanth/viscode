"""
Test script for Phase 3: Cache, Graph Builder, Orchestrator, FastAPI.
Tests local logic only (no AI calls needed).
"""

import sys
import os
import json
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = 0
FAIL = 0


def test(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} — {detail}")


# ──────────────────────────────────────────────
print("\n🧪 TEST 1: Cache Service")
# ──────────────────────────────────────────────
from cache.analysis_cache import AnalysisCache
from models.analysis import FileAnalysis

# Use temp dir for cache
cache_dir = tempfile.mkdtemp(prefix="viscode_cache_test_")
from pathlib import Path

cache = AnalysisCache(cache_dir=Path(cache_dir))

# Test empty cache
result = cache.get("abc123")
test("Cache miss on empty", result is None)

# Put something in cache
fa = FileAnalysis(
    file_path="test.py",
    file_summary="A test file.",
    role_in_project="test",
    language="python",
)
cache.put("hash123", fa, model="gpt-4.1-mini")
test("Cache put succeeds", True)

# Get it back
cached = cache.get("hash123", model="gpt-4.1-mini")
test("Cache hit", cached is not None)
test("Cached data correct", cached.file_path == "test.py" if cached else False)
test("Cached summary correct", cached.file_summary == "A test file." if cached else False)

# Different model = different cache entry
cached_other = cache.get("hash123", model="gpt-4.1")
test("Different model = cache miss", cached_other is None)

# Has check
test("cache.has() works", cache.has("hash123", "gpt-4.1-mini"))
test("cache.has() returns False for missing", not cache.has("nonexistent"))

# Stats
stats = cache.stats()
test("Stats shows 1 entry", stats["entries"] == 1)
test("Stats shows hits", stats["hits"] == 1)
test("Stats shows misses", stats["misses"] >= 1)

# Clear
count = cache.clear()
test("Cache clear returns count", count == 1)
test("Cache empty after clear", cache.stats()["entries"] == 0)

shutil.rmtree(cache_dir)


# ──────────────────────────────────────────────
print("\n🧪 TEST 2: Graph Builder — Overview")
# ──────────────────────────────────────────────
from services.graph_builder import build_overview_graph, build_file_detail_graph
from models.analysis import (
    FileManifest, FileInfo, FileAnalysis, CrossFileAnalysis,
    FileRelationship, GraphData, NodeType, EdgeType,
    FunctionAnalysis, ClassAnalysis, EndpointAnalysis, HTTPMethod,
    Complexity,
)

manifest = FileManifest(
    project_root="/tmp/project",
    total_files=3,
    total_lines=300,
    files=[
        FileInfo(path="main.py", absolute_path="/tmp/project/main.py", language="python", line_count=50, content_hash="a"),
        FileInfo(path="routes/user.py", absolute_path="/tmp/project/routes/user.py", language="python", line_count=100, content_hash="b"),
        FileInfo(path="services/db.py", absolute_path="/tmp/project/services/db.py", language="python", line_count=150, content_hash="c"),
    ],
    languages={"python": 3},
)

file_analyses = {
    "main.py": FileAnalysis(file_path="main.py", file_summary="App entry point", role_in_project="entry", language="python"),
    "routes/user.py": FileAnalysis(file_path="routes/user.py", file_summary="User routes", role_in_project="controller", language="python"),
    "services/db.py": FileAnalysis(file_path="services/db.py", file_summary="Database service", role_in_project="service", language="python"),
}

cross_file = CrossFileAnalysis(
    relationships=[
        FileRelationship(source_file="main.py", target_file="routes/user.py", relationship_type="imports", details=["user_router"]),
        FileRelationship(source_file="routes/user.py", target_file="services/db.py", relationship_type="calls", details=["get_connection"]),
    ],
    entry_points=["main.py"],
)

graph = build_overview_graph(manifest, file_analyses, cross_file, None, [])

test("Graph returns GraphData", isinstance(graph, GraphData))
test(f"Graph has nodes ({len(graph.nodes)})", len(graph.nodes) > 0)
test(f"Graph has edges ({len(graph.edges)})", len(graph.edges) > 0)

# Count node types
file_nodes = [n for n in graph.nodes if n.type == NodeType.FILE]
folder_nodes = [n for n in graph.nodes if n.type == NodeType.FOLDER]
test(f"3 file nodes", len(file_nodes) == 3)
test(f"Folder nodes created ({len(folder_nodes)})", len(folder_nodes) >= 2)  # routes, services

# Check import edges exist
import_edges = [e for e in graph.edges if e.type == EdgeType.IMPORTS]
call_edges = [e for e in graph.edges if e.type == EdgeType.CALLS]
test("Import edges from cross-file", len(import_edges) >= 1)
test("Call edges from cross-file", len(call_edges) >= 1)

# Check containment edges
contain_edges = [e for e in graph.edges if e.type == EdgeType.CONTAINS]
test("Containment edges exist", len(contain_edges) > 0)

# Test with failed files
graph_with_fail = build_overview_graph(
    manifest, file_analyses, cross_file, None,
    [{"path": "services/db.py", "error": "Timeout"}]
)
failed_node = [n for n in graph_with_fail.nodes if n.id == "file:services/db.py"]
test("Failed node has FAILED status", failed_node[0].status.value == "failed" if failed_node else False)


# ──────────────────────────────────────────────
print("\n🧪 TEST 3: Graph Builder — File Detail")
# ──────────────────────────────────────────────

detail_analysis = FileAnalysis(
    file_path="routes/user.py",
    file_summary="User route handlers.",
    role_in_project="controller",
    language="python",
    functions=[
        FunctionAnalysis(name="validate", description="Validates input", complexity=Complexity.SIMPLE, confidence=0.9),
    ],
    classes=[
        ClassAnalysis(
            name="UserController",
            description="Handles user requests",
            methods=[
                FunctionAnalysis(name="get_user", description="Gets a user", complexity=Complexity.SIMPLE, confidence=0.85),
                FunctionAnalysis(name="create_user", description="Creates a user", complexity=Complexity.MODERATE, confidence=0.9),
            ],
            confidence=0.92,
        ),
    ],
    endpoints=[
        EndpointAnalysis(method=HTTPMethod.GET, route="/users/{id}", description="Get user by ID", handler_function="get_user"),
    ],
)

detail_graph = build_file_detail_graph("routes/user.py", detail_analysis)

test("Detail graph created", isinstance(detail_graph, GraphData))
test("Detail view type", detail_graph.view_type == "file_detail")

detail_file_nodes = [n for n in detail_graph.nodes if n.type == NodeType.FILE]
detail_class_nodes = [n for n in detail_graph.nodes if n.type == NodeType.CLASS]
detail_func_nodes = [n for n in detail_graph.nodes if n.type == NodeType.FUNCTION]
detail_method_nodes = [n for n in detail_graph.nodes if n.type == NodeType.METHOD]
detail_endpoint_nodes = [n for n in detail_graph.nodes if n.type == NodeType.ENDPOINT]

test("1 file node", len(detail_file_nodes) == 1)
test("1 class node", len(detail_class_nodes) == 1)
test("1 function node", len(detail_func_nodes) == 1)
test("2 method nodes", len(detail_method_nodes) == 2)
test("1 endpoint node", len(detail_endpoint_nodes) == 1)

# Check confidence is on nodes
class_node = detail_class_nodes[0]
test("Class node has confidence", class_node.confidence == 0.92)


# ──────────────────────────────────────────────
print("\n🧪 TEST 4: FastAPI App — Import & Routes")
# ──────────────────────────────────────────────
from main import app

# Check routes exist
routes = [r.path for r in app.routes]
test("/health route exists", "/health" in routes)
test("/api/analyze route exists", "/api/analyze" in routes)
test("/api/estimate route exists", "/api/estimate" in routes)
test("/api/cache/stats route exists", "/api/cache/stats" in routes)

# Test via TestClient
from fastapi.testclient import TestClient

client = TestClient(app)

# Health check
resp = client.get("/health")
test("Health check returns 200", resp.status_code == 200)
health = resp.json()
test("Health status is ok", health["status"] == "ok")
test("Health shows api_key_valid", "api_key_valid" in health)
test("Health shows version", health["version"] == "1.0.0")

# Cache stats
resp = client.get("/api/cache/stats")
test("Cache stats returns 200", resp.status_code == 200)
stats = resp.json()
test("Cache stats has entries", "entries" in stats)
test("Cache stats has hit_rate", "hit_rate" in stats)

# Estimate endpoint
resp = client.post("/api/estimate", json={"path": "/nonexistent/path"})
test("Estimate rejects bad path", resp.status_code == 400)

# Analyze endpoint — bad path
resp = client.post("/api/analyze", json={"path": "/nonexistent/path"})
test("Analyze rejects bad path", resp.status_code == 400)

# Project not found
resp = client.get("/api/projects/nonexistent")
test("Project 404 for missing", resp.status_code == 404)


# ──────────────────────────────────────────────
print("\n🧪 TEST 5: Orchestrator — Estimate")
# ──────────────────────────────────────────────
from services.orchestrator import AnalysisOrchestrator
from config import config

config.ALLOWED_PATHS.extend(["/tmp", "/private"])

orch = AnalysisOrchestrator()

# Create small test project
test_dir = tempfile.mkdtemp(prefix="viscode_orch_test_")
try:
    with open(os.path.join(test_dir, "main.py"), "w") as f:
        f.write('def main():\n    print("hello")\n\nmain()\n')
    with open(os.path.join(test_dir, "utils.py"), "w") as f:
        f.write('def add(a, b):\n    return a + b\n')

    estimate = orch.get_estimate(test_dir)
    test("Estimate returns dict", isinstance(estimate, dict))
    test("Estimate has total_files", estimate["total_files"] == 2)
    test("Estimate has cost", estimate["estimated_cost_usd"] >= 0)
    test("Estimate has time", estimate["estimated_time_seconds"] > 0)
finally:
    shutil.rmtree(test_dir)


# ──────────────────────────────────────────────
print("\n" + "=" * 50)
print(f"📊 RESULTS: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
print("=" * 50)

if FAIL > 0:
    print("\n⚠️  Some tests failed!")
    sys.exit(1)
else:
    print("\n🎉 All tests passed!")
    sys.exit(0)
