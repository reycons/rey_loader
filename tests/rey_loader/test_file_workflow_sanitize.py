"""The Loader's sanitize_file process (row 589, step 4).

A thin handler: it calls the Loader-owned sanitization in rey_lib and reports
the same StepResult the legacy file_operator step reported.
"""

from __future__ import annotations

from unittest.mock import patch

from rey_lib.load.sanitize import FileSanitizationBatchResult
from rey_lib.workflow import RunContext

from rey_loader import workflow
from rey_loader.registration import WORKFLOW_OPERATIONS
from rey_loader.workflow import build_process_registry


def _run(run_log, *, apply: bool, selected: int):
    batch = FileSanitizationBatchResult(selected=selected, sanitized=0, results=())
    with patch.object(workflow, "run_file_sanitization", return_value=batch) as step:
        result = build_process_registry(object())["sanitize_file"](
            object(), run_log, {"feed": "all"}, RunContext(apply=apply))
    return result, step


def test_an_applied_run_reports_what_it_sanitized(run_log) -> None:
    result, step = _run(run_log, apply=True, selected=3)

    assert (result.status, result.detail) == ("ok", "Sanitized 3 governed file(s).")
    assert step.call_args.kwargs["apply"] is True


def test_a_dry_run_reports_what_it_would_sanitize(run_log) -> None:
    result, step = _run(run_log, apply=False, selected=2)

    assert (result.status, result.detail) == ("ok", "Would sanitize 2 governed file(s).")
    assert step.call_args.kwargs["apply"] is False


def test_the_operation_is_published_with_the_legacy_contract() -> None:
    published = {op["name"]: op for op in WORKFLOW_OPERATIONS}["sanitize_file"]

    assert [(p["name"], p["required"], p["value_type"]) for p in published["parameters"]] == [
        ("file_selection", True, "mapping"),
        ("outbox", True, "mapping"),
        ("sanitization", True, "mapping"),
        ("feed", True, "string"),
        ("scope", False, "string"),
    ]
