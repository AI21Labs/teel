"""Host side: runs guest requests on real threads, outside the guest.

`Dispatcher` has the same `submit`/`next` shape as the guest transport, so it
can back a wasm runtime (see `teel.wasmtime_host`) or be handed to
`teel.guest.Session` directly to run guest code natively.
"""

from __future__ import annotations

import itertools
import logging
import queue
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Optional

from . import wire

logger = logging.getLogger(__name__)


class Dispatcher:
    def __init__(
        self,
        functions: dict[str, Callable[..., Any]],
        max_workers: Optional[int] = None,
    ):
        self.functions = dict(functions)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.tokens = itertools.count()
        self.completed: queue.SimpleQueue[tuple[int, bytes]] = queue.SimpleQueue()

    def __enter__(self) -> Dispatcher:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=True)

    def submit(self, request: bytes) -> int:
        token = next(self.tokens)
        future = self.executor.submit(self._run, request)
        future.add_done_callback(lambda f: self._complete(token, f))
        return token

    def next(self) -> tuple[int, bytes]:
        """Block until any submitted request completes."""
        return self.completed.get()

    def _run(self, request: bytes) -> bytes:
        try:
            req = wire.decode_request(request)
            func = self.functions[req.name]
            return wire.encode_result(func(*req.args, **req.kwargs))
        except Exception as exc:
            logger.info(
                "host function failed",
                extra={"request": request[:200], "error": repr(exc)},
            )
            return wire.encode_error(exc)

    def _complete(self, token: int, future: Future) -> None:
        if future.cancelled():
            return
        self.completed.put((token, future.result()))
