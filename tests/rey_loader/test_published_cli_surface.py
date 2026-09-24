"""What the Console is offered for each command, against what main.py reads.

The screen used to show every parameter of every command at once, because the
registration declared one flat list carried by a positional ``command``
parameter and ``_commands`` gives each synthesised command the whole union. So
``run-workflow`` offered a destination table, and ``load`` offered ``source`` --
an sql_step name no load path reads. The two only looked related because they
were shown together.

These assert the declaration against **what main.py actually consumes**, which
is the only thing that makes a per-command split honest rather than a tidier
guess.

THE GOVERNING CONSTRAINT is workflow.publish_an_app_capability step 5: *"keep
the CLI dict equal to what main.py accepts. A command the parser exposes and the
registration omits is a command the Console will refuse to run."* The parser is
flat -- every option is accepted with every command -- so narrowing here removes
no invocation, but only while every command survives and every parameter stays
reachable. Both are asserted below.
"""

from __future__ import annotations

from typing import Any

from rey_loader.registration import get_registration


#: What each command reads, measured from main.py:
#:
#:   _run_workflow_command   args.workflow, args.source
#:   _execute_app_command    transform -> nothing; load -> the load options;
#:                           all -> apply only; sql -> args.source
#:
#: dry-run is `apply`, which main() derives for every command that branches on
#: it. `transform` does not: run_transform(ctx) runs whether or not a run
#: applies, so offering it a dry-run control would be a control with nothing
#: behind it.
CONSUMED: dict[str, set[str]] = {
    "run-workflow": {"workflow", "source", "dry-run"},
    "transform": set(),
    "load": {"file", "data-source", "table", "connection", "create",
             "file-type", "dry-run"},
    "all": {"dry-run"},
    "sql": {"source", "dry-run"},
}


def commands() -> dict[str, dict[str, Any]]:
    return {one["name"]: one for one in get_registration()["cli"]["commands"]}


def parameters(command: str) -> dict[str, dict[str, Any]]:
    return {one["name"]: one for one in commands()[command]["parameters"]}


class TestEachCommandDeclaresWhatItReads:

    def test_every_command_is_published(self) -> None:
        assert set(commands()) == set(CONSUMED)

    def test_each_declares_exactly_the_parameters_it_consumes(self) -> None:
        for command, expected in CONSUMED.items():
            assert set(parameters(command)) == expected, command

    def test_source_is_not_offered_to_a_load(self) -> None:
        """The reported confusion, stated as a test.

        `source` is the sql_step name for an sql or sql_apply workflow. No load
        path reads it, and a reader asked to tell it apart from `file` was
        being asked to distinguish two things that were never related.
        """
        assert "source" not in parameters("load")
        assert "source" in parameters("sql")
        assert "source" in parameters("run-workflow")

    def test_a_workflow_run_is_not_offered_a_destination(self) -> None:
        offered = set(parameters("run-workflow"))
        assert not offered & {"table", "connection", "create", "file-type",
                              "data-source", "file"}


class TestTheRecipesInvariants:
    """workflow.publish_an_app_capability step 5, as two assertions."""

    def test_no_command_the_parser_exposes_was_dropped(self) -> None:
        # The five the positional `command` parameter used to carry. Losing one
        # is how run-workflow itself once became unrunnable from the Console.
        assert set(commands()) == {
            "run-workflow", "transform", "load", "all", "sql",
        }

    def test_every_parameter_is_reachable_from_some_command(self) -> None:
        # Narrowing per command must remove offers, never invocations.
        declared = {
            name
            for command in commands()
            for name in parameters(command)
        }
        assert declared == {
            "workflow", "source", "file", "data-source", "table", "connection",
            "create", "file-type", "dry-run",
        }

    def test_one_declaration_style_only(self) -> None:
        # _commands refuses cli.commands beside a positional `command`
        # parameter rather than choosing between them.
        cli = get_registration()["cli"]
        assert "commands" in cli
        assert not [
            one for one in cli.get("parameters") or []
            if one.get("positional")
        ]


class TestRequirednessIsNeverOverstated:
    """`required` is unconditional, wherever it is read.

    `legacy/inventory.py::_parameter_row` projects it into a reader-facing row
    carrying no mode information, so a parameter that is required only in one
    shape must not claim it. That is what `required_when` is for.
    """

    def test_only_workflow_is_unconditionally_required(self) -> None:
        # _run_workflow_command raises "run-workflow requires --workflow" with
        # no mode involved. Every other requirement depends on a load shape.
        required = {
            (command, name)
            for command in commands()
            for name, one in parameters(command).items()
            if one.get("required")
        }
        assert required == {("run-workflow", "workflow")}

    def test_the_load_alternatives_are_required_only_within_a_shape(self) -> None:
        for name in ("file", "data-source", "table", "connection"):
            one = parameters("load")[name]
            assert not one.get("required"), name
            assert one.get("required_when"), name


class TestTheLoadShapesReproduceTheInvocationMatrix:
    """Measured from main.py::_check_load_arguments and _execute_app_command.

        load                              run_load(ctx), every data source
        load --file X                     REFUSED, "does not say where it goes"
        load --file X --data-source D     run_load_one
        load --file X --table T --conn C  run_load_direct
        load --table T --conn C           REFUSED, needs --file
    """

    @staticmethod
    def _group() -> dict[str, Any]:
        return commands()["load"]["mode_groups"][0]

    def test_three_shapes_are_declared(self) -> None:
        assert [one["name"] for one in self._group()["modes"]] == [
            "discovery", "configured", "direct",
        ]

    def test_discovery_is_the_default_and_takes_nothing(self) -> None:
        """Bare `load` is a valid invocation and must stay the opening state.

        An earlier draft made `file` globally required, which would have
        deleted the discovery shape from the screen entirely.
        """
        assert self._group()["default"] == "discovery"
        for one in parameters("load").values():
            membership = one.get("mode_membership") or {}
            assert "discovery" not in membership.get("load_shape", []), one["name"]

    def test_each_shape_declares_exactly_its_own_options(self) -> None:
        shape = {
            name: set((one.get("mode_membership") or {}).get("load_shape", []))
            for name, one in parameters("load").items()
            if one.get("mode_membership")
        }
        assert shape == {
            "file": {"configured", "direct"},
            "data-source": {"configured"},
            "table": {"direct"},
            "connection": {"direct"},
            "create": {"direct"},
            "file-type": {"direct"},
        }

    def test_the_direct_only_options_are_exactly_the_direct_ones(self) -> None:
        """Against main.py's own set, not a list rewritten here."""
        from main import _DIRECT_ONLY_OPTIONS

        direct = {
            name for name, one in parameters("load").items()
            if (one.get("mode_membership") or {}).get("load_shape") == ["direct"]
        }
        assert direct == {
            name.replace("_", "-") for name in _DIRECT_ONLY_OPTIONS
        }


class TestTheClosedVocabularies:

    def test_file_type_offers_what_the_loader_accepts(self) -> None:
        from rey_lib.files.file_loader import supported_file_types

        assert parameters("load")["file-type"]["possible_values"] == (
            supported_file_types()
        )

    def test_file_type_says_what_empty_means(self) -> None:
        # data_file_for resolves the format from the suffix when none is
        # declared, so blank is a real answer rather than a missing one.
        assert parameters("load")["file-type"]["placeholder"] == "Auto detect"

    def test_connection_is_a_resolved_collection(self) -> None:
        assert parameters("load")["connection"]["possible_values_from"] == (
            "connections"
        )

    def test_data_source_is_deliberately_NOT_one(self) -> None:
        """It was, and it took the whole configuration load down.

        `applications._choices` raises when a declared source is absent from
        the context, and an installation that declares no `data_sources:` block
        has no such attribute -- admin is one. So the failure was not an empty
        dropdown for that installation, it was `build_ctx` raising for every
        application in it.

        `connections` is safe because a database-backed installation always
        carries one; `data_sources` is optional configuration.

        Asserted rather than left absent, so restoring it is a decision someone
        makes against this comment. The general fix is
        load_choices_cannot_come_from_an_optional_collection.
        """
        declared = parameters("load")["data-source"]

        assert "possible_values_from" not in declared
        assert declared["value_type"] == "string"


class TestExecutionModePlacement:

    def test_dry_run_is_declared_away_from_the_fields(self) -> None:
        # An execution mode is not part of what is being defined. Which
        # parameter that is belongs here; the Console recognises no name.
        for command in ("run-workflow", "load", "all", "sql"):
            assert parameters(command)["dry-run"]["placement"] == "action_bar", command

    def test_nothing_else_leaves_the_form(self) -> None:
        placed = {
            (command, name)
            for command in commands()
            for name, one in parameters(command).items()
            if one.get("placement") == "action_bar"
        }
        assert {name for _command, name in placed} == {"dry-run"}
