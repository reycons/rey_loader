"""Point the CLI at one file and load it.

``load`` discovers files by pickup pattern across every configured data
source. An operator re-running a single delivery wants the file they name,
and there was no command path that selected one.

The capability already existed one layer down -- ``rey_lib``'s ``load_one``,
"Load exactly one file into its destination table. No discovery, no hooks."
So this is an argument and a dispatch over an existing mechanism, and these
tests assert the DISPATCH: which entry point was chosen, and what it was
handed.

**The data source must be named.** The installations that configure a loader
declare more than one, so it cannot be inferred -- and inferring it while only
one existed would become a silent change of meaning the moment a second was
added.
"""

from __future__ import annotations

import argparse
import inspect
from pathlib import Path
from types import SimpleNamespace as _NS
from unittest.mock import patch

import pytest

from rey_lib.files import file_loader
from rey_loader import load as load_module
from rey_loader.error_utils import ReyLoaderError


def _ctx(*names: str) -> _NS:
    """A context declaring one load per named data source, as lupo's does."""
    return _NS(
        sql_dir=None,
        data_sources=[
            _NS(name=name, loads=[_NS(name=f"{name}_load")]) for name in names
        ],
    )


@pytest.fixture
def source_file(tmp_path: Path) -> Path:
    path = tmp_path / "bal_20260922_v01.csv"
    path.write_text("a,b\n1,x\n", encoding="utf-8")
    return path



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


class TestItLoadsTheFileItWasGiven:
    """The outcome the row exists for."""

    def test_the_named_file_reaches_load_one(
        self, source_file: Path, run_log
    ) -> None:
        """Asserted by KEYWORD out of signature.bind().

        The pattern 220 established: a positional assertion once agreed with a
        call that could never run, because the index it checked happened to
        hold a different argument. A future parameter must not be able to make
        this agree with a mistake again.
        """
        with patch("rey_loader.load._load_one", autospec=True,
                   return_value=7) as one:
            total = load_module.run_load_one(
                _ctx("advantage_balance"), run_log,
                "advantage_balance", source_file,
            )

        bound = inspect.signature(file_loader.load_one).bind(
            *one.call_args[0], **one.call_args[1]
        )
        assert total == 7
        assert bound.arguments["file_path"] == source_file
        assert bound.arguments["run_log"] is run_log
        assert bound.arguments["data_source"].name == "advantage_balance"

    def test_it_never_reaches_discovery(
        self, source_file: Path, run_log
    ) -> None:
        """One named file is the opposite of scanning for files.

        run_load walks every data source's pickup pattern. Reaching it here
        would load files the operator did not ask for.
        """
        with patch("rey_loader.load._run_load",
                   side_effect=AssertionError("discovery must not run")), \
             patch("rey_loader.load._load_one", return_value=1):
            load_module.run_load_one(
                _ctx("advantage_balance"), run_log,
                "advantage_balance", source_file,
            )

    def test_the_load_config_comes_from_the_data_source(
        self, source_file: Path, run_log
    ) -> None:
        """Which is what carries the destination table and the transform."""
        with patch("rey_loader.load._load_one", autospec=True,
                   return_value=1) as one:
            load_module.run_load_one(
                _ctx("advantage", "advantage_balance"), run_log,
                "advantage_balance", source_file,
            )

        bound = inspect.signature(file_loader.load_one).bind(
            *one.call_args[0], **one.call_args[1]
        )
        assert bound.arguments["load_cfg"].name == "advantage_balance_load"


class TestWhatIsRefused:
    """Fail closed, and say which input was wrong."""

    def test_no_data_source_is_refused_by_name(
        self, source_file: Path, run_log
    ) -> None:
        """It cannot be inferred, so not naming one is not a default."""
        with pytest.raises(ReyLoaderError) as raised:
            load_module.run_load_one(
                _ctx("advantage_balance"), run_log, "", source_file
            )

        assert "--data-source" in str(raised.value)

    def test_an_unknown_data_source_is_refused_by_name(
        self, source_file: Path, run_log
    ) -> None:
        """Refused by the shared lookup, not by a second copy of it."""
        with pytest.raises(ReyLoaderError) as raised:
            load_module.run_load_one(
                _ctx("advantage_balance"), run_log, "not_a_source", source_file
            )

        assert "not_a_source" in str(raised.value)

    def test_a_file_that_is_not_there_is_refused_before_any_connection(
        self, tmp_path: Path, run_log
    ) -> None:
        """Opening a database to discover the file is missing would be waste."""
        with patch("rey_loader.load._load_one",
                   side_effect=AssertionError("must not reach the loader")):
            with pytest.raises(ReyLoaderError) as raised:
                load_module.run_load_one(
                    _ctx("advantage_balance"), run_log,
                    "advantage_balance", tmp_path / "absent.csv",
                )

        assert "absent.csv" in str(raised.value)


class TestTheResolversAreReusedNotRewritten:
    """One mechanism, not two that can disagree."""

    def test_it_calls_the_workflows_own_lookups(
        self, source_file: Path, run_log
    ) -> None:
        """_data_source and _first_load already answer this, and fail closed.

        A second lookup here would be the same question answered twice, free
        to drift -- the workflow would resolve a data source one way and the
        CLI another.
        """
        with patch("rey_loader.workflow._data_source",
                   return_value=_NS(name="ds", loads=[_NS(name="ld")])) as ds, \
             patch("rey_loader.workflow._first_load",
                   return_value=_NS(name="ld")) as fl, \
             patch("rey_loader.load._load_one", return_value=1):
            load_module.run_load_one(
                _ctx("advantage_balance"), run_log,
                "advantage_balance", source_file,
            )

        assert ds.called and fl.called


class TestTheSurfaceIsRegistered:
    """argparse is not the contract; registration.py is."""

    @staticmethod
    def _parser_argument_names() -> set[str]:
        """Every option the real parser accepts, as registration spells them."""
        import main as rey_loader_main

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

    def test_every_parser_option_is_registered(self) -> None:
        """A pipeline-step assembler reads the registration, not the parser.

        An argument added to one and not the other makes the published surface
        disagree with the CLI, and the disagreement stays invisible until a
        pipeline builds an invocation the app then rejects. Compared as SETS,
        so this catches the next argument too, not only the two added here.
        """
        from rey_loader.registration import CLI

        registered = registered_option_names() | {
            entry["name"] for entry in CLI["shared_parameters"]
        }
        # argparse supplies --help itself; it is not part of the contract.
        unregistered = self._parser_argument_names() - registered - {"help"}

        # Three shared options were already accepted and unregistered before
        # this row, all added by add_config_args rather than by main.py --
        # backlog rey_loader_registration_omits_three_shared_parameters.
        # Pinned EXACTLY rather than allowed loosely: a fourth fails here, and
        # so does fixing one without shrinking this set.
        assert unregistered == {"connection-alias", "log-level", "run-id"}, (
            f"CLI options accepted but not registered: {sorted(unregistered)}"
        )

    def test_the_two_this_row_adds_are_on_both_sides(self) -> None:
        """Named directly, because the set comparison above would also pass
        if the parser and the registration were both missing them."""
        registered = registered_option_names()
        accepted = self._parser_argument_names()

        for name in ("file", "data-source"):
            assert name in registered
            assert name in accepted
