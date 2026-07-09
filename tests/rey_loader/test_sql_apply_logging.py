"""Tests for rey_loader SQL apply run-log evidence."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rey_lib.run_lifecycle import run_app_operation
from rey_loader import sql_apply
from rey_loader.error_utils import DatabaseError


class _FakeConnection:
    def __init__(self, *, fail: bool = False) -> None:
        self.executed: list[str] = []
        self.closed = False
        self.fail = fail

    def execute(self, sql_text: str) -> None:
        self.executed.append(sql_text)
        if self.fail:
            raise RuntimeError("sql failed password=hunter2")

    def close(self) -> None:
        self.closed = True


class _FakeAdapter:
    def __init__(self, conn: _FakeConnection) -> None:
        self.conn = conn

    def get_connection(self, _db_cfg: object) -> _FakeConnection:
        return self.conn


class _FailingAdapter:
    def get_connection(self, _db_cfg: object) -> _FakeConnection:
        raise RuntimeError("connection failed password=hunter2")


def _records(ctx: object) -> list[dict]:
    return [
        json.loads(line)
        for line in Path(ctx.run_log_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_sql_apply_emits_one_sql_execution_per_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """SQL apply delegates execution evidence to procedure_map.execute_sql_text."""
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    first = sql_dir / "001_first.sql"
    second = sql_dir / "002_second.sql"
    first.write_text("select 1", encoding="utf-8")
    second.write_text("select 2", encoding="utf-8")
    conn = _FakeConnection()
    monkeypatch.setattr(sql_apply, "_db_adapter", _FakeAdapter(conn))

    ctx = SimpleNamespace(
        log_file=str(tmp_path / "rey_loader.log"),
        app_name="rey_loader",
        sql_steps=[
            SimpleNamespace(
                name="apply_sql",
                connection="warehouse",
                sql_path=str(sql_dir),
                file_pattern="*.sql",
                execution_order="filename",
                stop_on_error=True,
            )
        ],
        db_connections=[SimpleNamespace(name="warehouse")],
    )

    sql_apply.run_sql_apply(ctx, "apply_sql")

    assert conn.executed == ["select 1", "select 2"]
    assert conn.closed is True
    records = [
        record for record in _records(ctx)
        if record["record_type"] == "SQL_EXECUTION"
    ]
    assert len(records) == 2
    assert [record["sql_label"] for record in records] == [
        "001_first.sql",
        "002_second.sql",
    ]
    assert all(record["operation"] == "sql_apply" for record in records)
    assert all(record["status"] == "success" for record in records)
    assert all(record["connection_name"] == "warehouse" for record in records)
    assert all(record["sql_step"] == "apply_sql" for record in records)


def test_sql_apply_failure_records_canonical_error_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """SQL execution failures surface sanitized child ERROR evidence."""
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    sql_file = sql_dir / "001_bad.sql"
    sql_file.write_text("select broken", encoding="utf-8")
    conn = _FakeConnection(fail=True)
    monkeypatch.setattr(sql_apply, "_db_adapter", _FakeAdapter(conn))
    ctx = SimpleNamespace(
        log_file=str(tmp_path / "rey_loader.log"),
        app_name="rey_loader",
        sql_steps=[
            SimpleNamespace(
                name="apply_sql",
                connection="warehouse",
                sql_path=str(sql_dir),
                file_pattern="*.sql",
                execution_order="filename",
                stop_on_error=True,
            )
        ],
        db_connections=[SimpleNamespace(name="warehouse")],
    )

    with pytest.raises(DatabaseError):
        run_app_operation(ctx, "sql", lambda: sql_apply.run_sql_apply(ctx, "apply_sql"))

    records = _records(ctx)
    error = next(record for record in records if record["record_type"] == "ERROR")
    failure = next(record for record in records if record["record_type"] == "RUN_COMPLETE")
    sql_record = next(record for record in records if record["record_type"] == "SQL_EXECUTION")
    assert error["error_type"] == "DatabaseError"
    assert "001_bad.sql failed" in error["error_message"]
    assert "hunter2" not in json.dumps(records)
    assert failure["failure_record_id"] == error["error_id"]
    assert sql_record["status"] == "failed"
    assert sql_record["sql_label"] == "001_bad.sql"


def test_sql_apply_connection_failure_records_canonical_error_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Database connection failures surface sanitized child ERROR evidence."""
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "001.sql").write_text("select 1", encoding="utf-8")
    monkeypatch.setattr(sql_apply, "_db_adapter", _FailingAdapter())
    ctx = SimpleNamespace(
        log_file=str(tmp_path / "rey_loader.log"),
        app_name="rey_loader",
        sql_steps=[
            SimpleNamespace(
                name="apply_sql",
                connection="warehouse",
                sql_path=str(sql_dir),
                file_pattern="*.sql",
                execution_order="filename",
                stop_on_error=True,
            )
        ],
        db_connections=[SimpleNamespace(name="warehouse")],
    )

    with pytest.raises(RuntimeError):
        run_app_operation(ctx, "sql", lambda: sql_apply.run_sql_apply(ctx, "apply_sql"))

    records = _records(ctx)
    error = next(record for record in records if record["record_type"] == "ERROR")
    complete = next(record for record in records if record["record_type"] == "RUN_COMPLETE")
    assert error["error_type"] == "RuntimeError"
    assert "connection failed" in error["error_message"]
    assert "hunter2" not in json.dumps(records)
    assert complete["failure_record_id"] == error["error_id"]
