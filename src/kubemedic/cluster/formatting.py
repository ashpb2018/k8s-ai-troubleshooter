"""Small helpers for turning Kubernetes objects into readable text.

The agent consumes plain text, so these helpers favour compact, aligned output
over structured data.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone


def humanise_age(created: datetime | None) -> str:
    """Render an object's age like ``kubectl`` does (``5m``, ``3h``, ``2d``)."""
    if created is None:
        return "unknown"
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    seconds = int((datetime.now(tz=timezone.utc) - created).total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def fallback(value: object, placeholder: str = "<none>") -> str:
    return str(value) if value not in (None, "") else placeholder


class TextTable:
    """A minimal fixed-width table renderer.

    Columns are ``(header, width)`` pairs; the final column is left unpadded so
    long values (messages, IPs) are never truncated mid-word.
    """

    def __init__(self, columns: list[tuple[str, int]]) -> None:
        self._columns = columns
        self._rows: list[list[str]] = []

    def add(self, *cells: object) -> None:
        self._rows.append([str(c) for c in cells])

    def _format_row(self, cells: Iterable[str]) -> str:
        parts = []
        cells = list(cells)
        for idx, (_, width) in enumerate(self._columns):
            cell = cells[idx] if idx < len(cells) else ""
            if idx == len(self._columns) - 1:
                parts.append(cell)
            else:
                parts.append(cell.ljust(width))
        return " ".join(parts).rstrip()

    def render(self, *, empty_message: str = "No resources found.") -> str:
        if not self._rows:
            return empty_message
        header = self._format_row(h for h, _ in self._columns)
        body = "\n".join(self._format_row(row) for row in self._rows)
        return f"{header}\n{body}"
