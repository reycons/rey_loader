"""Tests for rey_loader public command dispatch."""

from __future__ import annotations

from argparse import Namespace
from unittest.mock import Mock, patch

import main as loader_main


def test_legacy_stage_mapping_is_removed() -> None:
    assert not hasattr(loader_main, "_VALID_STAGES")
    assert not hasattr(loader_main, "_STAGE_TO_WORKFLOW")


def test_transform_command_runs_transform_without_workflow() -> None:
    args = Namespace(command="transform", dry_run=False, source="", workflow=None)
    log = Mock()

    with patch.object(loader_main, "run_transform", return_value=1) as transform, \
         patch.object(loader_main, "run_process_workflow") as workflow:
        assert loader_main._run_app_command(object(), args, True, log) == 0

    transform.assert_called_once()
    workflow.assert_not_called()


def test_sql_command_runs_sql_without_workflow() -> None:
    ctx = object()
    args = Namespace(command="sql", dry_run=False, source="apply_sql", workflow=None)
    log = Mock()

    with patch.object(loader_main, "run_sql_apply") as sql_apply, \
         patch.object(loader_main, "run_process_workflow") as workflow:
        assert loader_main._run_app_command(ctx, args, True, log) == 0

    sql_apply.assert_called_once_with(ctx, "apply_sql")
    workflow.assert_not_called()


def test_run_workflow_uses_explicit_workflow_name() -> None:
    ctx = object()
    args = Namespace(command="run-workflow", workflow="transform_only", source="")

    with patch.object(loader_main, "needs_file_loop", return_value=False), \
         patch.object(loader_main, "run_process_workflow", return_value=0) as workflow:
        assert loader_main._run_workflow_command(ctx, args, True) == 0

    assert workflow.call_args.args[2] == "transform_only"
