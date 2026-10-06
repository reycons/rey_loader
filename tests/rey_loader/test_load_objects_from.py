"""The CLI parses; the canonical objects decide.

`_load_objects_from` puts each argument under the object and field it configures
and chooses no kind. `_execute_app_command` keeps the three entry paths apart:
direct options go to the canonical objects, `--file` with `--data-source` to the
configured load, and nothing to discovery.
"""

from __future__ import annotations

import argparse
from types import SimpleNamespace as _NS
from unittest.mock import patch

import main as rey_loader_main
from rey_lib.load.source import SOURCE_FIELDS
from rey_lib.load.target import TARGET_PARAMETERS
from rey_lib.load.transform import TRANSFORM_PARAMETERS


def _args(**kwargs) -> argparse.Namespace:
    base = dict(command="load", file="", data_source="", table="",
                connection="", create=False, replace=False, recreate=False, append=False,
                file_type="", statement="", source_connection="", sql_file="",
                out_file="", transform="", transform_file="",
                file_manifest_id="", file_mutation_id="", file_type_id="")
    base.update(kwargs)
    return argparse.Namespace(**base)


class TestEachArgumentGoesToItsObject:

    def test_the_mapping_is_the_objects_vocabulary(self) -> None:
        # EVERY SOURCE FIELD, the governed identities included: the registration
        # declares all three for `load`, so the parser accepts them.
        assert set(rey_loader_main._SOURCE_ARGUMENTS.values()) == set(SOURCE_FIELDS)
        assert set(rey_loader_main._TRANSFORM_ARGUMENTS.values()) == set(TRANSFORM_PARAMETERS)
        assert set(rey_loader_main._TARGET_ARGUMENTS.values()) == set(TARGET_PARAMETERS)

    def test_the_http_arguments_build_an_http_transform(self) -> None:
        # Backlog 668: the three land under the Transform's http fields, and
        # the Transform's own rule puts the http kind in force.
        _source, transform, _target = rey_loader_main._load_objects_from(_args(
            file="/in.csv", table="s.t", connection="c",
            http_connection="openfigi", http_adapter="openfigi",
            http_options='{"id_column": "symbol", "id_type": "TICKER", "batch_size": 100}',
        ))

        assert transform.selected_kind() == "http"
        assert transform.executed_declaration() == {
            "connection": "openfigi", "adapter": "openfigi",
            "options": {"id_column": "symbol", "id_type": "TICKER", "batch_size": 100},
            "declaration": None,
        }

    def test_http_transform_is_the_mapping_applied_before_sending(self) -> None:
        # Backlog 679: --http-transform lands under the Transform's field and
        # becomes the http kind's authored mapping.
        _source, transform, _target = rey_loader_main._load_objects_from(_args(
            file="/in.csv", table="s.t", connection="c",
            http_connection="openfigi", http_adapter="openfigi",
            http_transform='{"columns": [{"source": "cusip", "name": "lookup_id"}]}',
        ))

        assert transform.selected_kind() == "http"
        assert transform.executed_declaration()["declaration"] == {
            "columns": [{"source": "cusip", "name": "lookup_id"}],
        }

    def test_values_land_under_their_fields_and_no_kind_is_chosen(self) -> None:
        source, transform, target = rey_loader_main._load_objects_from(_args(
            statement="select 1", source_connection="w", table="s.t",
            connection="c", replace=True, transform="columns: []",
        ))

        assert source.declaration() == {
            "selected": None, "values": {"statement": "select 1", "source-connection": "w"},
        }
        assert transform.declaration() == {
            "selected": None, "values": {"transform": "columns: []"},
        }
        assert target.declaration() == {
            "selected": None, "values": {"table": "s.t", "connection": "c", "replace": True},
        }

    def test_nothing_given_is_nothing_held(self) -> None:
        objects = rey_loader_main._load_objects_from(_args())

        assert [one.declaration()["values"] for one in objects] == [{}, {}, {}]


class TestTheThreeEntryPathsStayApart:

    @staticmethod
    def _dispatch(args: argparse.Namespace) -> str:
        with patch.object(rey_loader_main, "run_load_objects") as objects, \
             patch.object(rey_loader_main, "run_load_one") as one, \
             patch.object(rey_loader_main, "run_load") as every:
            rey_loader_main._execute_app_command(
                _NS(), _NS(), args, True, _NS(info=lambda *_a: None),
            )
        taken = [name for name, mock in (
            ("objects", objects), ("configured", one), ("discovery", every),
        ) if mock.called]
        assert len(taken) == 1, taken
        return taken[0]

    def test_direct_options_reach_the_canonical_objects(self) -> None:
        assert self._dispatch(_args(file="f.csv", table="s.t", connection="c")) == "objects"
        assert self._dispatch(_args(statement="select 1", source_connection="w",
                                    out_file="/o.csv")) == "objects"

    def test_a_file_with_a_data_source_is_the_configured_load(self) -> None:
        assert self._dispatch(_args(file="f.csv", data_source="feed")) == "configured"

    def test_nothing_is_discovery(self) -> None:
        assert self._dispatch(_args()) == "discovery"


class TestAGovernedFileIsNamedByItsIdentity:

    def test_the_parser_accepts_the_three_identities(self) -> None:
        with patch("sys.argv", ["main.py", "load", "--file-manifest-id", "10",
                                "--file-mutation-id", "25", "--file-type-id", "4"]):
            args = rey_loader_main._parse_args()

        assert (args.file_manifest_id, args.file_mutation_id, args.file_type_id) == (
            "10", "25", "4")

    def test_a_file_with_its_mutation_is_a_file_source_and_a_direct_load(self) -> None:
        args = _args(file="/data/a.csv", file_mutation_id="1881",
                     table="s.t", connection="c")

        source, _, _ = rey_loader_main._load_objects_from(args)

        assert source.selected_kind() == "file"
        assert source.value("file-mutation-id") == "1881"
        assert rey_loader_main._names_a_direct_load(args) is True

    def test_an_identity_alone_is_a_manifest_source(self) -> None:
        source, _, _ = rey_loader_main._load_objects_from(_args(file_manifest_id="10"))

        assert source.selected_kind() == "manifest"


class TestAManifestSourceIsReadThroughTheRuntimesControl:

    def test_the_reader_is_passed_only_for_a_manifest_source(self) -> None:
        from rey_lib.load import Source, Target, Transform
        from rey_loader import load as load_module

        seen: list = []
        control = object()
        with patch.object(load_module, "run_selected_load",
                          lambda *a, reader=None: seen.append(reader) or 0), \
             patch.object(load_module, "open_shared_control",
                          lambda ctx: _NS(shared_control=control)):
            load_module.run_load_objects(_NS(), None, Source({"file-manifest-id": "10"}),
                                         Transform(), Target())
            load_module.run_load_objects(_NS(), None, Source({"file": "/a.csv"}),
                                         Transform(), Target())

        assert seen == [control, None]

