"""The Loader's excel_conversion process (row 589, step 3).

A thin handler: it refuses what the legacy handler refused, calls the
Loader-owned conversion in rey_lib, and reports the same StepResult the legacy
file_operator step reported.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from rey_lib.load.convert import ConversionError
from rey_lib.workflow import RunContext

from rey_loader import workflow
from rey_loader.registration import WORKFLOW_OPERATIONS
from rey_loader.workflow import build_process_registry


def _run(run_log, config: dict, *, apply: bool = True, code: int = 0):
    with patch.object(workflow, "run_excel_conversion", return_value=code) as step:
        result = build_process_registry(object())["excel_conversion"](
            object(), run_log, config, RunContext(apply=apply))
    return result, step


def test_a_completed_conversion_is_ok(run_log) -> None:
    result, step = _run(run_log, {"name": "all"})

    assert (result.status, result.detail) == ("ok", "inline configuration")
    assert step.call_args.kwargs["apply"] is True


def test_a_nonzero_exit_code_fails_the_step(run_log) -> None:
    result, _ = _run(run_log, {"name": "all"}, code=3)

    assert (result.status, result.detail) == (
        "failed", "Excel conversion returned exit code 3.")


def test_the_dry_run_boundary_is_forwarded(run_log) -> None:
    _, step = _run(run_log, {"name": "all"}, apply=False)

    assert step.call_args.kwargs["apply"] is False


@pytest.mark.parametrize(("config", "message"), [
    ({"config_ref": "x"}, "does not support config_ref"),
    ({}, "requires inline configuration"),
])
def test_the_legacy_configuration_refusals_are_kept(
    run_log, config: dict, message: str,
) -> None:
    with pytest.raises(ConversionError, match=message):
        _run(run_log, config)


def test_the_operation_is_published_with_the_legacy_contract() -> None:
    published = {op["name"]: op for op in WORKFLOW_OPERATIONS}["excel_conversion"]

    assert [(p["name"], p["required"], p["value_type"]) for p in published["parameters"]] == [
        ("file_selection", True, "mapping"),
        ("outbox", True, "mapping"),
        ("processing", False, "mapping"),
        ("archive", False, "mapping"),
        ("name", False, "string"),
        ("enabled", False, "flag"),
        ("include_hidden_sheets", False, "flag"),
        ("include_empty_sheets", False, "flag"),
        ("scope", False, "string"),
    ]
