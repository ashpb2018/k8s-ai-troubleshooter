"""The tool catalogue must stay consistent with the operations facade."""

from __future__ import annotations

from kubemedic.agent import toolspec
from kubemedic.cluster.operations import ClusterOperations


def test_every_tool_maps_to_a_real_operation():
    for spec in toolspec.TOOL_SPECS:
        assert hasattr(ClusterOperations, spec.handler), spec.name


def test_tool_names_are_unique():
    names = toolspec.tool_names()
    assert len(names) == len(set(names))


def test_schemas_are_well_formed():
    schemas = toolspec.schemas()
    assert len(schemas) == len(toolspec.TOOL_SPECS)
    for schema in schemas:
        assert schema["name"]
        params = schema["parameters"]
        assert params["type"] == "object"
        # Required keys must exist in the declared properties.
        for required in params["required"]:
            assert required in params["properties"], (schema["name"], required)


def test_handler_lookup_is_none_for_unknown_tool():
    assert toolspec.handler_for("does_not_exist") is None
    assert toolspec.handler_for("cluster_triage") == "triage"
