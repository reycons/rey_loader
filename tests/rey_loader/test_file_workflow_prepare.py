"""The Loader's create_prepared_files process (row 589, step 6).

A thin handler: it calls the Loader-owned preparation in rey_lib and reports
the StepResult texts and status rule the legacy file_operator step reported.
"""

from __future__ import annotations

from unittest.mock import patch

from rey_lib.load.prepare import CreatePreparedFilesBatchResult, PreparedFileResult
from rey_lib.workflow import RunContext

from rey_loader import workflow
from rey_loader.registration import WORKFLOW_OPERATIONS
from rey_loader.workflow import build_process_registry


def _item(*, failed: bool = False) -> PreparedFileResult:
    return PreparedFileResult(
        file_id=7, source_path="/data/bny/work/sanitized_csv/a.csv",
        prepared_path="" if failed else "/data/bny/work/prepared/a.csv",
        included_rows=0 if failed else 2, header_mapping=(),
        applied=not failed, status="failed" if failed else "success",
        reason="no profile" if failed else "",
    )


def _run(run_log, items: tuple[PreparedFileResult, ...], *, apply: bool = True):
    batch = CreatePreparedFilesBatchResult(
        selected=len(items),
        prepared=sum(item.applied for item in items),
        failed=sum(item.status == "failed" for item in items),
        results=items,
    )
    with patch.object(workflow, "run_create_prepared_files", return_value=batch) as step:
        result = build_process_registry(object())["create_prepared_files"](
            object(), run_log, {"file_selection": {}}, RunContext(apply=apply))
    return result, step


def test_everything_prepared_is_ok(run_log) -> None:
    result, step = _run(run_log, (_item(), _item()))

    assert (result.status, result.detail) == ("ok", "Prepared 2 of 2 governed file(s).")
    assert step.call_args.kwargs["apply"] is True


def test_a_partial_success_is_ok_and_names_the_failure(run_log) -> None:
    result, _ = _run(run_log, (_item(), _item(failed=True)))

    assert result.status == "ok"
    assert result.detail == (
        "Prepared 1 of 2 governed file(s). 1 failed: "
        "/data/bny/work/sanitized_csv/a.csv: no profile"
    )


def test_nothing_prepared_fails_the_step(run_log) -> None:
    result, _ = _run(run_log, (_item(failed=True),))

    assert result.status == "failed"


def test_a_dry_run_says_would_prepare(run_log) -> None:
    item = _item()
    item = PreparedFileResult(**{**vars(item), "applied": False})
    result, step = _run(run_log, (item,), apply=False)

    assert result.detail == "Would prepare 0 of 1 governed file(s)."
    assert step.call_args.kwargs["apply"] is False


def test_the_operation_is_published_with_its_contract() -> None:
    """One implementation for both prepared files: ``output`` says which (614)."""
    published = {op["name"]: op for op in WORKFLOW_OPERATIONS}["create_prepared_files"]

    assert [(p["name"], p["required"], p["value_type"]) for p in published["parameters"]] == [
        ("file_selection", True, "mapping"),
        ("outbox", True, "mapping"),
        ("preparation", True, "mapping"),
        ("output", False, "choice"),
        ("scope", False, "string"),
    ]
