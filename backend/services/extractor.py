"""
VisCode Ground Truth Extractor

Extracts code identifiers (functions, classes, imports, etc.) using regex patterns.
This provides the GROUND TRUTH that AI output is validated against.
No AI calls — pure pattern matching per language.
"""

from __future__ import annotations

import re
import logging
from models.analysis import (
    ExtractedIdentifier, ExtractedImport, GroundTruth, IdentifierKind
)

logger = logging.getLogger("viscode.extractor")


# ──────────────────────────────────────────────
# Language-specific regex patterns
# ──────────────────────────────────────────────

PATTERNS: dict[str, dict[str, str]] = {
    "python": {
        "function": r"^(\s*)def\s+(\w+)\s*\(",
        "class": r"^class\s+(\w+)\s*[\(:]",
        "decorator": r"^\s*@(\w+(?:\.\w+)*)",
        "constant": r"^([A-Z_][A-Z0-9_]{2,})\s*=",
        "import_from": r"^from\s+([\w.]+)\s+import\s+(.+)",
        "import_direct": r"^import\s+(.+)",
        "fastapi_route": r"@\w+\.(get|post|put|delete|patch|options|head)\s*\(\s*[\"']([^\"']+)",
        "flask_route": r"@\w+\.route\s*\(\s*[\"']([^\"']+)[\"']\s*(?:,\s*methods\s*=\s*\[([^\]]+)\])?",
    },
    "javascript": {
        "function_decl": r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(",
        "arrow_const": r"^(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(?.*?\)?\s*=>",
        "class": r"^(?:export\s+)?class\s+(\w+)",
        "import_from": r"^import\s+(?:\{([^}]+)\}|(\w+))\s+from\s+[\"']([^\"']+)[\"']",
        "import_require": r"^(?:const|let|var)\s+(?:\{([^}]+)\}|(\w+))\s*=\s*require\s*\(\s*[\"']([^\"']+)[\"']\s*\)",
        "express_route": r"\.\s*(get|post|put|delete|patch)\s*\(\s*[\"']([^\"']+)",
        "export_default": r"^export\s+default\s+(?:class|function)?\s*(\w+)?",
        "constant": r"^(?:export\s+)?const\s+([A-Z_][A-Z0-9_]{2,})\s*=",
    },
    "typescript": {},  # Inherits from javascript, plus extras below
    "java": {
        "class": r"^(?:public|private|protected)?\s*(?:abstract|final)?\s*class\s+(\w+)",
        "interface": r"^(?:public)?\s*interface\s+(\w+)",
        "method": r"^\s+(?:public|private|protected)?\s*(?:static)?\s*(?:abstract)?\s*(?:\w+(?:<[^>]+>)?)\s+(\w+)\s*\(",
        "import": r"^import\s+([\w.]+(?:\.\*)?)\s*;",
        "annotation": r"^\s*@(\w+)",
        "spring_mapping": r"@(?:Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*(?:value\s*=\s*)?[\"']([^\"']+)",
        "constant": r"^\s*(?:public|private|protected)?\s*static\s+final\s+\w+\s+([A-Z_][A-Z0-9_]+)\s*=",
    },
    "go": {
        "function": r"^func\s+(\w+)\s*\(",
        "method": r"^func\s+\(\w+\s+\*?(\w+)\)\s+(\w+)\s*\(",
        "type_struct": r"^type\s+(\w+)\s+struct\s*\{",
        "type_interface": r"^type\s+(\w+)\s+interface\s*\{",
        "import_single": r"^\s*\"([^\"]+)\"",
        "constant": r"^\s*(\w+)\s*(?:=|:=)",
        "package": r"^package\s+(\w+)",
    },
    "rust": {
        "function": r"^(?:pub(?:\(crate\))?\s+)?(?:async\s+)?fn\s+(\w+)",
        "struct": r"^(?:pub(?:\(crate\))?\s+)?struct\s+(\w+)",
        "enum": r"^(?:pub(?:\(crate\))?\s+)?enum\s+(\w+)",
        "impl": r"^impl(?:<[^>]+>)?\s+(\w+)",
        "trait": r"^(?:pub(?:\(crate\))?\s+)?trait\s+(\w+)",
        "use_stmt": r"^use\s+([\w:]+(?:::\{[^}]+\})?)\s*;",
        "constant": r"^(?:pub\s+)?(?:const|static)\s+([A-Z_][A-Z0-9_]+)\s*:",
    },
    "csharp": {
        "class": r"^(?:\s*)(?:public|private|internal|protected)?\s*(?:abstract|sealed|static|partial)?\s*class\s+(\w+)",
        "interface": r"^(?:\s*)(?:public|internal)?\s*interface\s+(\w+)",
        "method": r"^\s+(?:public|private|protected|internal)?\s*(?:static|async|virtual|override|abstract)?\s*(?:\w+(?:<[^>]+>)?)\s+(\w+)\s*\(",
        "using": r"^using\s+([\w.]+)\s*;",
        "attribute": r"^\s*\[(\w+)",
        "aspnet_route": r"\[Http(Get|Post|Put|Delete|Patch)\s*\(\s*[\"']?([^\"'\]]*)",
    },
    "ruby": {
        "function": r"^\s*def\s+(\w+[\?\!]?)",
        "class": r"^class\s+(\w+)",
        "module": r"^module\s+(\w+)",
        "require": r"^require\s+[\"']([^\"']+)[\"']",
        "require_relative": r"^require_relative\s+[\"']([^\"']+)[\"']",
        "constant": r"^\s*([A-Z][A-Z0-9_]+)\s*=",
    },
    "php": {
        "function": r"^(?:\s*)(?:public|private|protected)?\s*(?:static)?\s*function\s+(\w+)\s*\(",
        "class": r"^(?:abstract|final)?\s*class\s+(\w+)",
        "interface": r"^interface\s+(\w+)",
        "use": r"^use\s+([\w\\]+)\s*;",
        "constant": r"^\s*(?:const|define\s*\(\s*[\"'])([A-Z_][A-Z0-9_]+)",
        "laravel_route": r"Route::(get|post|put|delete|patch)\s*\(\s*[\"']([^\"']+)",
    },
}

# TypeScript inherits from JavaScript with additions
PATTERNS["typescript"] = {
    **PATTERNS["javascript"],
    "interface": r"^(?:export\s+)?interface\s+(\w+)",
    "type_alias": r"^(?:export\s+)?type\s+(\w+)\s*=",
    "enum": r"^(?:export\s+)?enum\s+(\w+)",
    "decorator": r"^\s*@(\w+)",
}

# Aliases for extended language names
for _alias, _base in [("vue", "typescript"), ("svelte", "typescript"), ("dart", "typescript")]:
    if _alias not in PATTERNS:
        PATTERNS[_alias] = PATTERNS.get(_base, {})


def _find_block_end(lines: list[str], start_line: int, language: str) -> int:
    """
    Find the end line of a code block (function/class) using indentation or brace matching.
    """
    if start_line >= len(lines):
        return start_line

    if language == "python":
        # Python: indentation-based
        start_indent = len(lines[start_line]) - len(lines[start_line].lstrip())
        for i in range(start_line + 1, len(lines)):
            stripped = lines[i].strip()
            if not stripped or stripped.startswith("#"):
                continue  # Skip empty lines and comments
            current_indent = len(lines[i]) - len(lines[i].lstrip())
            if current_indent <= start_indent:
                return i  # End of block (exclusive, so return previous)
        return len(lines)  # Block extends to end of file

    else:
        # Brace-based languages (JS, Java, Go, Rust, C#, etc.)
        brace_count = 0
        found_open = False
        for i in range(start_line, len(lines)):
            for char in lines[i]:
                if char == "{":
                    brace_count += 1
                    found_open = True
                elif char == "}":
                    brace_count -= 1
                    if found_open and brace_count == 0:
                        return i + 1  # End of block (1-indexed)
        return len(lines)


def _extract_params(line: str, language: str) -> list[str]:
    """Extract parameter names from a function definition line."""
    # Find content between parentheses
    paren_match = re.search(r"\(([^)]*)\)", line)
    if not paren_match:
        return []

    params_str = paren_match.group(1).strip()
    if not params_str:
        return []

    params = []
    for param in params_str.split(","):
        param = param.strip()
        if not param:
            continue
        # Remove type annotations, defaults, etc.
        if language == "python":
            # "name: type = default" → "name"
            name = param.split(":")[0].split("=")[0].strip()
            if name and name != "self" and name != "cls":
                params.append(name)
        elif language in ("java", "csharp", "go"):
            # "Type name" → "name"
            parts = param.strip().split()
            if len(parts) >= 2:
                params.append(parts[-1].strip("*&"))
            elif len(parts) == 1:
                params.append(parts[0].strip("*&"))
        else:
            # JS/TS: "name = default" or "name: type"
            name = param.split("=")[0].split(":")[0].strip()
            # Remove destructuring, rest operator
            name = name.lstrip("{[...").rstrip("}]")
            if name:
                params.append(name)

    return params


def extract_ground_truth(file_path: str, content: str, language: str) -> GroundTruth:
    """
    Extract all identifiers from a source file using regex patterns.

    Args:
        file_path: Relative file path (for reference).
        content: The raw source code content.
        language: Programming language identifier.

    Returns:
        GroundTruth with all extracted identifiers and imports.
    """
    lines = content.splitlines()
    line_count = len(lines)
    identifiers: list[ExtractedIdentifier] = []
    imports: list[ExtractedImport] = []

    lang_patterns = PATTERNS.get(language, {})
    if not lang_patterns:
        logger.warning(f"No extraction patterns for language: {language}")
        return GroundTruth(
            file_path=file_path,
            language=language,
            line_count=line_count,
        )

    current_class: str | None = None
    class_indent: int = -1

    for line_num, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//", "/*", "*", "<!--")):
            continue

        # Track current class context (for methods)
        if language == "python":
            indent = len(line) - len(line.lstrip())
            if indent <= class_indent:
                current_class = None
                class_indent = -1

        # --- Classes ---
        for pattern_name in ("class",):
            pattern = lang_patterns.get(pattern_name)
            if not pattern:
                continue
            m = re.match(pattern, line)
            if m:
                name = m.group(1)
                end_line = _find_block_end(lines, line_num, language)
                identifiers.append(ExtractedIdentifier(
                    name=name,
                    kind=IdentifierKind.CLASS,
                    line_start=line_num + 1,
                    line_end=end_line,
                ))
                if language == "python":
                    current_class = name
                    class_indent = len(line) - len(line.lstrip())

        # --- Interfaces / Type aliases ---
        for pattern_name in ("interface", "type_alias", "enum", "type_struct", "type_interface", "trait"):
            pattern = lang_patterns.get(pattern_name)
            if not pattern:
                continue
            m = re.match(pattern, line)
            if m:
                name = m.group(1)
                identifiers.append(ExtractedIdentifier(
                    name=name,
                    kind=IdentifierKind.TYPE,
                    line_start=line_num + 1,
                    line_end=_find_block_end(lines, line_num, language),
                ))

        # --- Functions / Methods ---
        for pattern_name in ("function", "function_decl", "arrow_const", "method"):
            pattern = lang_patterns.get(pattern_name)
            if not pattern:
                continue
            m = re.match(pattern, line)
            if m:
                name = m.groups()[-1]  # Last group is usually the name
                # Skip if already captured as arrow_const but it's not a function
                if pattern_name == "arrow_const" and "=>" not in line:
                    continue
                params = _extract_params(line, language)
                end_line = _find_block_end(lines, line_num, language)

                is_method = current_class is not None and language == "python"
                if pattern_name == "method" and language in ("java", "csharp"):
                    is_method = True
                # Go receiver methods: func (r *ReceiverType) MethodName()
                go_receiver = None
                if pattern_name == "method" and language == "go" and len(m.groups()) >= 2:
                    go_receiver = m.group(1)  # Receiver type name
                    name = m.group(2)         # Method name
                    is_method = True

                identifiers.append(ExtractedIdentifier(
                    name=name,
                    kind=IdentifierKind.METHOD if is_method else IdentifierKind.FUNCTION,
                    line_start=line_num + 1,
                    line_end=end_line,
                    parent=go_receiver or (current_class if is_method else None),
                    params=params,
                ))

        # --- Decorators / Annotations ---
        for pattern_name in ("decorator", "annotation", "attribute"):
            pattern = lang_patterns.get(pattern_name)
            if not pattern:
                continue
            m = re.match(pattern, line)
            if m:
                name = m.group(1)
                identifiers.append(ExtractedIdentifier(
                    name=name,
                    kind=IdentifierKind.DECORATOR,
                    line_start=line_num + 1,
                ))

        # --- API Routes / Endpoints ---
        for pattern_name in ("fastapi_route", "flask_route", "express_route",
                             "spring_mapping", "aspnet_route", "laravel_route"):
            pattern = lang_patterns.get(pattern_name)
            if not pattern:
                continue
            m = re.search(pattern, line)
            if m:
                groups = m.groups()
                if len(groups) >= 2:
                    method_or_route = groups[0]
                    route = groups[1] if len(groups) > 1 else groups[0]
                    identifiers.append(ExtractedIdentifier(
                        name=f"{method_or_route.upper()} {route}",
                        kind=IdentifierKind.ENDPOINT,
                        line_start=line_num + 1,
                    ))

        # --- Constants ---
        pattern = lang_patterns.get("constant")
        if pattern:
            m = re.match(pattern, line)
            if m:
                name = m.group(1)
                identifiers.append(ExtractedIdentifier(
                    name=name,
                    kind=IdentifierKind.CONSTANT,
                    line_start=line_num + 1,
                ))

        # --- Imports ---
        for pattern_name in ("import_from", "import_direct", "import_require",
                             "import", "import_single", "using", "use", "use_stmt",
                             "require", "require_relative"):
            pattern = lang_patterns.get(pattern_name)
            if not pattern:
                continue
            m = re.match(pattern, line)
            if m:
                groups = m.groups()
                if pattern_name == "import_from" and language == "python":
                    source = groups[0] or ""
                    names = [n.strip().split(" as ")[0].strip() for n in groups[1].split(",")]
                    for name in names:
                        if name and name != "*":
                            imports.append(ExtractedImport(
                                name=name,
                                source=source,
                                line=line_num + 1,
                            ))
                elif pattern_name in ("import_from",) and language in ("javascript", "typescript"):
                    named = groups[0]  # {a, b, c}
                    default = groups[1]  # default import
                    source = groups[2]
                    if named:
                        for n in named.split(","):
                            n = n.strip().split(" as ")[0].strip()
                            if n:
                                imports.append(ExtractedImport(name=n, source=source, line=line_num + 1))
                    if default:
                        imports.append(ExtractedImport(name=default, source=source, line=line_num + 1))
                elif pattern_name == "import_require" and language in ("javascript", "typescript"):
                    named = groups[0]  # {a, b, c}
                    default = groups[1]  # default require
                    source = groups[2]
                    if named:
                        for n in named.split(","):
                            n = n.strip()
                            if n:
                                imports.append(ExtractedImport(name=n, source=source, line=line_num + 1))
                    if default:
                        imports.append(ExtractedImport(name=default, source=source, line=line_num + 1))
                elif pattern_name == "import_direct" and language == "python":
                    for mod in groups[0].split(","):
                        mod = mod.strip().split(" as ")[0].strip()
                        if mod:
                            imports.append(ExtractedImport(name=mod, source=mod, line=line_num + 1))
                else:
                    # Generic: first group is the import source/name
                    source = groups[0] or ""
                    name = source.split(".")[-1].split("/")[-1].split("\\")[-1]
                    imports.append(ExtractedImport(name=name, source=source, line=line_num + 1))

    logger.debug(
        f"Extracted from {file_path}: "
        f"{len(identifiers)} identifiers, {len(imports)} imports"
    )

    return GroundTruth(
        file_path=file_path,
        language=language,
        identifiers=identifiers,
        imports=imports,
        line_count=line_count,
    )
