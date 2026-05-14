"""
Test script for VisCode Phase 2: Chunker, Analyzer (parsing only), Validator.
Note: AI API calls are NOT tested here (need API key). We test parsing/validation logic.
"""

import sys
import os
import json

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
print("\n🧪 TEST 1: Smart Chunker")
# ──────────────────────────────────────────────
from services.chunker import chunk_file, CodeChunk
from services.extractor import extract_ground_truth

# Small file — should be 1 chunk
small_code = """import os

def hello():
    print("hi")

def goodbye():
    print("bye")
"""

gt_small = extract_ground_truth("small.py", small_code, "python")
chunks_small = chunk_file("small.py", small_code, gt_small, max_chunk_lines=450)

test("Small file → 1 chunk", len(chunks_small) == 1)
test("Single chunk has full content", "hello" in chunks_small[0].content)
test("Single chunk has correct metadata", chunks_small[0].total_chunks == 1)
test("Single chunk line_start = 1", chunks_small[0].line_start == 1)

# Large file — should be multiple chunks
large_lines = ['import os\nimport sys\nfrom pathlib import Path\n\n']
for i in range(20):
    func = f"def function_{i}(x, y):\n"
    func += f'    """Function number {i}."""\n'
    for j in range(20):
        func += f"    result_{j} = x + y + {j}\n"
    func += f"    return result_0\n\n"
    large_lines.append(func)

large_code = "".join(large_lines)
gt_large = extract_ground_truth("large.py", large_code, "python")
chunks_large = chunk_file("large.py", large_code, gt_large, max_chunk_lines=200)

test(f"Large file → multiple chunks ({len(chunks_large)})", len(chunks_large) > 1)
test("Each chunk has context header", all(c.context_header for c in chunks_large))
test("Each chunk has consistent total_chunks", all(c.total_chunks == len(chunks_large) for c in chunks_large))
test("Chunk indices are sequential", [c.chunk_index for c in chunks_large] == list(range(len(chunks_large))))

# Verify imports are in each chunk
test("Each chunk contains imports", all("import os" in c.content for c in chunks_large))

# Verify no function is split
for chunk in chunks_large:
    def_count = chunk.content.count("\ndef function_")
    return_count = chunk.content.count("return result_0")
    test(f"Chunk {chunk.chunk_index}: no split functions ({def_count} defs, {return_count} returns)",
         def_count == return_count or chunk.chunk_index == 0)


# ──────────────────────────────────────────────
print("\n🧪 TEST 2: AI Analyzer — Parse Pass 1 Results")
# ──────────────────────────────────────────────
from services.analyzer import AIAnalyzer

analyzer = AIAnalyzer()

# Simulate AI response (as if GPT returned this JSON)
mock_pass1_response = {
    "file_summary": "A user service module that handles CRUD operations for user data.",
    "role_in_project": "service",
    "functions": [
        {
            "name": "validate_email",
            "description": "Validates email format using regex pattern matching.",
            "purpose": "Ensures email addresses are properly formatted before storage.",
            "calls": ["re.match"],
            "side_effects": [],
            "complexity": "simple",
            "confidence": 0.95,
        },
        {
            "name": "hallucinated_func",  # This doesn't exist — should be caught by validator
            "description": "Does something.",
            "purpose": "Unknown.",
            "calls": [],
            "side_effects": [],
            "complexity": "simple",
            "confidence": 0.3,
        },
    ],
    "classes": [
        {
            "name": "UserService",
            "description": "Service class for user CRUD operations.",
            "purpose": "Encapsulates all user-related database operations.",
            "inherits_from": [],
            "methods": [
                {
                    "name": "get_user",
                    "description": "Fetches a user by their ID from the database.",
                    "purpose": "Provides user lookup functionality.",
                    "calls": ["db.query"],
                    "side_effects": ["database_read"],
                    "complexity": "simple",
                    "confidence": 0.9,
                },
            ],
            "confidence": 0.92,
        },
    ],
    "endpoints": [
        {
            "method": "GET",
            "route": "/api/users/{user_id}",
            "description": "Retrieves a user by ID.",
            "handler_function": "get_user_endpoint",
            "auth_required": False,
            "middleware": [],
        },
    ],
    "data_models": [],
    "variables": [
        {"name": "MAX_SIZE", "type": "int", "description": "Maximum allowed size.", "is_constant": True},
    ],
    "key_logic": [
        {"description": "Email validation using regex", "why_it_matters": "Prevents invalid data", "line_start": 25, "line_end": 27},
    ],
    "error_handling": ["ValueError raised for invalid emails"],
    "imports_analysis": [
        {"name": "os", "source": "os", "type": "stdlib", "used_for": "File system operations"},
    ],
}

# Parse it
file_analysis = analyzer.parse_pass1_result(mock_pass1_response, "src/user.py", "python")

test("Parse returns FileAnalysis", file_analysis is not None)
test("File summary parsed", "user service" in file_analysis.file_summary.lower())
test("Role parsed", file_analysis.role_in_project == "service")
test(f"Functions parsed ({len(file_analysis.functions)})", len(file_analysis.functions) == 2)
test(f"Classes parsed ({len(file_analysis.classes)})", len(file_analysis.classes) == 1)
test(f"Endpoints parsed ({len(file_analysis.endpoints)})", len(file_analysis.endpoints) == 1)
test(f"Variables parsed ({len(file_analysis.variables)})", len(file_analysis.variables) == 1)
test("Function confidence", file_analysis.functions[0].confidence == 0.95)
test("Class confidence", file_analysis.classes[0].confidence == 0.92)
test("Endpoint method", file_analysis.endpoints[0].method.value == "GET")
test("Key logic parsed", len(file_analysis.key_logic) == 1)
test("Error handling parsed", len(file_analysis.error_handling) == 1)
test("Imports parsed", len(file_analysis.imports) == 1)
test("Import type is stdlib", file_analysis.imports[0].type == "stdlib")


# ──────────────────────────────────────────────
print("\n🧪 TEST 3: Post-Validator")
# ──────────────────────────────────────────────
from services.validator import validate_analysis
from models.analysis import GroundTruth, ExtractedIdentifier, IdentifierKind

# Create ground truth (what regex found)
gt = GroundTruth(
    file_path="src/user.py",
    language="python",
    identifiers=[
        ExtractedIdentifier(name="validate_email", kind=IdentifierKind.FUNCTION, line_start=25, line_end=27),
        ExtractedIdentifier(name="UserService", kind=IdentifierKind.CLASS, line_start=10, line_end=22),
        ExtractedIdentifier(name="get_user", kind=IdentifierKind.METHOD, line_start=15, line_end=18, parent="UserService"),
        ExtractedIdentifier(name="MAX_SIZE", kind=IdentifierKind.CONSTANT, line_start=5),
    ],
    line_count=40,
)

# Validate AI output against ground truth
validated, corrections = validate_analysis(file_analysis, gt)

test("Validator returns FileAnalysis", validated is not None)
test("Validator returns corrections list", isinstance(corrections, list))

# hallucinated_func should be removed
validated_func_names = [f.name for f in validated.functions]
test("Hallucinated function removed", "hallucinated_func" not in validated_func_names)
test("Valid function kept", "validate_email" in validated_func_names)
test(f"Corrections made ({len(corrections)})", len(corrections) >= 1)

# Check corrections contain the removal
has_removal = any("hallucinated" in c.lower() for c in corrections)
test("Correction mentions hallucinated removal", has_removal)

# Class should be kept
test("Valid class kept", len(validated.classes) == 1)
test("Class name correct", validated.classes[0].name == "UserService")

# Method should be kept
test("Valid method kept", len(validated.classes[0].methods) == 1)
test("Method name correct", validated.classes[0].methods[0].name == "get_user")


# ──────────────────────────────────────────────
print("\n🧪 TEST 4: Analyzer — Parse Pass 2 (Cross-File)")
# ──────────────────────────────────────────────

mock_pass2_response = {
    "relationships": [
        {"source_file": "main.py", "target_file": "routes/user.py", "relationship_type": "imports", "details": ["user_router"]},
        {"source_file": "routes/user.py", "target_file": "services/user.py", "relationship_type": "calls", "details": ["UserService"]},
    ],
    "data_flows": [
        {
            "description": "User creation flow: request → router → service → database",
            "steps": [
                {"file_path": "routes/user.py", "function_name": "create_user", "description": "Receives HTTP request", "step_type": "handler"},
                {"file_path": "services/user.py", "function_name": "create", "description": "Business logic", "step_type": "service"},
            ]
        }
    ],
    "circular_dependencies": [],
    "shared_models": [{"model_name": "User", "used_in_files": ["models/user.py", "routes/user.py"]}],
    "entry_points": ["main.py"],
}

cross_file = analyzer._parse_cross_file(mock_pass2_response)

test("Cross-file relationships parsed", len(cross_file.relationships) == 2)
test("Data flows parsed", len(cross_file.data_flows) == 1)
test("Flow steps parsed", len(cross_file.data_flows[0].steps) == 2)
test("Entry points parsed", cross_file.entry_points == ["main.py"])
test("Shared models parsed", len(cross_file.shared_models) == 1)


# ──────────────────────────────────────────────
print("\n🧪 TEST 5: Analyzer — Parse Pass 3 (Architecture)")
# ──────────────────────────────────────────────

mock_pass3_response = {
    "project_type": "REST API",
    "framework": "FastAPI",
    "design_patterns": ["MVC", "Repository"],
    "summary": "A user management REST API built with FastAPI. It provides CRUD operations for users with authentication. The project follows MVC architecture.",
    "reading_order": ["main.py", "config.py", "models/user.py", "routes/user.py"],
    "key_concepts": [
        {"concept": "Dependency Injection", "description": "FastAPI uses DI for database sessions", "relevant_files": ["main.py"]},
        {"concept": "Pydantic Models", "description": "Used for request/response validation", "relevant_files": ["models/user.py"]},
    ],
    "tech_stack": ["Python", "FastAPI", "SQLAlchemy", "PostgreSQL"],
}

arch = analyzer._parse_architecture(mock_pass3_response)

test("Project type parsed", arch.project_type == "REST API")
test("Framework parsed", arch.framework == "FastAPI")
test("Design patterns parsed", len(arch.design_patterns) == 2)
test("Summary parsed", len(arch.summary) > 0)
test("Reading order parsed", len(arch.reading_order) == 4)
test("Key concepts parsed", len(arch.key_concepts) == 2)
test("Tech stack parsed", "FastAPI" in arch.tech_stack)


# ──────────────────────────────────────────────
print("\n🧪 TEST 6: _extract_json — Robust JSON Parsing")
# ──────────────────────────────────────────────

# Test 1: Raw JSON
raw_json = '{"key": "value", "num": 42}'
result = AIAnalyzer._extract_json(raw_json)
test("Raw JSON parses", result == {"key": "value", "num": 42})

# Test 2: Markdown code block
markdown_json = '''Here is the analysis:

```json
{"project_type": "REST API", "framework": "FastAPI"}
```

Hope this helps!'''
result = AIAnalyzer._extract_json(markdown_json)
test("Markdown ```json block extracts", result.get("project_type") == "REST API")

# Test 3: Markdown code block without json tag
markdown_no_tag = '''```
{"summary": "test project"}
```'''
result = AIAnalyzer._extract_json(markdown_no_tag)
test("Markdown ``` block (no json tag) extracts", result.get("summary") == "test project")

# Test 4: JSON embedded in text
embedded = 'The analysis results are: {"functions": [{"name": "hello"}]} and that is all.'
result = AIAnalyzer._extract_json(embedded)
test("Embedded JSON brace extraction", len(result.get("functions", [])) == 1)

# Test 5: Empty content should fail
try:
    AIAnalyzer._extract_json("")
    test("Empty string raises error", False)
except:
    test("Empty string raises error", True)

# Test 6: No JSON at all
try:
    AIAnalyzer._extract_json("This has no JSON whatsoever")
    test("No-JSON string raises error", False)
except:
    test("No-JSON string raises error", True)


# ──────────────────────────────────────────────
print("\n🧪 TEST 7: Go Ground Truth Extraction")
# ──────────────────────────────────────────────

go_code = '''package diagnostics

import (
    "context"
    "fmt"
    "strings"
)

const MaxRetries = 3
const DatabaseTimeout = 30

type CheckResult struct {
    Name    string
    Status  string
    Message string
}

type DiagnosticService interface {
    RunChecks(ctx context.Context) []CheckResult
}

func NewDiagnosticService(db *Database) *diagnosticServiceImpl {
    return &diagnosticServiceImpl{db: db}
}

type diagnosticServiceImpl struct {
    db *Database
}

func (s *diagnosticServiceImpl) RunChecks(ctx context.Context) []CheckResult {
    results := make([]CheckResult, 0)
    return results
}

func (s *diagnosticServiceImpl) checkDatabase(ctx context.Context) CheckResult {
    return CheckResult{Name: "database", Status: "ok"}
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
    w.WriteHeader(200)
}
'''

gt_go = extract_ground_truth("checks/service.go", go_code, "go")

test(f"Go: Found identifiers ({len(gt_go.identifiers)})", len(gt_go.identifiers) >= 5)
test(f"Go: Found imports ({len(gt_go.imports)})", len(gt_go.imports) >= 2)

# Check specific identifiers
id_names = {i.name for i in gt_go.identifiers}
test("Go: Found struct CheckResult", "CheckResult" in id_names)
test("Go: Found interface DiagnosticService", "DiagnosticService" in id_names)
test("Go: Found function NewDiagnosticService", "NewDiagnosticService" in id_names)
test("Go: Found function healthHandler", "healthHandler" in id_names)

# Check methods are linked to receiver types
methods = [i for i in gt_go.identifiers if i.kind.value == "method"]
test(f"Go: Found methods ({len(methods)})", len(methods) >= 2)

method_parents = {m.name: m.parent for m in methods}
test("Go: RunChecks has parent diagnosticServiceImpl",
     method_parents.get("RunChecks") == "diagnosticServiceImpl")
test("Go: checkDatabase has parent diagnosticServiceImpl",
     method_parents.get("checkDatabase") == "diagnosticServiceImpl")

# Check imports
import_names = {i.name for i in gt_go.imports}
test("Go: Found import context", "context" in import_names)
test("Go: Found import fmt", "fmt" in import_names)


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
