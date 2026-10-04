"""The Loader's inventory_source_files process (row 589, step 1).

A thin handler: it calls the Loader-owned inventory in rey_lib and reports the
same StepResult the legacy file_operator step reported.
"""

from __future__ import annotations

from unittest.mock import patch

from rey_lib.workflow import RunContext

from rey_loader import workflow
from rey_loader.registration import WORKFLOW_OPERATIONS
from rey_loader.workflow import build_process_registry


def _handler():
    return build_process_registry(object())["inventory_source_files"]


def test_a_clean_inventory_reports_its_source_sets(run_log) -> None:
    config = {"sources": [{"name": "a"}, {"name": "b"}]}

    with patch.object(workflow, "run_source_inventory", return_value=0) as inventory:
        result = _handler()(object(), run_log, config, RunContext(apply=True))

    inventory.assert_called_once()
    assert (result.status, result.detail) == ("ok", "2 source set(s)")


def test_a_failed_inventory_fails_the_step(run_log) -> None:
    with patch.object(workflow, "run_source_inventory", return_value=1):
        result = _handler()(object(), run_log, {"sources": []}, RunContext(apply=True))

    assert (result.status, result.detail) == (
        "failed", "Source inventory returned exit code 1.")


def test_the_operation_is_published_with_the_legacy_contract_less_file_insertion() -> None:
    published = {op["name"]: op for op in WORKFLOW_OPERATIONS}["inventory_source_files"]

    assert [(p["name"], p["required"]) for p in published["parameters"]] == [
        ("sources", True), ("scope", False),
    ]


def test_the_handler_imports_nothing_from_file_operator() -> None:
    """The guardrail: the replacement never reaches the legacy implementation."""
    import inspect

    import rey_lib.load.inventory as inventory_module

    for module in (workflow, inventory_module):
        assert "file_operator" not in inspect.getsource(module).split('"""', 2)[-1]
