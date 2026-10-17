"""Tests for rey_loader public command dispatch."""

from __future__ import annotations

from argparse import Namespace
from unittest.mock import ANY, Mock, patch

import main as loader_main


def test_legacy_stage_mapping_is_removed() -> None:
    assert not hasattr(loader_main, "_VALID_STAGES")
    assert not hasattr(loader_main, "_STAGE_TO_WORKFLOW")


def test_transform_command_runs_transform(run_log) -> None:
    args = Namespace(command="transform", dry_run=False, source="")
    log = Mock()

    with patch.object(loader_main, "run_transform", return_value=1) as transform, \
         patch.object(loader_main, "run_app_operation",
                      side_effect=lambda _ctx, _run_log, _op, func, **_kw: func()) as lifecycle:
        assert loader_main._run_app_command(object(), run_log, args, True, log) == 0

    lifecycle.assert_called_once()
    assert lifecycle.call_args.args[2] == "transform"
    transform.assert_called_once()


def test_sql_command_runs_sql(run_log) -> None:
    ctx = object()
    args = Namespace(command="sql", dry_run=False, source="apply_sql")
    log = Mock()

    with patch.object(loader_main, "run_sql_apply") as sql_apply, \
         patch.object(loader_main, "run_app_operation",
                      side_effect=lambda _ctx, _run_log, _op, func, **_kw: func()) as lifecycle:
        assert loader_main._run_app_command(ctx, run_log, args, True, log) == 0

    lifecycle.assert_called_once()
    assert lifecycle.call_args.args[2] == "sql"
    sql_apply.assert_called_once_with(ctx, ANY, "apply_sql")


def test_a_command_records_what_it_was_invoked_with(run_log) -> None:
    """The run says what it was ASKED to do, not only what went wrong.

    A load refused for naming a table with no connection records the refusal
    and, without this, nothing about the arguments -- so the reader cannot see
    that --connection was empty, which is the whole explanation.
    """
    args = Namespace(command="load", dry_run=False, source="",
                     file="test", table="test", connection="", create=False)
    log = Mock()

    with patch.object(loader_main, "run_app_operation",
                      side_effect=lambda *_a, **kw: kw) as lifecycle:
        loader_main._run_app_command(object(), run_log, args, False, log)

    settings = lifecycle.call_args.kwargs["settings"]
    # The EMPTY one is the point: it is what explains a refusal.
    assert settings["connection"] == ""
    assert settings["table"] == "test"
    assert settings["file"] == "test"
    # Whether the run was allowed to change anything is the first thing to
    # know about one that did not.
    assert settings["apply"] is False
    # The operation is already recorded as the operation; repeating it as a
    # setting would be two answers to one question.
    assert "command" not in settings
