"""Tests for the rey_loader single-file process-model workflow.

The approved implementation catalog and its handlers: discover_file binding a
single file or a no-file signal, sql_operation delegation to the DB utility
layer, file operations, validation, and etl_operation failing closed (never
re-running the batch).
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rey_lib.config.applications import (
    Application,
    ApplicationCommand,
    ApplicationCommandParameter,
)

from tests.support.workflow_publication import prepared

from rey_lib.load import load_operation
from rey_lib.workflow import RunContext, StepResult

from rey_loader.error_utils import ReyLoaderError
from rey_loader.workflow import (
    _process_etl_operation,
    _process_file_operation,
    _process_sql_operation,
    _process_validate,
    build_process_registry,
)


class _NS:
    """Attribute namespace for config/ctx-shaped test inputs."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _workflow(*steps, processes=None):
    """One workflow whose processes bind to same-named published operations."""
    processes = processes or _NS(
        file_operation=_NS(implementation="file_operation"),
        sql_operation=_NS(implementation="sql_operation"),
        validate=_NS(implementation="validate"),
        etl_operation=_NS(implementation="etl_operation"),
    )
    return _NS(name="w", app="rey_loader", processes=processes, steps=list(steps))


def _publishing(*names: str, **parameters):
    """An application publishing these operations, with the settings named.

    The fixtures configure a marker and an operation; publication has to declare
    them or validation refuses the step, which is the contract working rather
    than a fixture detail.
    """
    return (
        Application(
            name="rey_loader",
            workflow_operations=tuple(
                ApplicationCommand(
                    name=name,
                    parameters=tuple(
                        ApplicationCommandParameter(name=one)
                        for one in ("marker", "operation", "scope", "id")
                    ),
                )
                for name in names
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Registry + detection
# ---------------------------------------------------------------------------

def test_build_process_registry_exposes_generic_groups():
    registry = build_process_registry(object())
    assert set(registry) == {
        "file_operation", "sql_operation", "validate", "etl_operation",
        "transform_files", "load_files", "validate_load", "sql_apply",
        # The inventory_and_prepare_files replacement (row 589).
        "inventory_source_files", "classify_source_files", "excel_conversion",
        "sanitize_file", "profile_csv_record_types", "create_prepared_files",
    }


# ---------------------------------------------------------------------------
# sql_operation delegates to the DB utility layer
# ---------------------------------------------------------------------------

def test_sql_operation_delegates_to_db_utils(run_log):
    ctx = _NS()
    config = {"operation": "execute_parameter_result", "procedure_map": "control",
              "connection": "control", "routine_binding": "start_batch",
              "params": {"batch_name": "B"}}
    adapter = MagicMock()
    with patch("rey_loader.workflow.shared_connection") as shared, \
         patch("rey_loader.workflow.get_procedure_map") as get_map, \
         patch("rey_loader.workflow.ProcedureMap") as procedure_map:
        shared.return_value.handle.return_value = "conn"
        result = _process_sql_operation(ctx, run_log, config, RunContext(), adapter)
    # The action resolves once from the named map, then executes (backlog 822).
    args, _ = procedure_map.resolve.call_args
    assert args == ("conn", get_map.return_value, "control", "start_batch")
    call_args, call_kwargs = procedure_map.resolve.return_value.call.call_args
    assert call_args == ("conn", {"batch_name": "B"}, run_log)
    assert call_kwargs.get("run_ctx") is ctx
    assert result.status == "ok"


def test_sql_operation_resolves_the_connection_the_step_names(run_log):
    """The step chooses the database; the procedure map is a routine contract."""
    ctx = _NS()
    config = {"operation": "execute_parameter_result", "procedure_map": "control",
              "connection": "control_test", "routine_binding": "start_batch"}
    adapter = MagicMock()
    with patch("rey_loader.workflow.shared_connection") as shared, \
         patch("rey_loader.workflow.get_procedure_map"), \
         patch("rey_loader.workflow.ProcedureMap"):
        _process_sql_operation(ctx, run_log, config, RunContext(), adapter)
    # Taken by the name the step gave, not by the map's name. It is the shared
    # object, so the step opens nothing of its own.
    assert shared.call_args[0][1] == "control_test"


def test_sql_operation_without_a_connection_fails_closed(run_log):
    """A map no longer answers which database, so the step must say."""
    config = {"operation": "execute_parameter_result", "procedure_map": "control",
              "routine_binding": "start_batch"}
    with pytest.raises(ReyLoaderError, match="missing 'connection'"):
        _process_sql_operation(_NS(), run_log, config, RunContext(), MagicMock())


def test_sql_operation_unsupported_operation_fails_closed(run_log):
    with pytest.raises(ReyLoaderError, match="unsupported operation"):
        _process_sql_operation(_NS(), run_log, {"operation": "nope"}, RunContext(), MagicMock())


# ---------------------------------------------------------------------------
# file_operation
# ---------------------------------------------------------------------------

def test_discover_file_binds_a_single_file(run_log, tmp_path):
    (tmp_path / "tran_1.csv").write_text("x")
    (tmp_path / "tran_2.csv").write_text("y")
    ds = _NS(name="advantage", paths=_NS(inbox_path=str(tmp_path)))
    ctx = _NS(data_sources=[ds])
    config = {"operation": "discover_file", "data_source": "advantage",
              "path": "inbox_path", "pattern": "tran_*.csv",
              "output": {"current_file": "current_file"}}
    result = _process_file_operation(ctx, run_log, config, RunContext(metadata={}))
    assert result.status == "ok"
    assert Path(ctx.current_file).name == "tran_1.csv"   # single, first in order
    assert ctx.no_file is False


def test_discover_file_no_file_sets_flag(run_log, tmp_path):
    ds = _NS(name="advantage", paths=_NS(inbox_path=str(tmp_path)))
    ctx = _NS(data_sources=[ds])
    config = {"operation": "discover_file", "data_source": "advantage",
              "path": "inbox_path", "pattern": "tran_*.csv",
              "output": {"current_file": "current_file"}}
    result = _process_file_operation(ctx, run_log, config, RunContext(metadata={}))
    assert result.status == "ok" and result.detail == "no file"
    assert ctx.no_file is True and ctx.current_file is None


def test_file_operation_move_uses_destination_key(run_log, tmp_path):
    ds = _NS(name="advantage", paths=_NS(processing_path=str(tmp_path / "proc")))
    ctx = _NS(data_sources=[ds], current_file=str(tmp_path / "f.csv"))
    config = {"operation": "move", "data_source": "advantage", "to": "processing_path"}
    with patch("rey_loader.workflow.move_file",
               return_value=tmp_path / "proc" / "f.csv") as mv:
        result = _process_file_operation(ctx, run_log, config, RunContext())
    mv.assert_called_once()
    assert result.status == "ok" and ctx.current_file.endswith("proc/f.csv")


def test_file_operation_delete_refuses_missing_current_file(run_log):
    ctx = _NS(data_sources=[])
    with pytest.raises(ReyLoaderError, match="no current file"):
        _process_file_operation(ctx, run_log, {"operation": "delete", "data_source": "advantage"},
                                RunContext())


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def test_validate_delimited_header_uses_header_validation(run_log, tmp_path):
    f = tmp_path / "f.csv"
    f.write_text("a,b,c\n1,2,3\n")
    ds = _NS(name="advantage", transforms=[_NS(file_type="delimited_header")])
    ctx = _NS(data_sources=[ds], current_file=str(f))
    with patch("rey_lib.files.file_loader._validate_header", return_value=True) as vh:
        result = _process_validate(ctx, run_log, {"operation": "validate_file",
                                         "data_source": "advantage"}, RunContext(metadata={}))
    vh.assert_called_once()
    assert result.status == "ok" and ctx.validation_status == "ok"


def test_validate_unsupported_file_type_fails_closed(run_log, tmp_path):
    f = tmp_path / "f.csv"
    f.write_text("x")
    ds = _NS(name="advantage", transforms=[_NS(file_type="mystery")])
    ctx = _NS(data_sources=[ds], current_file=str(f))
    with pytest.raises(ReyLoaderError, match="unsupported file_type"):
        _process_validate(ctx, run_log, {"operation": "validate_file", "data_source": "advantage"},
                          RunContext(metadata={}))


# ---------------------------------------------------------------------------
# etl_operation delegates to the public per-file APIs (never the batch runners)
# ---------------------------------------------------------------------------

def test_etl_transform_calls_transform_one_with_current_file(run_log):
    ctx = _NS(current_file="/x/f.csv", data_sources=[_NS(name="advantage")])
    with patch("rey_loader.workflow.transform_one", return_value=True) as t1:
        result = _process_etl_operation(ctx, run_log, {"operation": "transform_file",
                                              "data_source": "advantage"},
                                        RunContext(metadata={}))
    args = t1.call_args[0]
    assert str(args[3]).endswith("f.csv")   # the single current file
    assert result.status == "ok"


def test_etl_load_calls_load_one_with_current_file(run_log):
    """autospec, so the mock enforces load_one's REAL signature.

    Without it a plain MagicMock accepts any arity, and this test passed for
    a call that could never run: load_one takes (ctx, run_log, data_source,
    load_cfg, file_path) and was being given four arguments with run_log
    dropped. The assertion had been copied from the transform_one test, where
    index 3 IS the file -- here index 3 is load_cfg, so the wrong position
    agreed with the wrong call and both looked right.

    The file is asserted by KEYWORD below rather than by position, so a
    future argument cannot make this agree with a mistake again.
    """
    ds = _NS(name="advantage", loads=[_NS(name="ld")])
    ctx = _NS(current_file="/x/f.csv", data_sources=[ds])
    with patch("rey_loader.workflow.load_one", autospec=True,
               return_value=42) as l1:
        result = _process_etl_operation(ctx, run_log, {"operation": "load_file",
                                              "data_source": "advantage"},
                                        RunContext(metadata={}))

    bound = inspect.signature(load_operation.load_one).bind(*l1.call_args[0],
                                                         **l1.call_args[1])
    assert str(bound.arguments["file_path"]).endswith("f.csv")
    assert bound.arguments["run_log"] is run_log
    assert result.status == "ok" and "42" in result.detail


def test_etl_never_calls_the_batch_runners(run_log):
    ctx = _NS(current_file="/x/f.csv", data_sources=[_NS(name="advantage")])
    with patch("rey_loader.workflow.transform_one", return_value=True), \
         patch("rey_lib.files.file_loader.run_transform",
               side_effect=AssertionError("batch runner must not be called")), \
         patch("rey_lib.load.load_operation.run_load",
               side_effect=AssertionError("batch runner must not be called")):
        _process_etl_operation(ctx, run_log, {"operation": "transform_file",
                                     "data_source": "advantage"}, RunContext(metadata={}))


def test_etl_transform_rejected_fails_closed(run_log):
    ctx = _NS(current_file="/x/f.csv", data_sources=[_NS(name="advantage")])
    with patch("rey_loader.workflow.transform_one", return_value=False):
        with pytest.raises(ReyLoaderError, match="rejected"):
            _process_etl_operation(ctx, run_log, {"operation": "transform_file",
                                         "data_source": "advantage"}, RunContext(metadata={}))


def test_etl_unsupported_operation_fails_closed(run_log):
    ctx = _NS(current_file="/x/f.csv", data_sources=[_NS(name="advantage")])
    with pytest.raises(ReyLoaderError, match="unsupported operation"):
        _process_etl_operation(ctx, run_log, {"operation": "nope", "data_source": "advantage"},
                               RunContext(metadata={}))
