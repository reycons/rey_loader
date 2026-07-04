"""
Tests for rey_loader internal ETL workflows via the shared coordinator.

The private ``run_steps`` engine was retired
(SGC_Rey_Loader_Workflow_Coordinator_Alignment); these tests prove the migrated
batch workflows preserve the same behaviour through ``rey_lib.workflow.run_workflow``:
step order, fail-closed stop, dry-run apply_only skipping, return codes, and
unchanged transform output (run_load mocked so no database is touched).
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from rey_lib.workflow import run_workflow as coordinate_workflow

from rey_loader.error_utils import ReyLoaderError
from rey_loader.workflow import build_process_registry, run_process_workflow

from tests.conftest import write_advantage_csv


def _transform_load() -> dict:
    """The transform_load workflow in the shared process/step shape."""
    return {
        "name": "transform_load",
        "processes": {
            "transform_files": {},
            "load_files": {"apply_only": True},
            "validate_load": {},
        },
        "steps": [
            {"id": "transform_files", "label": "Transform files", "process": "transform_files"},
            {"id": "load_files", "label": "Load files", "process": "load_files"},
            {"id": "validate_load", "label": "Validate load", "process": "validate_load"},
        ],
    }


def _attach_workflows(ctx: Namespace) -> Namespace:
    """Attach the internal process-shaped workflow definitions to a test ctx.

    ctx.workflows items are attribute-accessed by rey_loader, so use Namespace
    (mirroring resolved config), with dict processes/steps the coordinator reads.
    """
    object.__setattr__(ctx, "workflows", [
        Namespace(**_transform_load()),
        Namespace(
            name="transform_only",
            processes={"transform_files": {}},
            steps=[{"id": "transform_files", "label": "Transform files",
                    "process": "transform_files"}],
        ),
    ])
    return ctx


def _converted(ctx: Namespace) -> Path:
    return ctx.data_sources[0].paths.converted_path


def _inbox(ctx: Namespace) -> Path:
    return ctx.data_sources[0].paths.inbox_path


# ---------------------------------------------------------------------------
# Coordinator mechanics (inspecting the WorkflowRun directly)
# ---------------------------------------------------------------------------

def test_steps_run_in_order_and_record_metadata(ctx: Namespace) -> None:
    """transform_files -> load_files -> validate_load, recording run metadata."""
    write_advantage_csv(_inbox(ctx), "tran_20260501.csv")
    registry = build_process_registry(object())

    with patch("rey_loader.workflow.run_load", return_value=7) as mock_load:
        run = coordinate_workflow(ctx, _transform_load(), registry, apply=True)

    assert run.status == "success"
    assert [o.id for o in run.outcomes] == ["transform_files", "load_files", "validate_load"]
    assert run.context.metadata["loaded_rows"] == 7
    assert run.context.metadata["validation_result"] == "7 row(s) loaded"
    mock_load.assert_called_once_with(ctx)


def test_fail_closed_stops_at_failing_step(ctx: Namespace) -> None:
    """A failing load stops the workflow; validate_load never runs."""
    write_advantage_csv(_inbox(ctx), "tran_20260501.csv")
    registry = build_process_registry(object())

    with patch("rey_loader.workflow.run_load", side_effect=RuntimeError("db down")):
        run = coordinate_workflow(ctx, _transform_load(), registry, apply=True)

    assert run.status == "failed"
    assert [o.status for o in run.outcomes] == ["ok", "failed"]
    assert "validation_result" not in run.context.metadata


def test_dry_run_skips_load_but_transforms(ctx: Namespace) -> None:
    """Dry-run skips the apply_only load step; transform still runs."""
    converted = _converted(ctx)
    write_advantage_csv(_inbox(ctx), "tran_20260501.csv")
    registry = build_process_registry(object())

    with patch("rey_loader.workflow.run_load") as mock_load:
        run = coordinate_workflow(ctx, _transform_load(), registry, apply=False)

    assert run.status == "success"
    mock_load.assert_not_called()
    assert run.context.metadata["validation_result"] == "skipped (load not applied)"
    assert list(converted.glob("tran_20260501_v01.csv")), "transform must still run"


# ---------------------------------------------------------------------------
# run_process_workflow runner (config lookup + exit codes)
# ---------------------------------------------------------------------------

def test_transform_only_succeeds(ctx: Namespace) -> None:
    """transform_only runs transform and returns 0."""
    _attach_workflows(ctx)
    converted = _converted(ctx)
    write_advantage_csv(_inbox(ctx), "tran_20260501.csv")
    assert run_process_workflow(ctx, object(), "transform_only", apply=True) == 0
    assert list(converted.glob("tran_20260501_v01.csv"))


def test_failure_returns_one(ctx: Namespace) -> None:
    """A failing step makes the runner return 1 (fail-closed)."""
    _attach_workflows(ctx)
    write_advantage_csv(_inbox(ctx), "tran_20260501.csv")
    with patch("rey_loader.workflow.run_load", side_effect=RuntimeError("x")):
        assert run_process_workflow(ctx, object(), "transform_load", apply=True) == 1


def test_unknown_workflow_raises(ctx: Namespace) -> None:
    """An unknown workflow name fails closed with a clear error."""
    _attach_workflows(ctx)
    with pytest.raises(ReyLoaderError, match="not found"):
        run_process_workflow(ctx, object(), "does_not_exist")


# ---------------------------------------------------------------------------
# Transform output must be unchanged by the migration
# ---------------------------------------------------------------------------

def test_workflow_transform_output_matches_expected(ctx: Namespace) -> None:
    """Running transform via the coordinator yields the same converted rows."""
    import csv

    converted = _converted(ctx)
    write_advantage_csv(_inbox(ctx), "tran_20260501.csv")
    registry = build_process_registry(object())
    workflow = {
        "name": "transform_only",
        "processes": {"transform_files": {}},
        "steps": [{"id": "transform_files", "label": "Transform files",
                   "process": "transform_files"}],
    }

    run = coordinate_workflow(ctx, workflow, registry, apply=True)

    assert run.status == "success"
    matches = sorted(converted.glob("tran_20260501_v01.csv"))
    assert matches, "no converted output"
    with matches[0].open(encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    assert rows, "no output rows"
    for row in rows:
        assert row.get("broker") == "advantage"
        assert row.get("record_source") == "CSV Import"
        assert "2026" in row.get("trade_date", "")
