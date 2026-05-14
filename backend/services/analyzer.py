"""
VisCode AI Analyzer

The heart of the system. Uses OpenAI GPT-4.1 to analyze code files
with a 3-pass pipeline:
  Pass 1: Per-file deep analysis (enriches ground truth with descriptions)
  Pass 2: Cross-file relationship analysis
  Pass 3: Architecture summary

Uses hybrid approach: regex provides facts, AI provides understanding.
"""

import json
import time
import asyncio
import logging
from openai import AsyncOpenAI

from config import config
from models.analysis import (
    FileAnalysis, FunctionAnalysis, ClassAnalysis, EndpointAnalysis,
    ImportInfo, DataModelAnalysis, VariableInfo, LogicBlock,
    CrossFileAnalysis, ArchitectureSummary, KeyConcept,
    FileRelationship, DataFlowChain, FlowStep,
    ParamInfo, ReturnInfo, FieldInfo, Complexity, HTTPMethod,
)
from services.chunker import CodeChunk

logger = logging.getLogger("viscode.analyzer")


# ──────────────────────────────────────────────
# JSON Schemas for structured output
# ──────────────────────────────────────────────

PASS1_SCHEMA = {
    "file_summary": "string: 2-sentence summary of what this file does",
    "role_in_project": "string: controller/model/utility/config/middleware/service/etc",
    "functions": [{
        "name": "string", "description": "string", "purpose": "string",
        "calls": ["string"], "side_effects": ["string"],
        "complexity": "simple|moderate|complex", "confidence": 0.9
    }],
    "classes": [{
        "name": "string", "description": "string", "purpose": "string",
        "inherits_from": ["string"],
        "methods": [{"name": "string", "description": "string", "purpose": "string",
                      "calls": ["string"], "side_effects": ["string"],
                      "complexity": "simple|moderate|complex", "confidence": 0.9}],
        "confidence": 0.9
    }],
    "endpoints": [{
        "method": "GET|POST|PUT|DELETE|PATCH",
        "route": "string", "description": "string",
        "handler_function": "string", "auth_required": False,
        "middleware": ["string"]
    }],
    "data_models": [{
        "name": "string", "description": "string",
        "fields": [{"name": "string", "type": "string", "description": "string"}]
    }],
    "variables": [{
        "name": "string", "type": "string|null",
        "description": "string", "is_constant": False
    }],
    "key_logic": [{
        "description": "string",
        "why_it_matters": "string",
        "line_start": 0, "line_end": 0
    }],
    "error_handling": ["string"],
    "imports_analysis": [{
        "name": "string", "source": "string",
        "type": "internal|external|stdlib", "used_for": "string"
    }]
}


class AIAnalyzer:
    """AI-powered code analysis engine using OpenAI GPT-4.1."""

    def __init__(self):
        api_key = config.OPENAI_API_KEY
        base_url = config.OPENAI_BASE_URL
        # Allow initialization without key (for testing parsing logic)
        # API calls will fail, but parse methods will work
        if api_key and api_key != "sk-your-key-here":
            client_kwargs = {"api_key": api_key}
            if base_url:
                client_kwargs["base_url"] = base_url
            self.client = AsyncOpenAI(**client_kwargs)
        else:
            self.client = None
            logger.warning("No OpenAI API key set. AI calls will fail, but parsing works.")
        self.semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_CALLS)
        self._call_count = 0
        self._total_tokens_in = 0
        self._total_tokens_out = 0

    async def _call_ai(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_retries: int = 3,
        timeout: int = 120,
    ) -> dict:
        """
        Make an AI API call with retry and rate limiting.
        Returns parsed JSON response.
        """
        async with self.semaphore:
            if self.client is None:
                raise RuntimeError("OpenAI API key not configured. Set OPENAI_API_KEY in .env")
            for attempt in range(max_retries):
                try:
                    start_time = time.time()

                    # Build request kwargs
                    kwargs = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.1,
                    }

                    # Only use json_object mode for native OpenAI
                    # Custom proxies (Claude, Azure) may not support it
                    if not config.OPENAI_BASE_URL:
                        kwargs["response_format"] = {"type": "json_object"}

                    response = await asyncio.wait_for(
                        self.client.chat.completions.create(**kwargs),
                        timeout=timeout,
                    )
                    duration = time.time() - start_time

                    # Track usage
                    self._call_count += 1
                    if response.usage:
                        self._total_tokens_in += response.usage.prompt_tokens
                        self._total_tokens_out += response.usage.completion_tokens

                    content = response.choices[0].message.content or ""

                    # Debug: log first 200 chars of response
                    logger.debug(f"AI raw response (first 200 chars): {content[:200]}")

                    if not content.strip():
                        logger.warning(f"AI returned empty content (attempt {attempt + 1})")
                        if attempt == max_retries - 1:
                            raise ValueError("AI returned empty response")
                        await asyncio.sleep(2 ** attempt)
                        continue

                    # Try to extract JSON — handle markdown code blocks
                    result = self._extract_json(content)

                    logger.info(
                        f"AI call #{self._call_count}: model={model}, "
                        f"tokens_in={response.usage.prompt_tokens if response.usage else '?'}, "
                        f"tokens_out={response.usage.completion_tokens if response.usage else '?'}, "
                        f"duration={duration:.1f}s"
                    )
                    return result

                except asyncio.TimeoutError:
                    logger.warning(f"AI call timeout (attempt {attempt + 1}/{max_retries})")
                    if attempt == max_retries - 1:
                        raise
                except json.JSONDecodeError as e:
                    logger.warning(f"AI returned invalid JSON (attempt {attempt + 1}): {e}")
                    if attempt == max_retries - 1:
                        raise
                except Exception as e:
                    wait = 2 ** attempt
                    logger.warning(f"AI call failed (attempt {attempt + 1}): {e}. Retrying in {wait}s...")
                    if attempt == max_retries - 1:
                        raise
                    await asyncio.sleep(wait)

        raise RuntimeError("AI call failed after all retries")

    @staticmethod
    def _extract_json(content: str) -> dict:
        """
        Extract JSON from AI response.
        Handles: raw JSON, markdown ```json blocks, and text with embedded JSON.
        """
        text = content.strip()

        # 1) Direct JSON parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2) Extract from ```json ... ``` code blocks
        import re
        json_block = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
        if json_block:
            try:
                return json.loads(json_block.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 3) Find first { ... } block
        brace_start = text.find('{')
        if brace_start >= 0:
            # Find matching closing brace
            depth = 0
            for i in range(brace_start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[brace_start:i + 1])
                        except json.JSONDecodeError:
                            break

        raise json.JSONDecodeError(
            f"Could not extract JSON from response (length={len(text)})",
            text[:200], 0
        )

    # ──────────────────────────────────────────
    # Pass 1: Per-File Analysis
    # ──────────────────────────────────────────

    async def analyze_file(
        self,
        chunk: CodeChunk,
        ground_truth_json: str,
        language: str,
        model_tier: str = "balanced",
    ) -> dict:
        """
        Analyze a single code chunk (Pass 1).

        Args:
            chunk: The code chunk to analyze.
            ground_truth_json: JSON string of extracted identifiers.
            language: Programming language.
            model_tier: "fast", "balanced", or "deep"

        Returns:
            Raw AI analysis result as dict.
        """
        # fast = cheap model, deep = best model, balanced = per-pass default
        if model_tier == "fast":
            model = config.OPENAI_MODEL_PASS1
        elif model_tier == "deep":
            model = config.OPENAI_MODEL_PASS2
        else:
            model = config.OPENAI_MODEL_PASS1

        system_prompt = """You are a senior code analyst. Your job is to analyze source code and provide clear, accurate descriptions of every code element. You produce structured JSON output.

CRITICAL RULES:
- ONLY describe identifiers that appear in the KNOWN IDENTIFIERS list
- Do NOT invent functions, classes, or variables that don't exist in the code
- If unsure about something, say "unclear" rather than guessing
- Rate your confidence 0.0-1.0 for each element
- Descriptions should be clear enough for a beginner to understand
- Focus on WHAT it does and WHY it exists"""

        user_prompt = f"""Analyze this {language} code file and provide a structured analysis.

FILE: {chunk.file_path}
CHUNK: {chunk.context_header}

KNOWN IDENTIFIERS (extracted from source code — these are verified facts):
{ground_truth_json}

CODE:
```{language}
{chunk.content}
```

For each known identifier, provide:
1. A clear 1-2 sentence description of what it does
2. WHY it exists (its purpose in the project)
3. What other functions/methods it calls
4. Any side effects (database writes, API calls, file I/O, logging)
5. Complexity: simple/moderate/complex
6. Your confidence in this analysis: 0.0-1.0

Also identify:
- Any API endpoints with their HTTP method, route, auth requirements
- Data models/schemas with field descriptions  
- Key logic blocks that are important to understand
- How errors are handled
- What each import is used for (internal/external/stdlib)

Respond with this JSON structure:
{json.dumps(PASS1_SCHEMA, indent=2)}"""

        return await self._call_ai(model, system_prompt, user_prompt)

    def parse_pass1_result(
        self,
        raw: dict,
        file_path: str,
        language: str,
    ) -> FileAnalysis:
        """Parse raw AI output into a validated FileAnalysis model."""
        functions = []
        for f in raw.get("functions", []):
            try:
                functions.append(FunctionAnalysis(
                    name=f.get("name", ""),
                    description=f.get("description", ""),
                    purpose=f.get("purpose", ""),
                    calls=f.get("calls", []),
                    side_effects=f.get("side_effects", []),
                    complexity=Complexity(f.get("complexity", "simple")),
                    confidence=min(1.0, max(0.0, float(f.get("confidence", 0.8)))),
                ))
            except Exception as e:
                logger.warning(f"Failed to parse function {f.get('name', '?')}: {e}")

        classes = []
        for c in raw.get("classes", []):
            try:
                methods = []
                for m in c.get("methods", []):
                    methods.append(FunctionAnalysis(
                        name=m.get("name", ""),
                        description=m.get("description", ""),
                        purpose=m.get("purpose", ""),
                        calls=m.get("calls", []),
                        side_effects=m.get("side_effects", []),
                        complexity=Complexity(m.get("complexity", "simple")),
                        confidence=min(1.0, max(0.0, float(m.get("confidence", 0.8)))),
                    ))
                classes.append(ClassAnalysis(
                    name=c.get("name", ""),
                    description=c.get("description", ""),
                    purpose=c.get("purpose", ""),
                    inherits_from=c.get("inherits_from", []),
                    methods=methods,
                    confidence=min(1.0, max(0.0, float(c.get("confidence", 0.8)))),
                ))
            except Exception as e:
                logger.warning(f"Failed to parse class {c.get('name', '?')}: {e}")

        endpoints = []
        for ep in raw.get("endpoints", []):
            try:
                method_str = ep.get("method", "GET").upper()
                if method_str not in [m.value for m in HTTPMethod]:
                    method_str = "GET"
                endpoints.append(EndpointAnalysis(
                    method=HTTPMethod(method_str),
                    route=ep.get("route", ""),
                    description=ep.get("description", ""),
                    handler_function=ep.get("handler_function", ""),
                    auth_required=ep.get("auth_required", False),
                    middleware=ep.get("middleware", []),
                ))
            except Exception as e:
                logger.warning(f"Failed to parse endpoint: {e}")

        imports = []
        for imp in raw.get("imports_analysis", []):
            try:
                imports.append(ImportInfo(
                    name=imp.get("name", ""),
                    source=imp.get("source", ""),
                    type=imp.get("type", "external"),
                    used_for=imp.get("used_for", ""),
                ))
            except Exception as e:
                logger.warning(f"Failed to parse import: {e}")

        data_models = []
        for dm in raw.get("data_models", []):
            try:
                fields = [FieldInfo(
                    name=f.get("name", ""),
                    type=f.get("type", ""),
                    description=f.get("description", ""),
                ) for f in dm.get("fields", [])]
                data_models.append(DataModelAnalysis(
                    name=dm.get("name", ""),
                    description=dm.get("description", ""),
                    fields=fields,
                ))
            except Exception as e:
                logger.warning(f"Failed to parse data model: {e}")

        variables = []
        for v in raw.get("variables", []):
            try:
                variables.append(VariableInfo(
                    name=v.get("name", ""),
                    type=v.get("type"),
                    description=v.get("description", ""),
                    is_constant=v.get("is_constant", False),
                ))
            except Exception as e:
                logger.warning(f"Failed to parse variable: {e}")

        key_logic = []
        for kl in raw.get("key_logic", []):
            try:
                key_logic.append(LogicBlock(
                    description=kl.get("description", ""),
                    why_it_matters=kl.get("why_it_matters", ""),
                    line_start=kl.get("line_start", 0),
                    line_end=kl.get("line_end", 0),
                ))
            except Exception as e:
                logger.warning(f"Failed to parse logic block: {e}")

        return FileAnalysis(
            file_path=file_path,
            file_summary=raw.get("file_summary", ""),
            role_in_project=raw.get("role_in_project", ""),
            language=language,
            imports=imports,
            classes=classes,
            functions=functions,
            endpoints=endpoints,
            data_models=data_models,
            variables=variables,
            key_logic=key_logic,
            error_handling=raw.get("error_handling", []),
        )

    # ──────────────────────────────────────────
    # Pass 2: Cross-File Analysis
    # ──────────────────────────────────────────

    async def analyze_cross_file(
        self,
        file_summaries: dict[str, str],
        import_map: dict[str, list[dict]],
        languages: dict[str, int],
        model_tier: str = "balanced",
    ) -> CrossFileAnalysis:
        """
        Analyze cross-file relationships (Pass 2).

        Args:
            file_summaries: {file_path: summary} for all analyzed files.
            import_map: {file_path: [{name, source}]} from ground truth.
            languages: {language: file_count}.
            model_tier: "fast", "balanced", or "deep".
        """
        if model_tier == "fast":
            model = config.OPENAI_MODEL_PASS1
        elif model_tier == "deep":
            model = config.OPENAI_MODEL_PASS2
        else:
            model = config.OPENAI_MODEL_PASS2

        system_prompt = """You are analyzing the relationships between files in a codebase. Your goal is to understand how files connect, how data flows, and what the overall structure is. Produce structured JSON output."""

        user_prompt = f"""Analyze the cross-file relationships in this codebase.

LANGUAGES: {json.dumps(languages)}

FILE SUMMARIES:
{json.dumps(file_summaries, indent=2)}

IMPORT MAP (which file imports what from where):
{json.dumps(import_map, indent=2)}

TASK:
1. For each import relationship, explain WHAT is being used and WHY
2. Identify data flow chains (e.g., "request → router → controller → service → DB")
3. Flag any circular dependencies
4. Identify the main entry points of the application
5. Note which files share data models or types

Respond with this JSON:
{{
  "relationships": [{{"source_file": "", "target_file": "", "relationship_type": "imports|extends|calls", "details": ["what is used"]}}],
  "data_flows": [{{"description": "flow description", "steps": [{{"file_path": "", "function_name": "", "description": "", "step_type": "entry|middleware|handler|service|data_access|response"}}]}}],
  "circular_dependencies": [["file1", "file2"]],
  "shared_models": [{{"model_name": "", "used_in_files": [""]}}],
  "entry_points": ["file paths where execution starts"]
}}"""

        raw = await self._call_ai(model, system_prompt, user_prompt)
        return self._parse_cross_file(raw)

    def _parse_cross_file(self, raw: dict) -> CrossFileAnalysis:
        """Parse raw cross-file analysis into model."""
        relationships = []
        for r in raw.get("relationships", []):
            relationships.append(FileRelationship(
                source_file=r.get("source_file", ""),
                target_file=r.get("target_file", ""),
                relationship_type=r.get("relationship_type", "imports"),
                details=r.get("details", []),
            ))

        data_flows = []
        for df in raw.get("data_flows", []):
            steps = [FlowStep(
                file_path=s.get("file_path", ""),
                function_name=s.get("function_name", ""),
                description=s.get("description", ""),
                step_type=s.get("step_type", ""),
            ) for s in df.get("steps", [])]
            data_flows.append(DataFlowChain(
                description=df.get("description", ""),
                steps=steps,
            ))

        return CrossFileAnalysis(
            relationships=relationships,
            data_flows=data_flows,
            circular_dependencies=raw.get("circular_dependencies", []),
            shared_models=raw.get("shared_models", []),
            entry_points=raw.get("entry_points", []),
        )

    # ──────────────────────────────────────────
    # Pass 3: Architecture Summary
    # ──────────────────────────────────────────

    async def analyze_architecture(
        self,
        file_summaries: dict[str, str],
        cross_file: CrossFileAnalysis,
        total_files: int,
        total_lines: int,
        languages: dict[str, int],
        model_tier: str = "balanced",
    ) -> ArchitectureSummary:
        """Generate architecture overview (Pass 3)."""
        if model_tier == "fast":
            model = config.OPENAI_MODEL_PASS1
        elif model_tier == "deep":
            model = config.OPENAI_MODEL_PASS3
        else:
            model = config.OPENAI_MODEL_PASS3

        system_prompt = """You are writing an architecture overview for a developer who has NEVER seen this codebase. Your overview should be clear enough for a complete beginner. Produce structured JSON output."""

        cross_summary = {
            "entry_points": cross_file.entry_points,
            "data_flows": [df.description for df in cross_file.data_flows],
            "circular_deps": cross_file.circular_dependencies,
        }

        user_prompt = f"""Write a comprehensive architecture overview for this codebase.

FILE COUNT: {total_files} files
TOTAL LINES: {total_lines}
LANGUAGES: {json.dumps(languages)}

FILE SUMMARIES:
{json.dumps(file_summaries, indent=2)}

CROSS-FILE ANALYSIS:
{json.dumps(cross_summary, indent=2)}

TASK:
1. What type of project is this? (REST API, CLI tool, full-stack app, library, etc.)
2. What framework and major libraries does it use?
3. What design patterns are employed? (MVC, Repository, Factory, etc.)
4. Write a 3-5 sentence overview a complete beginner could understand
5. Suggest a reading order: which files to read FIRST to understand the project
6. List 3-5 key concepts someone needs to understand about this codebase

Respond with this JSON:
{{
  "project_type": "REST API|CLI|Full-stack|Library|etc",
  "framework": "FastAPI|Express|Django|etc",
  "design_patterns": ["MVC", "etc"],
  "summary": "3-5 sentence overview",
  "reading_order": ["file1.py", "file2.py"],
  "key_concepts": [{{"concept": "name", "description": "explanation", "relevant_files": ["file.py"]}}],
  "tech_stack": ["Python", "FastAPI", "etc"]
}}"""

        raw = await self._call_ai(model, system_prompt, user_prompt)
        return self._parse_architecture(raw)

    def _parse_architecture(self, raw: dict) -> ArchitectureSummary:
        """Parse raw architecture analysis into model."""
        key_concepts = []
        for kc in raw.get("key_concepts", []):
            key_concepts.append(KeyConcept(
                concept=kc.get("concept", ""),
                description=kc.get("description", ""),
                relevant_files=kc.get("relevant_files", []),
            ))

        return ArchitectureSummary(
            project_type=raw.get("project_type", ""),
            framework=raw.get("framework", ""),
            design_patterns=raw.get("design_patterns", []),
            summary=raw.get("summary", ""),
            reading_order=raw.get("reading_order", []),
            key_concepts=key_concepts,
            tech_stack=raw.get("tech_stack", []),
        )

    def get_stats(self) -> dict:
        """Return usage statistics."""
        return {
            "api_calls": self._call_count,
            "total_tokens_in": self._total_tokens_in,
            "total_tokens_out": self._total_tokens_out,
        }
