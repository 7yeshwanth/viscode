"""
VisCode Analysis Data Models

Pydantic models for all data flowing through the analysis pipeline:
- Scanner output (FileManifest)
- Ground truth extraction output
- AI analysis output (Pass 1, 2, 3)
- Graph visualization data
"""

from __future__ import annotations
from pydantic import BaseModel, Field, field_validator
from enum import Enum
from typing import Any


# ──────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────

class IdentifierKind(str, Enum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    VARIABLE = "variable"
    CONSTANT = "constant"
    IMPORT = "import"
    ENDPOINT = "endpoint"
    DECORATOR = "decorator"
    TYPE = "type"
    INTERFACE = "interface"


class Complexity(str, Enum):
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


class HTTPMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    OPTIONS = "OPTIONS"
    HEAD = "HEAD"


class FileStatus(str, Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    CACHED = "cached"
    FAILED = "failed"
    SKIPPED = "skipped"


class NodeType(str, Enum):
    FOLDER = "folder"
    FILE = "file"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    ENDPOINT = "endpoint"
    MODEL = "model"
    VARIABLE = "variable"
    IMPORT = "import"


class EdgeType(str, Enum):
    IMPORTS = "imports"
    CALLS = "calls"
    EXTENDS = "extends"
    IMPLEMENTS = "implements"
    DATA_FLOW = "data_flow"
    CONTAINS = "contains"  # parent-child (file contains function)


class LayoutHint(str, Enum):
    DAGRE = "dagre"
    FORCE = "force"
    HORIZONTAL = "horizontal"


# ──────────────────────────────────────────────
# Scanner Models
# ──────────────────────────────────────────────

class FileInfo(BaseModel):
    """Metadata for a single discovered file."""
    path: str                          # Relative path from project root
    absolute_path: str                 # Full filesystem path
    language: str                      # e.g. "python", "javascript"
    size_bytes: int = 0
    line_count: int = 0
    content_hash: str = ""             # SHA-256 of file content
    is_minified: bool = False          # True if detected as minified
    is_generated: bool = False         # True if matches generated code patterns
    status: FileStatus = FileStatus.PENDING
    error: str | None = None           # Error message if status is FAILED/SKIPPED


class SkippedFile(BaseModel):
    """Record of a file that was skipped during scanning."""
    path: str
    reason: str                        # "binary", "too_large", "encoding", "permission", etc.


class FileManifest(BaseModel):
    """Result of scanning a project directory."""
    project_root: str
    total_files: int = 0
    total_lines: int = 0
    files: list[FileInfo] = Field(default_factory=list)
    languages: dict[str, int] = Field(default_factory=dict)    # language → file count
    skipped: list[SkippedFile] = Field(default_factory=list)


# ──────────────────────────────────────────────
# Ground Truth Extraction Models
# ──────────────────────────────────────────────

class ExtractedIdentifier(BaseModel):
    """A code identifier extracted via regex/AST (ground truth)."""
    name: str
    kind: IdentifierKind
    line_start: int
    line_end: int | None = None
    parent: str | None = None          # For methods: the class name
    params: list[str] = Field(default_factory=list)
    decorators: list[str] = Field(default_factory=list)

    @field_validator("line_start")
    @classmethod
    def line_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"line_start must be >= 1, got {v}")
        return v


class ExtractedImport(BaseModel):
    """An import statement extracted via regex."""
    name: str                          # What is imported
    source: str                        # Where from
    line: int
    alias: str | None = None


class GroundTruth(BaseModel):
    """Ground truth extraction result for a single file."""
    file_path: str
    language: str
    identifiers: list[ExtractedIdentifier] = Field(default_factory=list)
    imports: list[ExtractedImport] = Field(default_factory=list)
    line_count: int = 0


# ──────────────────────────────────────────────
# AI Analysis Models — Pass 1 (Per File)
# ──────────────────────────────────────────────

class ParamInfo(BaseModel):
    """Function/method parameter info."""
    name: str
    type: str | None = None
    description: str = ""
    default: str | None = None


class ReturnInfo(BaseModel):
    """Function/method return info."""
    type: str = ""
    description: str = ""


class FunctionAnalysis(BaseModel):
    """AI analysis of a single function or method."""
    name: str
    description: str = ""
    purpose: str = ""
    line_start: int = 0
    line_end: int = 0
    params: list[ParamInfo] = Field(default_factory=list)
    returns: ReturnInfo | None = None
    calls: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)
    complexity: Complexity = Complexity.SIMPLE
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ClassAnalysis(BaseModel):
    """AI analysis of a single class."""
    name: str
    description: str = ""
    purpose: str = ""
    line_start: int = 0
    line_end: int = 0
    inherits_from: list[str] = Field(default_factory=list)
    methods: list[FunctionAnalysis] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class EndpointAnalysis(BaseModel):
    """AI analysis of an API endpoint."""
    method: HTTPMethod
    route: str
    description: str = ""
    handler_function: str = ""
    auth_required: bool = False
    request_body: dict[str, Any] | None = None
    response_schema: dict[str, Any] | None = None
    middleware: list[str] = Field(default_factory=list)


class ImportInfo(BaseModel):
    """Enriched import information (ground truth + AI)."""
    name: str
    source: str
    type: str = "external"             # "internal", "external", "stdlib"
    alias: str | None = None
    line: int = 0
    used_for: str = ""                 # AI: what this import is used for


class FieldInfo(BaseModel):
    """Field in a data model."""
    name: str
    type: str = ""
    description: str = ""
    constraints: str | None = None
    default: str | None = None


class DataModelAnalysis(BaseModel):
    """AI analysis of a data model/schema/struct."""
    name: str
    description: str = ""
    fields: list[FieldInfo] = Field(default_factory=list)
    line_start: int = 0
    line_end: int = 0


class VariableInfo(BaseModel):
    """Module/global level variable info."""
    name: str
    type: str | None = None
    description: str = ""
    scope: str = "module"              # "global", "module", "class"
    line: int = 0
    is_constant: bool = False


class LogicBlock(BaseModel):
    """An important logic block within a file."""
    description: str
    why_it_matters: str = ""
    line_start: int = 0
    line_end: int = 0


class FileAnalysis(BaseModel):
    """Complete AI analysis result for a single file (Pass 1)."""
    file_path: str
    file_summary: str = ""
    role_in_project: str = ""          # "controller", "model", "utility", etc.
    language: str = ""
    imports: list[ImportInfo] = Field(default_factory=list)
    classes: list[ClassAnalysis] = Field(default_factory=list)
    functions: list[FunctionAnalysis] = Field(default_factory=list)
    endpoints: list[EndpointAnalysis] = Field(default_factory=list)
    data_models: list[DataModelAnalysis] = Field(default_factory=list)
    variables: list[VariableInfo] = Field(default_factory=list)
    key_logic: list[LogicBlock] = Field(default_factory=list)
    error_handling: list[str] = Field(default_factory=list)


# ──────────────────────────────────────────────
# AI Analysis Models — Pass 2 (Cross-File)
# ──────────────────────────────────────────────

class FileRelationship(BaseModel):
    """A relationship between two files."""
    source_file: str
    target_file: str
    relationship_type: str             # "imports", "extends", "calls", "instantiates"
    details: list[str] = Field(default_factory=list)


class FlowStep(BaseModel):
    """A single step in a data flow chain."""
    file_path: str
    function_name: str
    description: str = ""
    step_type: str = ""                # "entry", "middleware", "handler", "service", "data_access", "response"


class DataFlowChain(BaseModel):
    """A chain showing how data flows through the system."""
    description: str
    steps: list[FlowStep] = Field(default_factory=list)


class CrossFileAnalysis(BaseModel):
    """AI analysis of cross-file relationships (Pass 2)."""
    relationships: list[FileRelationship] = Field(default_factory=list)
    data_flows: list[DataFlowChain] = Field(default_factory=list)
    circular_dependencies: list[list[str]] = Field(default_factory=list)
    shared_models: list[dict[str, Any]] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)


# ──────────────────────────────────────────────
# AI Analysis Models — Pass 3 (Architecture)
# ──────────────────────────────────────────────

class KeyConcept(BaseModel):
    """A key concept in the project."""
    concept: str
    description: str
    relevant_files: list[str] = Field(default_factory=list)


class ArchitectureSummary(BaseModel):
    """AI-generated architecture overview (Pass 3)."""
    project_type: str = ""             # "REST API", "CLI tool", etc.
    framework: str = ""                # "FastAPI", "Express", etc.
    design_patterns: list[str] = Field(default_factory=list)
    summary: str = ""                  # 3-5 sentence overview
    reading_order: list[str] = Field(default_factory=list)
    key_concepts: list[KeyConcept] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)


# ──────────────────────────────────────────────
# Combined Project Analysis
# ──────────────────────────────────────────────

class ProjectAnalysis(BaseModel):
    """Complete analysis result for a project."""
    project_id: str
    project_root: str
    manifest: FileManifest
    file_analyses: dict[str, FileAnalysis] = Field(default_factory=dict)  # path → analysis
    cross_file: CrossFileAnalysis | None = None
    architecture: ArchitectureSummary | None = None
    failed_files: list[dict[str, str]] = Field(default_factory=list)  # [{path, error}]


# ──────────────────────────────────────────────
# Graph Visualization Models
# ──────────────────────────────────────────────

class GraphNode(BaseModel):
    """A node in the visualization graph."""
    id: str
    label: str
    type: NodeType
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    children: list[str] | None = None  # Child node IDs for drill-down
    confidence: float | None = None
    status: FileStatus | None = None   # For showing failed/skipped nodes


class GraphEdge(BaseModel):
    """An edge (connection) in the visualization graph."""
    id: str
    source: str                        # Source node ID
    target: str                        # Target node ID
    type: EdgeType
    label: str | None = None
    animated: bool = False


class GraphData(BaseModel):
    """Complete graph data for a single visualization view."""
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    view_type: str = "overview"        # "overview", "file_detail", "dependencies", "endpoints"
    layout_hint: LayoutHint = LayoutHint.DAGRE
    architecture: ArchitectureSummary | None = None


# ──────────────────────────────────────────────
# API Request/Response Models
# ──────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    """Request to start project analysis."""
    path: str
    ignore_patterns: list[str] = Field(default_factory=list)
    max_file_size_lines: int = 5000
    model_tier: str = "balanced"       # "fast", "balanced", "deep"


class ProjectStatus(BaseModel):
    """Current status of a project analysis."""
    project_id: str
    status: str                        # "scanning", "analyzing", "complete", "error"
    phase: str = ""
    message: str = ""
    percent: float = 0.0
    total_files: int = 0
    files_done: int = 0
    files_failed: int = 0
    estimated_cost_usd: float = 0.0


class CostEstimate(BaseModel):
    """Cost/time estimate before analysis."""
    total_files: int
    total_lines: int
    estimated_tokens: int
    estimated_cost_usd: float
    estimated_time_seconds: int
    languages: dict[str, int]
    warnings: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
    api_key_valid: bool = False
    version: str = "1.0.0"
    cache_dir: str = ""
