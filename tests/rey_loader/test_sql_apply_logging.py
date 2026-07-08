"""Tests for rey_loader SQL apply run-log evidence."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from rey_loader import sql_apply


class _FakeConnection:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.closed = False

    def execute(self, sql_text: str) -> None:
        self.executed.append(sql_text)

    def close(self) -> None:
        self.closed = True


class _FakeAdapter:
    def __init__(self, conn: _FakeConnection) -> None:
        self.conn = conn

    def get_connection(self, _db_cfg: object) -> _FakeConnection:
        return self.conn


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
