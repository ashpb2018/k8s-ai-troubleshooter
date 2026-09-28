"""Formatting helpers used to render cluster objects as text."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from kubemedic.cluster.formatting import TextTable, fallback, humanise_age


def test_humanise_age_scales():
    now = datetime.now(tz=timezone.utc)
    assert humanise_age(now - timedelta(seconds=30)).endswith("s")
    assert humanise_age(now - timedelta(minutes=5)).endswith("m")
    assert humanise_age(now - timedelta(hours=3)).endswith("h")
    assert humanise_age(now - timedelta(days=2)).endswith("d")
    assert humanise_age(None) == "unknown"


def test_fallback_placeholder():
    assert fallback(None) == "<none>"
    assert fallback("") == "<none>"
    assert fallback("value") == "value"


def test_text_table_renders_header_and_rows():
    table = TextTable([("NAME", 10), ("STATUS", 0)])
    table.add("web", "Running")
    out = table.render()
    lines = out.splitlines()
    assert lines[0].startswith("NAME")
    assert "web" in lines[1]
    assert "Running" in lines[1]


def test_text_table_empty_message():
    table = TextTable([("NAME", 10)])
    assert table.render(empty_message="nothing here") == "nothing here"
