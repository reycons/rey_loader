"""The loader's destination parameters and the canonical Target speak one vocabulary.

The Target's fields ARE the loader's declared destination parameters, so the
CLI, a panel and a workflow step name a destination setting the same way. And
the load shape derived from the Source and Target is one the loader declares,
drawing exactly the destination parameters of the Target kind that raised it.
"""

from __future__ import annotations

from typing import Any

from rey_lib.load.shape import LOAD_SHAPES
from rey_lib.load.target import TARGET_KINDS, TARGET_PARAMETERS
from rey_loader.registration import get_registration

_LOAD_SHAPE = "load_shape"


def _load() -> dict[str, Any]:
    """The load command, as the loader registers it."""
    return next(
        one for one in get_registration()["cli"]["commands"] if one["name"] == "load"
    )


def _destination_parameters() -> list[dict[str, Any]]:
    """The load command's parameters that belong to the destination object."""
    return [one for one in _load()["parameters"] if one.get("load_object") == "destination"]


def test_every_destination_parameter_is_a_target_parameter_and_no_more() -> None:
    assert {one["name"] for one in _destination_parameters()} == set(TARGET_PARAMETERS)


def test_every_derived_shape_is_a_declared_load_shape() -> None:
    group = next(one for one in _load()["mode_groups"] if one["name"] == _LOAD_SHAPE)
    declared = {mode["name"] for mode in group["modes"]}

    assert set(LOAD_SHAPES.values()) <= declared


def test_each_derived_shape_draws_its_target_kinds_fields() -> None:
    fields = {kind.id: set(kind.fields) for kind in TARGET_KINDS}
    for (_source_kind, target_kind), shape in LOAD_SHAPES.items():
        drawn = {
            one["name"] for one in _destination_parameters()
            if shape in (one.get("mode_membership") or {}).get(_LOAD_SHAPE, [])
        }
        assert drawn == fields[target_kind], shape
