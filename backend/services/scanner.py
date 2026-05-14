"""
VisCode File Scanner Service

Discovers all code files in a project directory.
Handles: language detection, binary detection, minified code detection,
encoding issues, symlinks, permissions, and file filtering.
"""

import os
import hashlib
import fnmatch
import logging
from pathlib import Path

from config import config
from models.analysis import FileInfo, FileManifest, SkippedFile, FileStatus

logger = logging.getLogger("viscode.scanner")


def _is_binary(file_path: str, chunk_size: int = 8192) -> bool:
    """Check if a file is binary by looking for null bytes in the first chunk."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(chunk_size)
            return b"\x00" in chunk
    except (OSError, PermissionError):
        return True  # Treat unreadable files as binary


def _compute_hash(file_path: str) -> str:
    """Compute SHA-256 hash of file content."""
    sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except (OSError, PermissionError):
        return ""


def _count_lines(file_path: str) -> tuple[int, bool]:
    """
    Count lines in a file and detect if it's minified.
    Returns (line_count, is_minified).
    A file is considered minified if any single line exceeds 1000 characters.
    """
    line_count = 0
    is_minified = False
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line_count += 1
                if len(line) > 1000:
                    is_minified = True
    except (OSError, PermissionError, UnicodeDecodeError):
        pass
    return line_count, is_minified


def _is_generated_code(filename: str) -> bool:
    """Check if a filename matches generated code patterns."""
    for pattern in config.GENERATED_CODE_PATTERNS:
        if fnmatch.fnmatch(filename, pattern):
            return True
    return False


def _should_ignore_dir(dirname: str) -> bool:
    """Check if a directory should be ignored."""
    return dirname in config.DEFAULT_IGNORE_DIRS


def _should_ignore_file(filename: str) -> bool:
    """Check if a file should be ignored by name or extension."""
    if filename in config.DEFAULT_IGNORE_FILES:
        return True
    _, ext = os.path.splitext(filename)
    # Check compound extensions like .min.js
    if filename.endswith(".min.js") or filename.endswith(".min.css"):
        return True
    if ext.lower() in config.DEFAULT_IGNORE_EXTENSIONS:
        return True
    return False


def _get_language(filename: str) -> str | None:
    """Detect programming language from file extension. Returns None if not a code file."""
    _, ext = os.path.splitext(filename)
    return config.LANGUAGE_MAP.get(ext.lower())


def _is_path_safe(path: str) -> bool:
    """
    Security check: ensure the path is under an allowed base directory
    and doesn't match blocked patterns.
    """
    resolved = str(Path(path).resolve())

    # Check blocked paths (top-level system dirs)
    for blocked in config.BLOCKED_PATHS:
        if resolved.startswith(blocked + "/") or resolved == blocked:
            return False

    # Check blocked patterns against individual path components (not substring)
    path_parts = resolved.split("/")
    for pattern in config.BLOCKED_PATTERNS:
        for part in path_parts:
            if part == pattern or part.startswith(pattern):
                return False

    # Check allowed base paths
    for allowed in config.ALLOWED_PATHS:
        if resolved.startswith(allowed):
            return True

    return False


def validate_project_path(path: str) -> tuple[bool, str]:
    """
    Validate that a project path is safe and accessible.
    Returns (is_valid, error_message).
    """
    resolved = Path(path).resolve()

    if not resolved.exists():
        return False, f"Path does not exist: {path}"

    if not resolved.is_dir():
        return False, f"Path is not a directory: {path}"

    if not _is_path_safe(str(resolved)):
        return False, f"Path is outside allowed directories. Allowed: {config.ALLOWED_PATHS}"

    # Check readability
    try:
        os.listdir(str(resolved))
    except PermissionError:
        return False, f"Permission denied: {path}"

    return True, ""


def scan_project(
    project_path: str,
    extra_ignore_patterns: list[str] | None = None,
    max_file_lines: int | None = None,
) -> FileManifest:
    """
    Scan a project directory and discover all code files.

    Args:
        project_path: Absolute path to the project root directory.
        extra_ignore_patterns: Additional glob patterns to ignore.
        max_file_lines: Maximum file size in lines (default from config).

    Returns:
        FileManifest with all discovered files and metadata.
    """
    max_lines = max_file_lines or config.MAX_FILE_LINES
    root = Path(project_path).resolve()
    root_str = str(root)

    files: list[FileInfo] = []
    skipped: list[SkippedFile] = []
    language_counts: dict[str, int] = {}
    total_lines = 0

    extra_ignores = set(extra_ignore_patterns or [])

    logger.info(f"Scanning project: {root_str}")

    for dirpath, dirnames, filenames in os.walk(root_str, followlinks=False):
        # Filter out ignored directories (modifies in-place to skip recursion)
        dirnames[:] = [
            d for d in dirnames
            if not _should_ignore_dir(d)
            and d not in extra_ignores
            and not d.startswith(".")  # Skip hidden directories
        ]

        # Skip symlinked directories that point outside project root
        dirnames[:] = [
            d for d in dirnames
            if not os.path.islink(os.path.join(dirpath, d))
            or str(Path(os.path.join(dirpath, d)).resolve()).startswith(root_str)
        ]

        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(filepath, root_str)

            # Skip ignored files
            if _should_ignore_file(filename):
                continue

            # Skip files matching extra ignore patterns
            if any(fnmatch.fnmatch(filename, p) or fnmatch.fnmatch(rel_path, p) for p in extra_ignores):
                continue

            # Skip hidden files
            if filename.startswith("."):
                continue

            # Skip symlinks pointing outside project root
            if os.path.islink(filepath):
                try:
                    resolved_link = str(Path(filepath).resolve())
                    if not resolved_link.startswith(root_str):
                        skipped.append(SkippedFile(path=rel_path, reason="symlink_outside_project"))
                        continue
                except OSError:
                    skipped.append(SkippedFile(path=rel_path, reason="broken_symlink"))
                    continue

            # Check language support
            language = _get_language(filename)
            if language is None:
                # Not a recognized code file — skip silently (don't add to skipped)
                continue

            # Check binary
            if _is_binary(filepath):
                skipped.append(SkippedFile(path=rel_path, reason="binary_file"))
                continue

            # Check permissions
            if not os.access(filepath, os.R_OK):
                skipped.append(SkippedFile(path=rel_path, reason="permission_denied"))
                continue

            # Count lines and detect minification
            line_count, is_minified = _count_lines(filepath)

            # Check file size
            if line_count > max_lines:
                skipped.append(SkippedFile(
                    path=rel_path,
                    reason=f"too_large ({line_count} lines > {max_lines} limit)"
                ))
                continue

            # Compute content hash
            content_hash = _compute_hash(filepath)

            # Check if generated code
            is_generated = _is_generated_code(filename)

            # Get file size in bytes
            try:
                size_bytes = os.path.getsize(filepath)
            except OSError:
                size_bytes = 0

            # Create FileInfo
            file_info = FileInfo(
                path=rel_path,
                absolute_path=filepath,
                language=language,
                size_bytes=size_bytes,
                line_count=line_count,
                content_hash=content_hash,
                is_minified=is_minified,
                is_generated=is_generated,
                status=FileStatus.PENDING,
            )
            files.append(file_info)

            # Track stats
            total_lines += line_count
            language_counts[language] = language_counts.get(language, 0) + 1

    # Sort files by path for consistent ordering
    files.sort(key=lambda f: f.path)

    manifest = FileManifest(
        project_root=root_str,
        total_files=len(files),
        total_lines=total_lines,
        files=files,
        languages=language_counts,
        skipped=skipped,
    )

    logger.info(
        f"Scan complete: {manifest.total_files} files, "
        f"{manifest.total_lines} lines, "
        f"{len(skipped)} skipped, "
        f"languages: {language_counts}"
    )

    return manifest


def estimate_cost(manifest: FileManifest, model_tier: str = "balanced") -> dict:
    """
    Estimate the cost and time for analyzing a project.

    Args:
        manifest: The scanned file manifest.
        model_tier: "fast" (mini only), "balanced" (mini + full), "deep" (full only).

    Returns:
        Dictionary with cost, time, and token estimates.
    """
    # Average tokens per line of code (rough estimate)
    TOKENS_PER_LINE = 10

    # Pricing per million tokens (approximate, GPT-4.1 as of 2026)
    PRICING = {
        "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
        "gpt-4.1": {"input": 2.00, "output": 8.00},
    }

    total_code_tokens = manifest.total_lines * TOKENS_PER_LINE
    prompt_overhead_per_file = 1500  # Template tokens per file
    output_per_file = 2000  # Expected output tokens per file

    analyzable_files = [f for f in manifest.files if not f.is_generated and not f.is_minified]
    n_files = len(analyzable_files)

    # Select models based on tier
    if model_tier == "fast":
        pass1_model = "gpt-4.1-mini"
        pass2_model = "gpt-4.1-mini"
    elif model_tier == "deep":
        pass1_model = "gpt-4.1"
        pass2_model = "gpt-4.1"
    else:  # balanced
        pass1_model = "gpt-4.1-mini"
        pass2_model = "gpt-4.1"

    # Pass 1: Per-file analysis
    pass1_input = sum(f.line_count * TOKENS_PER_LINE + prompt_overhead_per_file for f in analyzable_files)
    pass1_output = n_files * output_per_file
    p1_pricing = PRICING[pass1_model]
    pass1_cost = (pass1_input * p1_pricing["input"] + pass1_output * p1_pricing["output"]) / 1_000_000

    # Pass 2: Cross-file (one call with all summaries)
    pass2_input = n_files * 200 + 2000  # ~200 tokens per file summary + prompt
    pass2_output = 5000
    p2_pricing = PRICING[pass2_model]
    pass2_cost = (pass2_input * p2_pricing["input"] + pass2_output * p2_pricing["output"]) / 1_000_000

    # Pass 3: Architecture (one call)
    pass3_input = 10000
    pass3_output = 3000
    pass3_cost = (pass3_input * p2_pricing["input"] + pass3_output * p2_pricing["output"]) / 1_000_000

    total_cost = pass1_cost + pass2_cost + pass3_cost
    total_tokens = pass1_input + pass1_output + pass2_input + pass2_output + pass3_input + pass3_output

    # Time estimate: ~1 second per file with concurrency
    concurrent = config.MAX_CONCURRENT_CALLS
    estimated_seconds = max(1, (n_files // concurrent) * 2) + 10  # +10 for Pass 2/3

    warnings = []
    if n_files > 500:
        warnings.append(f"Large project ({n_files} files). Analysis may take several minutes.")
    if total_cost > 5.0:
        warnings.append(f"Estimated cost is ${total_cost:.2f}. Consider using 'fast' tier to reduce cost.")

    minified_count = sum(1 for f in manifest.files if f.is_minified)
    if minified_count > 0:
        warnings.append(f"{minified_count} minified files detected. These will be included in the tree but not deeply analyzed.")

    generated_count = sum(1 for f in manifest.files if f.is_generated)
    if generated_count > 0:
        warnings.append(f"{generated_count} generated code files detected. These will be skipped in AI analysis.")

    return {
        "total_files": n_files,
        "total_lines": manifest.total_lines,
        "estimated_tokens": total_tokens,
        "estimated_cost_usd": round(total_cost, 4),
        "estimated_time_seconds": estimated_seconds,
        "languages": manifest.languages,
        "model_tier": model_tier,
        "warnings": warnings,
    }
