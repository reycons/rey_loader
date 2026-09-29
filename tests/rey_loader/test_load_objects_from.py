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
                out_file="", transform="", transform_file="")
    base.update(kwargs)
    return argparse.Namespace(**base)


class TestEachArgumentGoesToItsObject:

    def test_the_mapping_is_the_objects_vocabulary(self) -> None:
        assert set(rey_loader_main._SOURCE_ARGUMENTS.values()) == set(SOURCE_FIELDS) - {
            "file-manifest-id", "file-mutation-id", "file-type-id",
        }
        assert set(rey_loader_main._TRANSFORM_ARGUMENTS.values()) == set(TRANSFORM_PARAMETERS)
        assert set(rey_loader_main._TARGET_ARGUMENTS.values()) == set(TARGET_PARAMETERS)

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
