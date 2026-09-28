"""Parsing the model's Markdown report into a structured incident."""

from __future__ import annotations

from kubemedic.agent.incident import Incident

REPORT = """\
Some preamble the model wrote.

**Root Cause**
The nginx deployment referenced an image tag that does not exist.

**Fix Applied**
Rolled the deployment back to revision 3.

**Verification**
- Pods report Running
- Endpoints populated

**Prevention**
Pin image digests and add a CI check.
"""


def test_absorb_report_extracts_sections():
    incident = Incident(request="nginx pods crashing")
    incident.absorb_report(REPORT)

    assert "image tag that does not exist" in incident.root_cause
    assert "Rolled the deployment back" in incident.remediation
    assert incident.verification == ["Pods report Running", "Endpoints populated"]
    assert "Pin image digests" in incident.prevention
    assert incident.narrative == REPORT


def test_absorb_report_handles_hash_headings():
    incident = Incident(request="x")
    incident.absorb_report("## Root Cause\nDisk pressure on node-1.\n")
    assert "Disk pressure" in incident.root_cause


def test_title_prefers_root_cause_first_line():
    incident = Incident(request="investigate crash")
    incident.absorb_report("**Root Cause**\nImagePullBackOff on api pod\n")
    assert incident.title() == "ImagePullBackOff on api pod"


def test_title_falls_back_to_request():
    incident = Incident(request="pods are pending")
    assert incident.title() == "pods are pending"


def test_missing_sections_leave_defaults():
    incident = Incident(request="x")
    incident.absorb_report("Just a plain sentence, no headings.")
    assert incident.root_cause == ""
    assert incident.verification == []
