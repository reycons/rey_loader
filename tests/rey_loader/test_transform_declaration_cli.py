"""A load can be handed the declaration its transform applies.

    --transform        inline
    --transform-file   from a file

THE SIBLING OF ``--statement`` / ``--sql-file``, and for the same reason: a
declaration worth reviewing cannot be pasted onto a command line and cannot be
read in a diff. Both forms produce one declaration through one normaliser, and
nothing below the CLI learns which was used.

It is NOT a registry. An argument stores nothing and declares nothing
permanent; it carries the shape a ``transforms:`` block already holds, which
is where transform declarations are owned.
"""

from __future__ import annotations

import argparse
from types import SimpleNamespace as _NS
from unittest.mock import patch

import pytest

import main as rey_loader_main
from rey_loader.error_utils import ReyLoaderError

_STATEMENT = "select a, b from orders"
_YAML = """
columns:
  - name: identifier
    source: a
  - name: label
    source: b
"""


def _args(**kwargs) -> argparse.Namespace:
    base = dict(command="load", file="", data_source="", table="",
                connection="", create=False, replace=False, append=False, file_type="",
                statement="", source_connection="", sql_file="",
                out_file="", transform="", transform_file="")
    base.update(kwargs)
    return argparse.Namespace(**base)


def _written(tmp_path, text: str) -> str:
    path = tmp_path / "transform.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


class TestTheTwoFormsAreOneDeclaration:

    def test_a_file_and_an_inline_declaration_read_the_same(self, tmp_path) -> None:
        """THE ASSERTION THAT SAYS THIS IS A TRANSPORT.

        If they diverged below this point, one of them would be a second way
        of declaring a transform -- which is the registry this must not be.
        """
        from_file = rey_loader_main._transform_from(
            _args(transform_file=_written(tmp_path, _YAML))
        )
        inline = rey_loader_main._transform_from(_args(transform=_YAML))

        assert from_file == inline
        assert [one["name"] for one in inline["columns"]] == ["identifier", "label"]

    def test_json_is_read_by_the_same_reader(self) -> None:
        """YAML is a superset of JSON, so a caller sending JSON needs no
        second reader -- which is what lets a browser and an operator use one
        declaration shape.
        """
        declared = rey_loader_main._transform_from(
            _args(transform='{"columns": [{"name": "a", "source": "A"}]}')
        )

        assert declared == {"columns": [{"name": "a", "source": "A"}]}

    def test_giving_both_forms_is_refused_and_names_both(self) -> None:
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(
                _args(statement=_STATEMENT, source_connection="w",
                      table="t", connection="c",
                      transform=_YAML, transform_file="t.yaml")
            )

        message = str(raised.value)
        assert "--transform" in message and "--transform-file" in message
        assert "TRANSFORM" in message


class TestNothingDeclaredIsNotAnEmptyDeclaration:

    def test_no_declaration_answers_with_nothing(self) -> None:
        """None means "load the rows as they came".

        An empty declaration would mean a load that produces no columns at
        all, and the two must not collapse into each other.
        """
        assert rey_loader_main._transform_from(_args()) is None

    def test_a_declaration_with_no_columns_is_refused(self) -> None:
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._transform_from(_args(transform="columns: []"))

        assert "declares no columns" in str(raised.value)

    def test_an_empty_file_is_refused(self, tmp_path) -> None:
        """A mistyped path or an unsaved editor.

        Letting it through would silently load untransformed rows, which is a
        load that ran and did the wrong thing rather than one that refused.
        """
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._transform_from(
                _args(transform_file=_written(tmp_path, "   \n\n"))
            )

        assert "--transform-file" in str(raised.value)

    def test_a_missing_file_is_refused_by_name(self) -> None:
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._transform_from(
                _args(transform_file="/nowhere/transform.yaml")
            )

        message = str(raised.value)
        assert "--transform-file" in message and "/nowhere" in message

    def test_something_that_is_not_a_declaration_is_refused(self) -> None:
        with pytest.raises(ReyLoaderError):
            rey_loader_main._transform_from(_args(transform="just a string"))


class TestItReachesTheLoad:

    @staticmethod
    def _run(args: argparse.Namespace) -> dict:
        seen: dict = {}

        def _capture(_ctx, _log, *positional, **kwargs):
            seen.update(kwargs)
            return 3

        with patch.object(rey_loader_main, "run_load_query", _capture), \
             patch.object(rey_loader_main, "run_load_query_to_file", _capture):
            rey_loader_main._execute_app_command(
                _NS(), _NS(), args, True, _NS(info=lambda *_a: None),
            )
        return seen

    def test_a_query_to_a_table_carries_it(self) -> None:
        seen = self._run(_args(
            statement=_STATEMENT, source_connection="w",
            table="landing.records", connection="reporting", transform=_YAML,
        ))

        assert [one["name"] for one in seen["transform"]["columns"]] == [
            "identifier", "label",
        ]

    def test_a_query_to_a_file_carries_it(self, tmp_path) -> None:
        seen = self._run(_args(
            statement=_STATEMENT, source_connection="w",
            out_file="/tmp/rows.csv",
            transform_file=_written(tmp_path, _YAML),
        ))

        assert [one["name"] for one in seen["transform"]["columns"]] == [
            "identifier", "label",
        ]

    def test_a_load_naming_none_carries_none(self) -> None:
        """THE REGRESSION THAT MATTERS.

        Every load that says nothing about a transform must reach the library
        exactly as it did before.
        """
        seen = self._run(_args(
            statement=_STATEMENT, source_connection="w",
            table="landing.records", connection="reporting",
        ))

        assert seen["transform"] is None
