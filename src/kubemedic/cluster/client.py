"""A thin, typed wrapper over the official Kubernetes Python client."""

from __future__ import annotations

from kubernetes import client, config
from kubernetes.client import ApiClient, AppsV1Api, BatchV1Api, CoreV1Api, NetworkingV1Api


class ClusterClient:
    """Owns the API client handles and connection bootstrap logic."""

    def __init__(self, kubeconfig: str | None = None, context: str | None = None) -> None:
        self._load_config(kubeconfig, context)
        api = ApiClient()
        self._api = api
        self.core = CoreV1Api(api)
        self.apps = AppsV1Api(api)
        self.batch = BatchV1Api(api)
        self.networking = NetworkingV1Api(api)

    @staticmethod
    def _load_config(kubeconfig: str | None, context: str | None) -> None:
        if kubeconfig:
            config.load_kube_config(config_file=kubeconfig, context=context)
            return
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config(context=context)

    @property
    def raw_api(self) -> ApiClient:
        return self._api

    def active_context(self) -> str:
        try:
            _, active = config.list_kube_config_contexts()
            return active["name"] if active else "in-cluster"
        except Exception:
            return "unknown"

    def server_version(self) -> str:
        try:
            return client.VersionApi(self._api).get_code().git_version
        except Exception:
            return "unknown"
