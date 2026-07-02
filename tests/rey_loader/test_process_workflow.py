"""Tests for the rey_loader process-model workflow spine.

Covers SGC_Rey_Loader_Workflow_Process_Model (additive spine): the generic
process registry, coordinator-once-per-file orchestration, sql_operation
delegation to the rey_lib DB utility layer, file_operation discover/move/delete,
validate file-type dispatch, and etl_operation failing closed (never re-running
the batch per file).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rey_lib.workflow import RunContext, StepResult

from rey_loader.error_utils import ReyLoaderError
from rey_loader.workflow import (
    _partition_by_scope,
    _process_etl_operation,
    _process_file_operation,
    _process_sql_operation,
    _process_validate,
    build_process_registry,
    is_process_workflow,
    run_process_workflow,
)


class _NS:
    """Attribute namespace for config/ctx-shaped test inputs."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


# ---------------------------------------------------------------------------
# Registry + detection + partition
# ---------------------------------------------------------------------------

def test_build_process_registry_exposes_generic_groups():
    registry = build_process_registry(object())
    assert set(registry) == {"file_operation", "sql_operation", "validate", "etl_operation"}


def test_is_process_workflow_detects_processes_block():
    ctx = _NS(workflows=[_NS(name="w", app="rey_loader", processes=_NS(x=1))])
    assert is_process_workflow(ctx, "w") is True
    ctx2 = _NS(workflows=[_NS(name="s", app="rey_loader", steps=[])])
    assert is_process_workflow(ctx2, "s") is False


def test_partition_by_scope_splits_prefix_perfile_suffix():
    steps = [_NS(id="a"), _NS(id="b", scope="file"), _NS(id="c", scope="file"), _NS(id="d")]
    prefix, per_file, suffix = _partition_by_scope(steps)
    assert [s.id for s in prefix] == ["a"]
    assert [s.id for s in per_file] == ["b", "c"]
    assert [s.id for s in suffix] == ["d"]


# ---------------------------------------------------------------------------
# Coordinator-once-per-file orchestration
# ---------------------------------------------------------------------------

def test_run_process_workflow_runs_coordinator_once_per_file():
    calls: list[tuple] = []

    def discover(ctx, config, run):
        object.__setattr__(ctx, "discovered_files", ["f1", "f2"])
        calls.append(("discover", None))
        return StepResult("d", "ok")

    def per_file(ctx, config, run):
        calls.append(("validate", getattr(ctx, "current_file", None)))
        return StepResult("v", "ok")

    def end_batch(ctx, config, run):
        calls.append(("end_batch", None))
        return StepResult("e", "ok")

    stub = {"file_operation": discover, "validate": per_file,
            "sql_operation": end_batch, "etl_operation": per_file}

    wf = _NS(
        name="w", app="rey_loader",
        processes=_NS(file_operation=_NS(), validate=_NS(), sql_operation=_NS(),
                      etl_operation=_NS()),
        steps=[
            _NS(id="discover_files", process="file_operation",
                config=_NS(operation="discover", output=_NS(files="discovered_files"))),
            _NS(id="validate_file", process="validate", scope="file",
                config=_NS(operation="validate_file")),
            _NS(id="end_batch", process="sql_operation",
                config=_NS(operation="execute_routine_binding")),
        ],
    )
    ctx = _NS(workflows=[wf])
    with patch("rey_loader.workflow.build_process_registry", return_value=stub):
        code = run_process_workflow(ctx, object(), "w", apply=True)

    assert code == 0
    assert calls == [("discover", None), ("validate", "f1"),
                     ("validate", "f2"), ("end_batch", None)]


# ---------------------------------------------------------------------------
# sql_operation delegates to the DB utility layer
# ---------------------------------------------------------------------------

def test_sql_operation_delegates_to_db_utils():
    ctx = _NS()
    config = {"operation": "execute_routine_binding", "procedure_map": "control",
              "routine_name": "start_batch", "values": {"batch_name": "B"}}
    adapter = MagicMock()
    with patch("rey_loader.workflow.get_connection_config", return_value="conn_cfg"), \
         patch("rey_loader.workflow.execute_mapped_routine") as emr:
        result = _process_sql_operation(ctx, config, RunContext(), adapter)
    args, kwargs = emr.call_args
    assert args[2] == "control" and args[3] == "start_batch"
    assert kwargs.get("run_ctx") is ctx
    assert result.status == "ok"


def test_sql_operation_unsupported_operation_fails_closed():
    with pytest.raises(ReyLoaderError, match="unsupported operation"):
        _process_sql_operation(_NS(), {"operation": "nope"}, RunContext(), MagicMock())


# ---------------------------------------------------------------------------
# file_operation
# ---------------------------------------------------------------------------

def test_file_operation_discover_resolves_path_and_stores_files(tmp_path):
    (tmp_path / "tran_1.csv").write_text("x")
    (tmp_path / "tran_2.csv").write_text("y")
    ds = _NS(name="advantage", paths=_NS(inbox_path=str(tmp_path)))
    ctx = _NS(data_sources=[ds])
    config = {"operation": "discover", "data_source": "advantage", "path": "inbox_path",
              "pattern": "tran_*.csv", "output": {"files": "discovered_files"}}
    result = _process_file_operation(ctx, config, RunContext(metadata={}))
    assert result.status == "ok"
    assert sorted(Path(f).name for f in ctx.discovered_files) == ["tran_1.csv", "tran_2.csv"]


def test_file_operation_move_uses_destination_key(tmp_path):
    ds = _NS(name="advantage", paths=_NS(processing_path=str(tmp_path / "proc")))
    ctx = _NS(data_sources=[ds], current_file=str(tmp_path / "f.csv"))
    config = {"operation": "move", "data_source": "advantage", "to": "processing_path"}
    with patch("rey_loader.workflow.move_file",
               return_value=tmp_path / "proc" / "f.csv") as mv:
        result = _process_file_operation(ctx, config, RunContext())
    mv.assert_called_once()
    assert result.status == "ok"
    assert ctx.current_file.endswith("proc/f.csv")


def test_file_operation_delete_refuses_missing_current_file():
    ctx = _NS(data_sources=[])
    with pytest.raises(ReyLoaderError, match="no current file"):
        _process_file_operation(ctx, {"operation": "delete", "data_source": "advantage"},
                                RunContext())


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def test_validate_delimited_header_uses_header_validation(tmp_path):
    f = tmp_path / "f.csv"
    f.write_text("a,b,c\n1,2,3\n")
    ds = _NS(name="advantage", transforms=[_NS(file_type="delimited_header")])
    ctx = _NS(data_sources=[ds], current_file=str(f))
    with patch("rey_lib.files.file_loader._validate_header", return_value=True) as vh:
        result = _process_validate(ctx, {"operation": "validate_file",
                                         "data_source": "advantage"}, RunContext(metadata={}))
    vh.assert_called_once()
    assert result.status == "ok" and ctx.validation_status == "ok"


def test_validate_unsupported_file_type_fails_closed(tmp_path):
    f = tmp_path / "f.csv"
    f.write_text("x")
    ds = _NS(name="advantage", transforms=[_NS(file_type="mystery")])
    ctx = _NS(data_sources=[ds], current_file=str(f))
    with pytest.raises(ReyLoaderError, match="unsupported file_type"):
        _process_validate(ctx, {"operation": "validate_file", "data_source": "advantage"},
                          RunContext(metadata={}))


# ---------------------------------------------------------------------------
# etl_operation fails closed (never re-runs the batch per file)
# ---------------------------------------------------------------------------

def test_etl_operation_fails_closed():
    with pytest.raises(ReyLoaderError, match="not yet wired"):
        _process_etl_operation(_NS(), {"operation": "transform_file"}, RunContext())
