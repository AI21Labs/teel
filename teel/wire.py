"""Byte format shared by the guest and the host.

Requests and responses are compact UTF-8 JSON. Requests are canonical (sorted
keys, no whitespace), so the request bytes double as the cache key.

    request:  {"args": [...], "kwargs": {...}, "name": "..."}
    response: {"ok": <value>} | {"error": {"type": "...", "message": "..."}}
"""

from __future__ import annotations

import json
from typing import Any, NamedTuple


class Request(NamedTuple):
    name: str
    args: list
    kwargs: dict[str, Any]


class HostError(Exception):
    """A host function raised; carries the host-side exception type name."""

    def __init__(self, type_name: str, message: str):
        super().__init__(f"{type_name}: {message}")
        self.type_name = type_name
        self.message = message


def _dumps(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def encode_request(name: str, args: Any, kwargs: dict[str, Any]) -> bytes:
    return _dumps({"name": name, "args": list(args), "kwargs": kwargs})


def decode_request(data: bytes) -> Request:
    obj = json.loads(data)
    return Request(obj["name"], obj["args"], obj["kwargs"])


def encode_result(value: Any) -> bytes:
    return _dumps({"ok": value})


def encode_error(exc: BaseException) -> bytes:
    return _dumps({"error": {"type": type(exc).__name__, "message": str(exc)}})


def is_error(data: bytes) -> bool:
    return "error" in json.loads(data)


def decode_response(data: bytes) -> Any:
    """Return the result, or raise HostError if the host function failed."""
    obj = json.loads(data)
    if "error" in obj:
        raise HostError(obj["error"]["type"], obj["error"]["message"])
    return obj["ok"]
