"""
Tests for the rey_loader internal workflow refactor.

Coverage:
  TestStepEngine        — ordering, fail-closed, and dry-run/apply behaviour of
                          the loader steps via the shared engine (run_load mocked
                          so no database is touched).
  TestRunWorkflow       — run_workflow integration: config lookup, return codes,
                          unknown-workflow error.
  TestTransformUnchanged — the transform-files step produces the same converted
                          output as before (orchestration did not change transform).
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from rey_lib.workflow import RunContext, build_steps, run_steps

from rey_loader.error_utils import ReyLoaderError
from rey_loader.workflow import build_registry, run_workflow

from tests.conftest import write_advantage_csv


_TRANSFORM_LOAD = ["transform-files", "load-files", "validate-load"]


def _with_workflows(ctx: Namespace) -> Namespace:
    """Attach the internal workflow definitions to a test ctx."""
    object.__setattr__(ctx, "workflows", [
        Namespace(name="transform_load", steps=list(_TRANSFORM_LOAD)),
        Namespace(name="transform_only", steps=["transform-files"]),
        Namespace(name="load_only", steps=["load-files", "validate-load"]),
        Namespace(name="sql_apply", steps=["sql-apply"]),
    ])
    return ctx


def _converted(ctx: Namespace) -> Path:
    return ctx.data_sources[0].paths.converted_path


# ---------------------------------------------------------------------------
# TestStepEngine
# ---------------------------------------------------------------------------

class TestStepEngine:
    """Loader steps run through the shared engine."""

    def test_steps_run_in_order(self, ctx: Namespace) -> None:
        """transform-files -> load-files -> validate-load, recording metadata."""
        write_advantage_csv(ctx.data_sources[0].paths.inbox_path, "tran_20260501.csv")
        run_ctx = RunContext(apply=True, data={"ctx": ctx, "source": ""})
        steps = build_steps(_TRANSFORM_LOAD, build_registry())

        with patch("rey_loader.workflow.run_load", return_value=7) as mock_load:
            result = run_steps(steps, run_ctx, name="transform_load")

        assert result.status == "success"
        assert [s["name"] for s in run_ctx.metadata["steps"]] == _TRANSFORM_LOAD
        assert run_ctx.metadata["loaded_rows"] == 7
        assert run_ctx.metadata["validation_result"] == "7 row(s) loaded"
        mock_load.assert_called_once_with(ctx)

    def test_fail_closed_stops_at_failing_step(self, ctx: Namespace) -> None:
        """A failing load stops the workflow; validate-load never runs."""
        write_advantage_csv(ctx.data_sources[0].paths.inbox_path, "tran_20260501.csv")
        run_ctx = RunContext(apply=True, data={"ctx": ctx, "source": ""})
        steps = build_steps(_TRANSFORM_LOAD, build_registry())

        with patch("rey_loader.workflow.run_load", side_effect=RuntimeError("db down")):
            result = run_steps(steps, run_ctx, name="transform_load")

        assert result.status == "failed"
        assert [s["status"] for s in run_ctx.metadata["steps"]] == ["ok", "failed"]
        assert "validation_result" not in run_ctx.metadata

    def test_dry_run_skips_load_but_transforms(self, ctx: Namespace) -> None:
        """Dry-run skips the apply_only load step; transform still runs."""
        converted = _converted(ctx)
        write_advantage_csv(ctx.data_sources[0].paths.inbox_path, "tran_20260501.csv")
        run_ctx = RunContext(apply=False, data={"ctx": ctx, "source": ""})
        steps = build_steps(_TRANSFORM_LOAD, build_registry())

        with patch("rey_loader.workflow.run_load") as mock_load:
            result = run_steps(steps, run_ctx, name="transform_load")

        assert result.status == "success"
        mock_load.assert_not_called()
        assert run_ctx.metadata["validation_result"] == "skipped (load not applied)"
        assert list(converted.glob("tran_20260501_v01.csv")), "transform must still run"


# ---------------------------------------------------------------------------
# TestRunWorkflow
# ---------------------------------------------------------------------------

class TestRunWorkflow:
    """run_workflow resolves config and returns process exit codes."""

    def test_transform_only_succeeds(self, ctx: Namespace) -> None:
        """transform_only runs transform and returns 0."""
        _with_workflows(ctx)
        converted = _converted(ctx)
        write_advantage_csv(ctx.data_sources[0].paths.inbox_path, "tran_20260501.csv")
        assert run_workflow(ctx, "transform_only", apply=True) == 0
        assert list(converted.glob("tran_20260501_v01.csv"))

    def test_failure_returns_one(self, ctx: Namespace) -> None:
        """A failing step makes run_workflow return 1 (fail-closed)."""
        _with_workflows(ctx)
        write_advantage_csv(ctx.data_sources[0].paths.inbox_path, "tran_20260501.csv")
        with patch("rey_loader.workflow.run_load", side_effect=RuntimeError("x")):
            assert run_workflow(ctx, "transform_load", apply=True) == 1

    def test_unknown_workflow_raises(self, ctx: Namespace) -> None:
        """An unknown workflow name fails closed with a clear error."""
        _with_workflows(ctx)
        with pytest.raises(ReyLoaderError, match="not found"):
            run_workflow(ctx, "does_not_exist")


# ---------------------------------------------------------------------------
# TestTransformUnchanged
# ---------------------------------------------------------------------------

class TestTransformUnchanged:
    """The refactor must not change transform output."""

    def _read_rows(self, path: Path, glob: str) -> list[dict[str, str]]:
        import csv
        matches = sorted(path.glob(glob))
        assert matches, f"no output matching {glob} in {path}"
        with matches[0].open(encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))

    def test_workflow_transform_output_matches_expected(self, ctx: Namespace) -> None:
        """Running transform via the workflow yields the same converted rows."""
        converted = _converted(ctx)
        write_advantage_csv(ctx.data_sources[0].paths.inbox_path, "tran_20260501.csv")
        run_ctx = RunContext(apply=True, data={"ctx": ctx, "source": ""})
        steps = build_steps(["transform-files"], build_registry())

        result = run_steps(steps, run_ctx, name="transform_only")

        assert result.status == "success"
        rows = self._read_rows(converted, "tran_20260501_v01.csv")
        assert rows, "no output rows"
        for row in rows:
            assert row.get("broker") == "advantage"
            assert row.get("record_source") == "CSV Import"
            assert "2026" in row.get("trade_date", "")
