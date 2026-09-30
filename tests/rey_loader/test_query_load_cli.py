"""Load what a query returns into a table, with no configuration at all.

    load --statement "select ..." --source-connection warehouse \\
         --table landing.records --connection reporting

rey_lib could run this load (``load_query_to_table``) and nothing could ask
rey_loader to do it: all three existing shapes began at a file.

**THE LOADER IS TWO-ENDED NOW**, and that is what most of this module is
about. A query load carries TWO connections -- one the statement runs on, one
the destination lives on -- so an incomplete invocation has to be refused by
the END that is short. A message naming the wrong end sends an operator to
fix something that was never missing.
"""

from __future__ import annotations

import argparse
from types import SimpleNamespace as _NS
from unittest.mock import patch

import pytest

import main as rey_loader_main
from rey_loader import load as load_module
from rey_lib.db.query_source import QuerySource
from rey_lib.errors.error_utils import ConfigError
from rey_lib.files.data_file.base import DataFile
from rey_lib.load.target import TARGET_KINDS
from rey_loader.error_utils import ReyLoaderError

_STATEMENT = "select a, b from orders"


def _args(**kwargs) -> argparse.Namespace:
    """A `load` invocation with everything absent unless named."""
    base = dict(command="load", file="", data_source="", table="",
                connection="", create=False, replace=False, recreate=False, append=False, file_type="",
                statement="", source_connection="", sql_file="",
                out_file="", transform="", transform_file="")
    base.update(kwargs)
    return argparse.Namespace(**base)


def _whole(**over) -> argparse.Namespace:
    """A COMPLETE query invocation: both ends fully named."""
    return _args(statement=_STATEMENT, source_connection="warehouse",
                 table="landing.records", connection="reporting", **over)


class TestACompleteQueryInvocationIsAccepted:
    """The shape has to be reachable before its refusals matter."""

    def test_it_is_not_refused(self) -> None:
        """THE OBSTRUCTION GUARD.

        `--table` and `--connection` were refused without a `--file`, because
        a file was the only source there had ever been. A valid query load
        gives both and no file, so that refusal blocked every one of them --
        and no existing test would have caught it, since none exercises a
        `--table` without a `--file`.
        """
        rey_loader_main._check_load_arguments(_whole())

    def test_create_is_allowed_on_it(self) -> None:
        rey_loader_main._check_load_arguments(_whole(create=True))


class TestEachEndIsProvedByItsObject:
    """A short end is refused by ITS canonical object, which names itself."""

    @pytest.mark.parametrize(("args", "named", "field"), [
        (dict(statement=_STATEMENT, table="landing.records", connection="reporting"),
         "Source", "source-connection"),
        (dict(statement=_STATEMENT, source_connection="warehouse"), "Target", "table"),
        (dict(statement=_STATEMENT, source_connection="warehouse", table="landing.records"),
         "Target", "connection"),
        # A connection alone is SHARED by both query kinds and decides nothing,
        # so the Source is a file source and says so -- its own rule, not ours.
        (dict(source_connection="warehouse", table="landing.records", connection="reporting"),
         "Source", "file"),
        (dict(table="landing.records", connection="reporting"), "Source", "file"),
    ])
    def test_the_short_end_is_named(self, canonical, args, named, field) -> None:
        with pytest.raises(ConfigError) as raised:
            canonical.run(_args(**args))

        message = str(raised.value)
        assert named in message and field in message
        assert canonical.calls == []


class TestASourceIsOne:
    """A statement and a file are two sources, not a preference."""

    def test_a_statement_with_a_file(self) -> None:
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(
                _whole(file="asset.csv")
            )

        assert "SOURCE" in str(raised.value)

    def test_a_statement_with_a_data_source(self) -> None:
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(
                _args(statement=_STATEMENT, data_source="advantage")
            )

        assert "--data-source" in str(raised.value)

    def test_a_statement_with_a_file_type(self) -> None:
        """A statement has no format.

        `file_type` sat among the destination options and is a SOURCE
        property; offering it for a query would be a control with nothing
        behind it.
        """
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(_whole(file_type="CSV"))

        message = str(raised.value)
        assert "--file-type" in message
        assert "format" in message


class TestTheDispatch:
    """A query invocation is parsed into the objects and executed through them."""

    def test_a_query_reaches_the_boundary_as_a_resolved_query(self, canonical) -> None:
        canonical.run(_whole(create=True))

        seen = canonical.boundary
        assert isinstance(seen["source"], QuerySource)
        assert seen["source"].statement == _STATEMENT
        assert seen["source"].conn == "handle:warehouse"
        assert (seen["target"].schema, seen["target"].name) == ("landing", "records")
        assert seen["target"].connection == "reporting"
        assert seen["loader"].create_destination is True
        assert seen["load_name"] == "query:landing.records"

    def test_it_takes_no_other_entry_path(self, canonical) -> None:
        with patch.object(rey_loader_main, "run_load_one") as one, \
             patch.object(rey_loader_main, "run_load") as every:
            canonical.run(_whole())

        assert not (one.called or every.called)
        assert len(canonical.calls) == 1

    @pytest.mark.parametrize(("flag", "attribute"), [
        ("replace", "replace_destination"), ("recreate", "recreate_destination"),
    ])
    def test_every_mode_reaches_the_boundary(self, canonical, flag, attribute) -> None:
        """THE REGRESSION: these raised TypeError through the old wrapper."""
        canonical.run(_whole(**{flag: True}))

        assert getattr(canonical.boundary["loader"], attribute) is True


class TestTheQueryEntryPoint:
    """run_load_objects is a wrapper: it hands the objects to rey_lib and counts."""

    def test_it_hands_the_objects_over(self, run_log) -> None:
        seen: dict = {}

        def _capture(_ctx, _log, source, transform, target, reader=None):
            seen.update(source=source, transform=transform, target=target)
            return 5

        source, transform, target = rey_loader_main._load_objects_from(_whole())
        with patch.object(load_module, "run_selected_load", _capture):
            total = load_module.run_load_objects(_NS(), run_log, source, transform, target)

        assert total == 5
        assert seen["source"] is source and seen["target"] is target

    def test_an_empty_statement_is_refused_before_the_boundary(self, canonical) -> None:
        with pytest.raises(ConfigError) as raised:
            canonical.run(_args(statement="   ", source_connection="warehouse",
                                table="landing.records", connection="reporting"))

        # A blank statement says nothing, so the Source refuses by its own
        # contract -- before any connection or boundary is reached.
        assert "Source" in str(raised.value)
        assert canonical.calls == []


class TestAQueryMayGoToAFile:
    """``--out-file`` instead of a table and a connection."""

    @staticmethod
    def _to_file(**over) -> argparse.Namespace:
        return _args(statement=_STATEMENT, source_connection="warehouse",
                     out_file="/tmp/rows.csv", **over)

    def test_a_complete_invocation_is_accepted(self) -> None:
        rey_loader_main._check_load_arguments(self._to_file())

    def test_it_reaches_the_boundary_with_a_target_file(self, canonical) -> None:
        canonical.run(self._to_file())

        seen = canonical.boundary
        assert isinstance(seen["source"], QuerySource)
        assert isinstance(seen["target"], DataFile)
        assert str(seen["target"].path) == "/tmp/rows.csv"
        assert "loader" not in seen
        assert seen["load_name"] == "query:rows.csv"

    def test_a_target_file_has_no_format_field(self) -> None:
        """`--file-type` describes a file being READ; a target file's suffix says."""
        file_kind = next(one for one in TARGET_KINDS if one.id == "file")

        assert "file-type" not in file_kind.fields

    def test_a_file_and_a_table_are_two_destinations(self) -> None:
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(
                self._to_file(table="landing.records", connection="reporting")
            )

        message = str(raised.value)
        assert "DESTINATION" in message
        assert "--out-file" in message and "--table" in message

    def test_a_file_destination_with_no_source(self, canonical) -> None:
        with pytest.raises(ConfigError) as raised:
            canonical.run(_args(out_file="/tmp/rows.csv"))

        assert "Source" in str(raised.value)
        assert canonical.calls == []

    def test_a_format_is_still_refused_beside_a_statement(self) -> None:
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(self._to_file(file_type="CSV"))

        assert "--file-type" in str(raised.value)


class TestTheStatementCanComeFromAFile:
    """``--sql-file`` is a TRANSPORT for the statement, not a second source.

    Both forms produce one QuerySource, read by the canonical Source.
    """

    @staticmethod
    def _written(tmp_path, text: str) -> str:
        path = tmp_path / "query.sql"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_a_file_and_an_inline_statement_reach_the_same_query(
        self, canonical, tmp_path,
    ) -> None:
        canonical.run(_args(sql_file=self._written(tmp_path, _STATEMENT),
                            source_connection="warehouse", table="landing.records",
                            connection="reporting"))
        canonical.run(_whole())

        from_file, inline = (call[0][0] for call in canonical.calls)
        assert from_file.statement == inline.statement == _STATEMENT
        assert from_file.conn == inline.conn

    def test_giving_both_forms_is_refused_and_names_both(self) -> None:
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(_whole(sql_file="query.sql"))

        message = str(raised.value)
        assert "--statement" in message and "--sql-file" in message

    def test_a_file_and_a_sql_file_are_two_sources(self) -> None:
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(
                _args(file="asset.csv", sql_file="query.sql", source_connection="w",
                      table="landing.records", connection="reporting")
            )

        assert "SOURCE" in str(raised.value)

    def test_a_format_beside_a_sql_file_is_refused(self) -> None:
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(
                _args(sql_file="query.sql", source_connection="w", file_type="CSV",
                      table="landing.records", connection="reporting")
            )

        assert "--file-type" in str(raised.value)

    @pytest.mark.parametrize("text", [None, "   \n\n"])
    def test_a_missing_or_empty_file_is_refused_by_the_source(
        self, canonical, tmp_path, text,
    ) -> None:
        path = self._written(tmp_path, text) if text is not None else "/nowhere/q.sql"

        with pytest.raises(ConfigError) as raised:
            canonical.run(_args(sql_file=path, source_connection="warehouse",
                                table="landing.records", connection="reporting"))

        assert "sql_file" in str(raised.value)
        assert canonical.calls == []
