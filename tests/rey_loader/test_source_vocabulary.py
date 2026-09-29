"""The loader's source parameters and the canonical Source speak one vocabulary.

The Source's field names ARE the loader's declared source parameters, so the
CLI, a panel and a workflow step all name a setting the same way. A parameter
added to the load command's source without a Source field -- or a Source field
no parameter declares -- would be one setting with two spellings, or a setting
one entry point cannot reach.
"""

from __future__ import annotations

from rey_lib.load.source import SOURCE_FIELDS
from rey_loader.registration import get_registration


def _load_source_parameters() -> set[str]:
    load = next(
        one for one in get_registration()["cli"]["commands"] if one["name"] == "load"
    )
    return {
        one["name"] for one in load["parameters"] if one.get("load_object") == "source"
    }


def test_every_source_parameter_is_a_source_field_and_no_more() -> None:
    assert _load_source_parameters() == set(SOURCE_FIELDS)
