"""Tests for rey_loader SQL apply run-log evidence."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rey_lib.db._sqlalchemy import ReyConnection
from rey_lib.run_lifecycle import run_app_operation
from rey_loader import sql_apply
from rey_loader.error_utils import DatabaseError


class _FakeResult:
    rowcount = 1


class _FakeCoreConnection:
    def __init__(self, *, fail: bool = False) -> None:
        self.executed: list[str] = []
        self.closed = False
        self.fail = fail
        self.committed = 0
        self.rolled_back = 0

    def exec_driver_sql(self, sql_text: str, _params: object = None) -> _FakeResult:
        self.executed.append(sql_text)
        if self.fail:
            raise RuntimeError("sql failed password=hunter2")
        return _FakeResult()

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1

    def close(self) -> None:
        self.closed = True


class _FakeEngine:
    def dispose(self) -> None:
        pass


class _FakeConnection(ReyConnection):
    def __init__(self, *, fail: bool = False) -> None:
        self.core = _FakeCoreConnection(fail=fail)
        super().__init__("postgres", _FakeEngine(), self.core)

    @property
    def executed(self) -> list[str]:
        return self.core.executed

    @property
    def closed(self) -> bool:
        return self.core.closed

    @property
    def committed(self) -> int:
        return self.core.committed

    @property
    def rolled_back(self) -> int:
        return self.core.rolled_back


class _FakeSharedConnection:
    """What ``shared_connection`` answers with: something holding a handle.

    The connection is the sole path to a database, so that is the seam a test
    stands in at. Patching the module's DBAdapter stopped standing in for
    anything when sql_apply started opening its connection through
    ``shared_connection``.
    """

    def __init__(self, conn: _FakeConnection) -> None:
        self.conn = conn

    def handle(self) -> _FakeConnection:
        return self.conn


def _fake_connection(conn: _FakeConnection):
    """A ``shared_connection`` replacement handing back this connection."""
    def shared_connection(_ctx: object, _name: str) -> _FakeSharedConnection:
        return _FakeSharedConnection(conn)
    return shared_connection


def _failing_connection(_ctx: object, _name: str) -> _FakeSharedConnection:
    """A ``shared_connection`` replacement that cannot open one."""
    raise RuntimeError("connection failed password=hunter2")


def _canonical(record: dict) -> dict:
    """The canonical error object an ERROR record carries.

    ERROR is one of the two record types whose whole payload is the
    ``error_message`` object, so the identity and the evidence are read from
    that object rather than from the record's own fields.
    """
    return record.get("error_message") or {}


def _records(run_log: object) -> list[dict]:
    """The records a run log wrote, read from the log's own path.

    Asked of the run log rather than of the context: the log owns where it
    writes, and a context does not carry that.
    """
    return [
        json.loads(line)
        for line in Path(run_log.path()).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_sql_apply_emits_one_sql_execution_per_file(run_log, 
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
    monkeypatch.setattr(sql_apply, "shared_connection", _fake_connection(conn))

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
        # A connection states its provider. DBAdapter resolves the dialect from
        # it and refuses a connection that names neither a provider nor a
        # recognizable driver, which is what this fixture predated.
        db_connections=[SimpleNamespace(name="warehouse", provider="postgres")],
    )

    sql_apply.run_sql_apply(ctx, run_log, "apply_sql")

    # Each file is applied inside its own transaction, so the statements a
    # connection sees are the envelope as well as the SQL.
    assert [statement for statement in conn.executed
            if statement not in ("BEGIN", "COMMIT", "ROLLBACK")] == [
        "select 1", "select 2",
    ]
    # Not closed here. The connection is the runtime's, reached through
    # shared_connection, so a step that used one does not dispose of something
    # the next step is entitled to reuse.
    assert conn.closed is False
    records = [
        record for record in _records(run_log)
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


def test_sql_apply_failure_records_canonical_error_evidence(run_log, 
    tmp_path: Path,
    monkeypatch,
) -> None:
    """SQL execution failures surface sanitized child ERROR evidence."""
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    sql_file = sql_dir / "001_bad.sql"
    sql_file.write_text("select broken", encoding="utf-8")
    conn = _FakeConnection(fail=True)
    monkeypatch.setattr(sql_apply, "shared_connection", _fake_connection(conn))
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
        # A connection states its provider. DBAdapter resolves the dialect from
        # it and refuses a connection that names neither a provider nor a
        # recognizable driver, which is what this fixture predated.
        db_connections=[SimpleNamespace(name="warehouse", provider="postgres")],
    )

    with pytest.raises(DatabaseError):
        run_app_operation(ctx, run_log, "sql", lambda: sql_apply.run_sql_apply(ctx, run_log, "apply_sql"))

    records = _records(run_log)
    error = next(record for record in records if record["record_type"] == "ERROR")
    failure = next(record for record in records if record["record_type"] == "RUN_COMPLETE")
    sql_record = next(record for record in records if record["record_type"] == "SQL_EXECUTION")
    assert _canonical(error)["error_type"] == "DatabaseError"
    assert "001_bad.sql failed" in _canonical(error)["error_message"]
    assert "hunter2" not in json.dumps(records)
    assert failure["failure_record_id"] == _canonical(error)["error_id"]
    assert sql_record["status"] == "failed"
    assert sql_record["sql_label"] == "001_bad.sql"


def test_sql_apply_connection_failure_records_canonical_error_evidence(run_log, 
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Database connection failures surface sanitized child ERROR evidence."""
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / "001.sql").write_text("select 1", encoding="utf-8")
    monkeypatch.setattr(sql_apply, "shared_connection", _failing_connection)
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
        # A connection states its provider. DBAdapter resolves the dialect from
        # it and refuses a connection that names neither a provider nor a
        # recognizable driver, which is what this fixture predated.
        db_connections=[SimpleNamespace(name="warehouse", provider="postgres")],
    )

    with pytest.raises(RuntimeError):
        run_app_operation(ctx, run_log, "sql", lambda: sql_apply.run_sql_apply(ctx, run_log, "apply_sql"))

    records = _records(run_log)
    error = next(record for record in records if record["record_type"] == "ERROR")
    complete = next(record for record in records if record["record_type"] == "RUN_COMPLETE")
    assert _canonical(error)["error_type"] == "RuntimeError"
    assert "connection failed" in _canonical(error)["error_message"]
    assert "hunter2" not in json.dumps(records)
    assert complete["failure_record_id"] == _canonical(error)["error_id"]
