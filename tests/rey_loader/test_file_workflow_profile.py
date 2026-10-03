"""The Loader's profile_csv_record_types process (row 589, step 5).

A thin handler: it calls the Loader-owned profiling in rey_lib, supplies this
application's version as the profiler's, and reports the StepResult texts the
legacy file_operator step reported -- including that ANY unprofiled file fails
the step.
"""

from __future__ import annotations

from unittest.mock import patch

from rey_lib.load.profile import ProfilingBatchResult
from rey_lib.workflow import RunContext

from rey_loader import __version__, workflow
from rey_loader.registration import WORKFLOW_OPERATIONS
from rey_loader.workflow import build_process_registry


def _run(run_log, batch: ProfilingBatchResult, *, apply: bool = True):
    with patch.object(workflow, "run_record_type_profiling", return_value=batch) as step:
        result = build_process_registry(object())["profile_csv_record_types"](
            object(), run_log, {"file_selection": {}}, RunContext(apply=apply))
    return result, step


def _batch(**values) -> ProfilingBatchResult:
    held = {"records_read": 3, "selected": 3, "profiled": 3, "failures": (), "applied": True}
    held.update(values)
    return ProfilingBatchResult(**held)


def test_nothing_selected_is_ok(run_log) -> None:
    result, _ = _run(run_log, _batch(records_read=4, selected=0, profiled=0))

    assert (result.status, result.detail) == (
        "ok", "No source selected from 4 manifest record(s).")


def test_a_dry_run_reports_what_it_would_profile(run_log) -> None:
    result, step = _run(run_log, _batch(profiled=0, applied=False), apply=False)

    assert (result.status, result.detail) == (
        "ok",
        "Would profile 3 source(s) into the governed profile library; nothing written.",
    )
    assert step.call_args.kwargs["apply"] is False


def test_a_complete_run_is_ok(run_log) -> None:
    result, step = _run(run_log, _batch())

    assert (result.status, result.detail) == (
        "ok", "Profiled 3 of 3 source(s) into the governed profile library.")
    # The profiler's version is this application's own.
    assert step.call_args.kwargs["profiler_version"] == __version__


def test_any_unprofiled_file_fails_the_step(run_log) -> None:
    result, _ = _run(run_log, _batch(profiled=2, failures=("bad.csv: empty",)))

    assert result.status == "failed"
    assert result.detail == (
        "Profiled 2 of 3 source(s) into the governed profile library. "
        "1 not profiled: bad.csv: empty"
    )


def test_profiling_resolves_only_to_the_profiling_handler() -> None:
    """The binding can never resolve to a redacting preparation step."""
    registry = build_process_registry(object())

    assert registry["profile_csv_record_types"] is not registry.get("prepare_rule_set_inputs")
    assert "profile" in registry["profile_csv_record_types"].__name__


def test_the_operation_is_published_with_the_legacy_contract() -> None:
    published = {op["name"]: op for op in WORKFLOW_OPERATIONS}["profile_csv_record_types"]

    assert [(p["name"], p["required"], p["value_type"]) for p in published["parameters"]] == [
        ("file_selection", True, "mapping"),
        ("kickouts", False, "mapping"),
        ("scope", False, "string"),
    ]
