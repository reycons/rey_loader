"""What this application publishes, and what its catalog will run.

Four of the eight are dispatchers: they read an ``operation`` and accept a
different subset of the rest depending on which was named. The published
contract is the union that dispatcher intentionally accepts, with requiredness
declared only where it holds whatever the operation is. What a selected
operation additionally requires is validated inside this application.
"""

from __future__ import annotations

from rey_loader.registration import get_registration
from rey_loader.workflow import build_process_registry


def published() -> dict[str, dict]:
    return {one["name"]: one for one in get_registration()["workflow_operations"]}


class TestPublicationAndCatalogAgree:

    def test_every_published_operation_is_in_the_catalog(self) -> None:
        assert set(published()) <= set(build_process_registry(object()))

    def test_the_catalog_holds_nothing_unpublished(self) -> None:
        assert set(build_process_registry(object())) <= set(published())


class TestTheDispatchers:
    """Requiredness holds whatever the operation is; the rest is app-owned."""

    def test_a_dispatcher_requires_only_its_operation(self) -> None:
        for name in ("file_operation", "sql_operation", "validate", "etl_operation"):
            required = {
                one["name"] for one in published()[name]["parameters"]
                if one["required"]
            }
            assert required == {"operation"}, name

    def test_an_operation_publishes_the_values_it_accepts(self) -> None:
        """An author reads which operations exist from the contract."""
        operation = next(
            one for one in published()["file_operation"]["parameters"]
            if one["name"] == "operation"
        )

        assert set(operation["possible_values"]) == {
            "discover", "discover_file", "move", "delete",
        }

    def test_operation_specific_requirements_are_not_published(self) -> None:
        """sql_operation refuses without a procedure_map, and says so itself.

        Declaring that outside would make the generic engine hold rey_loader's
        semantics, and would refuse the operations that legitimately omit it.
        """
        procedure_map = next(
            one for one in published()["sql_operation"]["parameters"]
            if one["name"] == "procedure_map"
        )

        assert procedure_map["required"] is False


class TestTheGuardsSetting:
    """scope is declared data to the engine and semantics to this app."""

    def test_every_operation_accepts_scope(self) -> None:
        """The guard wraps every handler, so any step may carry it."""
        for name, operation in published().items():
            names = {one["name"] for one in operation["parameters"]}
            assert "scope" in names, name

    def test_scope_is_never_required(self) -> None:
        """A step that is not file-scoped simply does not say so."""
        for name, operation in published().items():
            scope = next(
                one for one in operation["parameters"] if one["name"] == "scope"
            )
            assert scope["required"] is False, name
