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
from rey_loader.error_utils import ReyLoaderError

_STATEMENT = "select a, b from orders"


def _args(**kwargs) -> argparse.Namespace:
    """A `load` invocation with everything absent unless named."""
    base = dict(command="load", file="", data_source="", table="",
                connection="", create=False, file_type="",
                statement="", source_connection="", sql_file="")
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


class TestEachEndIsProvedSeparately:
    """A refusal names the end that is short, not merely that one is."""

    def test_a_statement_with_no_source_connection(self) -> None:
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(
                _args(statement=_STATEMENT, table="landing.records",
                      connection="reporting")
            )

        message = str(raised.value)
        assert "--source-connection" in message
        assert "SOURCE" in message

    def test_a_statement_with_no_destination_table(self) -> None:
        """THE HOLE THIS TEST EXISTS FOR.

        Both source options given, so the dispatch selects the query branch
        and the wrapper is reached WITH NO DESTINATION. Each end being
        internally consistent is not the same as the shape being whole.
        """
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(
                _args(statement=_STATEMENT, source_connection="warehouse")
            )

        message = str(raised.value)
        assert "--table" in message
        assert "DESTINATION" in message

    def test_a_statement_with_a_table_and_no_destination_connection(
        self,
    ) -> None:
        """The destination's connection, and the message must say so.

        Two connections exist now. "Add --connection" without saying which
        end is exactly the ambiguity this wording prevents.
        """
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(
                _args(statement=_STATEMENT, source_connection="warehouse",
                      table="landing.records")
            )

        message = str(raised.value)
        assert "--connection" in message
        assert "DESTINATION" in message

    def test_a_source_connection_with_no_statement(self) -> None:
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(
                _args(source_connection="warehouse", table="landing.records",
                      connection="reporting")
            )

        assert "--statement" in str(raised.value)

    def test_a_destination_with_no_source_at_all_still_refuses(self) -> None:
        """The refusal the obstruction was written for, widened.

        It used to say "add --file". A statement is a source too, so it now
        offers both -- and still refuses, because a destination alone says
        nothing about what to put in it.
        """
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(
                _args(table="landing.records", connection="reporting")
            )

        message = str(raised.value)
        assert "--file" in message and "--statement" in message


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
    """Which entry point a query invocation reaches."""

    @staticmethod
    def _run(args: argparse.Namespace) -> dict:
        seen: dict = {}

        def _capture(_ctx, _log, statement, source_connection, destination,
                     connection, **kwargs):
            seen.update(statement=statement,
                        source_connection=source_connection,
                        destination=destination, connection=connection,
                        **kwargs)
            return 7

        with patch.object(rey_loader_main, "run_load_query", _capture), \
             patch.object(rey_loader_main, "run_load_direct") as direct, \
             patch.object(rey_loader_main, "run_load_one") as one, \
             patch.object(rey_loader_main, "run_load") as every:
            rey_loader_main._execute_app_command(
                _NS(), _NS(), args, True, _NS(info=lambda *_a: None),
            )

        seen["other_shapes_untouched"] = not any(
            (direct.called, one.called, every.called)
        )
        return seen

    def test_a_query_invocation_reaches_the_query_wrapper_verbatim(
        self,
    ) -> None:
        seen = self._run(_whole(create=True))

        assert seen["statement"] == _STATEMENT
        assert seen["source_connection"] == "warehouse"
        assert seen["destination"] == "landing.records"
        assert seen["connection"] == "reporting"
        assert seen["create_destination"] is True

    def test_it_takes_no_other_shape(self) -> None:
        """One branch, and the file shapes are not consulted."""
        assert self._run(_whole())["other_shapes_untouched"]


class TestTheQueryEntryPoint:
    """What run_load_query does with what it is given."""

    def test_it_reaches_the_library_with_the_arguments_verbatim(
        self, run_log
    ) -> None:
        seen: dict = {}

        def _capture(_ctx, _log, statement, source_connection, destination,
                     connection, **kwargs):
            seen.update(statement=statement,
                        source_connection=source_connection,
                        destination=destination, connection=connection,
                        **kwargs)
            return 5

        with patch.object(load_module, "_load_query_to_table", _capture):
            total = load_module.run_load_query(
                _NS(), run_log, _STATEMENT, "warehouse",
                "landing.records", "reporting", create_destination=True,
            )

        assert total == 5
        assert seen["statement"] == _STATEMENT
        assert seen["source_connection"] == "warehouse"
        assert seen["destination"] == "landing.records"
        assert seen["connection"] == "reporting"
        assert seen["create_destination"] is True

    def test_an_empty_statement_is_refused_before_any_connection(
        self, run_log
    ) -> None:
        """The sibling of "no such file", and for the same reason.

        Letting an empty statement reach the database turns a mistyped
        invocation into a provider syntax error, which names the wrong thing.
        """
        def _never(*_a, **_k):
            raise AssertionError("reached the library with no statement")

        with patch.object(load_module, "_load_query_to_table", _never):
            with pytest.raises(ReyLoaderError) as raised:
                load_module.run_load_query(
                    _NS(), run_log, "   ", "warehouse",
                    "landing.records", "reporting",
                )

        assert "--statement" in str(raised.value)


class TestTheStatementCanComeFromAFile:
    """``--sql-file`` is a TRANSPORT for the statement, not a second source.

    A statement long enough to be worth version-controlling cannot be pasted
    onto a command line and cannot be reviewed in a diff. Both forms produce
    one QuerySource through one entry point, and nothing below the CLI learns
    which was used -- which is what these assert.
    """

    @staticmethod
    def _written(tmp_path, text: str) -> str:
        path = tmp_path / "query.sql"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_a_file_and_an_inline_statement_produce_the_same_text(
        self, tmp_path
    ) -> None:
        """THE ASSERTION THAT SAYS THIS IS A TRANSPORT.

        If the two forms ever diverged below this point, one of them would be
        a second source model.
        """
        from_file = rey_loader_main._statement_from(
            _args(sql_file=self._written(tmp_path, _STATEMENT))
        )
        inline = rey_loader_main._statement_from(_args(statement=_STATEMENT))

        assert from_file == inline == _STATEMENT

    def test_a_complete_file_invocation_is_not_refused(self, tmp_path) -> None:
        rey_loader_main._check_load_arguments(
            _args(sql_file=self._written(tmp_path, _STATEMENT),
                  source_connection="warehouse", table="landing.records",
                  connection="reporting")
        )

    def test_giving_both_forms_is_refused_and_names_both(self) -> None:
        """Nothing is left to choose between them."""
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(
                _whole(sql_file="query.sql")
            )

        message = str(raised.value)
        assert "--statement" in message and "--sql-file" in message

    def test_a_missing_file_is_refused_by_name(self) -> None:
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._statement_from(_args(sql_file="/nowhere/q.sql"))

        message = str(raised.value)
        assert "--sql-file" in message and "/nowhere/q.sql" in message

    def test_an_empty_file_is_refused(self, tmp_path) -> None:
        """A mistyped path or an unsaved editor.

        Letting it through reaches the database as a syntax error naming the
        wrong thing.
        """
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._statement_from(
                _args(sql_file=self._written(tmp_path, "   \n\n"))
            )

        assert "--sql-file" in str(raised.value)

    def test_the_whole_shape_is_proved_for_it_too(self, tmp_path) -> None:
        """THE NORMALISATION WORKING, not a second set of checks.

        Every refusal the inline form gets, this form gets -- because the
        guard reads "a query is named" once rather than testing two options
        everywhere.
        """
        given = self._written(tmp_path, _STATEMENT)

        for absent, expected in (
            ({"table": "landing.records", "connection": "reporting"},
             "--source-connection"),
            ({"source_connection": "warehouse"}, "--table"),
            ({"source_connection": "warehouse", "table": "landing.records"},
             "--connection"),
        ):
            with pytest.raises(ReyLoaderError) as raised:
                rey_loader_main._check_load_arguments(
                    _args(sql_file=given, **absent)
                )
            assert expected in str(raised.value), absent

    def test_a_file_source_reaches_the_query_wrapper(self, tmp_path) -> None:
        """One entry point, whichever transport was used."""
        seen = TestTheDispatch._run(
            _args(sql_file=self._written(tmp_path, _STATEMENT),
                  source_connection="warehouse", table="landing.records",
                  connection="reporting")
        )

        assert seen["statement"] == _STATEMENT
        assert seen["other_shapes_untouched"]
