"""Load a file into a table over a connection, with no configuration at all.

The request that started this: load a JSON file into `testing.asset`. For a
long time the only answer was "author a data_sources: block first". This is
the surface that answers it, and it is thin because the object graph beneath
it was built first.

    load --file asset.jsonl --table testing.asset --connection rey_loader

**Two single-file modes, and they must not collapse.** `--file` already meant
something: with `--data-source` it is the configured path. The obvious way to
add a direct mode is to make `--file` require `--table`, which silently
removes the surface that already exists.

    CONFIGURED   --file --data-source        the definition decides
    DIRECT       --file --table --connection the arguments decide

A third, `--statement --source-connection --table --connection`, arrived with
the database source; the file shapes here are unchanged by it.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace as _NS
from unittest.mock import patch

import pytest

import main as rey_loader_main
from rey_loader import load as load_module
from rey_lib.errors.error_utils import ConfigError
from rey_loader.error_utils import ReyLoaderError


def _args(**kwargs) -> argparse.Namespace:
    """A `load` invocation with everything absent unless named."""
    # Every option the parser defines, because _check_load_arguments reads
    # them directly -- a helper shorter than the parser tests a namespace no
    # invocation produces.
    base = dict(command="load", file="", data_source="", table="",
                connection="", create=False, replace=False, recreate=False, append=False, file_type="",
                statement="", source_connection="", sql_file="",
                out_file="", transform="", transform_file="")
    base.update(kwargs)
    return argparse.Namespace(**base)



def registered_option_names() -> set[str]:
    """Every option the registration publishes, across all its commands.

    The registration used to declare one flat ``cli.parameters`` list carried
    by a positional ``command`` parameter, so a name lived in exactly one
    place. It declares ``cli.commands`` now, one per command with exactly the
    parameters that invocation reads -- so a name lives under whichever
    commands read it, and the surface these tests guard is the union.

    The invariant is unchanged: the parser and the registration must offer the
    same options (workflow.publish_an_app_capability step 5).
    """
    from rey_loader.registration import CLI

    return {
        parameter["name"]
        for command in CLI["commands"]
        for parameter in command["parameters"]
    }


class TestTheTwoModes:
    """Both are valid; neither may swallow the other."""

    def test_the_configured_mode_still_works(self) -> None:
        """THE REGRESSION GUARD.

        Making --file depend on --table would remove the configured
        single-file surface entirely, and it would look like a tidy
        simplification while doing it.
        """
        rey_loader_main._check_load_arguments(
            _args(file="x.jsonl", data_source="advantage")
        )

    def test_the_direct_mode_is_accepted(self) -> None:
        rey_loader_main._check_load_arguments(
            _args(file="x.jsonl", table="s.t", connection="c")
        )

    def test_plain_discovery_is_untouched(self) -> None:
        """`load` with no arguments still discovers by pickup pattern."""
        rey_loader_main._check_load_arguments(_args())


class TestIncompleteFormsAreRefusedByTheObjects:
    """Completeness is the canonical objects' own refusal, reached through the CLI."""

    def test_a_table_with_no_connection(self, canonical, tmp_path: Path) -> None:
        source = tmp_path / "x.jsonl"
        source.write_text('{"a": 1}\n', encoding="utf-8")

        with pytest.raises(ConfigError) as raised:
            canonical.run(_args(file=str(source), table="s.t"))

        assert "Target" in str(raised.value) and "connection" in str(raised.value)
        assert canonical.calls == []

    def test_a_file_and_a_connection_with_no_table(self, canonical) -> None:
        """Still the kept invocation refusal: --file names no destination."""
        with pytest.raises(ReyLoaderError) as raised:
            canonical.run(_args(file="x.jsonl", connection="c"))

        assert "--table" in str(raised.value)
        assert canonical.calls == []

    def test_a_file_that_says_nowhere_to_put_it(self) -> None:
        """Neither a data source nor a destination: an ambiguous invocation, kept."""
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(_args(file="x.jsonl"))

        assert "--data-source" in str(raised.value)
        assert "--table" in str(raised.value)

    def test_a_data_source_without_a_file_is_refused(self, canonical) -> None:
        """Backlog 288: --data-source names how a FILE is loaded; alone it loaded every source."""
        with pytest.raises(ReyLoaderError) as raised:
            canonical.run(_args(data_source="d"))

        assert str(raised.value) == "--data-source names how a file is loaded; add --file."
        assert canonical.calls == []

    def test_direct_options_without_a_source(self, canonical) -> None:
        """A destination but nothing to put in it: the Source says what it needs."""
        with pytest.raises(ConfigError) as raised:
            canonical.run(_args(table="s.t", connection="c"))

        assert "Source" in str(raised.value) and "file" in str(raised.value)
        assert canonical.calls == []


class TestOptionOwnership:
    """A definition owns what it declares, so the CLI refuses to shadow it."""

    @pytest.mark.parametrize("option,declares", [
        ("table", "load.destination_table"),
        ("connection", "load.connection"),
        ("create", "load.create_destination_table"),
        ("file_type", "transforms[].file_type"),
    ])
    def test_a_direct_only_option_with_a_data_source_is_REFUSED(
        self, option: str, declares: str
    ) -> None:
        """Refused, NOT ignored -- which is the whole point.

        Every one of these parses cleanly and would do nothing, leaving the
        operator believing they had overridden the definition's destination,
        create policy or file type. A silent no-op flag is worse than a
        rejected one: it produces confident wrong beliefs.
        """
        value = True if option == "create" else "something"

        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(
                _args(file="x.jsonl", data_source="advantage", **{option: value})
            )

        message = str(raised.value)
        assert f"--{option.replace('_', '-')}" in message
        assert declares in message, "the refusal must say what already declares it"

    def test_the_refusal_offers_both_ways_out(self) -> None:
        """Drop the option, or drop --data-source. Either is a real answer."""
        with pytest.raises(ReyLoaderError) as raised:
            rey_loader_main._check_load_arguments(
                _args(file="x.jsonl", data_source="advantage", create=True)
            )

        assert "--data-source" in str(raised.value)


class TestTheDirectLoadRunsThroughTheObjects:
    """A direct file load, parsed into the objects and executed through them."""

    def test_the_file_and_table_reach_the_boundary_resolved(
        self, canonical, tmp_path: Path, run_log,
    ) -> None:
        source = tmp_path / "asset.jsonl"
        source.write_text('{"a": 1}\n', encoding="utf-8")

        canonical.run(_args(file=str(source), table="testing.asset",
                            connection="rey_loader", create=True, file_type="JSONL"),
                      run_log)

        seen = canonical.boundary
        assert str(seen["source"].path) == str(source)
        assert seen["target"].schema == "testing" and seen["target"].name == "asset"
        assert seen["target"].connection == "rey_loader"
        assert seen["loader"].create_destination is True
        assert seen["run_log"] is run_log

    @pytest.mark.parametrize(("flag", "attribute"), [
        ("replace", "replace_destination"), ("recreate", "recreate_destination"),
    ])
    def test_every_mode_reaches_the_boundary(
        self, canonical, tmp_path: Path, flag: str, attribute: str,
    ) -> None:
        """THE REGRESSION for rey_loader_direct_loads_pass_modes_the_wrappers_do_not_take.

        The old dispatch passed replace_destination= and recreate_destination=
        to a wrapper that took neither, so every direct load raised TypeError.
        """
        source = tmp_path / "asset.csv"
        source.write_text("a\n1\n", encoding="utf-8")

        canonical.run(_args(file=str(source), table="s.t", connection="c", **{flag: True}))

        assert getattr(canonical.boundary["loader"], attribute) is True

    def test_a_missing_file_is_refused_before_the_boundary(
        self, canonical, tmp_path: Path,
    ) -> None:
        with pytest.raises(ConfigError) as raised:
            canonical.run(_args(file=str(tmp_path / "gone.jsonl"), table="s.t", connection="c"))

        assert "gone.jsonl" in str(raised.value)
        assert canonical.calls == []


class TestTheSurfaceIsRegistered:
    """argparse is not the contract; registration.py is."""

    @staticmethod
    def _parser_options() -> set[str]:
        captured: set[str] = set()
        real_add = argparse.ArgumentParser.add_argument

        def _record(self, *args, **kwargs):
            for value in args:
                if isinstance(value, str) and value.startswith("--"):
                    captured.add(value[2:])
            return real_add(self, *args, **kwargs)

        with patch.object(argparse.ArgumentParser, "add_argument", _record), \
             patch.object(argparse.ArgumentParser, "parse_args",
                          return_value=argparse.Namespace()):
            rey_loader_main._parse_args()
        return captured

    def test_every_new_option_is_registered(self) -> None:
        registered = registered_option_names()

        for name in ("table", "connection", "create", "file-type"):
            assert name in registered
            assert name in self._parser_options()

    def test_the_parser_has_NO_encoding_option(self) -> None:
        """Deliberately not exposed, and this is what keeps it that way.

        file-type exists because a suffix naming no format makes a load
        impossible -- the flag is the only way through. Encoding has a working
        default and no such failure. If it is ever added it must join the
        direct-only rule, and this failing is the reminder.
        """
        assert "encoding" not in self._parser_options()
