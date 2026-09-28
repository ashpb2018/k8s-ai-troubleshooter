"""Runbook rendering and indexing."""

from __future__ import annotations

from kubemedic.agent.incident import Incident
from kubemedic.runbooks import RunbookLibrary


def _library(tmp_path):
    return RunbookLibrary(directory=tmp_path, cluster="kind-test", backend="Ollama / llama3.2")


def test_save_writes_markdown_file(tmp_path):
    incident = Incident(request="nginx CrashLoopBackOff")
    incident.root_cause = "Bad image tag"
    incident.remediation = "Rolled back"
    incident.verification = ["Pods Running"]
    incident.prevention = "Pin digests"
    incident.resolved = True

    library = _library(tmp_path)
    path = library.save(incident)

    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "Bad Image Tag" in text or "Bad image tag" in text
    assert "Rolled back" in text
    assert "- Pods Running" in text
    assert "Resolved" in text
    assert "kind-test" in text


def test_unresolved_incident_marked_investigating(tmp_path):
    incident = Incident(request="something odd")
    path = _library(tmp_path).save(incident)
    assert "Investigating" in path.read_text(encoding="utf-8")


def test_index_lists_saved_runbooks(tmp_path):
    library = _library(tmp_path)
    library.save(Incident(request="first issue"))
    library.save(Incident(request="second issue"))

    index = library.write_index()
    body = index.read_text(encoding="utf-8")

    assert "Total: **2**" in body
    assert index.name == "index.md"
    # The index itself is excluded from the entry listing.
    assert all(p.name != "index.md" for p in library.entries())


def test_slug_is_filesystem_safe(tmp_path):
    incident = Incident(request="weird / name: with * chars")
    path = _library(tmp_path).save(incident)
    assert "/" not in path.name.replace(str(tmp_path), "")
    assert path.suffix == ".md"
