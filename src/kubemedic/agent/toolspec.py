"""Tool catalogue exposed to the LLM.

Each :class:`ToolSpec` carries the JSON schema the model sees plus the name of
the :class:`~kubemedic.cluster.operations.ClusterOperations` method that backs
it. Keeping the two names separate lets the wire-facing tool name and the
Python method evolve independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    handler: str
    description: str
    properties: dict[str, Any] = field(default_factory=dict)
    required: tuple[str, ...] = ()

    def to_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": self.properties,
                "required": list(self.required),
            },
        }


def _string(desc: str) -> dict:
    return {"type": "string", "description": desc}


def _int(desc: str) -> dict:
    return {"type": "integer", "description": desc}


def _bool(desc: str) -> dict:
    return {"type": "boolean", "description": desc}


_CATALOGUE: tuple[ToolSpec, ...] = (
    ToolSpec(
        "cluster_triage",
        "triage",
        "Summarise overall cluster health: node readiness, troubled and pending "
        "pods, and recent warning events. Start most investigations here.",
    ),
    ToolSpec(
        "list_namespaces",
        "list_namespaces",
        "List all namespaces and their phase.",
    ),
    ToolSpec(
        "list_pods",
        "list_pods",
        "List pods in a namespace with ready count, status, restarts and age. "
        "Reveals CrashLoopBackOff, ImagePullBackOff, Pending and OOMKilled pods.",
        {
            "namespace": _string("Namespace (default: 'default')"),
            "selector": _string("Optional label selector, e.g. 'app=nginx'"),
        },
    ),
    ToolSpec(
        "pod_logs",
        "pod_logs",
        "Read recent logs from a pod. Set previous=true to read the last crashed "
        "container instance.",
        {
            "pod": _string("Pod name"),
            "namespace": _string("Namespace"),
            "container": _string("Container name (needed for multi-container pods)"),
            "previous": _bool("Read the previously terminated container's logs"),
        },
        required=("pod",),
    ),
    ToolSpec(
        "events",
        "events",
        "List namespace events, warnings first. Good for scheduling failures, "
        "image pull errors and OOM kills.",
        {
            "namespace": _string("Namespace"),
            "field_selector": _string("e.g. 'involvedObject.name=my-pod' or 'type=Warning'"),
        },
    ),
    ToolSpec(
        "describe_pod",
        "describe_pod",
        "Detailed view of a pod: container state, resource requests/limits, "
        "conditions and node assignment.",
        {"pod": _string("Pod name"), "namespace": _string("Namespace")},
        required=("pod",),
    ),
    ToolSpec(
        "list_nodes",
        "list_nodes",
        "List cluster nodes with status, roles, age and kubelet version.",
    ),
    ToolSpec(
        "describe_node",
        "describe_node",
        "Detailed node view: conditions, capacity and allocatable resources.",
        {"node": _string("Node name")},
        required=("node",),
    ),
    ToolSpec(
        "list_deployments",
        "list_deployments",
        "List deployments in a namespace with replica health.",
        {"namespace": _string("Namespace")},
    ),
    ToolSpec(
        "list_services",
        "list_services",
        "List services in a namespace with type, cluster IP and ports.",
        {"namespace": _string("Namespace")},
    ),
    ToolSpec(
        "list_pvcs",
        "list_pvcs",
        "List PersistentVolumeClaims in a namespace.",
        {"namespace": _string("Namespace")},
    ),
    ToolSpec(
        "resource_quotas",
        "resource_quotas",
        "Show resource quota usage in a namespace to detect exhaustion.",
        {"namespace": _string("Namespace")},
    ),
    ToolSpec(
        "kubectl",
        "kubectl",
        "Run an arbitrary kubectl command for anything the other tools do not "
        "cover, e.g. 'top nodes' or 'get ingress -A'. Mutating verbs prompt for "
        "confirmation.",
        {"command": _string("kubectl arguments, everything after 'kubectl'")},
        required=("command",),
    ),
    # --- remediation ---
    ToolSpec(
        "restart_deployment",
        "restart_deployment",
        "Rolling-restart a deployment (like 'kubectl rollout restart'). Prefer "
        "this before changing configuration.",
        {"name": _string("Deployment name"), "namespace": _string("Namespace")},
        required=("name",),
    ),
    ToolSpec(
        "scale_deployment",
        "scale_deployment",
        "Scale a deployment to a target replica count.",
        {
            "name": _string("Deployment name"),
            "replicas": _int("Target replica count"),
            "namespace": _string("Namespace"),
        },
        required=("name", "replicas"),
    ),
    ToolSpec(
        "rollback_deployment",
        "rollback_deployment",
        "Roll a deployment back to its previous or a specific revision.",
        {
            "name": _string("Deployment name"),
            "namespace": _string("Namespace"),
            "revision": _int("Revision to roll back to (0 = previous)"),
        },
        required=("name",),
    ),
    ToolSpec(
        "delete_pod",
        "delete_pod",
        "Delete a pod so its controller recreates it. Useful for wedged pods.",
        {"pod": _string("Pod name"), "namespace": _string("Namespace")},
        required=("pod",),
    ),
    ToolSpec(
        "apply_manifest",
        "apply_manifest",
        "Apply a complete YAML manifest to create or update resources.",
        {"manifest_yaml": _string("Full YAML manifest")},
        required=("manifest_yaml",),
    ),
    ToolSpec(
        "patch_resource",
        "patch_resource",
        "Apply a JSON merge patch to an existing resource.",
        {
            "kind": _string("Resource kind, e.g. deployment, service, configmap"),
            "name": _string("Resource name"),
            "namespace": _string("Namespace"),
            "merge_patch": _string('JSON merge patch, e.g. {"spec":{"replicas":3}}'),
        },
        required=("kind", "name", "namespace", "merge_patch"),
    ),
)


TOOL_SPECS: tuple[ToolSpec, ...] = _CATALOGUE
_BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in _CATALOGUE}


def schemas() -> list[dict]:
    """The JSON schemas handed to a backend."""
    return [spec.to_schema() for spec in _CATALOGUE]


def handler_for(name: str) -> str | None:
    """Return the ClusterOperations method name backing a tool, if known."""
    spec = _BY_NAME.get(name)
    return spec.handler if spec else None


def tool_names() -> list[str]:
    return list(_BY_NAME)
