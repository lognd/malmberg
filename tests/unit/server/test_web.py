"""Tests for the dashboard HTML template (malmberg_server.api.web)."""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from malmberg_server.api.web import render_dashboard_html

_ROLES = ("server", "display")


@pytest.mark.parametrize("role", _ROLES)
def test_dashboard_renders(role: str) -> None:
    """Both roles render a non-trivial HTML document with one script block."""
    html = render_dashboard_html(role)
    assert "<html" in html.lower()
    assert len(re.findall(r"<script>(.*?)</script>", html, re.S)) == 1


@pytest.mark.parametrize("role", _ROLES)
def test_dashboard_inline_js_is_valid(role: str) -> None:
    """The inline dashboard JS must parse -- a syntax error breaks the whole
    page silently (pytest cannot execute JS, so we shell out to node when
    available). This guards against unescaped quotes and similar template
    mistakes that render tests and Python tests would miss."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available to syntax-check inline JS")
    html = render_dashboard_html(role)
    js = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
    proc = subprocess.run(
        [node, "--check", "-"],
        input=js,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"inline JS syntax error ({role}):\n{proc.stderr}"
