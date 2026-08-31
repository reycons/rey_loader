"""rey_loader enters through the common process boundary.

``app_runtime`` composes the context and collects the shared runtime objects it
created when the block exits. It has to enclose the existing ``finally``, not
sit inside it: the run log is finalized there, and finalization must happen
while the shared objects are still live.

``run_app_operation`` is deliberately not that boundary. It wraps execution and
can nest -- a pipeline sub-app runs inside its parent's -- so collecting there
would close connections the surrounding run is still using.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import main as loader_main

MAIN = Path(loader_main.__file__)


def _calls_to(name: str) -> list[int]:
    """Lines where ``name`` is called in the entry point."""
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", getattr(n.func, "attr", "")) == name]


class TestTheEntryPointUsesTheCommonBoundary:
    """Structure, asserted on the source rather than inferred."""

    def test_bootstrap_is_not_called_directly(self, run_log) -> None:
        assert _calls_to("build_ctx_for_app") == []
        assert "build_ctx_for_app" not in MAIN.read_text(encoding="utf-8")

    def test_the_entry_point_enters_through_app_runtime(self, run_log) -> None:
        assert len(_calls_to("app_runtime")) == 1

    def test_the_bootstrap_arguments_are_unchanged(self, run_log) -> None:
        tree = ast.parse(MAIN.read_text(encoding="utf-8"))
        call = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.Call)
                    and getattr(n.func, "id", "") == "app_runtime")

        assert sorted(k.arg for k in call.keywords) == ["ctx", "operation"]

    def test_the_app_adds_no_cleanup_of_its_own(self, run_log) -> None:
        source = MAIN.read_text(encoding="utf-8")

        assert "collect_runtime" not in source
        assert "shared_connections" not in source


class TestTheBoundaryEnclosesFinalization:
    """Ordering: finalize inside, collect after."""

    def test_finalize_run_log_runs_inside_the_boundary(self, run_log) -> None:
        tree = ast.parse(MAIN.read_text(encoding="utf-8"))
        with_node = next(n for n in ast.walk(tree)
                         if isinstance(n, ast.With)
                         and any(getattr(i.context_expr.func, "id", "") == "app_runtime"
                                 for i in n.items
                                 if isinstance(i.context_expr, ast.Call)))
        enclosed = {n.lineno for n in ast.walk(with_node) if hasattr(n, "lineno")}

        finalize = _calls_to("finalize_run_log")
        assert finalize and set(finalize) <= enclosed

    def test_run_app_operation_is_not_the_boundary(self, run_log) -> None:
        """Execution lifecycle stays where it was; it can nest."""
        source = MAIN.read_text(encoding="utf-8")

        assert "collect_runtime" not in source


class TestExitBehaviourIsUnchanged:
    """The process still ends the way it did."""

    def _run(self, monkeypatch, *, command_result=None, raises=None) -> Any:
        """Drive main() with bootstrap and command execution stubbed out."""
        from rey_lib.config import bootstrap

        collected: list[str] = []

        def _build(*_a: Any, **kw: Any) -> Any:
            ctx = kw.get("ctx") or SimpleNamespace()
            ctx.run_log_path = "run.jsonl"
            # Identity is established at the launch boundary before the run log
            # is opened, so a context a launch produces always carries it.
            ctx.run_id = "00000000-0000-4000-8000-000000000001"
            ctx.run_timestamp = "20260822_000000"
            ctx.log_file = "run.jsonl"
            return ctx

        monkeypatch.setattr(bootstrap, "build_ctx_for_app", _build)
        monkeypatch.setattr(
            loader_main, "finalize_run_log",
            lambda log, **_kwargs: collected.append(f"finalized:{log.path()}"))

        def _command(*_a: Any, **_k: Any) -> int:
            if raises is not None:
                raise raises
            return command_result

        monkeypatch.setattr(loader_main, "_run_app_command", _command)
        monkeypatch.setattr(loader_main, "_run_workflow_command", _command)
        return collected

    def test_a_successful_command_exits_with_its_code(self, monkeypatch) -> None:
        collected = self._run(monkeypatch, command_result=0)
        args = SimpleNamespace(command="load", dry_run=False, ctx_file=None,
                               env_overrides=[])

        with patch.object(loader_main, "build_ctx_from_args",
                          return_value=SimpleNamespace()), \
             patch.object(loader_main, "_parse_args", return_value=args):
            with pytest.raises(SystemExit) as exc:
                loader_main.main()

        assert exc.value.code == 0
        assert collected == ["finalized:run.jsonl"]

    def test_a_nonzero_command_result_is_preserved(self, monkeypatch) -> None:
        self._run(monkeypatch, command_result=3)
        args = SimpleNamespace(command="load", dry_run=False, ctx_file=None,
                               env_overrides=[])

        with patch.object(loader_main, "build_ctx_from_args",
                          return_value=SimpleNamespace()), \
             patch.object(loader_main, "_parse_args", return_value=args):
            with pytest.raises(SystemExit) as exc:
                loader_main.main()

        assert exc.value.code == 3

    def test_an_app_error_still_exits_one(self, monkeypatch) -> None:
        from rey_lib.errors.error_utils import AppError

        collected = self._run(monkeypatch, raises=AppError("boom"))
        args = SimpleNamespace(command="load", dry_run=False, ctx_file=None,
                               env_overrides=[])

        with patch.object(loader_main, "build_ctx_from_args",
                          return_value=SimpleNamespace()), \
             patch.object(loader_main, "_parse_args", return_value=args), \
             patch.object(loader_main, "handle_exception", lambda *a: None):
            with pytest.raises(SystemExit) as exc:
                loader_main.main()

        assert exc.value.code == 1
        assert collected == ["finalized:run.jsonl"]

    def test_an_unexpected_error_still_exits_two(self, monkeypatch) -> None:
        collected = self._run(monkeypatch, raises=RuntimeError("unexpected"))
        args = SimpleNamespace(command="load", dry_run=False, ctx_file=None,
                               env_overrides=[])

        with patch.object(loader_main, "build_ctx_from_args",
                          return_value=SimpleNamespace()), \
             patch.object(loader_main, "_parse_args", return_value=args), \
             patch.object(loader_main, "handle_exception", lambda *a: None):
            with pytest.raises(SystemExit) as exc:
                loader_main.main()

        assert exc.value.code == 2
        assert collected == ["finalized:run.jsonl"]


class TestCollectionHappensAfterFinalization:
    """Shared objects stay live until the block exits."""

    def test_connections_are_live_during_finalization_and_closed_after(
            self, monkeypatch) -> None:
        from rey_lib.config import bootstrap
        from rey_lib.db import connection as connection_module
        from rey_lib.runtime import register_runtime_object

        seen: dict[str, bool] = {}

        def _build(*_a: Any, **kw: Any) -> Any:
            ctx = kw.get("ctx") or SimpleNamespace()
            ctx.run_log_path = "run.jsonl"
            ctx.log_file = "run.jsonl"
            ctx.run_id = "00000000-0000-4000-8000-000000000001"
            ctx.run_timestamp = "20260822_000000"
            ctx.connections = [SimpleNamespace(name="control", provider="postgres")]
            from rey_lib.db.connection import build_connections
            ctx.shared_connections = build_connections(ctx)
            for connection in ctx.shared_connections.values():
                register_runtime_object(ctx, connection)
            return ctx

        holder: dict[str, Any] = {}

        def _finalize(_path: str, **_kwargs: Any) -> None:
            # The run log is finalized while the shared objects are still live.
            seen["open_during_finalize"] = holder["ctx"].shared_connections[
                "control"].is_open

        def _command(ctx: Any, *_a: Any, **_k: Any) -> int:
            holder["ctx"] = ctx
            ctx.shared_connections["control"].handle()
            return 0

        monkeypatch.setattr(bootstrap, "build_ctx_for_app", _build)
        monkeypatch.setattr(loader_main, "finalize_run_log", _finalize)
        monkeypatch.setattr(loader_main, "_run_app_command", _command)
        args = SimpleNamespace(command="load", dry_run=False, ctx_file=None,
                               env_overrides=[])

        with patch.object(connection_module, "_db") as backend:
            backend.get_connection.return_value = SimpleNamespace(close=lambda: None)
            with patch.object(loader_main, "build_ctx_from_args",
                              return_value=SimpleNamespace()), \
                 patch.object(loader_main, "_parse_args", return_value=args):
                with pytest.raises(SystemExit):
                    loader_main.main()

        assert seen["open_during_finalize"] is True
        assert holder["ctx"].shared_connections["control"].is_open is False
