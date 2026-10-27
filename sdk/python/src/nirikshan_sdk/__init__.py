"""Nirikshan Python SDK: capture errors and send them to a Nirikshan server."""

__version__ = "0.1.0"

from .client import (  # noqa: E402
    Client,
    add_breadcrumb,
    capture_exception,
    capture_message,
    close,
    flush,
    get_client,
    init,
    set_tag,
    set_user,
)

__all__ = [
    "Client",
    "__version__",
    "add_breadcrumb",
    "capture_exception",
    "capture_message",
    "close",
    "flush",
    "get_client",
    "init",
    "set_tag",
    "set_user",
]
