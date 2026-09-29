"""The loader's transform parameters and the canonical Transform speak one vocabulary.

The loader's transform parameters ARE the Transform's parameter fields, so the
CLI, a panel and a workflow step name a transform setting the same way. The
Transform also holds ``declaration`` and ``persistence`` -- a stored definition
and its identities -- which are its own fields and not loader parameters, so
the comparison is with ``TRANSFORM_PARAMETERS``, not every field it holds.
"""

from __future__ import annotations

from rey_lib.load.transform import TRANSFORM_PARAMETERS
from rey_loader.registration import get_registration


def _load_transform_parameters() -> set[str]:
    """The load command's parameters that belong to the transform object."""
    load = next(
        one for one in get_registration()["cli"]["commands"] if one["name"] == "load"
    )
    return {
        one["name"] for one in load["parameters"] if one.get("load_object") == "transform"
    }


def test_every_transform_parameter_is_a_transform_parameter_field_and_no_more() -> None:
    assert _load_transform_parameters() == set(TRANSFORM_PARAMETERS)
