"""
Test script for VisCode Phase 1 components.
Tests: Config, Scanner, Extractor, Models
"""

import sys
import os
import tempfile
import shutil

# Ensure backend is on path
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
print("\n🧪 TEST 1: Config Loading")
# ──────────────────────────────────────────────
from config import config

test("Config loads", config is not None)
test("LANGUAGE_MAP has python", ".py" in config.LANGUAGE_MAP)
test("LANGUAGE_MAP has javascript", ".js" in config.LANGUAGE_MAP)
test("DEFAULT_IGNORE_DIRS has node_modules", "node_modules" in config.DEFAULT_IGNORE_DIRS)
test("DEFAULT_IGNORE_DIRS has .git", ".git" in config.DEFAULT_IGNORE_DIRS)
test("BLOCKED_PATHS has /etc", "/etc" in config.BLOCKED_PATHS)
test("MAX_CONCURRENT_CALLS is int", isinstance(config.MAX_CONCURRENT_CALLS, int))

warnings = config.validate()
test("Validate returns warnings (no API key set)", len(warnings) > 0)

cache_path = config.get_cache_path()
test("Cache path resolves", cache_path.exists())


# ──────────────────────────────────────────────
print("\n🧪 TEST 2: Pydantic Models")
# ──────────────────────────────────────────────
from models.analysis import (
    FileInfo, FileManifest, SkippedFile, FileStatus,
    ExtractedIdentifier, IdentifierKind, GroundTruth,
    FunctionAnalysis, ClassAnalysis, FileAnalysis,
    GraphNode, GraphEdge, GraphData, NodeType, EdgeType,
    AnalyzeRequest, ProjectStatus, CostEstimate, HealthResponse,
    EndpointAnalysis, HTTPMethod, Complexity,
)

# Test FileInfo
fi = FileInfo(
    path="src/main.py",
    absolute_path="/tmp/src/main.py",
    language="python",
    size_bytes=1024,
    line_count=100,
    content_hash="abc123",
)
test("FileInfo creates", fi.path == "src/main.py")
test("FileInfo language", fi.language == "python")

# Test FileManifest
manifest = FileManifest(
    project_root="/tmp/project",
    total_files=1,
    total_lines=100,
    files=[fi],
    languages={"python": 1},
)
test("FileManifest creates", manifest.total_files == 1)

# Test ExtractedIdentifier
eid = ExtractedIdentifier(
    name="my_func",
    kind=IdentifierKind.FUNCTION,
    line_start=10,
    line_end=20,
    params=["x", "y"],
)
test("ExtractedIdentifier creates", eid.name == "my_func")
test("ExtractedIdentifier kind enum", eid.kind == IdentifierKind.FUNCTION)

# Test line_start validation
try:
    bad = ExtractedIdentifier(name="bad", kind=IdentifierKind.FUNCTION, line_start=0)
    test("ExtractedIdentifier rejects line_start=0", False, "Should have raised")
except Exception:
    test("ExtractedIdentifier rejects line_start=0", True)

# Test FunctionAnalysis confidence clamping
fa = FunctionAnalysis(name="func1", confidence=0.95)
test("FunctionAnalysis creates", fa.name == "func1")
test("FunctionAnalysis confidence", fa.confidence == 0.95)

try:
    bad_fa = FunctionAnalysis(name="bad", confidence=1.5)
    test("FunctionAnalysis rejects confidence > 1.0", False, "Should have raised")
except Exception:
    test("FunctionAnalysis rejects confidence > 1.0", True)

# Test GraphNode
gn = GraphNode(id="file:main.py", label="main.py", type=NodeType.FILE, description="Entry point")
test("GraphNode creates", gn.id == "file:main.py")
test("GraphNode type enum", gn.type == NodeType.FILE)

# Test GraphEdge
ge = GraphEdge(id="e1", source="f1", target="f2", type=EdgeType.IMPORTS)
test("GraphEdge creates", ge.source == "f1")

# Test API models
req = AnalyzeRequest(path="/tmp/project")
test("AnalyzeRequest creates", req.path == "/tmp/project")
test("AnalyzeRequest default tier", req.model_tier == "balanced")

health = HealthResponse(status="ok", api_key_valid=False)
test("HealthResponse creates", health.status == "ok")


# ──────────────────────────────────────────────
print("\n🧪 TEST 3: Scanner Service")
# ──────────────────────────────────────────────
from services.scanner import scan_project, validate_project_path, estimate_cost

# Allow /tmp for testing (macOS resolves /tmp to /private/tmp)
config.ALLOWED_PATHS.extend(["/tmp", "/private"])

# Create a temp project for testing
test_dir = tempfile.mkdtemp(prefix="viscode_test_")
try:
    # Create project structure
    os.makedirs(os.path.join(test_dir, "src"))
    os.makedirs(os.path.join(test_dir, "src", "utils"))
    os.makedirs(os.path.join(test_dir, "node_modules", "pkg"))  # Should be ignored
    os.makedirs(os.path.join(test_dir, ".git"))  # Should be ignored

    # Create code files
    with open(os.path.join(test_dir, "src", "main.py"), "w") as f:
        f.write('"""Main module."""\nimport os\n\ndef main():\n    print("hello")\n\nif __name__ == "__main__":\n    main()\n')

    with open(os.path.join(test_dir, "src", "utils", "helper.py"), "w") as f:
        f.write('def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b\n')

    with open(os.path.join(test_dir, "src", "app.js"), "w") as f:
        f.write('const express = require("express");\nconst app = express();\napp.get("/api/users", (req, res) => { res.json([]); });\napp.listen(3000);\n')

    # Create a file that should be ignored
    with open(os.path.join(test_dir, "node_modules", "pkg", "index.js"), "w") as f:
        f.write("module.exports = {}")

    # Create a binary file
    with open(os.path.join(test_dir, "src", "image.png"), "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00")

    # Create a non-code file
    with open(os.path.join(test_dir, "README.md"), "w") as f:
        f.write("# Test Project\n")

    with open(os.path.join(test_dir, ".gitignore"), "w") as f:
        f.write("node_modules/\n")

    # Test path validation
    valid, msg = validate_project_path(test_dir)
    test("validate_project_path accepts temp dir", valid, msg)

    valid2, msg2 = validate_project_path("/nonexistent/path")
    test("validate_project_path rejects nonexistent", not valid2)

    # Test scanning
    manifest = scan_project(test_dir)

    test("Scanner returns FileManifest", isinstance(manifest, FileManifest))
    test(f"Scanner found files (got {manifest.total_files})", manifest.total_files == 3, f"Expected 3 files")
    test("Scanner detected python", "python" in manifest.languages)
    test("Scanner detected javascript", "javascript" in manifest.languages)
    test("Scanner counted python files", manifest.languages.get("python", 0) == 2)
    test("Scanner counted js files", manifest.languages.get("javascript", 0) == 1)
    test("Scanner has total_lines > 0", manifest.total_lines > 0)

    # Check that node_modules was ignored
    paths = [f.path for f in manifest.files]
    test("Scanner ignored node_modules", not any("node_modules" in p for p in paths))
    test("Scanner ignored .git", not any(".git" in p for p in paths))

    # Check that files have hashes
    test("Files have content hashes", all(f.content_hash for f in manifest.files))

    # Check that non-code files are not included
    test("README.md not in results", not any("README" in p for p in paths))

    # Test cost estimation
    estimate = estimate_cost(manifest)
    test("Cost estimate has total_files", estimate["total_files"] > 0)
    test("Cost estimate has cost_usd", estimate["estimated_cost_usd"] >= 0)
    test("Cost estimate has time", estimate["estimated_time_seconds"] > 0)

finally:
    shutil.rmtree(test_dir)


# ──────────────────────────────────────────────
print("\n🧪 TEST 4: Ground Truth Extractor")
# ──────────────────────────────────────────────
from services.extractor import extract_ground_truth

# Test Python extraction
python_code = '''"""A sample Python module."""

import os
from pathlib import Path
from typing import Optional

MAX_SIZE = 1024
API_VERSION = "v1"

class UserService:
    """Handles user operations."""
    
    def __init__(self, db):
        self.db = db
    
    def get_user(self, user_id: int) -> Optional[dict]:
        """Fetch a user by ID."""
        return self.db.query(user_id)
    
    def create_user(self, name: str, email: str) -> dict:
        """Create a new user."""
        return self.db.insert({"name": name, "email": email})

def validate_email(email: str) -> bool:
    """Check if email is valid."""
    return "@" in email

@app.get("/api/users/{user_id}")
def get_user_endpoint(user_id: int):
    """API endpoint to get user."""
    svc = UserService(db)
    return svc.get_user(user_id)

@app.post("/api/users")
def create_user_endpoint(name: str, email: str):
    """API endpoint to create user."""
    if not validate_email(email):
        raise ValueError("Invalid email")
    svc = UserService(db)
    return svc.create_user(name, email)
'''

gt = extract_ground_truth("src/services/user.py", python_code, "python")

test("Extractor returns GroundTruth", isinstance(gt, GroundTruth))
test(f"Extractor found identifiers ({len(gt.identifiers)})", len(gt.identifiers) > 0)
test(f"Extractor found imports ({len(gt.imports)})", len(gt.imports) > 0)

# Check specific identifiers
names = [i.name for i in gt.identifiers]
kinds = {i.name: i.kind for i in gt.identifiers}

test("Found class UserService", "UserService" in names)
test("Found function validate_email", "validate_email" in names)
test("Found constant MAX_SIZE", "MAX_SIZE" in names)
test("Found constant API_VERSION", "API_VERSION" in names)

# Check that UserService is classified as CLASS
test("UserService is CLASS kind", kinds.get("UserService") == IdentifierKind.CLASS)
test("validate_email is FUNCTION kind", kinds.get("validate_email") == IdentifierKind.FUNCTION)
test("MAX_SIZE is CONSTANT kind", kinds.get("MAX_SIZE") == IdentifierKind.CONSTANT)

# Check methods detected
method_names = [i.name for i in gt.identifiers if i.kind == IdentifierKind.METHOD]
test(f"Found methods ({method_names})", "get_user" in method_names or "__init__" in method_names)

# Check imports
import_names = [i.name for i in gt.imports]
test("Found import os", "os" in import_names)
test("Found import Path", "Path" in import_names)

# Check endpoints
endpoint_names = [i.name for i in gt.identifiers if i.kind == IdentifierKind.ENDPOINT]
test(f"Found endpoints ({len(endpoint_names)})", len(endpoint_names) >= 2)

# Check line numbers are valid
test("All line_start > 0", all(i.line_start > 0 for i in gt.identifiers))
test("Line count matches", gt.line_count == len(python_code.splitlines()))


# Test JavaScript extraction
js_code = '''import React from 'react';
import { useState, useEffect } from 'react';
const axios = require('axios');

const API_URL = "http://localhost:3000";

class UserComponent extends React.Component {
    render() {
        return <div>Hello</div>;
    }
}

export default function App() {
    const [users, setUsers] = useState([]);
    return <UserComponent />;
}

const fetchUsers = async () => {
    const res = await axios.get(API_URL + "/users");
    return res.data;
};

export const helpers = {
    formatName: (name) => name.trim(),
};
'''

gt_js = extract_ground_truth("src/App.jsx", js_code, "javascript")
js_names = [i.name for i in gt_js.identifiers]
js_import_names = [i.name for i in gt_js.imports]

test("JS: Found identifiers", len(gt_js.identifiers) > 0)
test("JS: Found imports", len(gt_js.imports) > 0)
test("JS: Found class UserComponent", "UserComponent" in js_names)
test("JS: Found function App", "App" in js_names)
test("JS: Found const fetchUsers", "fetchUsers" in js_names)
test("JS: Found constant API_URL", "API_URL" in js_names)
test("JS: Found import React", "React" in js_import_names)
test("JS: Found import useState", "useState" in js_import_names)
test("JS: Found import axios", "axios" in js_import_names)


# ──────────────────────────────────────────────
print("\n" + "=" * 50)
print(f"📊 RESULTS: {PASS} passed, {FAIL} failed, {PASS + FAIL} total")
print("=" * 50)

if FAIL > 0:
    print("\n⚠️  Some tests failed! Review above for details.")
    sys.exit(1)
else:
    print("\n🎉 All tests passed!")
    sys.exit(0)
