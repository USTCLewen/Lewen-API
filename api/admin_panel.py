"""HTML admin panel response helpers."""

from __future__ import annotations

from fastapi.responses import HTMLResponse

import config

_TEMPLATE_PATH = config.PROJECT_ROOT / "api" / "admin_panel.html"


def _load_panel_html() -> str:
    """Load the admin panel template from disk.

    This intentionally does not cache the file so UI-only admin panel edits can
    be picked up by refreshing the browser.
    """
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def panel_response() -> HTMLResponse:
    return HTMLResponse(_load_panel_html())
