"""Offline, deterministic evaluation support for the fixed contract fixtures."""

from evaluation.runner import (
    EvaluationReport,
    evaluate_cases,
    load_cases,
    render_markdown_report,
)

__all__ = [
    "EvaluationReport",
    "evaluate_cases",
    "load_cases",
    "render_markdown_report",
]
