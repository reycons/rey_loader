"""rey_loader: one canonical AppError per failure (backlog 712, rule 79).

sql_apply has two explicit branches: with stop_on_error a failed file raises
one DatabaseError from the original and is not reported locally; otherwise the
failure is consumed and reported as the one AppError that represents it, and
the next file applies. A failed workflow is status here.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from rey_loader import sql_apply
from rey_loader.error_utils import DatabaseError

from tests.rey_loader.test_sql_apply_logging import _FakeConnection, _fake_connection


def _errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


def _ctx(tmp_path: Path, *, stop_on_error: bool) -> SimpleNamespace:
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "001_bad.sql").write_text("select broken", encoding="utf-8")
    (sql_dir / "002_bad.sql").write_text("select broken", encoding="utf-8")
    return SimpleNamespace(
        log_file=str(tmp_path / "rey_loader.log"),
        app_name="rey_loader",
        sql_steps=[SimpleNamespace(
            name="apply_sql", connection="warehouse", sql_path=str(sql_dir),
            file_pattern="*.sql", execution_order="filename",
            stop_on_error=stop_on_error,
        )],
        db_connections=[SimpleNamespace(name="warehouse", provider="postgres")],
    )


def test_without_stop_on_error_each_failed_file_is_reported_once(
    run_log: Any, tmp_path: Path, monkeypatch: Any, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(sql_apply, "shared_connection",
                        _fake_connection(_FakeConnection(fail=True)))
    ctx = _ctx(tmp_path, stop_on_error=False)

    with caplog.at_level(logging.ERROR):
        sql_apply.run_sql_apply(ctx, run_log, "apply_sql")

    reported = [r for r in _errors(caplog) if r.name == sql_apply.__name__]
    assert len(reported) == 2
    for record in reported:
        # Already an AppError (the provider's DatabaseError), so reported as
        # itself; its text is evidence the handler redacts on persistence.
        assert isinstance(record.exc_info[1], DatabaseError)
        assert "hunter2" not in record.getMessage()


def test_with_stop_on_error_the_failure_propagates_unreported(
    run_log: Any, tmp_path: Path, monkeypatch: Any, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(sql_apply, "shared_connection",
                        _fake_connection(_FakeConnection(fail=True)))
    ctx = _ctx(tmp_path, stop_on_error=True)

    with caplog.at_level(logging.ERROR), pytest.raises(DatabaseError) as raised:
        sql_apply.run_sql_apply(ctx, run_log, "apply_sql")

    assert str(raised.value) == "sql apply 'apply_sql': 001_bad.sql failed"
    assert raised.value.__cause__ is not None
    assert [r for r in _errors(caplog) if r.name == sql_apply.__name__] == []


def test_a_failed_workflow_is_status_and_returns_nonzero(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from rey_loader import workflow

    failed_run = SimpleNamespace(
        status="failed", outcomes=[SimpleNamespace(status="failed", id="s1")],
    )
    with patch.object(workflow, "_get_workflow", return_value={"steps": [{}]}), \
            patch.object(workflow, "_require"), \
            patch.object(workflow, "_guarded_registry", return_value={}), \
            patch.object(workflow, "build_process_registry", return_value={}), \
            patch.object(workflow, "coordinate_workflow", return_value=failed_run), \
            caplog.at_level(logging.WARNING):
        assert workflow.run_process_workflow(
            SimpleNamespace(), object(), object(), "wf", apply=False,
        ) == 1

    assert _errors(caplog) == []
    (warning,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "failed at step: s1" in warning.getMessage()
