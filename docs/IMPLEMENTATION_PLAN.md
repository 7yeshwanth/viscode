# VisCode — Implementation Plan
> **Version:** 1.0  
> **Date:** 2026-05-14  
> **Incorporates:** All 8-role technical review findings  

---

## Build Strategy

**Principle:** Build vertically, not horizontally. Get one complete slice working end-to-end before expanding.

```
Slice 1: Scan a project → Extract identifiers → AI enriches → Show on canvas
Slice 2: Add more views (deps, endpoints, call graph)
Slice 3: Polish (search, filters, caching, flow tracing)
Slice 4: Open source readiness (Docker, README, demo)
```

---

## MVP Definition (from Engineering Manager review)

**MVP = the minimum that proves the concept and delivers value**

| In MVP ✅ | NOT in MVP ❌ |
|-----------|--------------|
| Project Overview (files as nodes, imports as edges) | Call Graph view |
| File Deep Dive (click file → see internals) | Data Flow view |
| Detail Panel (description, code ref, connections) | Complexity Heatmap |
| 3-pass AI analysis | Export as image/PDF |
| Hybrid extraction (AST + AI) | Local model support (Ollama) |
| SSE progress streaming | Docker setup |
| File-hash caching | Multi-project management |
| Search by name | Share via link |
| n8n-style canvas with zoom/pan | Mobile support |

---

## Phase 1: Backend Foundation

### Task 1.1: Project Setup
```
viscode/
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── requirements.txt
│   ├── .env.example
│   ├── services/
│   ├── models/
│   ├── cache/
│   └── utils/
```

**requirements.txt:**
```
fastapi>=0.115.0
uvicorn>=0.30.0
openai>=1.50.0
pydantic>=2.9.0
python-dotenv>=1.0.0
aiofiles>=24.0.0
sse-starlette>=2.0.0
chardet>=5.0.0
httpx>=0.27.0
```

**config.py:** Environment-based config with validation
- `OPENAI_API_KEY` — required
- `OPENAI_MODEL_PASS1` — default: `gpt-4.1-mini`
- `OPENAI_MODEL_PASS2` — default: `gpt-4.1`
- `OPENAI_MODEL_PASS3` — default: `gpt-4.1`
- `MAX_CONCURRENT_CALLS` — default: 5
- `MAX_FILE_LINES` — default: 5000
- `CACHE_DIR` — default: `.viscode_cache`
- `ALLOWED_PATHS` — default: `/Users,/home,/Volumes`

### Task 1.2: File Scanner Service
**File:** `services/scanner.py`

Responsibilities:
- Walk directory tree recursively
- Apply ignore patterns (`.git`, `node_modules`, `__pycache__`, `dist`, `build`, `.env`, `*.min.js`, etc.)
- Detect language from file extension
- Compute SHA-256 hash of file content
- Skip binary files (check for null bytes in first 8KB)
- Skip files > MAX_FILE_LINES with warning
- Detect non-UTF8 encoding (try `chardet`, skip with warning if unreadable)
- Detect minified code (any single line > 1000 chars → flag as minified)
- Detect generated code (`*_pb2.py`, `*.generated.*` → flag, skip AI analysis)
- Resolve symlinks (skip if target is outside project root)
- Handle `PermissionError` gracefully (log + skip)
- Return `FileManifest` with all metadata + skipped file reasons

Key logic:
```python
DEFAULT_IGNORE = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".nuxt", "target", "bin", "obj",
    ".idea", ".vscode", ".DS_Store", "*.min.js", "*.min.css",
    "package-lock.json", "yarn.lock", "poetry.lock",
    "*.pyc", "*.pyo", "*.class", "*.o", "*.so", "*.dylib"
}

LANGUAGE_MAP = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".java": "java",
    ".go": "go", ".rs": "rust", ".cs": "csharp",
    ".rb": "ruby", ".php": "php", ".swift": "swift",
    ".kt": "kotlin", ".scala": "scala", ".c": "c",
    ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
}
```

### Task 1.3: Ground Truth Extractor
**File:** `services/extractor.py`

Uses regex patterns per language to extract identifiers WITHOUT AI.
This is the **ground truth** that AI output will be validated against.

Per-language regex patterns for:
- Function/method definitions + line numbers
- Class definitions + line ranges
- Import statements + sources
- Decorator/annotation names
- API route definitions (framework-specific)
- Top-level variable assignments
- Type/interface/struct definitions

Example (Python):
```python
PYTHON_PATTERNS = {
    "function": r"^(\s*)def\s+(\w+)\s*\(",
    "class": r"^class\s+(\w+)",
    "import": r"^(?:from\s+([\w.]+)\s+)?import\s+(.+)",
    "decorator": r"^@(\w+(?:\.\w+)*)",
    "variable": r"^([A-Z_][A-Z0-9_]*)\s*=",  # Constants
    "fastapi_route": r"@\w+\.(get|post|put|delete|patch)\s*\(\s*[\"']([^\"']+)",
    "flask_route": r"@\w+\.route\s*\(\s*[\"']([^\"']+)",
}
```

### Task 1.4: Pydantic Models
**File:** `models/analysis.py` and `models/graph.py`

All data models from the Design Document (Section 5) implemented as Pydantic BaseModel classes with validation.

Critical validators:
- `line_start` must be > 0 and <= file line count
- `name` must be non-empty
- `language` must be in LANGUAGE_MAP values
- `method` (for endpoints) must be valid HTTP method

---

## Phase 2: AI Analysis Engine

### Task 2.1: Smart Chunker
**File:** `services/chunker.py`

Rules:
1. If file <= 500 lines → single chunk (no splitting)
2. If file > 500 lines → split at **function/class boundaries**
3. Each chunk includes:
   - The imports section (always prepended for context)
   - One or more complete function/class definitions
   - Target chunk size: 300-500 lines
4. Never split inside a function body
5. Each chunk gets a `chunk_context` header telling AI what file and position this is

```python
def chunk_file(content: str, ground_truth: GroundTruth) -> list[CodeChunk]:
    """Split file at function/class boundaries, keeping imports as context."""
    # Use ground_truth identifiers to know where functions start/end
    # Group consecutive functions into chunks of ~400 lines
    # Always prepend import section to each chunk
```

### Task 2.2: AI Analyzer (Core Engine)
**File:** `services/analyzer.py`

The heart of the system. Three methods for three passes.

**Pass 1 Prompt Template:**
```
You are a senior code analyst. Analyze this {language} code file and provide a structured analysis.

FILE: {file_path}
ROLE: This is part of a {project_type} project.

KNOWN IDENTIFIERS (verified from source code):
{ground_truth_identifiers_json}

CODE:
```{language}
{code_content}
```

TASK: For each identifier listed above, provide:
1. A clear 1-2 sentence description of what it does
2. WHY it exists (its purpose in the project)
3. What other functions/methods it calls
4. Any side effects (database writes, API calls, file I/O)
5. Complexity: simple/moderate/complex
6. Your confidence in this analysis: 0.0-1.0 (1.0 = very confident)

Also identify:
- Any API endpoints with their HTTP method, route, auth requirements
- Data models/schemas with field descriptions
- Key logic blocks that are important to understand
- How errors are handled

CRITICAL RULES:
- ONLY describe identifiers that appear in the KNOWN IDENTIFIERS list
- Do NOT invent functions or classes that don't exist in the code
- If you're unsure about something, say "unclear" rather than guessing
- Line numbers must reference actual positions in the code provided

Respond in this exact JSON structure:
{json_schema}
```

**Pass 2 Prompt Template:**
```
You are analyzing relationships between files in a codebase.

PROJECT TYPE: {project_type}
FRAMEWORK: {detected_framework}

FILE SUMMARIES:
{all_file_summaries_json}

IMPORT MAP:
{import_relationships_from_ground_truth}

TASK: Analyze the cross-file relationships:
1. For each import relationship, explain WHAT is being used and WHY
2. Identify data flow chains (e.g., "request → router → controller → service → DB → response")
3. Flag any circular dependencies
4. Identify the main entry points of the application
5. Note which files share data models or types

Respond in this exact JSON structure:
{cross_file_schema}
```

**Pass 3 Prompt Template:**
```
You are writing an architecture overview for a developer who has never seen this codebase.

PROJECT SUMMARY:
{pass2_output_summary}

FILE COUNT: {total_files} files across {total_folders} directories
LANGUAGES: {language_breakdown}
TOTAL LINES: {total_lines}

TASK: Write a comprehensive but accessible architecture summary:
1. What type of project is this? (REST API, CLI tool, full-stack app, etc.)
2. What framework and major libraries does it use?
3. What design patterns are employed? (MVC, Repository, etc.)
4. Write a 3-5 sentence overview a beginner could understand
5. Suggest a reading order: which files to read first to understand the project
6. List the 3-5 key concepts someone needs to understand about this codebase

Respond in this exact JSON structure:
{architecture_schema}
```

**Key Implementation Details:**
- Use `openai.AsyncClient` for async API calls
- Structured output with `response_format={"type": "json_object"}`
- Retry with exponential backoff: wait 1s, 2s, 4s (max 3 retries)
- Semaphore limiting concurrent calls to `MAX_CONCURRENT_CALLS`
- Timeout: 60 seconds per API call
- Log every API call with: file, model, tokens_in, tokens_out, duration, cost

### Task 2.3: Post-Validator
**File:** `services/validator.py`

After AI returns analysis, cross-check against ground truth:
```python
def validate_analysis(ai_output: FileAnalysis, ground_truth: GroundTruth) -> FileAnalysis:
    """
    - Remove any AI-reported functions not in ground truth
    - Fix line numbers that are off by > 5 lines (use ground truth)
    - Flag elements with low confidence
    - Log all corrections made
    """
```

### Task 2.4: Analysis Cache
**File:** `cache/store.py`

Cache structure:
```
.viscode_cache/
├── {project_hash}/
│   ├── manifest.json          # File manifest with hashes
│   ├── files/
│   │   ├── {file_hash}.json   # Per-file analysis (Pass 1)
│   │   └── ...
│   ├── cross_analysis.json    # Pass 2 output
│   ├── architecture.json      # Pass 3 output
│   └── graph_data.json        # Final graph data
```

Cache key: `SHA256(file_content) + model_version`

On re-analysis:
1. Scan all files, compute hashes
2. Compare with cached manifest
3. Only re-analyze files with changed hashes
4. If ANY file changed → re-run Pass 2 and Pass 3
5. Rebuild graph data

---

## Phase 3: API Server & Orchestrator

### Task 3.1: Analysis Orchestrator
**File:** `services/orchestrator.py`

Coordinates the full pipeline with progress reporting:

```python
class AnalysisOrchestrator:
    async def analyze_project(self, path: str, progress_callback) -> ProjectAnalysis:
        # 1. Validate path (security sandboxing check)
        # 2. Scan files → FileManifest (incl. skipped files + reasons)
        progress("scanning", "Found {n} code files ({m} skipped)", 5)
        
        # 3. Check cache, identify files needing analysis
        progress("cache_check", "Skipping {n} cached files", 10)
        
        # 4. Extract ground truth for each uncached file
        progress("extracting", file_name, 15)
        
        # 5. Run Pass 1 (concurrent with semaphore, max 5)
        failed_files = []
        for file in uncached_files:
            try:
                progress("analyzing", file_name, percent)
                # chunk → analyze → validate → cache
            except AnalysisError as e:
                failed_files.append((file, str(e)))
                progress("warning", f"Failed: {file_name} - {e}", percent)
                # Continue with next file — NEVER abort pipeline
        
        # 6. Run Pass 2 (cross-file) — retry up to 3x
        try:
            progress("cross_analysis", "Analyzing relationships", 90)
        except Exception:
            progress("warning", "Cross-file analysis unavailable", 90)
            # Serve Pass 1 results only
        
        # 7. Run Pass 3 (architecture) — retry up to 3x
        try:
            progress("architecture", "Generating overview", 95)
        except Exception:
            progress("warning", "Architecture summary unavailable", 95)
        
        # 8. Build graph data
        progress("building_graph", "Creating visualization", 98)
        
        # 9. Cache everything
        # 10. Report results including failures
        progress("complete", f"Done! {len(failed_files)} files failed", 100)
```

### Task 3.2: FastAPI Server
**File:** `main.py`

- All routes from API contract (Design Doc Section 6)
- SSE endpoint for progress streaming using `sse-starlette`
- CORS configured for frontend dev server (`http://localhost:5173`)
- Startup: validate API key with test call, create cache dir
- Global error handler with structured JSON error responses
- Request ID middleware for tracing (UUID per request)
- **`GET /health`** endpoint returning `{"status": "ok", "api_key_valid": bool, "version": str}`
- **`GET /api/projects/{id}/estimate`** endpoint:
  - Scans project (fast, no AI calls)
  - Returns: file count, total lines, estimated tokens, estimated cost in USD, estimated time
  - Uses formula: `cost = files × avg_tokens × price_per_token × passes`

### Task 3.3: Graph Builder
**File:** `services/graph_builder.py`

Transforms analysis data into D3.js-compatible graph format:

```python
class GraphBuilder:
    def build_overview(self, analysis: ProjectAnalysis) -> GraphData:
        """Project Overview: files as nodes, imports as edges"""
        # Group files by directory → create folder nodes
        # Create file nodes with metadata (language, lines, function count)
        # Create edges from import relationships
        # Layout hint: "dagre"
    
    def build_file_detail(self, file_analysis: FileAnalysis) -> GraphData:
        """File Deep Dive: all elements inside one file"""
        # Create nodes for classes, functions, endpoints, variables
        # Create edges for method-of-class, calls, etc.
        # Layout hint: "dagre" (vertical)
    
    def build_dependency_graph(self, analysis: ProjectAnalysis) -> GraphData:
        """Dependency Web: import relationships"""
        # Files as nodes
        # Import relationships as directed edges
        # Highlight circular dependencies in red
        # Layout hint: "force"
    
    def build_endpoint_map(self, analysis: ProjectAnalysis) -> GraphData:
        """API Endpoints: routes → handlers → services"""
        # Endpoint nodes (with HTTP method badges)
        # Handler function nodes
        # Service/DB nodes
        # Layout hint: "horizontal"
```

---

## Phase 4: Frontend — Canvas & UI

### Task 4.1: Vite Project Setup
```bash
npx -y create-vite@latest ./ --template vanilla
npm install d3 dagre-d3 highlight.js
```

### Task 4.2: Design System (CSS)
**File:** `styles/index.css`

Core design tokens:
```css
:root {
    /* Dark theme */
    --bg-primary: #0a0a0f;
    --bg-secondary: #12121a;
    --bg-card: rgba(255, 255, 255, 0.04);
    --bg-card-hover: rgba(255, 255, 255, 0.08);
    
    /* Accent colors */
    --accent-blue: #00d4ff;
    --accent-purple: #7c3aed;
    --accent-green: #10b981;
    --accent-orange: #f59e0b;
    --accent-pink: #ec4899;
    --accent-red: #ef4444;
    
    /* Node type colors */
    --node-file: #3b82f6;
    --node-function: #10b981;
    --node-class: #6366f1;
    --node-endpoint: #8b5cf6;
    --node-model: #f59e0b;
    --node-variable: #fbbf24;
    --node-import: #6b7280;
    
    /* Text */
    --text-primary: #f0f0f5;
    --text-secondary: #9ca3af;
    --text-muted: #6b7280;
    
    /* Glass effect */
    --glass-bg: rgba(255, 255, 255, 0.05);
    --glass-border: rgba(255, 255, 255, 0.1);
    --glass-blur: 12px;
    
    /* Canvas */
    --canvas-grid-color: rgba(255, 255, 255, 0.03);
    --canvas-grid-size: 20px;
    
    /* Typography */
    --font-family: 'Inter', -apple-system, sans-serif;
    --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
    
    /* Spacing */
    --radius-sm: 6px;
    --radius-md: 10px;
    --radius-lg: 16px;
    
    /* Transitions */
    --transition-fast: 150ms ease;
    --transition-normal: 250ms ease;
}
```

### Task 4.3: Infinite Canvas Engine
**File:** `src/canvas/engine.js`

Built on D3.js zoom behavior:
```javascript
class CanvasEngine {
    constructor(container) {
        // Create SVG with D3
        // Add zoom/pan behavior (d3.zoom)
        // Render dot grid background
        // Setup minimap
    }
    
    setData(graphData) {
        // Apply layout algorithm (dagre)
        // Render nodes by type (different shapes/colors)
        // Render edges with optional animation
        // Fit view to content
    }
    
    // Interactions
    onNodeClick(callback) {}
    onNodeHover(callback) {}
    onNodeDoubleClick(callback) {}
    onCanvasClick(callback) {}
    
    // Navigation
    zoomToNode(nodeId) {}
    fitToView() {}
    centerOn(x, y) {}
}
```

Key features:
- Dot grid background (moves with pan, scales with zoom)
- Smooth animated transitions when switching views
- Node glow effect on hover
- Edge flow animation (dashed line moving along the edge)
- Viewport culling (only render nodes in visible area for performance)

### Task 4.4: Node Renderer
**File:** `src/canvas/nodes.js`

Different SVG shapes per node type:
```javascript
const NODE_RENDERERS = {
    file: (g, data) => {
        // Rounded rectangle with language-colored header
        // Icon (file icon) + label
        // Subtitle with line count
    },
    function: (g, data) => {
        // Pill/stadium shape
        // Green gradient fill
        // Label + param count badge
    },
    class: (g, data) => {
        // Large rounded rectangle with thick border
        // Blue gradient
        // Method count badge
    },
    endpoint: (g, data) => {
        // Badge shape
        // HTTP method tag (GET=green, POST=blue, etc.)
        // Route as label
    },
    // ... model, variable, import, folder
};
```

### Task 4.5: Sidebar & Detail Panel
**Files:** `src/panels/sidebar.js`, `src/panels/detail.js`

**Sidebar (left):**
- File tree explorer (collapsible folders)
- Click file → highlights on canvas
- Stats summary (file count, function count, etc.)
- Filter toggles (show/hide by element type)

**Detail Panel (right):**
- Opens when a node is clicked
- Shows: name, type badge, AI description, purpose
- **Confidence indicator** — colored dot (green > 0.8, yellow > 0.5, red < 0.5)
- Code snippet preview (with syntax highlighting via `highlight.js` npm package)
- Connections: "Calls" and "Called by" lists (clickable → zooms to that node)
- File reference with line number
- Complexity badge (simple=green, moderate=yellow, complex=red)
- Tags (async, database, auth, etc.)
- For failed files: "⚠️ Analysis failed" with retry button

### Task 4.6: View Switcher
**File:** `src/views/` directory

Tab bar at top of canvas area:
- **Overview** (default) — project-level file graph
- **File Detail** — activated on double-click file node
- **Dependencies** — import/export web
- **Endpoints** — API routes (only shown if endpoints exist)

Each view fetches its own graph data from the backend.

---

## Phase 5: Integration & Testing

### Task 5.1: End-to-End Flow
1. User opens `http://localhost:5173`
2. Enters project path in input field
3. Clicks "Analyze"
4. SSE stream shows real-time progress with file names
5. On completion, canvas renders project overview
6. User can click/zoom/pan to explore
7. Click node → detail panel shows description
8. Double-click file → drill into file contents
9. Switch views via tabs

### Task 5.2: Test with Real Projects
Test fixtures (open source projects):
- **Small**: A single FastAPI file (10-20 functions)
- **Medium**: A typical Express.js project (20-50 files)
- **Large**: A Django project (100+ files)

Validation checklist:
- [ ] All files discovered correctly
- [ ] Ground truth extraction matches actual code
- [ ] AI descriptions are accurate and helpful
- [ ] No hallucinated functions/classes
- [ ] Cross-file relationships are correct
- [ ] Canvas renders without performance issues
- [ ] Detail panel shows correct information
- [ ] Caching works on re-analysis

---

## Phase 6: Polish

### Task 6.1: Progress UX
- Animated progress bar with phase labels
- Per-file status indicators (analyzing, done, failed, cached)
- Estimated time remaining
- Cost counter (running total of API spend)
- Skipped files section with reasons

### Task 6.2: Error States
- No files found → helpful message with supported languages list
- API key invalid → clear error with setup instructions + link
- File analysis failed → warning icon (⚠️) on node, hover for reason, click to retry
- Network error → retry button with backoff indicator
- Path not found / permission denied → specific error message

### Task 6.3: Data Privacy Warning
- On first analysis, show modal: "Your code will be sent to OpenAI for analysis."
- Checkbox: "I understand and consent"
- Link to OpenAI data usage policy
- Remember consent per session (localStorage)

### Task 6.4: Search
- Global search across all element names
- Highlight matching nodes on canvas
- Search results list with type badges and confidence indicators
- Keyboard shortcut: Ctrl+F / Cmd+F

### Task 6.5: Flow Tracing
- Right-click endpoint → "Trace Request Flow"
- Highlights the entire path: endpoint → handler → service → DB
- Animated edges show direction of data flow
- Breadcrumb shows the flow chain

---

## Build Order (Recommended)

```
Session 1: Backend Core
  ├── 1.1 Project setup + config
  ├── 1.2 Scanner service
  ├── 1.3 Ground truth extractor
  ├── 1.4 Pydantic models
  ├── 2.1 Smart chunker
  └── 2.2 AI analyzer (Pass 1 only first)

Session 2: Backend Complete + API
  ├── 2.2 AI analyzer (Pass 2 + 3)
  ├── 2.3 Post-validator
  ├── 2.4 Cache store
  ├── 3.1 Orchestrator
  ├── 3.2 FastAPI server + SSE
  └── 3.3 Graph builder

Session 3: Frontend
  ├── 4.1 Vite setup
  ├── 4.2 Design system CSS
  ├── 4.3 Canvas engine
  ├── 4.4 Node renderer
  ├── 4.5 Sidebar + Detail panel
  └── 4.6 View switcher

Session 4: Integration + Polish
  ├── 5.1 End-to-end flow
  ├── 5.2 Test with real projects
  ├── 6.1 Progress UX
  ├── 6.2 Error states
  └── 6.3 Search
```

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| AI hallucinations in output | High | High | Hybrid extraction + post-validation |
| GPT-4.1 rate limits hit | Medium | Medium | Semaphore + exponential backoff |
| Large file breaks chunker | Medium | Medium | Function-boundary splitting + max size limit |
| Canvas lag on large projects | Low | Medium | SVG viewport culling + node limit |
| OpenAI API cost higher than expected | Low | Low | Cost estimator + model tier selection |
| Regex extraction misses edge cases | Medium | Low | AI fills gaps, log extraction failures |
