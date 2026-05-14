# VisCode — System Design Document
> **Version:** 1.0  
> **Date:** 2026-05-14  
> **Status:** Pre-Implementation  

---

## 1. Problem Statement

Developers joining new teams or reviewing unfamiliar codebases face a steep comprehension curve. Reading code linearly across hundreds of files fails to reveal the **big picture** — how files connect, how data flows, what each piece does and WHY. Traditional code navigation tools (find references, go to definition) are useful but don't provide a holistic, visual understanding.

**VisCode** solves this by analyzing entire codebases using AI and generating interactive, graphical visualizations that make any project understandable at a glance — even for beginners.

---

## 2. Goals & Non-Goals

### Goals
- Analyze any codebase (multi-language) and produce structured analysis data
- Generate interactive node-based visualizations (n8n-style infinite canvas)
- Provide AI-generated descriptions for every code element (functions, classes, endpoints, etc.)
- Support drill-down from project-level → file-level → element-level
- Cache analysis results — only re-analyze changed files
- Handle real-world edge cases (large files, binary files, minified code)

### MVP Scope (v1)
> Only these features ship in v1. Everything else is deferred.

| In MVP ✅ | NOT in MVP ❌ |
|-----------|--------------|
| Project Overview (files as nodes, imports as edges) | Call Graph view |
| File Deep Dive (click file → see internals) | Data Flow view |
| Detail Panel (description, code ref, connections) | Complexity Heatmap |
| 3-pass AI analysis | Export as image/PDF |
| Hybrid extraction (regex + AI) | Local model support (Ollama) |
| SSE progress streaming | Docker setup |
| File-hash caching | Multi-project management |
| Search by name | Share via link |
| n8n-style canvas with zoom/pan | Mobile support |

### Non-Goals (v1)
- Real-time code editing / live sync with IDE
- Mobile support
- Multi-user collaboration
- Self-hosted cloud deployment
- Support for non-code files (images, configs parsed semantically)

---

## 3. Architecture

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        USER                                 │
│                    (Browser Tab)                             │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP + SSE
┌──────────────────────▼──────────────────────────────────────┐
│                   API GATEWAY                                │
│  FastAPI Server                                              │
│  ┌──────────┐ ┌──────────────┐ ┌───────────┐                │
│  │ Validator │ │ Rate Limiter │ │ Error Hdlr│                │
│  └──────────┘ └──────────────┘ └───────────┘                │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                 SERVICE LAYER                                │
│                                                              │
│  ┌─────────────────────────────────────────────────┐        │
│  │            Analysis Orchestrator                 │        │
│  │  (coordinates the full pipeline)                 │        │
│  └──┬──────┬──────────┬──────────┬──────────┬──────┘        │
│     │      │          │          │          │                │
│  ┌──▼──┐┌──▼───┐ ┌────▼────┐┌───▼────┐┌───▼──────┐        │
│  │Scan-││Chunk-│ │Analyzer ││Resolv- ││Graph     │        │
│  │ner  ││er    │ │(AI+AST) ││er      ││Builder   │        │
│  └─────┘└──────┘ └────┬────┘└────────┘└──────────┘        │
│                        │                                     │
└────────────────────────┼─────────────────────────────────────┘
                         │
           ┌─────────────┼──────────────┐
           │             │              │
    ┌──────▼──┐   ┌──────▼──┐   ┌──────▼──┐
    │ Pass 1  │   │ Pass 2  │   │ Pass 3  │
    │Per-File │   │Cross-   │   │Archit-  │
    │Analysis │   │File Rels│   │ecture   │
    └─────────┘   └─────────┘   └─────────┘
           │             │              │
           └─────────────┼──────────────┘
                         │
                  ┌──────▼──────┐
                  │ OpenAI API  │
                  │ GPT-4.1     │
                  └─────────────┘

Storage:
  ┌──────────────┐  ┌──────────────┐
  │ Analysis     │  │ Project      │
  │ Cache (JSON) │  │ Config       │
  └──────────────┘  └──────────────┘
```

### 3.2 Component Responsibilities

| Component | Responsibility | Input | Output |
|-----------|---------------|-------|--------|
| **Scanner** | Discovers all code files, filters ignored paths, detects languages | Directory path | File list with metadata (path, language, size, hash) |
| **Chunker** | Splits large files into analyzable chunks respecting function boundaries | File content | List of code chunks with context |
| **Analyzer** | Runs 3-pass AI analysis with hybrid extraction (AST + AI) | Code chunks | Structured analysis JSON |
| **Resolver** | Resolves cross-file references, builds relationship map | All file analyses | Cross-reference graph |
| **Graph Builder** | Transforms analysis data into visualization-ready graph format | Analysis + cross-refs | Nodes + Edges JSON |
| **Cache** | Stores analysis results keyed by file content hash | Analysis results | Cached/fresh indicator |
| **Orchestrator** | Coordinates the full pipeline, manages progress, handles failures | Project path | Complete graph data |

### 3.3 Smart Chunker Strategy

> Files > 500 lines must be split for AI analysis. Splitting must respect code structure.

```
Rules:
1. If file <= 500 lines → single chunk (no splitting)
2. If file > 500 lines → split at function/class boundaries using ground truth line ranges
3. Each chunk includes:
   - The imports section (always prepended as context)
   - One or more complete function/class definitions
   - Target chunk size: 300-500 lines
4. NEVER split inside a function or method body
5. Each chunk gets a context header: file name, chunk N of M, what comes before/after
6. After analysis, chunk results are merged into a single FileAnalysis
```

### 3.4 Data Flow

```
1. User submits project path
2. Validate path (security sandboxing)
3. Scanner walks directory → produces file manifest
4. For each file:
   a. Check cache (file_hash + model_version) → if cached, skip
   b. Detect encoding (skip non-UTF8 with warning)
   c. Detect minified code (single line > 1000 chars → warn, skip deep analysis)
   d. Chunker splits if > 500 lines (respecting function boundaries)
   e. AST/Regex extracts identifiers + line numbers (GROUND TRUTH)
   f. AI adds descriptions + relationship analysis (ENRICHMENT)
   g. Post-validator checks AI output against ground truth
   h. Store in cache
5. Resolver builds cross-file relationship map
6. AI Pass 2: Cross-file relationship analysis
7. AI Pass 3: Architecture narrative
8. Graph Builder creates visualization nodes + edges
9. Frontend renders on canvas
```

### 3.5 Partial Failure Handling

> Analysis WILL fail for some files (timeout, malformed AI response, encoding issues).
> The system must handle this gracefully — never abort the entire pipeline.

```
On file analysis failure (after 3 retries):
  1. Mark file status as "analysis_failed" with error reason
  2. Log: file path, error type, retry count, duration
  3. Continue processing remaining files
  4. Include failed file in visualization with:
     - Warning icon (⚠️) on the node
     - Tooltip: "Analysis failed: {reason}. Click to retry."
     - Basic metadata still shown (name, language, line count from scanner)
  5. Allow manual re-trigger for individual failed files via API

On Pass 2/3 failure:
  1. Retry up to 3 times with backoff
  2. If still fails: serve Pass 1 results without cross-file analysis
  3. Show warning banner: "Cross-file analysis unavailable"
```

---

## 4. Hybrid Extraction Strategy (Critical Design Decision)

> **Principle:** Never trust AI for facts that can be programmatically verified.  
> AI is for *understanding*. Regex/AST is for *facts*.

### What Regex/AST Extracts (Ground Truth)
- Function/method names and line numbers
- Class names and line ranges
- Import statements and sources
- Variable declarations (top-level/module scope)
- Decorator names
- API route definitions (e.g., `@app.get("/users")`)
- Export statements

### What AI Provides (Enrichment)
- Plain-English descriptions of what each element does and WHY
- Purpose/role classification (controller, model, utility, middleware)
- Side effects identification (DB write, API call, file I/O)
- Complexity assessment (simple/moderate/complex)
- Key logic block explanations
- Cross-file relationship reasoning (Pass 2)
- Architecture pattern identification (Pass 3)

### Post-Validation Rules
```python
# After AI returns analysis, validate:
for element in ai_output.functions:
    assert element.name in ground_truth.function_names, f"AI hallucinated: {element.name}"
    assert element.line_start <= file_line_count, f"Invalid line: {element.line_start}"
    
for imp in ai_output.imports:
    if imp.type == "internal":
        assert resolve_import_path(imp.source, project_root) exists
```

---

## 5. Data Models

### 5.1 Scanner Output: FileManifest

```python
class FileInfo:
    path: str              # Relative path from project root
    absolute_path: str     # Full filesystem path
    language: str          # "python", "javascript", "typescript", etc.
    size_bytes: int
    line_count: int
    content_hash: str      # SHA-256 of file content
    
class FileManifest:
    project_root: str
    total_files: int
    total_lines: int
    files: list[FileInfo]
    languages: dict[str, int]   # language → file count
    ignored_paths: list[str]    # What was skipped and why
```

### 5.2 Ground Truth Extraction Output

```python
class ExtractedIdentifier:
    name: str
    kind: str              # "function", "class", "method", "variable", "import", "endpoint", "decorator"
    line_start: int
    line_end: int | None
    parent: str | None     # For methods: the class name
    params: list[str]      # For functions: parameter names
    decorators: list[str]  # Decorator names
    
class GroundTruth:
    file_path: str
    language: str
    identifiers: list[ExtractedIdentifier]
    import_statements: list[dict]   # {name, source, line}
    raw_content: str
```

### 5.3 Shared Sub-Models

```python
class ParamInfo:
    name: str
    type: str | None            # Parameter type (if annotated/inferable)
    description: str             # What this parameter is for
    default: str | None          # Default value if any

class ReturnInfo:
    type: str                    # Return type
    description: str             # What the return value represents

class ImportInfo:
    name: str                    # What is imported (e.g., "FastAPI", "router")
    source: str                  # Where from (e.g., "fastapi", "./routes/user")
    type: str                    # "internal" | "external" | "stdlib"
    alias: str | None            # Import alias if any
    line: int

class VariableInfo:
    name: str
    type: str | None
    description: str
    scope: str                   # "global" | "module" | "class"
    line: int
    is_constant: bool            # ALL_CAPS naming convention

class FieldInfo:
    name: str
    type: str
    description: str
    constraints: str | None      # "required", "optional", "max_length=255", etc.
    default: str | None
```

### 5.4 AI Analysis Output (Per File — Pass 1)

```python
class FunctionAnalysis:
    name: str                    # Must match ground truth
    description: str             # What it does (1-2 sentences)
    purpose: str                 # WHY it exists
    line_start: int              # From ground truth (AI confirms or corrects)
    line_end: int
    params: list[ParamInfo]      # {name, type, description}
    returns: ReturnInfo | None   # {type, description}
    calls: list[str]             # Functions it calls
    side_effects: list[str]      # "database_write", "api_call", "file_io", "logging"
    complexity: str              # "simple" | "moderate" | "complex"
    confidence: float            # 0.0-1.0 — AI's confidence in its analysis
    
class ClassAnalysis:
    name: str
    description: str
    purpose: str
    line_start: int
    line_end: int
    inherits_from: list[str]
    methods: list[FunctionAnalysis]
    
class EndpointAnalysis:
    method: str                  # GET, POST, PUT, DELETE, PATCH
    route: str                   # "/api/users/:id"
    description: str             # What this endpoint does for the end user
    handler_function: str        # Function that handles this route
    auth_required: bool
    request_body: dict | None    # Schema description
    response_schema: dict | None
    middleware: list[str]

class DataModelAnalysis:
    name: str
    description: str
    fields: list[FieldInfo]      # {name, type, description, constraints}
    
class LogicBlock:
    description: str             # Plain English: what this block does
    why_it_matters: str          # Why this is important
    line_start: int
    line_end: int

class FileAnalysis:
    file_path: str
    file_summary: str            # 2-sentence summary
    role_in_project: str         # "controller", "model", "utility", "config", etc.
    language: str
    imports: list[ImportInfo]
    classes: list[ClassAnalysis]
    functions: list[FunctionAnalysis]
    endpoints: list[EndpointAnalysis]
    data_models: list[DataModelAnalysis]
    variables: list[VariableInfo]
    key_logic: list[LogicBlock]
    error_handling: list[str]
```

### 5.4 Cross-File Analysis (Pass 2)

```python
class FileRelationship:
    source_file: str
    target_file: str
    relationship_type: str       # "imports", "extends", "calls", "instantiates"
    details: list[str]           # What specifically is used
    
class FlowStep:
    file_path: str               # File where this step occurs
    function_name: str           # Function that executes this step
    description: str             # What happens at this step
    step_type: str               # "entry" | "middleware" | "handler" | "service" | "data_access" | "response"

class DataFlowChain:
    description: str             # "User request → auth middleware → controller → service → DB"
    steps: list[FlowStep]        # Ordered list of file+function hops
    
class CrossFileAnalysis:
    relationships: list[FileRelationship]
    data_flows: list[DataFlowChain]
    circular_dependencies: list[list[str]]
    shared_models: list[dict]    # Models used across multiple files
    entry_points: list[str]      # Files where execution begins
```

### 5.5 Architecture Summary (Pass 3)

```python
class ArchitectureSummary:
    project_type: str            # "REST API", "CLI tool", "Full-stack web app", etc.
    framework: str               # "FastAPI", "Express", "Django", etc.
    design_patterns: list[str]   # "MVC", "Repository", "Factory", etc.
    summary: str                 # 3-5 sentence overview of the entire project
    reading_order: list[str]     # Suggested order to read files for understanding
    key_concepts: list[dict]     # {concept, description, relevant_files}
    tech_stack: list[str]        # Technologies used
```

### 5.6 Graph Data (Visualization-Ready)

```python
class GraphNode:
    id: str                      # Unique identifier
    label: str                   # Display name
    type: str                    # "file", "function", "class", "endpoint", etc.
    description: str             # AI-generated description
    metadata: dict               # Type-specific data
    position: dict | None        # {x, y} if manually positioned
    file_path: str | None        # Source file reference
    line_start: int | None       # Code reference
    line_end: int | None
    children: list[str] | None   # Child node IDs (for drill-down)
    
class GraphEdge:
    id: str
    source: str                  # Source node ID
    target: str                  # Target node ID
    type: str                    # "imports", "calls", "extends", "data_flow"
    label: str | None            # Edge label
    animated: bool               # Whether to show flow animation
    
class GraphData:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    view_type: str               # "overview", "file_detail", "dependencies", "endpoints"
    layout_hint: str             # "dagre", "force", "horizontal"
```

---

## 6. API Contract

### 6.1 Endpoints

```
POST   /api/projects                    → Start analysis
GET    /api/projects/{id}               → Get project metadata + status
GET    /api/projects/{id}/stream        → SSE: real-time progress
GET    /api/projects/{id}/graph/{view}  → Graph data for a specific view
GET    /api/projects/{id}/files         → List all analyzed files
GET    /api/projects/{id}/files/{path}  → Single file analysis detail
GET    /api/projects/{id}/search?q=     → Search across all elements
GET    /api/projects/{id}/architecture  → Architecture summary (Pass 3)
DELETE /api/projects/{id}               → Delete project + clear cache
GET    /api/projects/{id}/estimate      → Cost/time estimate before analysis
GET    /health                          → Health check
```

### 6.2 Key Request/Response Schemas

**POST /api/projects**
```json
// Request
{
  "path": "/absolute/path/to/project",
  "ignore_patterns": [".git", "node_modules", "__pycache__", ".env"],
  "max_file_size_lines": 5000,
  "model_tier": "balanced"  // "fast" (mini only) | "balanced" (mini+full) | "deep" (full only)
}

// Response
{
  "project_id": "uuid",
  "status": "scanning",
  "estimated_files": 0,
  "estimated_cost_usd": 0.0,
  "stream_url": "/api/projects/{id}/stream"
}
```

**GET /api/projects/{id}/stream (SSE)**
```
event: progress
data: {"phase": "scanning", "message": "Found 87 code files", "percent": 5}

event: progress
data: {"phase": "extracting", "file": "src/main.py", "percent": 15, "files_done": 3, "files_total": 87}

event: progress
data: {"phase": "analyzing", "file": "src/main.py", "percent": 45, "files_done": 30, "files_total": 87}

event: progress
data: {"phase": "cross_analysis", "message": "Analyzing cross-file relationships", "percent": 90}

event: progress  
data: {"phase": "building_graph", "message": "Generating visualization data", "percent": 95}

event: complete
data: {"project_id": "uuid", "total_files": 87, "total_time_seconds": 142, "cost_usd": 2.34}

event: error
data: {"file": "src/broken.py", "error": "Analysis failed after 3 retries", "severity": "warning"}
```

**GET /api/projects/{id}/graph/overview**
```json
{
  "view": "overview",
  "layout": "dagre",
  "nodes": [
    {
      "id": "file:src/main.py",
      "label": "main.py",
      "type": "file",
      "description": "Application entry point. Sets up FastAPI server and registers all route handlers.",
      "metadata": {"language": "python", "lines": 245, "functions": 8, "classes": 2, "endpoints": 5},
      "file_path": "src/main.py",
      "children": ["func:main.py:app_startup", "class:main.py:AppConfig", "..."]
    }
  ],
  "edges": [
    {
      "id": "edge:main→routes",
      "source": "file:src/main.py",
      "target": "file:src/routes/user.py",
      "type": "imports",
      "label": "imports user_router"
    }
  ],
  "architecture": {
    "project_type": "REST API",
    "framework": "FastAPI",
    "summary": "A user management API with authentication..."
  }
}
```

---

## 7. Security Considerations

### Path Sandboxing
```python
ALLOWED_BASE_PATHS = ["/home", "/Users", "/Volumes"]  # Configurable
BLOCKED_PATHS = ["/etc", "/var", "/usr", "/bin", "/sbin", "/sys", "/proc"]
BLOCKED_PATTERNS = [".env", ".git/config", "id_rsa", ".ssh"]

def validate_path(path: str) -> bool:
    resolved = Path(path).resolve()
    # Must be under an allowed base
    # Must not contain .. traversal
    # Must not match blocked patterns
    # Must be a directory (not a file)
```

### API Key Handling
- Stored in backend `.env` file ONLY
- Never sent to or from frontend
- Validated on startup with a test API call
- Logged as `sk-...xxxx` (masked) in logs

### Data Privacy
- Frontend displays warning: "Your code will be sent to OpenAI for analysis"
- Future: support for local models (Ollama) for sensitive codebases
- Analysis cache stored locally only

---

## 8. Supported Languages (v1)

| Language | File Extensions | AST/Regex Extraction |
|----------|----------------|---------------------|
| Python | `.py` | regex (def, class, @app.route) |
| JavaScript | `.js`, `.jsx` | regex (function, const, class, export) |
| TypeScript | `.ts`, `.tsx` | regex (same as JS + type, interface) |
| Java | `.java` | regex (class, public/private, @RequestMapping) |
| Go | `.go` | regex (func, type, package) |
| Rust | `.rs` | regex (fn, struct, impl, pub) |
| C# | `.cs` | regex (class, void, [HttpGet]) |
| Ruby | `.rb` | regex (def, class, module) |
| PHP | `.php` | regex (function, class) |

Other files (`.json`, `.yaml`, `.md`, `.sql`) are noted in the file tree but not deeply analyzed.

---

## 9. Performance Targets

| Metric | Target |
|--------|--------|
| **Scan speed** | < 2 seconds for 1000-file project |
| **Analysis speed** | ~1 second per file (with 5 concurrent API calls) |
| **100-file project total** | < 2 minutes |
| **Cache hit** | < 100ms per file |
| **Frontend render** | < 1 second for < 200 nodes |
| **Canvas interaction** | 60fps zoom/pan for < 500 nodes |
| **Max project size** | 2000 files (soft limit, warn above) |

### Rendering Performance Tiers

| Node Count | Strategy | Detail |
|-----------|----------|--------|
| < 200 | SVG (full) | All nodes rendered. Crisp, fully interactive. |
| 200–1000 | SVG + viewport culling | Only render nodes in visible area. Off-screen nodes removed from DOM. |
| > 1000 | Collapse + aggregate | Auto-collapse folders into single nodes. Expand on click. |

---

## 10. Edge Case Handling

| Edge Case | Detection | Handling |
|-----------|-----------|----------|
| **Binary files** | Null bytes in first 8KB | Skip, don't include in manifest |
| **Minified code** | Single line > 1000 chars | Warn, include in tree but skip deep analysis |
| **Non-UTF8 encoding** | `chardet` detection or decode error | Try common encodings, skip with warning if all fail |
| **Empty files** | 0 bytes | Include in tree, mark as empty |
| **Huge files (> 5000 lines)** | Line count check | Skip deep analysis, warn user, show in tree with size warning |
| **Circular imports** | Cycle detection in resolver | Detect, flag in visualization (red edges), don't infinite loop |
| **Generated code** (protobuf, etc.) | Filename patterns (`*_pb2.py`, `*.generated.*`) | Include in tree but skip AI analysis |
| **Symlinks** | `os.path.islink()` | Resolve once, skip if outside project root |
| **Permission denied** | `PermissionError` catch | Log warning, skip file |
