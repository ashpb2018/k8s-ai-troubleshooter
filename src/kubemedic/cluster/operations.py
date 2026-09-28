"""The catalogue of Kubernetes operations the agent can invoke.

Read operations are always safe. Mutating operations route through
:meth:`ClusterOperations._guard`, which either auto-approves (when configured)
or defers to a confirmation callback supplied by the agent.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from kubernetes.client.rest import ApiException

from .client import ClusterClient
from .formatting import TextTable, fallback, humanise_age

ConfirmFn = Callable[[str], bool]

# Container waiting reasons that indicate a genuine problem.
_BAD_WAITING = {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "OOMKilled", "Error"}
# kubectl verbs that change cluster state and therefore need confirmation.
_MUTATING_VERBS = {"delete", "apply", "patch", "replace", "edit", "scale", "annotate", "label"}


class ClusterError(RuntimeError):
    pass


class ClusterOperations:
    def __init__(
        self,
        client: ClusterClient,
        *,
        max_log_lines: int = 200,
        auto_approve: bool = False,
    ) -> None:
        self._client = client
        self._max_log_lines = max_log_lines
        self._auto_approve = auto_approve
        # Injected by the agent; returns True to proceed with a mutation.
        self.confirm: ConfirmFn | None = None

    # ------------------------------------------------------------------ read

    def list_namespaces(self) -> str:
        table = TextTable([("NAME", 40), ("STATUS", 12), ("AGE", 6)])
        for ns in self._client.core.list_namespace().items:
            phase = ns.status.phase if ns.status else "Unknown"
            table.add(ns.metadata.name, phase, humanise_age(ns.metadata.creation_timestamp))
        return table.render(empty_message="No namespaces found.")

    def list_pods(self, namespace: str = "default", selector: str = "") -> str:
        kwargs = {"label_selector": selector} if selector else {}
        pods = self._client.core.list_namespaced_pod(namespace=namespace, **kwargs)
        if not pods.items:
            return f"No pods in namespace '{namespace}'."

        table = TextTable(
            [("NAME", 52), ("READY", 7), ("STATUS", 22), ("RESTARTS", 9), ("AGE", 6)]
        )
        for pod in pods.items:
            total = len(pod.spec.containers or [])
            ready = restarts = 0
            reason = pod.status.phase or "Unknown"
            for cs in pod.status.container_statuses or []:
                ready += 1 if cs.ready else 0
                restarts += cs.restart_count or 0
            for cs in pod.status.container_statuses or []:
                if cs.state.waiting and cs.state.waiting.reason:
                    reason = cs.state.waiting.reason
                    break
                if cs.state.terminated and cs.state.terminated.reason:
                    reason = cs.state.terminated.reason
                    break
            if pod.metadata.deletion_timestamp:
                reason = "Terminating"
            table.add(
                pod.metadata.name,
                f"{ready}/{total}",
                reason,
                restarts,
                humanise_age(pod.metadata.creation_timestamp),
            )
        return table.render()

    def pod_logs(
        self,
        pod: str,
        namespace: str = "default",
        container: str = "",
        previous: bool = False,
    ) -> str:
        kwargs: dict = {
            "name": pod,
            "namespace": namespace,
            "tail_lines": self._max_log_lines,
            "timestamps": True,
        }
        if container:
            kwargs["container"] = container
        if previous:
            kwargs["previous"] = True
        try:
            return self._client.core.read_namespaced_pod_log(**kwargs) or "(log is empty)"
        except ApiException as exc:
            if exc.status == 400:
                return f"{exc.reason}: try passing an explicit container name."
            return f"Could not read logs: {exc.reason}"

    def events(self, namespace: str = "default", field_selector: str = "") -> str:
        kwargs = {"namespace": namespace}
        if field_selector:
            kwargs["field_selector"] = field_selector
        items = self._client.core.list_namespaced_event(**kwargs).items
        if not items:
            return f"No events in namespace '{namespace}'."
        ordered = sorted(items, key=lambda e: 0 if e.type == "Warning" else 1)
        table = TextTable([("TYPE", 9), ("REASON", 28), ("OBJECT", 46), ("MESSAGE", 0)])
        for ev in ordered[:60]:
            obj = f"{ev.involved_object.kind}/{ev.involved_object.name}"
            message = (ev.message or "").replace("\n", " ")[:120]
            table.add(ev.type, ev.reason, obj, message)
        return table.render()

    def describe_pod(self, pod: str, namespace: str = "default") -> str:
        try:
            obj = self._client.core.read_namespaced_pod(name=pod, namespace=namespace)
        except ApiException as exc:
            return f"Could not read pod: {exc.reason}"

        lines = [
            f"Name:       {obj.metadata.name}",
            f"Namespace:  {obj.metadata.namespace}",
            f"Node:       {fallback(obj.spec.node_name)}",
            f"Phase:      {fallback(obj.status.phase)}",
            f"Pod IP:     {fallback(obj.status.pod_ip)}",
            f"Start Time: {fallback(obj.status.start_time)}",
            f"Labels:     {json.dumps(obj.metadata.labels or {})}",
            "",
            "Containers:",
        ]
        for c in obj.spec.containers or []:
            requests = (c.resources.requests if c.resources else None) or {}
            limits = (c.resources.limits if c.resources else None) or {}
            lines += [
                f"  - {c.name} ({c.image})",
                f"      requests: cpu={requests.get('cpu', '-')} mem={requests.get('memory', '-')}",
                f"      limits:   cpu={limits.get('cpu', '-')} mem={limits.get('memory', '-')}",
            ]
        if obj.status.container_statuses:
            lines += ["", "Container status:"]
            for cs in obj.status.container_statuses:
                lines.append(f"  - {cs.name}: ready={cs.ready} restarts={cs.restart_count}")
                state = cs.state
                if state.waiting:
                    lines.append(
                        f"      waiting: {state.waiting.reason} {state.waiting.message or ''}"
                    )
                elif state.terminated:
                    lines.append(
                        f"      terminated: {state.terminated.reason} "
                        f"exit={state.terminated.exit_code}"
                    )
                elif state.running:
                    lines.append(f"      running since {state.running.started_at}")
        for cond in obj.status.conditions or []:
            lines.append(f"  condition {cond.type}={cond.status} {cond.message or ''}")
        return "\n".join(lines)

    def list_nodes(self) -> str:
        table = TextTable(
            [("NAME", 42), ("STATUS", 10), ("ROLES", 18), ("AGE", 6), ("VERSION", 0)]
        )
        for node in self._client.core.list_node().items:
            roles = (
                ",".join(
                    key.split("/", 1)[1]
                    for key in (node.metadata.labels or {})
                    if key.startswith("node-role.kubernetes.io/")
                )
                or "worker"
            )
            status = "Unknown"
            for cond in node.status.conditions or []:
                if cond.type == "Ready":
                    status = "Ready" if cond.status == "True" else "NotReady"
                    break
            version = node.status.node_info.kubelet_version if node.status.node_info else "?"
            table.add(node.metadata.name, status, roles, humanise_age(node.metadata.creation_timestamp), version)
        return table.render(empty_message="No nodes found.")

    def describe_node(self, node: str) -> str:
        try:
            obj = self._client.core.read_node(name=node)
        except ApiException as exc:
            return f"Could not read node: {exc.reason}"
        lines = [f"Name: {obj.metadata.name}", "Conditions:"]
        for cond in obj.status.conditions or []:
            lines.append(f"  {cond.type}={cond.status} {cond.message or ''}")
        if obj.status.allocatable:
            lines.append(f"Allocatable: {dict(obj.status.allocatable)}")
        if obj.status.capacity:
            lines.append(f"Capacity:    {dict(obj.status.capacity)}")
        return "\n".join(lines)

    def list_deployments(self, namespace: str = "default") -> str:
        deps = self._client.apps.list_namespaced_deployment(namespace=namespace).items
        if not deps:
            return f"No deployments in namespace '{namespace}'."
        table = TextTable([("NAME", 42), ("READY", 9), ("UPDATED", 9), ("AVAILABLE", 11), ("AGE", 0)])
        for d in deps:
            s = d.status
            table.add(
                d.metadata.name,
                f"{s.ready_replicas or 0}/{d.spec.replicas or 0}",
                s.updated_replicas or 0,
                s.available_replicas or 0,
                humanise_age(d.metadata.creation_timestamp),
            )
        return table.render()

    def list_services(self, namespace: str = "default") -> str:
        svcs = self._client.core.list_namespaced_service(namespace=namespace).items
        if not svcs:
            return f"No services in namespace '{namespace}'."
        table = TextTable(
            [("NAME", 40), ("TYPE", 14), ("CLUSTER-IP", 17), ("PORTS", 24), ("AGE", 0)]
        )
        for svc in svcs:
            ports = ",".join(f"{p.port}/{p.protocol}" for p in (svc.spec.ports or [])) or "-"
            table.add(
                svc.metadata.name,
                svc.spec.type,
                fallback(svc.spec.cluster_ip),
                ports,
                humanise_age(svc.metadata.creation_timestamp),
            )
        return table.render()

    def list_pvcs(self, namespace: str = "default") -> str:
        pvcs = self._client.core.list_namespaced_persistent_volume_claim(namespace=namespace).items
        if not pvcs:
            return f"No PVCs in namespace '{namespace}'."
        table = TextTable([("NAME", 40), ("STATUS", 12), ("VOLUME", 40), ("CAPACITY", 10), ("AGE", 0)])
        for pvc in pvcs:
            capacity = dict(pvc.status.capacity or {}).get("storage", "?")
            table.add(
                pvc.metadata.name,
                pvc.status.phase,
                fallback(pvc.spec.volume_name),
                capacity,
                humanise_age(pvc.metadata.creation_timestamp),
            )
        return table.render()

    def resource_quotas(self, namespace: str = "default") -> str:
        try:
            quotas = self._client.core.list_namespaced_resource_quota(namespace=namespace).items
        except ApiException:
            return "Could not read resource quotas."
        if not quotas:
            return f"No resource quotas in namespace '{namespace}'."
        lines: list[str] = []
        for quota in quotas:
            lines.append(f"ResourceQuota {quota.metadata.name}:")
            hard = quota.status.hard or {}
            used = quota.status.used or {}
            for resource, limit in hard.items():
                lines.append(f"  {resource}: {used.get(resource, '?')} / {limit}")
        return "\n".join(lines)

    def triage(self) -> str:
        """A whole-cluster health summary — the usual first move."""
        sections: list[str] = []

        nodes = self._client.core.list_node().items
        not_ready = [
            n.metadata.name
            for n in nodes
            if not any(
                c.type == "Ready" and c.status == "True" for c in (n.status.conditions or [])
            )
        ]
        sections.append(
            f"Nodes: {len(nodes)} total, {len(not_ready)} NotReady"
            + (f" [{', '.join(not_ready)}]" if not_ready else "")
        )

        pods = self._client.core.list_pod_for_all_namespaces().items
        troubled: list[str] = []
        pending: list[str] = []
        for pod in pods:
            ref = f"{pod.metadata.namespace}/{pod.metadata.name}"
            phase = pod.status.phase or ""
            if phase == "Pending":
                pending.append(ref)
            if phase in ("Failed", "Unknown"):
                troubled.append(f"{ref} ({phase})")
                continue
            for cs in pod.status.container_statuses or []:
                if cs.state.waiting and cs.state.waiting.reason in _BAD_WAITING:
                    troubled.append(f"{ref} ({cs.state.waiting.reason})")
                    break
                if (cs.restart_count or 0) > 5:
                    troubled.append(f"{ref} (restarts={cs.restart_count})")
                    break

        sections.append(self._bulleted("Troubled pods", troubled))
        sections.append(self._bulleted("Pending pods", pending))

        warnings = self._client.core.list_event_for_all_namespaces(
            field_selector="type=Warning"
        ).items
        latest = sorted(
            warnings,
            key=lambda e: e.last_timestamp or e.event_time or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )[:10]
        warning_lines = [
            f"{e.involved_object.kind}/{e.involved_object.name}: {e.message or ''}" for e in latest
        ]
        sections.append(
            self._bulleted(f"Recent warning events ({len(warnings)} total, latest 10)", warning_lines)
        )
        return "\n\n".join(sections)

    @staticmethod
    def _bulleted(title: str, items: list[str]) -> str:
        if not items:
            return f"{title}: none"
        joined = "\n  ".join(items)
        return f"{title}: {len(items)}\n  {joined}"

    # -------------------------------------------------------------- mutating

    def restart_deployment(self, name: str, namespace: str = "default") -> str:
        if not self._guard(f"rolling-restart deployment {namespace}/{name}"):
            return "Cancelled."
        stamp = datetime.now(tz=timezone.utc).isoformat()
        patch = {
            "spec": {
                "template": {
                    "metadata": {"annotations": {"kubemedic.io/restartedAt": stamp}}
                }
            }
        }
        try:
            self._client.apps.patch_namespaced_deployment(name=name, namespace=namespace, body=patch)
            return f"Triggered a rolling restart of deployment {namespace}/{name}."
        except ApiException as exc:
            return f"Restart failed: {exc.reason}"

    def scale_deployment(self, name: str, replicas: int, namespace: str = "default") -> str:
        if not self._guard(f"scale deployment {namespace}/{name} to {replicas} replica(s)"):
            return "Cancelled."
        try:
            self._client.apps.patch_namespaced_deployment_scale(
                name=name, namespace=namespace, body={"spec": {"replicas": replicas}}
            )
            return f"Scaled deployment {namespace}/{name} to {replicas} replica(s)."
        except ApiException as exc:
            return f"Scale failed: {exc.reason}"

    def rollback_deployment(self, name: str, namespace: str = "default", revision: int = 0) -> str:
        target = revision or "previous"
        if not self._guard(f"roll back deployment {namespace}/{name} to {target} revision"):
            return "Cancelled."
        args = f"rollout undo deployment/{name} -n {namespace}"
        if revision:
            args += f" --to-revision={revision}"
        return self._run_kubectl(args, confirmed=True)

    def delete_pod(self, pod: str, namespace: str = "default") -> str:
        if not self._guard(f"delete pod {namespace}/{pod}"):
            return "Cancelled."
        try:
            self._client.core.delete_namespaced_pod(name=pod, namespace=namespace)
            return f"Deleted pod {namespace}/{pod}. A controller will recreate it if one manages it."
        except ApiException as exc:
            return f"Delete failed: {exc.reason}"

    def apply_manifest(self, manifest_yaml: str) -> str:
        preview = manifest_yaml.strip()[:400]
        if not self._guard(f"apply manifest:\n{preview}"):
            return "Cancelled."
        tmp = Path(tempfile.mkstemp(suffix=".yaml")[1])
        try:
            tmp.write_text(manifest_yaml, encoding="utf-8")
            return self._run_kubectl(f"apply -f {shlex.quote(str(tmp))}", confirmed=True)
        finally:
            tmp.unlink(missing_ok=True)

    def patch_resource(self, kind: str, name: str, namespace: str, merge_patch: str) -> str:
        if not self._guard(f"patch {kind}/{name} in {namespace}: {merge_patch}"):
            return "Cancelled."
        try:
            payload = json.dumps(json.loads(merge_patch))
        except json.JSONDecodeError as exc:
            return f"Invalid patch JSON: {exc}"
        args = [
            "patch", kind, name, "-n", namespace, "--type=merge", "--patch", payload,
        ]
        return self._exec_kubectl(args, confirmed=True)

    def kubectl(self, command: str) -> str:
        """Run an arbitrary kubectl command (mutating verbs need confirmation)."""
        return self._run_kubectl(command, confirmed=False)

    # --------------------------------------------------------------- helpers

    def _guard(self, action: str) -> bool:
        if self._auto_approve:
            return True
        if self.confirm is not None:
            return self.confirm(action)
        answer = input(f"\n[confirm] {action}\nProceed? (yes/no): ").strip().lower()
        return answer in {"yes", "y"}

    def _run_kubectl(self, command: str, *, confirmed: bool) -> str:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return f"Could not parse command: {exc}"
        if not confirmed and argv and argv[0] in _MUTATING_VERBS and not self._guard(f"kubectl {command}"):
            return "Cancelled."
        return self._exec_kubectl(argv, confirmed=True)

    def _exec_kubectl(self, argv: list[str], *, confirmed: bool) -> str:
        if shutil.which("kubectl") is None:
            return "kubectl is not installed or not on PATH."
        try:
            result = subprocess.run(
                ["kubectl", *argv],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return "kubectl timed out after 60s."
        except OSError as exc:
            return f"Failed to run kubectl: {exc}"
        output = (result.stdout or result.stderr).strip()
        return output or "(no output)"
