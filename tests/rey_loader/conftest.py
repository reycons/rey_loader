"""Running a `load` invocation down the real canonical-object path.

The CLI parses; the canonical Source, Transform and Target validate, resolve and
execute themselves. What these tests stop is only the transfer boundary itself --
``_load_one_file`` is recorded rather than run -- and the configured connections,
which are named handles here. Everything between the parsed arguments and that
boundary is the shipped code.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import main as rey_loader_main
from rey_lib.load import load_operation
from rey_lib.load import source as source_module


class CanonicalPath:
    """One `load` invocation, run for real up to the transfer boundary."""

    def __init__(self) -> None:
        #: Every call the transfer boundary received, as (args, kwargs).
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def run(self, args: Any, run_log: Any = None) -> None:
        """Dispatch the invocation exactly as the CLI does, applying it."""
        rey_loader_main._check_load_arguments(args)
        rey_loader_main._execute_app_command(
            SimpleNamespace(), run_log if run_log is not None else SimpleNamespace(),
            args, True, SimpleNamespace(info=lambda *_a: None),
        )

    @property
    def boundary(self) -> dict[str, Any]:
        """The single boundary call, by role."""
        (args, kwargs), = self.calls
        return {"source": args[0], "transform": args[1], "target": args[2], **kwargs}


@pytest.fixture()
def canonical(monkeypatch: pytest.MonkeyPatch) -> CanonicalPath:
    """The real path, with the transfer boundary recorded and connections named."""
    path = CanonicalPath()

    def record(*args: Any, **kwargs: Any) -> int:
        path.calls.append((args, kwargs))
        return 3

    def shared_connection(_ctx: Any, name: str) -> Any:
        return SimpleNamespace(handle=lambda: f"handle:{name}")

    monkeypatch.setattr(load_operation, "_load_one_file", record)
    monkeypatch.setattr(source_module, "shared_connection", shared_connection)
    monkeypatch.setattr(load_operation, "shared_connection", shared_connection)
    return path
