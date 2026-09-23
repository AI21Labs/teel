"""Guest side: speculative host calls for single-threaded interpreters (WASI).

The guest cannot start threads, so the host runs the work and the guest drives
the lookahead. When the guest blocks on a host function, it first submits the
calls the lookahead predicts; while waiting it resumes the lookahead with each
prefetched result as it arrives, submitting further predictions.

    @host_function
    def fetch(url: str) -> str: ...   # body never runs in the guest

    @jit
    def main():
        return [fetch(u) for u in urls]

    with Session():
        main()

Arguments and results must be JSON-serializable (see `teel.wire`).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Optional, Protocol, TypeVar

from . import lookahead, wire
from .wire import HostError

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

_local = threading.local()


class Transport(Protocol):
    def submit(self, request: bytes) -> int: ...

    def next(self) -> tuple[int, bytes]: ...


def default_transport() -> Transport:
    """The wasm host imports, available only in the teel WASI interpreter."""
    import _teel_host  # type: ignore[import-not-found]

    return _teel_host


@dataclass
class _Pending:
    """A submitted request and the lookahead states waiting on its result."""

    token: int
    response: Optional[bytes] = None
    waiters: list[tuple[lookahead.State, int]] = field(default_factory=list)


class Session:
    """Caches host results and runs the lookahead for the calls made inside it."""

    def __init__(self, transport: Optional[Transport] = None):
        self.transport = transport if transport is not None else default_transport()
        self.requests: dict[bytes, _Pending] = {}
        self.in_flight: dict[int, _Pending] = {}
        self.step = 0

    def __enter__(self) -> Session:
        _local.session = self
        return self

    def __exit__(self, *exc: Any) -> None:
        _local.session = None

    def call(self, name: str, args: tuple, kwargs: dict[str, Any]) -> Any:
        """Make a real (non-speculative) host call and wait for its result."""
        self.step += 1
        pending = self._submit(wire.encode_request(name, args, kwargs), retry=True)
        self._speculate(None, lookahead.PENDING, self.step)
        while pending.response is None:
            self._pump()
        return wire.decode_response(pending.response)

    def _submit(self, request: bytes, retry: bool = False) -> _Pending:
        pending = self.requests.get(request)
        if pending is not None and not (
            retry and pending.response is not None and wire.is_error(pending.response)
        ):
            return pending
        pending = _Pending(self.transport.submit(request))
        self.requests[request] = self.in_flight[pending.token] = pending
        return pending

    def _pump(self) -> None:
        token, response = self.transport.next()
        pending = self.in_flight.pop(token, None)
        if pending is None:  # submitted by an earlier session
            return
        pending.response = response
        waiters, pending.waiters = pending.waiters, []
        if wire.is_error(response):
            return
        result = wire.decode_response(response)
        for state, step in waiters:
            self._speculate(state, result, step)

    def _speculate(self, state: Optional[lookahead.State], ret: Any, step: int) -> None:
        # A worklist rather than recursion: a prediction whose result is
        # already cached resumes the lookahead right away.
        work = [(state, ret)]
        while work and step == self.step:
            state, ret = work.pop()
            for request, cb_state in self._predict(state, ret):
                pending = self._submit(request)
                if pending.response is None:
                    pending.waiters.append((cb_state, step))
                elif not wire.is_error(pending.response):
                    work.append((cb_state, wire.decode_response(pending.response)))

    def _predict(
        self, state: Optional[lookahead.State], ret: Any
    ) -> list[tuple[bytes, lookahead.State]]:
        """Best effort: a failed lookahead only loses the prefetch."""
        predictions = []
        try:
            for cb in lookahead.search(state=state, ret=ret):
                name = getattr(cb.func, "_teel_name", None)
                if name is None:
                    continue  # a @cacheable target, not a host function
                try:
                    request = wire.encode_request(name, cb.args, cb.kwargs)
                except (TypeError, ValueError):
                    continue  # arguments are not JSON; the real call will fail too
                predictions.append((request, cb.state))
        except Exception:
            logger.debug("lookahead failed", exc_info=True)
        return predictions


def _call_without_session(name: str, args: tuple, kwargs: dict[str, Any]) -> Any:
    transport = default_transport()
    token = transport.submit(wire.encode_request(name, args, kwargs))
    while True:
        done, response = transport.next()
        if done == token:
            return wire.decode_response(response)


def host_function(func: Optional[F] = None, *, name: Optional[str] = None) -> Any:
    """Declare a function the host implements; the guest only knows its name."""

    def decorate(func: F) -> F:
        host_name = name or func.__name__

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            session = getattr(_local, "session", None)
            if session is None:
                return _call_without_session(host_name, args, kwargs)
            return session.call(host_name, args, kwargs)

        wrapper._teel_name = host_name  # type: ignore[attr-defined]
        lookahead.add_target(wrapper)
        return wrapper  # type: ignore[return-value]

    return decorate(func) if func is not None else decorate


__all__ = ["HostError", "Session", "Transport", "host_function"]
