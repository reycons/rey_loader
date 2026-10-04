"""The Loader's classify_source_files process (row 589, step 2).

A thin handler: it calls the Loader-owned classification in rey_lib and reports
the same StepResult the legacy file_operator step reported.
"""

from __future__ import annotations

from unittest.mock import patch

from rey_lib.load.classify import SourceClassificationBatchResult
from rey_lib.workflow import RunContext

from rey_loader import workflow
from rey_loader.registration import WORKFLOW_OPERATIONS
from rey_loader.workflow import build_process_registry


def _run(run_log, candidates: int, classified: int):
    batch = SourceClassificationBatchResult(
        outcomes=(), candidates=candidates, classified=classified,
        rejected=candidates - classified,
    )
    with patch.object(workflow, "run_source_file_classification", return_value=batch):
        return build_process_registry(object())["classify_source_files"](
            object(), run_log, {"sources": []}, RunContext(apply=True))


def test_counts_are_reported(run_log) -> None:
    result = _run(run_log, 4, 3)

    assert (result.status, result.detail) == (
        "ok", "Classified 3 of 4 candidate(s); 1 rejected.")


def test_a_rejection_is_not_a_failure(run_log) -> None:
    assert _run(run_log, 4, 1).status == "ok"


def test_classifying_nothing_of_something_fails_the_step(run_log) -> None:
    assert _run(run_log, 2, 0).status == "failed"


def test_no_candidates_is_ok(run_log) -> None:
    assert _run(run_log, 0, 0).status == "ok"


def test_the_operation_is_published_with_the_legacy_contract() -> None:
    published = {op["name"]: op for op in WORKFLOW_OPERATIONS}["classify_source_files"]

    assert [(p["name"], p["required"]) for p in published["parameters"]] == [
        ("sources", True), ("scope", False),
    ]
