"""The structured record the agent builds while working an incident.

The final assistant message is expected to be Markdown with a handful of named
sections. :meth:`Incident.absorb_report` parses those sections out so the
runbook writer has clean fields to work with, while still keeping the full
narrative for reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Maps a normalised heading keyword to the Incident attribute it populates.
_SECTION_KEYS = {
    "root cause": "root_cause",
    "fix applied": "remediation",
    "verification": "verification",
    "prevention": "prevention",
}

_HEADING = re.compile(r"^\s*(?:#+\s*|\*\*)\s*(.+?)\s*(?:\*\*)?\s*:?\s*$")


@dataclass
class Incident:
    request: str
    root_cause: str = ""
    remediation: str = ""
    verification: list[str] = field(default_factory=list)
    prevention: str = ""
    affected: list[str] = field(default_factory=list)
    narrative: str = ""
    resolved: bool = False

    def absorb_report(self, report: str) -> None:
        """Parse the model's Markdown report into structured fields."""
        self.narrative = report
        buckets: dict[str, list[str]] = {}
        current: str | None = None

        for line in report.splitlines():
            heading = self._match_heading(line)
            if heading is not None:
                current = heading
                buckets.setdefault(current, [])
            elif current is not None:
                buckets[current].append(line)

        for attr, lines in ((_SECTION_KEYS[k], v) for k, v in buckets.items() if k in _SECTION_KEYS):
            text = "\n".join(lines).strip()
            if attr == "verification":
                self.verification = self._to_bullets(text)
            else:
                setattr(self, attr, text)

        # Models often lead with a "the root cause is …" sentence before any
        # heading. If the heading parse missed it, recover it from the prose.
        if not self.root_cause:
            self.root_cause = self._sniff_root_cause(report)

    @staticmethod
    def _match_heading(line: str) -> str | None:
        match = _HEADING.match(line)
        if not match:
            return None
        label = match.group(1).lower().strip()
        for key in _SECTION_KEYS:
            if key in label:
                return key
        return None

    @staticmethod
    def _sniff_root_cause(report: str) -> str:
        """Best-effort: find a sentence naming the root cause in free prose."""
        for line in report.splitlines():
            stripped = line.strip()
            if "root cause" in stripped.lower() and not _HEADING.match(stripped):
                return re.sub(r"[*#`]", "", stripped).strip()
        return ""

    @staticmethod
    def _to_bullets(text: str) -> list[str]:
        return [
            re.sub(r"^[\-\*\d\.\s]+", "", line).strip()
            for line in text.splitlines()
            if line.strip()
        ]

    def title(self) -> str:
        source = self.root_cause or self.request
        first = next((ln.strip() for ln in source.splitlines() if ln.strip()), "")
        cleaned = re.sub(r"[*#`]", "", first)
        return cleaned[:80] or "Kubernetes incident"
