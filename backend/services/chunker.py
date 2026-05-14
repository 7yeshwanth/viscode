"""
VisCode Smart Chunker

Splits large code files into analyzable chunks while respecting
function/class boundaries. Never splits inside a function body.
Each chunk includes the imports section for context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from models.analysis import GroundTruth, IdentifierKind

logger = logging.getLogger("viscode.chunker")


@dataclass
class CodeChunk:
    """A chunk of code ready for AI analysis."""
    file_path: str
    chunk_index: int           # 0-based index
    total_chunks: int
    content: str               # The code content
    line_start: int            # 1-indexed start line in original file
    line_end: int              # 1-indexed end line in original file
    context_header: str        # Description of chunk position
    identifiers_in_chunk: list[str] = field(default_factory=list)


def _extract_imports_section(lines: list[str], language: str) -> tuple[list[str], int]:
    """
    Extract the imports section from the top of a file.
    Returns (import_lines, last_import_line_index).
    """
    import_lines: list[str] = []
    last_import_idx = -1

    import_keywords = {
        "python": ("import ", "from "),
        "javascript": ("import ", "const ", "require(", "var ", "let "),
        "typescript": ("import ", "const ", "require(", "var ", "let "),
        "java": ("import ", "package "),
        "go": ("import ", "package "),
        "rust": ("use ", "extern "),
        "csharp": ("using ",),
        "ruby": ("require ", "require_relative "),
        "php": ("use ", "require ", "include ", "namespace "),
    }

    keywords = import_keywords.get(language, ("import ",))

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip empty lines and comments at top
        if not stripped or stripped.startswith(("#", "//", "/*", "*", "*/", "\"\"\"", "'''", "<!--")):
            import_lines.append(line)
            continue

        # Check if line is an import
        is_import = any(stripped.startswith(kw) or kw in stripped for kw in keywords)

        if is_import:
            import_lines.append(line)
            last_import_idx = i
        elif last_import_idx >= 0:
            # We've passed the imports section
            break
        else:
            # First non-import, non-comment line
            # Include file-level docstrings/comments
            if i < 5:  # Allow up to 5 lines of header
                import_lines.append(line)
            else:
                break

    # Trim trailing empty lines from imports
    while import_lines and not import_lines[-1].strip():
        import_lines.pop()

    return import_lines, max(last_import_idx, len(import_lines) - 1)


def _get_block_boundaries(ground_truth: GroundTruth) -> list[tuple[int, int, str]]:
    """
    Get sorted list of (start_line, end_line, name) for all top-level blocks
    (functions and classes, NOT methods).
    """
    boundaries = []
    for ident in ground_truth.identifiers:
        # Only top-level: functions and classes (not methods which have a parent)
        if ident.kind in (IdentifierKind.FUNCTION, IdentifierKind.CLASS) and ident.parent is None:
            end = ident.line_end or (ident.line_start + 10)
            boundaries.append((ident.line_start, end, ident.name))
        # Also include standalone endpoints/decorators with significant blocks
        elif ident.kind == IdentifierKind.ENDPOINT:
            boundaries.append((ident.line_start, ident.line_start + 1, ident.name))

    # Sort by start line
    boundaries.sort(key=lambda b: b[0])
    return boundaries


def chunk_file(
    file_path: str,
    content: str,
    ground_truth: GroundTruth,
    max_chunk_lines: int = 450,
    min_chunk_lines: int = 50,
) -> list[CodeChunk]:
    """
    Split a file into chunks respecting function/class boundaries.

    Rules:
    1. Files <= max_chunk_lines: single chunk (no splitting)
    2. Larger files: split at function/class boundaries
    3. Each chunk includes imports section as context
    4. Never split inside a function body
    5. Target chunk size: min_chunk_lines to max_chunk_lines

    Args:
        file_path: Relative file path.
        content: Raw file content.
        ground_truth: Extracted identifiers with line numbers.
        max_chunk_lines: Maximum lines per chunk (default 450).
        min_chunk_lines: Minimum lines before creating a new chunk.

    Returns:
        List of CodeChunk objects.
    """
    lines = content.splitlines()
    total_lines = len(lines)

    # Small files: single chunk
    if total_lines <= max_chunk_lines:
        return [CodeChunk(
            file_path=file_path,
            chunk_index=0,
            total_chunks=1,
            content=content,
            line_start=1,
            line_end=total_lines,
            context_header=f"File: {file_path} (complete file, {total_lines} lines)",
            identifiers_in_chunk=[i.name for i in ground_truth.identifiers],
        )]

    # Extract imports section
    import_lines, imports_end_idx = _extract_imports_section(lines, ground_truth.language)
    imports_text = "\n".join(import_lines) + "\n" if import_lines else ""
    imports_line_count = len(import_lines)

    # Get block boundaries
    blocks = _get_block_boundaries(ground_truth)

    if not blocks:
        # No blocks found — fall back to naive splitting at empty lines
        logger.warning(f"No block boundaries found for {file_path}, using naive split")
        return _naive_chunk(file_path, content, lines, total_lines, max_chunk_lines, imports_text)

    # Group blocks into chunks
    chunks: list[CodeChunk] = []
    current_start_line = imports_end_idx + 2  # Line after imports (1-indexed)
    current_blocks: list[tuple[int, int, str]] = []
    current_line_count = 0

    for block_start, block_end, block_name in blocks:
        block_size = block_end - block_start + 1

        # If adding this block would exceed max, finalize current chunk
        if current_blocks and (current_line_count + block_size > max_chunk_lines):
            chunk = _create_chunk(
                file_path, lines, current_blocks, imports_text,
                imports_line_count, len(chunks), total_lines
            )
            chunks.append(chunk)
            current_blocks = []
            current_line_count = 0

        current_blocks.append((block_start, block_end, block_name))
        current_line_count += block_size

    # Don't forget the last group
    if current_blocks:
        chunk = _create_chunk(
            file_path, lines, current_blocks, imports_text,
            imports_line_count, len(chunks), total_lines
        )
        chunks.append(chunk)

    # Update total_chunks count
    total = len(chunks)
    for c in chunks:
        c.total_chunks = total

    logger.info(f"Chunked {file_path}: {total_lines} lines → {total} chunks")
    return chunks


def _create_chunk(
    file_path: str,
    lines: list[str],
    blocks: list[tuple[int, int, str]],
    imports_text: str,
    imports_line_count: int,
    chunk_idx: int,
    total_lines: int,
) -> CodeChunk:
    """Create a CodeChunk from a group of blocks."""
    first_start = blocks[0][0]
    last_end = blocks[-1][1]
    block_names = [b[2] for b in blocks]

    # Extract the code lines (0-indexed)
    code_lines = lines[first_start - 1: last_end]
    code_text = "\n".join(code_lines)

    # Prepend imports for context
    full_content = f"{imports_text}\n# --- Chunk {chunk_idx + 1} (lines {first_start}-{last_end} of {total_lines}) ---\n\n{code_text}"

    return CodeChunk(
        file_path=file_path,
        chunk_index=chunk_idx,
        total_chunks=0,  # Updated later
        content=full_content,
        line_start=first_start,
        line_end=last_end,
        context_header=(
            f"File: {file_path}, Chunk {chunk_idx + 1}, "
            f"Lines {first_start}-{last_end} of {total_lines}. "
            f"Contains: {', '.join(block_names)}"
        ),
        identifiers_in_chunk=block_names,
    )


def _naive_chunk(
    file_path: str,
    content: str,
    lines: list[str],
    total_lines: int,
    max_chunk_lines: int,
    imports_text: str,
) -> list[CodeChunk]:
    """Fallback: split at empty lines when no block boundaries are found."""
    chunks: list[CodeChunk] = []
    chunk_start = 0

    for i in range(max_chunk_lines, total_lines, max_chunk_lines):
        # Find nearest empty line to split at
        split_at = i
        for j in range(i, min(i + 50, total_lines)):
            if not lines[j].strip():
                split_at = j
                break

        chunk_lines = lines[chunk_start:split_at]
        chunk_content = imports_text + "\n".join(chunk_lines) if chunks else "\n".join(chunk_lines)

        chunks.append(CodeChunk(
            file_path=file_path,
            chunk_index=len(chunks),
            total_chunks=0,
            content=chunk_content,
            line_start=chunk_start + 1,
            line_end=split_at,
            context_header=f"File: {file_path}, Lines {chunk_start + 1}-{split_at} of {total_lines}",
        ))
        chunk_start = split_at

    # Last chunk
    if chunk_start < total_lines:
        chunk_lines = lines[chunk_start:]
        chunks.append(CodeChunk(
            file_path=file_path,
            chunk_index=len(chunks),
            total_chunks=0,
            content=imports_text + "\n".join(chunk_lines),
            line_start=chunk_start + 1,
            line_end=total_lines,
            context_header=f"File: {file_path}, Lines {chunk_start + 1}-{total_lines} of {total_lines}",
        ))

    total = len(chunks)
    for c in chunks:
        c.total_chunks = total

    return chunks
