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

import pytest

import main as rey_loader_main
from rey_lib.errors.error_utils import ConfigError
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
                connection="", create=False, replace=False, recreate=False, append=False, file_type="",
                statement="", source_connection="", sql_file="",
                out_file="", transform="", transform_file="")
    base.update(kwargs)
    return argparse.Namespace(**base)


def _written(tmp_path, text: str) -> str:
    path = tmp_path / "transform.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _query(**over) -> argparse.Namespace:
    """A complete query-to-table invocation, with whatever transform is named."""
    return _args(statement=_STATEMENT, source_connection="w",
                 table="landing.records", connection="reporting", **over)


class TestTheTwoFormsAreOneDeclaration:
    """Inline and from a file, read by the canonical Transform alike."""

    def test_a_file_and_an_inline_declaration_reach_the_load_alike(
        self, canonical, tmp_path,
    ) -> None:
        canonical.run(_query(transform_file=_written(tmp_path, _YAML)))
        canonical.run(_query(transform=_YAML))

        from_file, inline = (call[0][1] for call in canonical.calls)
        assert from_file.columns == inline.columns == ["identifier", "label"]

    def test_json_is_read_by_the_same_reader(self, canonical) -> None:
        canonical.run(_query(
            transform='{"columns": [{"name": "identifier", "source": "a"}]}',
        ))

        assert canonical.boundary["transform"].columns == ["identifier"]

    def test_giving_both_forms_is_refused_and_names_both(self) -> None:
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(
                _query(transform=_YAML, transform_file="t.yaml")
            )

        message = str(raised.value)
        assert "--transform" in message and "--transform-file" in message


class TestNothingDeclaredIsNotAnEmptyDeclaration:
    """No declaration is the identity transform; a bad one is refused."""

    def test_no_declaration_is_the_identity_transform(self, canonical) -> None:
        canonical.run(_query())

        assert type(canonical.boundary["transform"]).__name__ == "IdentityTransform"

    @pytest.mark.parametrize(("given", "refused"), [
        ({"transform": "columns: []"}, "declares no columns"),
        ({"transform": "just a string"}, "not a declaration"),
    ])
    def test_a_bad_inline_declaration_is_refused(self, canonical, given, refused) -> None:
        with pytest.raises(ConfigError, match=refused):
            canonical.run(_query(**given))
        assert canonical.calls == []

    def test_an_empty_file_is_refused(self, canonical, tmp_path) -> None:
        with pytest.raises(ConfigError, match="holds no declaration"):
            canonical.run(_query(transform_file=_written(tmp_path, "  \n")))
        assert canonical.calls == []

    def test_a_missing_file_is_refused_by_name(self, canonical) -> None:
        with pytest.raises(ConfigError) as raised:
            canonical.run(_query(transform_file="/nowhere/t.yaml"))

        assert "/nowhere/t.yaml" in str(raised.value)
        assert canonical.calls == []


class TestItReachesTheLoad:

    def test_a_query_to_a_table_carries_it(self, canonical) -> None:
        canonical.run(_query(transform=_YAML))

        assert canonical.boundary["transform"].columns == ["identifier", "label"]

    def test_a_query_to_a_file_carries_it(self, canonical, tmp_path) -> None:
        canonical.run(_args(
            statement=_STATEMENT, source_connection="w", out_file="/tmp/rows.csv",
            transform_file=_written(tmp_path, _YAML),
        ))

        assert canonical.boundary["transform"].columns == ["identifier", "label"]

    def test_a_load_naming_none_carries_the_identity_transform(self, canonical) -> None:
        """Every load that says nothing about a transform loads its rows as they came."""
        canonical.run(_query())

        assert type(canonical.boundary["transform"]).__name__ == "IdentityTransform"
