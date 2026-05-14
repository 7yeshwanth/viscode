# VisCode — Full Vision & Roadmap
> **Purpose:** Preserve the complete product vision beyond MVP.  
> **These features are NOT in v1** but are the north star for the project.

---

## Post-MVP Feature Roadmap

### 🔮 Phase 2: Advanced Views

#### Call Graph View
- Function-to-function call relationships across entire project
- Entry points highlighted (main, route handlers)
- Dead code detection — functions never called, marked with ⚠️
- Recursive call detection — flagged with warning
- Depth control slider (show 1-hop, 2-hop, N-hop callers/callees)

#### Data Flow View
- Trace how data moves: request → middleware → handler → service → DB → response
- Variable transformation tracking (what happens to data at each step)
- Highlight where data is validated, sanitized, or exposed
- Useful for security audits and understanding business logic

#### Complexity Heatmap
- Toggle to color-code all nodes by complexity (green → yellow → red)
- Cyclomatic complexity estimation
- Helps identify refactoring targets
- "Hotspot" detection — files/functions that are both complex AND frequently imported

---

### 🎨 Phase 3: Polish & Power Features

#### Flow Tracing (Interactive)
- Right-click any endpoint → "Trace Request Flow"
- Entire data path lights up with animated edges
- Step-by-step walkthrough mode (click "Next" to follow the flow)
- Breadcrumb trail shows current position in the flow

#### Advanced Search & Filtering
- Search by: name, description, type, file path, tag
- Regex search support
- Filter by: language, complexity, file size, has-endpoints, has-side-effects
- "Show only" mode — hide everything except matching nodes
- Saved filters / presets

#### Export & Sharing
- Export visualization as high-res PNG/SVG
- Export as interactive HTML (self-contained, shareable)
- Export analysis as JSON (for programmatic access)
- PDF report generation with architecture summary + diagrams
- Shareable link (upload to cloud, get URL)

#### Code Diff Visualization
- Compare two versions of the same project
- Highlight: new files (green), deleted files (red), modified files (yellow)
- Show what functions were added/removed/changed
- Useful for PR reviews and understanding changes

---

### 🤖 Phase 4: AI Enhancements

#### Local Model Support (Ollama / llama.cpp)
- For sensitive/proprietary codebases that can't be sent to OpenAI
- Support Ollama API (same interface, different backend)
- Model selection in config: `openai`, `ollama`, `anthropic`
- Quality may vary — show warning about potential quality differences

#### Interactive AI Q&A
- Chat panel: "What does this function do?" "How does auth work?"
- Context-aware — AI knows the full project analysis
- Click a node → ask questions about it
- "Explain this like I'm a beginner" mode

#### Auto-Documentation Generation
- Generate README.md from analysis
- Generate API documentation from endpoint analysis
- Generate architecture decision records (ADRs)
- Generate onboarding guide for new developers

#### Continuous Analysis
- Watch mode: re-analyze changed files on save
- Git integration: analyze only files changed since last commit
- VS Code extension wrapper: trigger from command palette

---

### 🏗️ Phase 5: Platform & Scale

#### Docker & Cloud Deployment
- Docker Compose for one-command setup
- GitHub Action for CI/CD analysis
- Cloud-hosted version (analyze public GitHub repos by URL)
- Multi-user with auth (for teams)

#### VS Code Extension
- Wrap the web app in a VS Code webview panel
- Click node → jump to that line in editor
- Trigger analysis from command palette
- Side-by-side: code editor + visualization

#### Multi-Project Management
- Dashboard to manage multiple analyzed projects
- Compare architectures between projects
- Track project evolution over time (weekly snapshots)

#### Plugin System
- Custom node types for domain-specific elements
- Custom analysis passes (e.g., security audit, performance audit)
- Theme plugins (light mode, high contrast, colorblind-friendly)
- Language plugins (add support for new languages)

---

### 📊 Phase 6: Intelligence Layer

#### Pattern Detection
- Auto-detect: MVC, Repository, Factory, Singleton, Observer patterns
- Anti-pattern detection: God classes, circular deps, deep nesting
- Suggest refactoring opportunities
- Architecture compliance checking (does code match intended architecture?)

#### Dependency Health
- Check npm/pip package versions against latest
- Flag known vulnerabilities (integrate with CVE databases)
- License compatibility checking
- Bundle size impact analysis

#### Onboarding Score
- Rate how "onboarding-friendly" a codebase is
- Metrics: documentation coverage, naming quality, code organization
- Suggestions to improve developer experience
- "Time to understand" estimation

---

## Visual Node Types (Full Set)

All node types planned across all phases:

| Element | Shape | Color | Phase |
|---------|-------|-------|-------|
| Folder | Container with header | Dark gray | MVP |
| File | Rounded rectangle | Language-colored | MVP |
| Class | Thick-bordered rectangle | Blue gradient | MVP |
| Function/Method | Pill/stadium shape | Green gradient | MVP |
| API Endpoint | Diamond/badge | Purple + HTTP method tag | MVP |
| Data Model | Table-like rectangle | Orange gradient | MVP |
| Variable/Constant | Small dot | Gold | MVP |
| Import | Hexagon | Gray | MVP |
| Middleware | Triangle | Pink | Phase 2 |
| Database Table | Cylinder | Dark blue | Phase 2 |
| External Service | Cloud shape | Light blue | Phase 2 |
| Config/Environment | Gear icon | Gray-green | Phase 3 |
| Test File | Rectangle with checkmark | Teal | Phase 3 |
| Error Handler | Rectangle with ! | Red-orange | Phase 3 |

---

## Interaction Features (Full Set)

| Feature | Description | Phase |
|---------|-------------|-------|
| Hover tooltip | Name + 1-line description | MVP |
| Click → detail panel | Full description, code ref, connections | MVP |
| Double-click → drill-down | File → internals, function → call tree | MVP |
| Zoom/Pan | Scroll wheel + drag | MVP |
| Search | Find by name, highlight on canvas | MVP |
| Right-click context menu | "Show callers", "Trace flow", "View source" | Phase 2 |
| Flow tracing | Highlight entire request path | Phase 2 |
| Drag to reposition | Move nodes on canvas | Phase 2 |
| Group selection | Drag-select multiple nodes | Phase 3 |
| Minimap | Overview navigator in corner | Phase 3 |
| Breadcrumb navigation | Project → folder → file → function | Phase 3 |
| Keyboard shortcuts | Ctrl+F search, Esc close panel, etc. | Phase 3 |
| Collaborative cursors | See other users' positions | Phase 5 |

---

## Tech Stack Evolution

| Layer | MVP | Phase 2-3 | Phase 4-5 |
|-------|-----|-----------|-----------|
| Frontend | Vite + Vanilla JS + D3.js | + Web Workers for layout | + WebSocket for live updates |
| Backend | FastAPI + OpenAI | + Ollama support | + Redis queue + PostgreSQL |
| AI | GPT-4.1-mini (P1) + GPT-4.1 (P2/P3) | + Anthropic Claude | + Local models |
| Deployment | Local dev server | + Docker Compose | + Cloud (Vercel/Railway) |
| Storage | JSON file cache | + SQLite | + PostgreSQL |
