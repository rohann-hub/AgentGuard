"""Serves the built admin dashboard (a static React app) at /dashboard.

The page holds no secrets: it asks for the admin key and sends it as X-Admin-Key to
the same admin APIs anything else would use. The headers below keep it from loading
anything but its own files and from being framed.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


class DashboardFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers.update(SECURITY_HEADERS)
        if path in ("", ".", "index.html"):
            # The page names its hashed assets: always fetch the current one.
            response.headers["Cache-Control"] = "no-cache"
        return response


def mount_dashboard(app: FastAPI, directory: str) -> None:
    if not (Path(directory) / "index.html").is_file():
        raise RuntimeError(f"AGENTGUARD_DASHBOARD_DIR has no index.html: {directory}")
    app.mount("/dashboard", DashboardFiles(directory=directory, html=True), name="dashboard")
