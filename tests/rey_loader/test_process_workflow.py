"""Tests for the rey_loader single-file process-model workflow.

Covers SGC_Rey_Loader_Workflow_Process_Model + the single-file run model
(SGC_Rey_Loader_Single_File_Workflow_Run_Model): the generic process registry,
one coordinator pass per run, discover_file binding a single file or a no-file
signal, the rey_loader repeat-until-no-file loop, no-file skipping of file-scoped
steps, sql_operation delegation to the DB utility layer, and etl_operation
failing closed (never re-running the batch).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rey_lib.workflow import RunContext, StepResult

from rey_loader.error_utils import ReyLoaderError
from rey_loader.workflow import (
    _process_etl_operation,
    _process_file_operation,
    _process_sql_operation,
    _process_validate,
    build_process_registry,
    is_process_workflow,
    run_file_workflow,
    run_process_workflow,
)


class _NS:
    """Attribute namespace for config/ctx-shaped test inputs."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _workflow(*steps, processes=None):
    return _NS(
        name="w", app="rey_loader",
        processes=processes or _NS(file_operation=_NS(), sql_operation=_NS(),
                                   validate=_NS(), etl_operation=_NS()),
        steps=list(steps),
    )


# ---------------------------------------------------------------------------
# Registry + detection
# ---------------------------------------------------------------------------

def test_build_process_registry_exposes_generic_groups():
    registry = build_process_registry(object())
    assert set(registry) == {"file_operation", "sql_operation", "validate", "etl_operation"}


def test_is_process_workflow_detects_processes_block():
    ctx = _NS(workflows=[_NS(name="w", app="rey_loader", processes=_NS(x=1))])
    assert is_process_workflow(ctx, "w") is True
    ctx2 = _NS(workflows=[_NS(name="s", app="rey_loader", steps=[])])
    assert is_process_workflow(ctx2, "s") is False


# ---------------------------------------------------------------------------
# Single coordinator pass + rey_loader repeat loop
# ---------------------------------------------------------------------------

def test_run_process_workflow_is_a_single_ordered_pass():
    order: list = []

    def handler(ctx, config, run):
        order.append(config.get("marker"))
        return StepResult("x", "ok")

    stub = {"file_operation": handler, "sql_operation": handler,
            "validate": handler, "etl_operation": handler}
    wf = _workflow(
        _NS(id="s1", process="sql_operation", config=_NS(marker="s1")),
        _NS(id="s2", process="file_operation", config=_NS(marker="s2",
                                                          operation="discover_file")),
        _NS(id="s3", process="validate", config=_NS(marker="s3")),
    )
    ctx = _NS(workflows=[wf])
    with patch("rey_loader.workflow.build_process_registry", return_value=stub):
        code = run_process_workflow(ctx, object(), "w", apply=True)
    assert code == 0
    assert order == ["s1", "s2", "s3"]


def test_run_file_workflow_repeats_until_no_file():
    calls = {"n": 0}

    def fake_pass(ctx, adapter, name, *, apply=True):
        calls["n"] += 1
        object.__setattr__(ctx, "no_file", calls["n"] >= 3)
        return 0

    ctx = _NS()
    with patch("rey_loader.workflow.run_process_workflow", side_effect=fake_pass):
        code = run_file_workflow(ctx, object(), "w", apply=True)
    assert code == 0
    assert calls["n"] == 3  # two files processed, third pass finds no file


def test_run_file_workflow_dry_run_is_single_pass():
    calls = {"n": 0}

    def fake_pass(ctx, adapter, name, *, apply=True):
        calls["n"] += 1
        object.__setattr__(ctx, "no_file", False)  # a file is always available
        return 0

    ctx = _NS()
    with patch("rey_loader.workflow.run_process_workflow", side_effect=fake_pass):
        run_file_workflow(ctx, object(), "w", apply=False)
    assert calls["n"] == 1  # dry-run does not consume files, so it runs once


def test_no_file_skips_file_scoped_steps():
    ran: list = []

    def discover(ctx, config, run):
        object.__setattr__(ctx, "no_file", True)
        ran.append("discover")
        return StepResult("d", "ok")

    def handler(ctx, config, run):
        ran.append(config.get("id"))
        return StepResult("x", "ok")

    stub = {"file_operation": discover, "sql_operation": handler,
            "validate": handler, "etl_operation": handler}
    wf = _workflow(
        _NS(id="discover", process="file_operation", config=_NS(operation="discover_file")),
        _NS(id="batch_step", process="sql_operation", config=_NS(id="batch_step")),
        _NS(id="file_step", process="validate", config=_NS(id="file_step", scope="file")),
    )
    ctx = _NS(workflows=[wf], no_file=False)
    with patch("rey_loader.workflow.build_process_registry", return_value=stub):
        run_process_workflow(ctx, object(), "w", apply=True)
    assert "discover" in ran and "batch_step" in ran  # batch-scoped steps run
    assert "file_step" not in ran                      # file-scoped step skipped


# ---------------------------------------------------------------------------
# sql_operation delegates to the DB utility layer
# ---------------------------------------------------------------------------

def test_sql_operation_delegates_to_db_utils():
    ctx = _NS()
    config = {"operation": "execute_parameter_result", "procedure_map": "control",
              "routine_binding": "start_batch", "params": {"batch_name": "B"}}
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

def test_discover_file_binds_a_single_file(tmp_path):
    (tmp_path / "tran_1.csv").write_text("x")
    (tmp_path / "tran_2.csv").write_text("y")
    ds = _NS(name="advantage", paths=_NS(inbox_path=str(tmp_path)))
    ctx = _NS(data_sources=[ds])
    config = {"operation": "discover_file", "data_source": "advantage",
              "path": "inbox_path", "pattern": "tran_*.csv",
              "output": {"current_file": "current_file"}}
    result = _process_file_operation(ctx, config, RunContext(metadata={}))
    assert result.status == "ok"
    assert Path(ctx.current_file).name == "tran_1.csv"   # single, first in order
    assert ctx.no_file is False


def test_discover_file_no_file_sets_flag(tmp_path):
    ds = _NS(name="advantage", paths=_NS(inbox_path=str(tmp_path)))
    ctx = _NS(data_sources=[ds])
    config = {"operation": "discover_file", "data_source": "advantage",
              "path": "inbox_path", "pattern": "tran_*.csv",
              "output": {"current_file": "current_file"}}
    result = _process_file_operation(ctx, config, RunContext(metadata={}))
    assert result.status == "ok" and result.detail == "no file"
    assert ctx.no_file is True and ctx.current_file is None


def test_file_operation_move_uses_destination_key(tmp_path):
    ds = _NS(name="advantage", paths=_NS(processing_path=str(tmp_path / "proc")))
    ctx = _NS(data_sources=[ds], current_file=str(tmp_path / "f.csv"))
    config = {"operation": "move", "data_source": "advantage", "to": "processing_path"}
    with patch("rey_loader.workflow.move_file",
               return_value=tmp_path / "proc" / "f.csv") as mv:
        result = _process_file_operation(ctx, config, RunContext())
    mv.assert_called_once()
    assert result.status == "ok" and ctx.current_file.endswith("proc/f.csv")


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
# etl_operation delegates to the public per-file APIs (never the batch runners)
# ---------------------------------------------------------------------------

def test_etl_transform_calls_transform_one_with_current_file():
    ctx = _NS(current_file="/x/f.csv", data_sources=[_NS(name="advantage")])
    with patch("rey_loader.workflow.transform_one", return_value=True) as t1:
        result = _process_etl_operation(ctx, {"operation": "transform_file",
                                              "data_source": "advantage"},
                                        RunContext(metadata={}))
    args = t1.call_args[0]
    assert str(args[2]).endswith("f.csv")   # the single current file
    assert result.status == "ok"


def test_etl_load_calls_load_one_with_current_file():
    ds = _NS(name="advantage", loads=[_NS(name="ld")])
    ctx = _NS(current_file="/x/f.csv", data_sources=[ds])
    with patch("rey_loader.workflow.load_one", return_value=42) as l1:
        result = _process_etl_operation(ctx, {"operation": "load_file",
                                              "data_source": "advantage"},
                                        RunContext(metadata={}))
    assert str(l1.call_args[0][3]).endswith("f.csv")
    assert result.status == "ok" and "42" in result.detail


def test_etl_never_calls_the_batch_runners():
    ctx = _NS(current_file="/x/f.csv", data_sources=[_NS(name="advantage")])
    with patch("rey_loader.workflow.transform_one", return_value=True), \
         patch("rey_lib.files.file_loader.run_transform",
               side_effect=AssertionError("batch runner must not be called")), \
         patch("rey_lib.files.file_loader.run_load",
               side_effect=AssertionError("batch runner must not be called")):
        _process_etl_operation(ctx, {"operation": "transform_file",
                                     "data_source": "advantage"}, RunContext(metadata={}))


def test_etl_transform_rejected_fails_closed():
    ctx = _NS(current_file="/x/f.csv", data_sources=[_NS(name="advantage")])
    with patch("rey_loader.workflow.transform_one", return_value=False):
        with pytest.raises(ReyLoaderError, match="rejected"):
            _process_etl_operation(ctx, {"operation": "transform_file",
                                         "data_source": "advantage"}, RunContext(metadata={}))


def test_etl_unsupported_operation_fails_closed():
    ctx = _NS(current_file="/x/f.csv", data_sources=[_NS(name="advantage")])
    with pytest.raises(ReyLoaderError, match="unsupported operation"):
        _process_etl_operation(ctx, {"operation": "nope", "data_source": "advantage"},
                               RunContext(metadata={}))
