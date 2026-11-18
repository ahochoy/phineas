"""Local same-origin UI host; not a new public deployment or API implementation."""

from pathlib import Path

from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from phineas.api import create_configured_app


class _PrivateResponses(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response


def create_web_app(api: FastAPI | None = None) -> Starlette:
    # Deliberately local/repository-based. Only web/, not the repository root,
    # is exposed. Cloudflare hosting is a separate deployment slice.
    directory = Path(__file__).resolve().parents[2] / "web"
    application = Starlette(routes=[
        Mount("/api", app=api if api is not None else create_configured_app()),
        Mount("/", app=StaticFiles(directory=directory, html=True)),
    ])
    application.add_middleware(_PrivateResponses)
    return application
