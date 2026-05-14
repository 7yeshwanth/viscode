"""
VisCode Post-Validator

Validates AI analysis output against ground truth (regex-extracted identifiers).
Removes hallucinated elements, fixes line numbers, logs corrections.
"""

from __future__ import annotations

import logging
from models.analysis import FileAnalysis, GroundTruth, IdentifierKind

logger = logging.getLogger("viscode.validator")


def validate_analysis(
    ai_output: FileAnalysis,
    ground_truth: GroundTruth,
) -> tuple[FileAnalysis, list[str]]:
    """
    Validate AI analysis against ground truth.

    - Removes functions/classes not found in ground truth
    - Fixes line numbers that are way off
    - Logs all corrections

    Args:
        ai_output: The AI-generated file analysis.
        ground_truth: Regex-extracted identifiers (source of truth).

    Returns:
        (corrected_analysis, list_of_corrections)
    """
    corrections: list[str] = []

    # Build ground truth lookup
    gt_names = {i.name for i in ground_truth.identifiers}
    gt_by_name: dict[str, list] = {}
    for ident in ground_truth.identifiers:
        gt_by_name.setdefault(ident.name, []).append(ident)

    # --- Validate Functions ---
    valid_functions = []
    for func in ai_output.functions:
        if func.name in gt_names:
            # Check line numbers
            func = _fix_line_numbers(func, gt_by_name, corrections)
            valid_functions.append(func)
        else:
            corrections.append(f"REMOVED hallucinated function: '{func.name}'")
    ai_output.functions = valid_functions

    # --- Validate Classes ---
    valid_classes = []
    for cls in ai_output.classes:
        if cls.name in gt_names:
            cls = _fix_line_numbers(cls, gt_by_name, corrections)

            # Validate methods within class
            gt_methods = set()
            for ident in ground_truth.identifiers:
                if ident.parent == cls.name and ident.kind == IdentifierKind.METHOD:
                    gt_methods.add(ident.name)

            valid_methods = []
            for method in cls.methods:
                if method.name in gt_methods or method.name in gt_names:
                    method = _fix_line_numbers(method, gt_by_name, corrections)
                    valid_methods.append(method)
                else:
                    corrections.append(f"REMOVED hallucinated method: '{cls.name}.{method.name}'")
            cls.methods = valid_methods

            valid_classes.append(cls)
        else:
            corrections.append(f"REMOVED hallucinated class: '{cls.name}'")
    ai_output.classes = valid_classes

    # --- Validate Endpoints (lighter check — AI may identify routes not caught by regex) ---
    # Keep all endpoints but log if handler function doesn't exist
    for ep in ai_output.endpoints:
        if ep.handler_function and ep.handler_function not in gt_names:
            corrections.append(
                f"WARNING: endpoint {ep.method} {ep.route} references unknown handler '{ep.handler_function}'"
            )

    # --- Validate Variables ---
    valid_vars = []
    for var in ai_output.variables:
        if var.name in gt_names:
            valid_vars.append(var)
        else:
            # AI might identify variables regex missed — keep but flag
            var.description = f"[AI-identified] {var.description}"
            valid_vars.append(var)
            corrections.append(f"NOTE: variable '{var.name}' not in ground truth, kept with flag")
    ai_output.variables = valid_vars

    # --- Log summary ---
    if corrections:
        logger.info(
            f"Validated {ai_output.file_path}: "
            f"{len(corrections)} corrections made"
        )
        for c in corrections:
            logger.debug(f"  → {c}")

    return ai_output, corrections


def _fix_line_numbers(element, gt_by_name: dict, corrections: list[str]):
    """Fix element line numbers using ground truth if they're way off."""
    if not hasattr(element, "line_start") or not hasattr(element, "name"):
        return element

    gt_entries = gt_by_name.get(element.name, [])
    if not gt_entries:
        return element

    # Find the closest ground truth entry
    gt = gt_entries[0]
    for g in gt_entries:
        if hasattr(element, "line_start") and element.line_start > 0:
            if abs(g.line_start - element.line_start) < abs(gt.line_start - element.line_start):
                gt = g

    # Fix line_start if off by more than 5 lines
    if element.line_start > 0 and abs(element.line_start - gt.line_start) > 5:
        corrections.append(
            f"FIXED line_start for '{element.name}': "
            f"AI said {element.line_start}, actual is {gt.line_start}"
        )
        element.line_start = gt.line_start

    if gt.line_end and hasattr(element, "line_end"):
        element.line_end = gt.line_end

    return element
