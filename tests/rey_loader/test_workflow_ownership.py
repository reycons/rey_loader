"""Ownership enforcement for rey_loader workflow consumption.

Verifies rey_loader consumes only resolved-ctx workflows assigned to itself:
its own workflows resolve, a workflow owned by another app is refused before it
can run, and the workflow module performs no filesystem workflow discovery.
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from rey_loader import workflow as workflow_mod
from rey_loader.error_utils import ReyLoaderError
from rey_loader.workflow import APP_NAME, _get_workflow


# Discovery primitives an app must never use to locate workflow definitions.
_DISCOVERY_TOKENS = (
    "rglob",
    ".glob(",
    "os.walk",
    ".iterdir(",
    "safe_load",
    "load_yaml",
    "parse_yaml",
    "import yaml",
)


def _ctx(*workflows: Namespace) -> Namespace:
    """Return a minimal ctx exposing a resolved ``workflows`` list."""
    return Namespace(workflows=list(workflows))


def test_resolves_own_workflow() -> None:
    """A rey_loader-owned workflow resolves from the ctx."""
    ctx = _ctx(Namespace(name="transform_load", app="rey_loader",
                         steps=["transform-files"]))
    assert _get_workflow(ctx, "transform_load").name == "transform_load"


def test_only_sees_own_when_ctx_holds_multiple_apps() -> None:
    """A full-installation ctx may hold other apps' workflows; only ours resolve."""
    ctx = _ctx(
        Namespace(name="transform_load", app="rey_loader", steps=["transform-files"]),
        Namespace(name="postgres_version_lint_comment", app="rey_db_admin",
                  steps=["lint-sql"]),
    )
    assert _get_workflow(ctx, "transform_load").app == "rey_loader"
    with pytest.raises(ReyLoaderError) as exc:
        _get_workflow(ctx, "postgres_version_lint_comment")
    assert "assigned to rey_db_admin" in str(exc.value)
    assert f"cannot be executed by {APP_NAME}" in str(exc.value)


def test_wrong_app_execution_is_rejected() -> None:
    """A workflow owned by another app is refused fail-closed."""
    ctx = _ctx(Namespace(name="foreign", app="rey_db_admin", steps=["x"]))
    with pytest.raises(ReyLoaderError):
        _get_workflow(ctx, "foreign")


def test_no_app_side_workflow_discovery() -> None:
    """The workflow module reads ctx only — never scans the filesystem."""
    source = Path(workflow_mod.__file__).read_text(encoding="utf-8")
    for token in _DISCOVERY_TOKENS:
        assert token not in source, (
            f"rey_loader.workflow must not discover workflow files: {token!r}"
        )
