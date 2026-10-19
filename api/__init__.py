"""HTTP API (Starlette). ``create_app(services)`` is the only entry point."""

from .app import create_app

__all__ = ["create_app"]
