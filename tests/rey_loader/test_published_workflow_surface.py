"""What this application publishes, and what its catalog will run.

Every operation publishes a JSON Schema contract of the settings its reader
takes (backlog 939). Four are dispatchers: they read an ``operation`` and take
different settings depending on which was named. file_operation's variants
differ in what they read, so its contract holds one variant per operation value;
the other three read the same settings whatever the value.
"""

from __future__ import annotations

from rey_loader.registration import get_registration
from rey_loader.workflow import build_process_registry


def published() -> dict[str, dict]:
    return {one["name"]: one for one in get_registration()["workflow_operations"]}


def contract(name: str) -> dict:
    return published()[name]["contract_definition"]


class TestPublicationAndCatalogAgree:

    def test_every_published_operation_is_in_the_catalog(self) -> None:
        assert set(published()) <= set(build_process_registry(object()))

    def test_the_catalog_holds_nothing_unpublished(self) -> None:
        assert set(build_process_registry(object())) <= set(published())


class TestTheDispatchers:
    """What each dispatcher reads, as its reader reads it."""

    def test_file_operation_holds_one_variant_per_operation(self) -> None:
        definition = contract("file_operation")
        chosen = [variant["properties"]["operation"]["const"] for variant in definition["oneOf"]]

        assert chosen == ["discover", "discover_file", "move", "delete"]
        assert definition["properties"]["operation"]["enum"] == chosen

    def test_each_file_operation_variant_requires_what_it_reads(self) -> None:
        required = {
            variant["properties"]["operation"]["const"]: set(variant["required"])
            for variant in contract("file_operation")["oneOf"]
        }

        assert required == {
            "discover": {"operation", "data_source", "path"},
            "discover_file": {"operation", "data_source", "path"},
            "move": {"operation", "data_source", "to"},
            "delete": {"operation"},
        }

    def test_sql_operation_requires_what_its_reader_refuses_without(self) -> None:
        """_process_sql_operation refuses every operation lacking any of these."""
        assert set(contract("sql_operation")["required"]) == {
            "operation", "procedure_map", "routine_binding", "connection",
        }

    def test_validate_publishes_the_one_value_its_reader_accepts(self) -> None:
        """_process_validate refuses anything but validate_file (#937)."""
        assert contract("validate")["properties"]["operation"]["enum"] == ["validate_file"]

    def test_etl_operation_publishes_its_two_operations(self) -> None:
        assert contract("etl_operation")["properties"]["operation"]["enum"] == [
            "transform_file", "load_file",
        ]


class TestTheGuardsSetting:
    """scope is declared data to the engine and semantics to this app."""

    @staticmethod
    def _scopes(definition: dict) -> list[dict]:
        holders = definition.get("oneOf") or [definition]
        return [holder for holder in holders if "scope" in holder.get("properties", {})], holders

    def test_every_operation_accepts_scope(self) -> None:
        """The guard wraps every handler, so any step may carry it."""
        for name in published():
            with_scope, holders = self._scopes(contract(name))
            assert len(with_scope) == len(holders), name

    def test_scope_is_never_required(self) -> None:
        """A step that is not file-scoped simply does not say so."""
        for name in published():
            _with_scope, holders = self._scopes(contract(name))
            assert all("scope" not in holder.get("required", []) for holder in holders), name
