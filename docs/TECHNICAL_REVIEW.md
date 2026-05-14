# 🔍 VisCode Plan Review — Multi-Role Technical Audit

---

## 1. 👔 Engineering Manager

**Focus:** Feasibility, scope, timeline, risk, team capacity

### Assessment: ⚠️ Scope is Ambitious — Needs Phasing Discipline

| Concern | Detail |
|---------|--------|
| **Scope creep risk** | 6 view modes, 3-pass AI, infinite canvas, minimap, heatmap, flow tracing — this is a LOT for a first release. We're building n8n + ChatGPT + VS Code in one go. |
| **MVP definition is missing** | The plan jumps to "everything." What's the ONE view that proves the concept works? Ship that first. |
| **Cost estimation** | No estimate of API costs at scale. 500-file project × 3 passes = 1,500 API calls. At GPT-4.1 pricing, this could be $5-15 per analysis. Users need to know upfront. |
| **Timeline** | "Build today" with this scope is unrealistic for production-grade quality. Realistic: MVP in 1 session, full product in 3-4. |

### Recommendations
1. **Define a strict MVP**: Project Overview (Galaxy View) + File Deep Dive + Detail Panel. That's it for v1.
2. **Add a cost estimator**: Before analysis, scan the project and show estimated token count + cost.
3. **Cut Phase 1 scope**: Remove call graph, data flow, and heatmap from Phase 1. Add in Phase 2.
4. **Add progress tracking**: Analysis of 100 files takes time. Need a real-time progress bar with per-file status.

---

## 2. 🏛️ System Architect

**Focus:** Architecture patterns, scalability, design decisions, tech choices

### Assessment: ✅ Solid Foundation — But Has Gaps

| Area | Verdict | Detail |
|------|---------|--------|
| **Orchestrator pattern** | ✅ Good | Single coordinator for multi-step pipeline. Correct pattern. |
| **Service layer** | ✅ Good | Clean separation: scanner → chunker → analyzer → resolver → graph builder |
| **Caching** | ⚠️ Needs work | Plan says "SQLite / JSON" — needs to be concrete. Cache key should be `file_hash + model_version`. |
| **State management** | ❌ Missing | Frontend has `state.js` but no spec for what state is managed and how. |
| **WebSocket vs SSE** | ❌ Missing | Analysis is long-running. REST polling is wrong pattern. Need Server-Sent Events (SSE) for real-time progress. |
| **Concurrency model** | ⚠️ Unclear | "Parallel processing" mentioned but no spec. How many concurrent API calls? Semaphore? |

### Architecture Gaps to Fix

**1. Long-Running Task Pattern:**
```
Current (wrong):
  POST /analyze → waits 5 minutes → returns result

Should be:
  POST /analyze → returns task_id immediately
  GET /analyze/{task_id}/stream → SSE stream of progress + results
```

**2. Cache Invalidation Strategy:**
```
Cache key = hash(file_content) + ai_model_version
On re-analyze:
  - Hash each file
  - Skip files with unchanged hash
  - Only re-analyze changed files
  - Re-run Pass 2 & 3 if any file changed (cross-file relationships may shift)
```

**3. Add a Queue System:**
```
For large projects:
  Files → Queue → Worker Pool (N concurrent) → Results → Aggregator
  This prevents overwhelming the OpenAI API
```

### Recommendations
1. **Use SSE** for real-time analysis progress streaming
2. **Define concurrency**: Max 5 concurrent API calls with semaphore
3. **File-hash-based caching** — only re-analyze changed files
4. **Add WebSocket** for canvas collaboration (future: share visualizations live)

---

## 3. 🔧 Senior Backend Engineer

**Focus:** API design, data pipeline, error handling, code quality

### Assessment: ✅ Good Structure — Needs API Contract Spec

| Area | Verdict | Detail |
|------|---------|--------|
| **API design** | ⚠️ Incomplete | No API endpoint specs defined. What are the exact routes, request/response schemas? |
| **Error handling** | ⚠️ Mentioned, not specified | "Retry with backoff" — but what about partial failures? If 3 out of 100 files fail analysis? |
| **Token management** | ❌ Missing | GPT-4.1 has a context limit. Large files (1000+ lines) need splitting. How? The "smart chunker" needs spec. |
| **Output validation** | ❌ Missing | AI returns JSON — but what if it's malformed? Need Pydantic validation on every AI response. |

### API Contract (should be defined)

```
POST   /api/projects                → Create analysis project
GET    /api/projects/{id}           → Get project status + metadata
GET    /api/projects/{id}/stream    → SSE: real-time analysis progress
GET    /api/projects/{id}/graph     → Full graph data for visualization
GET    /api/projects/{id}/files     → List analyzed files
GET    /api/projects/{id}/files/{f} → Single file analysis detail
GET    /api/projects/{id}/search    → Search across all elements
DELETE /api/projects/{id}           → Delete project + cache
```

### Critical: Smart Chunker Spec
```
For files > 500 lines:
  1. Parse into logical blocks (functions, classes) using basic regex/AST
  2. Each chunk = 1 logical block + its imports context
  3. Analyze each chunk separately
  4. Merge chunk results into single file analysis
  
NOT: split at line 500 arbitrarily (breaks function bodies)
```

### Partial Failure Handling
```
If file analysis fails after 3 retries:
  - Mark file as "analysis_failed" with error reason
  - Continue with remaining files
  - Include failed files in visualization with warning icon
  - Allow manual re-trigger for individual files
```

### Recommendations
1. **Define full API contract** before coding
2. **Validate every AI response** with Pydantic — reject malformed, retry
3. **Smart chunker must respect function boundaries** — never split mid-function
4. **Partial failure is expected** — design for graceful degradation

---

## 4. 🎨 Senior Frontend Engineer

**Focus:** UI/UX, canvas performance, interaction design, rendering

### Assessment: ✅ Good Vision — Performance Concerns

| Area | Verdict | Detail |
|------|---------|--------|
| **n8n-style canvas** | ✅ Great choice | Users understand node-based UIs. Familiar pattern. |
| **D3.js for canvas** | ⚠️ Consider alternatives | D3 is powerful but verbose. For node-based canvas, consider **Cytoscape.js** (built for graph visualization) or **elkjs** for layout. |
| **Performance at scale** | ⚠️ Critical concern | 500 nodes + 2000 edges in SVG = laggy. Need virtualization or Canvas (HTML5) fallback. |
| **Node design** | ✅ Good | Different shapes/colors per type. Clear visual language. |
| **Mobile support** | ❌ Not considered | Canvas interactions on mobile? Touch zoom/pan? Probably out of scope — but state it. |

### Performance Strategy
```
Node count strategy:
  < 200 nodes  → SVG rendering (crisp, interactive)
  200-1000     → SVG with virtualization (only render visible nodes)
  > 1000       → HTML5 Canvas rendering (performant but less interactive)
  
Recommendation: Start with SVG, add virtualization if needed.
Most projects will have < 200 top-level nodes.
```

### Layout Algorithm Choice
```
For different views, different layouts:
  Project Overview → dagre (hierarchical, top-down)
  Dependency Graph → force-directed (organic, shows clusters)
  Call Graph       → dagre (tree-like)
  API Endpoints    → horizontal flow (left-to-right)
  File Deep Dive   → vertical stack (top-down within file)
```

### Recommendations
1. **Use dagre-d3** for layout (not manual positioning) — auto-arrange is essential
2. **SVG with viewport culling** — only render nodes in the visible area
3. **Debounce zoom/pan** — avoid re-rendering on every pixel of movement
4. **Canvas fallback** for very large projects (> 500 nodes)
5. **Explicitly exclude mobile** from v1 scope

---

## 5. 🤖 AI/ML Engineer

**Focus:** Prompt engineering, output quality, token optimization, model selection

### Assessment: ⚠️ This Is The Make-or-Break Layer — Needs More Rigor

| Area | Verdict | Detail |
|------|---------|--------|
| **3-pass approach** | ✅ Excellent | Necessary for quality. Single-pass can't capture cross-file relationships. |
| **Structured output** | ✅ Good | JSON schema is well-defined. |
| **Prompt engineering** | ❌ Not specified | The prompts are the MOST important part and they're not written yet. |
| **Token budget** | ❌ Not calculated | What's the actual token cost? Need math. |
| **Model choice** | ⚠️ Consider options | GPT-4.1 is good. But gpt-4.1-mini might be sufficient for Pass 1, saving 80% cost. |
| **Hallucination risk** | 🔴 CRITICAL | AI might invent functions that don't exist, misidentify relationships, or generate wrong line numbers. MUST validate against actual code. |

### Token Budget Math
```
GPT-4.1 pricing (approximate):
  Input:  $2.00 / 1M tokens
  Output: $8.00 / 1M tokens

Average file: 200 lines ≈ 2,000 tokens
Prompt template: ~1,500 tokens
Output per file: ~2,000 tokens

Per file cost: (3,500 × $2 + 2,000 × $8) / 1M = $0.023

100-file project:
  Pass 1: 100 files × $0.023 = $2.30
  Pass 2: 1 call with summaries (~20K tokens in, ~5K out) = $0.08
  Pass 3: 1 call (~10K tokens in, ~3K out) = $0.044
  TOTAL ≈ $2.42
```

### CRITICAL: Hallucination Mitigation
```
Problem: AI says "function getUserById on line 45" but the function
         is actually on line 52, or doesn't exist at all.

Solutions:
  1. POST-VALIDATION: After AI returns analysis, verify:
     - Every function name exists in the actual source code
     - Line numbers are within file bounds
     - Import sources actually exist as files in the project
     - Class names match actual definitions
  
  2. GROUND THE PROMPT: Include explicit instruction:
     "Only report elements that ACTUALLY EXIST in the code.
      Do NOT invent or assume anything not present.
      If unsure about a line number, set it to -1."
  
  3. TWO-STAGE EXTRACTION: 
     First use regex/AST to extract function names and line numbers.
     Send THOSE to the AI and ask it to add descriptions.
     This eliminates hallucinated identifiers entirely.
```

### Tiered Model Strategy (cost optimization)
```
Pass 1 (per-file): gpt-4.1-mini (cheap, good enough for single-file analysis)
Pass 2 (cross-file): gpt-4.1 (needs deep reasoning about relationships)
Pass 3 (architecture): gpt-4.1 (needs high-level synthesis)

This cuts total cost by ~60% with minimal quality loss.
```

### Recommendations
1. **Write and test prompts FIRST** before building anything else
2. **Hybrid extraction**: Use regex/AST for identifiers + line numbers, AI for descriptions
3. **Post-validate EVERYTHING** — never trust AI line numbers or names blindly
4. **Tiered model usage** — mini for Pass 1, full for Pass 2-3
5. **Add confidence scores** — AI should rate its confidence for each element
6. **Include the file's language** in prompt — AI behaves differently per language

---

## 6. 🔒 Security Engineer

**Focus:** API key handling, file system access, data safety

### Assessment: ⚠️ Several Concerns

| Risk | Severity | Detail |
|------|----------|--------|
| **API key exposure** | 🔴 HIGH | Key stored where? If frontend sends it, it's in browser memory. If backend `.env`, safer. |
| **File system access** | 🔴 HIGH | Backend reads arbitrary paths. User could point to `/etc/passwd`. Need path validation + sandboxing. |
| **Code sent to OpenAI** | 🟠 MEDIUM | Proprietary code is sent to OpenAI servers. Must warn users. Consider: can we support local models (Ollama) as alternative? |
| **CORS** | 🟡 LOW | Frontend-backend CORS config needed. Lock down origins. |

### Recommendations
1. **API key**: Store ONLY in backend `.env`. Frontend never sees it. Add key validation endpoint.
2. **Path sandboxing**: Whitelist allowed base directories. Reject paths with `..`, symlinks outside sandbox.
3. **Data warning**: Show clear warning: "Your code will be sent to OpenAI for analysis."
4. **Future**: Support local models (Ollama/llama.cpp) for sensitive codebases.
5. **Rate limit by IP**: Prevent abuse if deployed publicly.

---

## 7. 🚀 DevOps / SRE

**Focus:** Deployment, reliability, monitoring

### Assessment: ✅ Good for Local — Not Yet Production-Deployable

| Area | Status |
|------|--------|
| **Local dev** | ✅ Simple: `pip install` + `npm run dev` |
| **Docker** | ❌ Not in Phase 1, but needed for open source |
| **Monitoring** | ❌ No observability. Add structured logs at minimum. |
| **Health checks** | ❌ Missing. Need `/health` endpoint. |

### Recommendations
1. Add `/health` and `/ready` endpoints
2. Structured JSON logging with request IDs
3. Docker Compose for one-command setup (Phase 2)
4. Track: analysis duration, API call count, failure rate, cache hit rate

---

## 8. 🧪 QA Lead

**Focus:** Testability, edge cases, validation

### Assessment: ⚠️ Edge Cases Not Addressed

| Edge Case | Risk | Mitigation |
|-----------|------|------------|
| **Empty project** | Low | Show helpful message, not crash |
| **Binary files** | Medium | Detect and skip (images, compiled code, etc.) |
| **Minified code** | High | 1 line = 50K characters. Chunker will break. Detect + warn. |
| **Non-UTF8 files** | Medium | Encoding detection needed |
| **Huge files (10K+ lines)** | High | Smart chunker must handle. Set max file size limit. |
| **No code files found** | Low | Show message: "No supported code files found" |
| **API timeout** | High | Set per-call timeout (60s), retry, then mark failed |
| **Circular imports** | Medium | Dependency graph must handle cycles (not infinite loop) |
| **Generated code** (e.g., protobuf) | Medium | Detect + optionally skip |

### Recommendations
1. **Define supported languages** explicitly (Python, JS/TS, Go, Java, C#, Ruby, PHP, Rust)
2. **File size limits**: Skip files > 5,000 lines with warning
3. **Binary detection**: Check file headers, skip non-text files
4. **Timeout per file**: 60 second max analysis time
5. **Integration test**: Use a known open-source project as test fixture

---

## 📋 Consolidated Action Items

| # | Action | Source | Priority | Phase |
|---|--------|--------|----------|-------|
| 1 | **Define strict MVP** — Overview + File Dive + Detail Panel only | Manager | 🔴 P0 | Before build |
| 2 | **Hybrid extraction** — regex/AST for names+lines, AI for descriptions | AI Engineer | 🔴 P0 | Backend |
| 3 | **Post-validate AI output** against actual source code | AI Engineer | 🔴 P0 | Backend |
| 4 | **Path sandboxing** — prevent arbitrary file system access | Security | 🔴 P0 | Backend |
| 5 | **SSE for progress streaming** — not REST polling | Architect | 🔴 P0 | Backend |
| 6 | **Smart chunker spec** — respect function boundaries | Backend | 🔴 P0 | Backend |
| 7 | **Write AI prompts first** and test before building UI | AI Engineer | 🔴 P0 | Backend |
| 8 | **Partial failure handling** — graceful degradation | Backend | 🟠 P1 | Backend |
| 9 | **File-hash caching** — skip unchanged files | Architect | 🟠 P1 | Backend |
| 10 | **Tiered models** — mini for Pass 1, full for Pass 2-3 | AI Engineer | 🟠 P1 | Backend |
| 11 | **SVG viewport culling** — only render visible nodes | Frontend | 🟠 P1 | Frontend |
| 12 | **Cost estimator** — show estimated cost before analysis | Manager | 🟠 P1 | Backend |
| 13 | **Data privacy warning** — "code sent to OpenAI" notice | Security | 🟠 P1 | Frontend |
| 14 | **API contract spec** — define all endpoints | Backend | 🟠 P1 | Backend |
| 15 | **Docker Compose** setup | DevOps | 🟡 P2 | Infra |
| 16 | **Supported languages list** | QA | 🟡 P2 | Docs |
| 17 | **Health check endpoints** | DevOps | 🟡 P2 | Backend |
| 18 | **Local model support** (Ollama) | Security | 🟡 P2 | Future |
