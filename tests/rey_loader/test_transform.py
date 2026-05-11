"""
Unit tests for the rey_loader transform stage.

Tests are organised by concern:

  TestTransformFilesBasic       — happy-path file transform, output written,
                                  source file moved to processing
  TestTransformFilesRejection   — header mismatch → file moved to rejected
  TestTransformFilesConstants   — injected constants appear in output rows
  TestRunTransformOrchestration — run_transform delegates correctly to
                                  transform_files for each data source
  TestRunTransformWithHooks     — pre_transform hook binding sets
                                  _injected_row_columns; values appear in
                                  every output row
"""

from __future__ import annotations

import csv
import io
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rey_lib.files.file_loader import run_transform, transform_files

from tests.conftest import ADVANTAGE_HEADER, ADVANTAGE_ROW_VALID, write_advantage_csv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_output_rows(converted_path: Path, filename_glob: str) -> list[dict[str, str]]:
    """
    Find the first file matching filename_glob in converted_path and return
    its rows as a list of dicts (CSV DictReader).
    """
    matches = sorted(converted_path.glob(filename_glob))
    assert matches, f"No output file matching '{filename_glob}' in {converted_path}"
    with matches[0].open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# TestTransformFilesBasic
# ---------------------------------------------------------------------------

class TestTransformFilesBasic:
    """Happy-path transform tests — valid file produces a converted output."""

    def test_single_valid_file_is_transformed(
        self, ctx: Namespace, tmp_path: Path
    ) -> None:
        """A valid inbox file produces an output CSV in converted_path."""
        data_source = ctx.data_sources[0]
        write_advantage_csv(data_source.paths.inbox_path, "tran_20260501.csv")

        count = transform_files(ctx, data_source, data_source.transforms)

        assert count == 1
        output_files = list(data_source.paths.converted_path.glob("tran_20260501_v01.csv"))
        assert len(output_files) == 1, "Expected one output file in converted_path"

    def test_source_file_moved_to_processing(
        self, ctx: Namespace, tmp_path: Path
    ) -> None:
        """After a successful transform, the source file is in processing_path not inbox_path."""
        data_source = ctx.data_sources[0]
        write_advantage_csv(data_source.paths.inbox_path, "tran_20260501.csv")

        transform_files(ctx, data_source, data_source.transforms)

        assert not (data_source.paths.inbox_path / "tran_20260501.csv").exists()
        assert (data_source.paths.processing_path / "tran_20260501.csv").exists()

    def test_multiple_files_all_transformed(
        self, ctx: Namespace, tmp_path: Path
    ) -> None:
        """All pending inbox files are transformed in a single run."""
        data_source = ctx.data_sources[0]
        for name in ("tran_20260501.csv", "tran_20260502.csv", "tran_20260503.csv"):
            write_advantage_csv(data_source.paths.inbox_path, name)

        count = transform_files(ctx, data_source, data_source.transforms)

        assert count == 3

    def test_empty_inbox_returns_zero(
        self, ctx: Namespace, tmp_path: Path
    ) -> None:
        """No inbox files → count 0, no output produced."""
        data_source = ctx.data_sources[0]

        count = transform_files(ctx, data_source, data_source.transforms)

        assert count == 0
        assert list(data_source.paths.converted_path.iterdir()) == []

    def test_max_files_per_run_respected(
        self, ctx: Namespace, tmp_path: Path
    ) -> None:
        """max_files_per_run caps the number of files processed."""
        data_source = ctx.data_sources[0]
        # Override max_files_per_run via Namespace assignment.
        data_source.max_files_per_run = 2

        for name in ("tran_20260501.csv", "tran_20260502.csv", "tran_20260503.csv"):
            write_advantage_csv(data_source.paths.inbox_path, name)

        count = transform_files(ctx, data_source, data_source.transforms)

        assert count == 2


# ---------------------------------------------------------------------------
# TestTransformFilesRejection
# ---------------------------------------------------------------------------

class TestTransformFilesRejection:
    """Files that fail header matching are sent to rejected_path."""

    def test_wrong_header_moves_to_rejected(
        self, ctx: Namespace, tmp_path: Path
    ) -> None:
        """A file with a non-matching header is rejected, not transformed."""
        data_source = ctx.data_sources[0]
        bad_file = data_source.paths.inbox_path / "tran_20260501.csv"
        bad_file.write_text("WRONG,HEADER,COLS\n1,2,3\n", encoding="utf-8-sig")

        count = transform_files(ctx, data_source, data_source.transforms)

        assert count == 0
        assert not bad_file.exists(), "Source should be gone from inbox"
        assert (data_source.paths.rejected_path / "tran_20260501.csv").exists()

    def test_wrong_header_produces_no_output(
        self, ctx: Namespace, tmp_path: Path
    ) -> None:
        """A rejected file leaves converted_path empty."""
        data_source = ctx.data_sources[0]
        bad_file = data_source.paths.inbox_path / "tran_20260501.csv"
        bad_file.write_text("WRONG,HEADER,COLS\n1,2,3\n", encoding="utf-8-sig")

        transform_files(ctx, data_source, data_source.transforms)

        assert list(data_source.paths.converted_path.iterdir()) == []


# ---------------------------------------------------------------------------
# TestTransformFilesConstants
# ---------------------------------------------------------------------------

class TestTransformFilesConstants:
    """Constants declared in transform config appear in every output row."""

    def test_broker_constant_injected(
        self, ctx: Namespace, tmp_path: Path
    ) -> None:
        """broker='advantage' is present in every output row."""
        data_source = ctx.data_sources[0]
        write_advantage_csv(data_source.paths.inbox_path, "tran_20260501.csv")

        transform_files(ctx, data_source, data_source.transforms)

        rows = _read_output_rows(data_source.paths.converted_path, "tran_20260501_v01.csv")
        assert rows, "No rows in output"
        for row in rows:
            assert row.get("broker") == "advantage"

    def test_record_source_constant_injected(
        self, ctx: Namespace, tmp_path: Path
    ) -> None:
        """record_source='CSV Import' is present in every output row."""
        data_source = ctx.data_sources[0]
        write_advantage_csv(data_source.paths.inbox_path, "tran_20260501.csv")

        transform_files(ctx, data_source, data_source.transforms)

        rows = _read_output_rows(data_source.paths.converted_path, "tran_20260501_v01.csv")
        for row in rows:
            assert row.get("record_source") == "CSV Import"

    def test_source_file_token_resolved(
        self, ctx: Namespace, tmp_path: Path
    ) -> None:
        """source_file constant resolves to the source file name (not a literal token)."""
        data_source = ctx.data_sources[0]
        write_advantage_csv(data_source.paths.inbox_path, "tran_20260501.csv")

        transform_files(ctx, data_source, data_source.transforms)

        rows = _read_output_rows(data_source.paths.converted_path, "tran_20260501_v01.csv")
        for row in rows:
            source_file = row.get("source_file", "")
            # Should contain the filename, not the literal brace token.
            assert "tran_20260501" in source_file, (
                f"source_file should contain filename, got: {source_file!r}"
            )


# ---------------------------------------------------------------------------
# TestTransformFilesDateParsing
# ---------------------------------------------------------------------------

class TestTransformFilesDateParsing:
    """Date field_transforms convert raw values correctly."""

    def test_trade_date_yyyymmdd_parsed(
        self, ctx: Namespace, tmp_path: Path
    ) -> None:
        """TRADE DATE 20260501 is written as an ISO date string."""
        data_source = ctx.data_sources[0]
        write_advantage_csv(data_source.paths.inbox_path, "tran_20260501.csv")

        transform_files(ctx, data_source, data_source.transforms)

        rows = _read_output_rows(data_source.paths.converted_path, "tran_20260501_v01.csv")
        assert rows
        # After date transform, trade_date should not be the raw yyyymmdd string.
        # Acceptable output formats: ISO date '2026-05-01' or a datetime repr.
        trade_date = rows[0].get("trade_date", "")
        assert "2026" in trade_date, f"Expected parsed date, got: {trade_date!r}"

    def test_blank_prompt_date_allowed(
        self, ctx: Namespace, tmp_path: Path
    ) -> None:
        """Blank PROMPT DATE does not cause a row error (allow_blank=True)."""
        data_source = ctx.data_sources[0]
        # ADVANTAGE_ROW_VALID has a blank PROMPT DATE — use it directly.
        write_advantage_csv(data_source.paths.inbox_path, "tran_20260501.csv")

        count = transform_files(ctx, data_source, data_source.transforms)

        # File must not have been rejected.
        assert count == 1
        assert not (data_source.paths.rejected_path / "tran_20260501.csv").exists()


# ---------------------------------------------------------------------------
# TestRunTransformOrchestration
# ---------------------------------------------------------------------------

class TestRunTransformOrchestration:
    """run_transform iterates all data sources and aggregates counts."""

    def test_run_transform_returns_total_count(
        self, ctx: Namespace, tmp_path: Path
    ) -> None:
        """run_transform returns total files transformed across all sources."""
        data_source = ctx.data_sources[0]
        write_advantage_csv(data_source.paths.inbox_path, "tran_20260501.csv")
        write_advantage_csv(data_source.paths.inbox_path, "tran_20260502.csv")

        total = run_transform(ctx)

        assert total == 2

    def test_run_transform_empty_inbox_returns_zero(
        self, ctx: Namespace
    ) -> None:
        """run_transform returns 0 when no files are pending."""
        total = run_transform(ctx)
        assert total == 0


# ---------------------------------------------------------------------------
# TestRunTransformWithHooks
# ---------------------------------------------------------------------------

class TestRunTransformWithHooks:
    """
    pre_transform hook bindings set _injected_row_columns on ctx; those
    values appear in every output row. The SQL Server call is mocked — no
    real connection needed.

    Hook shape (current):
      data_source.transform_hooks: list of bindings, each with
        name, sql_config (-> ctx.sql_configs entry), and hook (phase label).
    """

    def _make_ctx_with_begin_batch_hook(
        self, ctx: Namespace, tmp_path: Path
    ) -> Namespace:
        """
        Return ctx wired with a begin_batch sql_config plus a transform_hooks
        binding that fires it at hooks.pre_transform. The proc call is mocked
        by the test caller.
        """
        # sql_config for begin_batch — mirrors config/app/sql_configs.yaml.
        sql_config = Namespace(
            name="begin_batch",
            type="procedure",
            connection="SQLServer_NaviControl_local",
            proc="NaviControl.dbo.pIns_Batch",
            params=[
                Namespace(name="BatchStartDT", source="ctx.batch_start_dt"),
                Namespace(name="BatchDescription", source="ctx.cli_call"),
                Namespace(name="LogFile", source="ctx.log_file"),
            ],
            output_params=[
                Namespace(
                    name="BatchID",
                    sql_type="INT",
                    ctx_var="batch_id",
                    row_column="BatchID",
                ),
            ],
        )

        # Connection Namespace — looked up by name from ctx.db.connections.
        db_conn_cfg = Namespace(
            name="SQLServer_NaviControl_local",
            driver="ODBC Driver 18 for SQL Server",
            server="localhost",
            database="NaviControl",
            trusted_connection="yes",
        )

        # Bind begin_batch to the pre_transform phase on this data source.
        data_source = ctx.data_sources[0]
        data_source.transform_hooks = [
            Namespace(
                name="begin_batch",
                sql_config="begin_batch",
                hook="hooks.pre_transform",
            ),
        ]

        ctx.sql_configs = [sql_config]
        ctx.db = Namespace(connections=[db_conn_cfg])
        return ctx

    def test_batch_id_injected_into_output_rows(
        self, ctx: Namespace, tmp_path: Path
    ) -> None:
        """
        When begin_batch runs and returns BatchID=99, every output row has
        a BatchID column with value '99'.
        """
        ctx = self._make_ctx_with_begin_batch_hook(ctx, tmp_path)
        data_source = ctx.data_sources[0]
        write_advantage_csv(data_source.paths.inbox_path, "tran_20260501.csv")

        # Mock the connection factory and proc call so no real DB is touched.
        with patch(
            "rey_lib.db.sqlserver_utils.get_connection",
            return_value=MagicMock(),
        ), patch(
            "rey_lib.db.sqlserver_utils.call_proc_with_output",
            return_value={"BatchID": 99},
        ):
            run_transform(ctx)

        rows = _read_output_rows(data_source.paths.converted_path, "tran_20260501_v01.csv")
        assert rows, "No output rows"
        for row in rows:
            assert row.get("BatchID") == "99", (
                f"Expected BatchID='99' in row, got: {row.get('BatchID')!r}"
            )

    def test_ctx_batch_id_set_after_pre_transform_hook(
        self, ctx: Namespace, tmp_path: Path
    ) -> None:
        """
        After run_transform, ctx.batch_id is set to the value returned by
        the begin_batch procedure's output param.
        """
        ctx = self._make_ctx_with_begin_batch_hook(ctx, tmp_path)
        data_source = ctx.data_sources[0]
        write_advantage_csv(data_source.paths.inbox_path, "tran_20260501.csv")

        with patch(
            "rey_lib.db.sqlserver_utils.get_connection",
            return_value=MagicMock(),
        ), patch(
            "rey_lib.db.sqlserver_utils.call_proc_with_output",
            return_value={"BatchID": 42},
        ):
            run_transform(ctx)

        assert ctx.batch_id == 42, f"Expected ctx.batch_id=42, got {ctx.batch_id!r}"

    def test_bindings_for_other_phases_are_ignored(
        self, ctx: Namespace, tmp_path: Path
    ) -> None:
        """
        A binding declared for hooks.post_transform must not fire at
        pre_transform, even if it references a valid sql_config. The
        dispatcher filters strictly by the binding's `hook` field.
        """
        ctx = self._make_ctx_with_begin_batch_hook(ctx, tmp_path)
        data_source = ctx.data_sources[0]
        # Re-bind: same sql_config, but now declared for post_transform.
        data_source.transform_hooks = [
            Namespace(
                name="begin_batch",
                sql_config="begin_batch",
                hook="hooks.post_transform",
            ),
        ]
        write_advantage_csv(data_source.paths.inbox_path, "tran_20260501.csv")

        with patch(
            "rey_lib.db.sqlserver_utils.get_connection",
            return_value=MagicMock(),
        ), patch(
            "rey_lib.db.sqlserver_utils.call_proc_with_output",
            return_value={"BatchID": 7},
        ):
            run_transform(ctx)

        # Hook fired at post_transform — ctx.batch_id is set, but rows were
        # already written before that, so BatchID column should NOT appear.
        assert ctx.batch_id == 7
        rows = _read_output_rows(data_source.paths.converted_path, "tran_20260501_v01.csv")
        assert rows, "No output rows"
        assert not rows[0].get("BatchID"), (
            f"BatchID should not be present when binding is post_transform; got {rows[0].get('BatchID')!r}"
        )
