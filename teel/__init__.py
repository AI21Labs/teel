from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Optional
from concurrent.futures import ThreadPoolExecutor, Future
import threading
import json

from . import lookahead
from .timeline import Timeline

_local = threading.local()


def _callback_key(func: Callable, args: list, kwargs: dict[str, Any]):
    return (func, json.dumps([args, kwargs], sort_keys=True))


def cacheable(wrapped):

    @wraps(wrapped)
    def wrapper(*args, **kwargs):
        teel = getattr(_local, "t", None)

        if teel is None:
            return wrapped(*args, **kwargs)

        return teel._run(wrapper, args, kwargs)

    lookahead.add_target(wrapper)

    return wrapper


def jit(func):
    lookahead.add_source(func)
    return func


def inline(func):
    lookahead.add_inline(func)
    return func


def _should_retry(future: Future):
    if not future.done():
        return False
    try:
        future.result()
    except Exception:
        return True
    else:
        return False


class Teel:
    def __init__(self, max_workers=None, *, trace_path: Optional[str] = None):
        self.calls = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.lock = threading.Lock()
        self.trace_path = trace_path
        self.timeline = Timeline() if trace_path is not None else None
        self.step: int = 0
        self.callno: int = 0

    def __enter__(self):
        self.executor.__enter__()
        _local.t = self
        return self

    def __exit__(self, *exc):
        _local.t = None
        self.executor.__exit__(*exc)
        if (self.timeline is not None) and self.trace_path:
            self.timeline.save(self.trace_path)

    def _get_future(self, func, args, kwargs) -> tuple[Future, bool]:
        key = _callback_key(func, args, kwargs)
        owner = False
        with self.lock:
            if ((future := self.calls.get(key)) is None) or _should_retry(future):
                self.calls[key] = future = Future()
                owner = True
        return future, owner

    def _get_step(self, step: Optional[int]) -> Optional[int]:
        with self.lock:
            if step is None:
                self.step += 1
                return self.step
            if step != self.step:
                return None
            return self.step

    def _inc_callno(self):
        with self.lock:
            self.callno += 1
            return self.callno

    def _run(
        self,
        func,
        args,
        kwargs,
        state=None,
        step: Optional[int] = None,
        parent_callno: Optional[int] = None,
    ):
        callno = self._inc_callno()

        if (step := self._get_step(step)) is None:
            return

        future, owner = self._get_future(func, args, kwargs)

        if state is None:
            self._dispatch(step=step, callno=callno)

        if owner:
            try:
                callback = func.__wrapped__
                if self.timeline is not None:
                    callback = self.timeline.measure(
                        callback, callno=callno, parent_callno=parent_callno
                    )
                result = callback(*args, **kwargs)
            except Exception as exc:
                future.set_exception(exc)
                raise
            else:
                future.set_result(result)
        else:
            result = future.result()

        if state is not None:
            self._dispatch(state=state, ret=result, step=step, callno=callno)

        return result

    def _dispatch(
        self, /, *, state=None, ret=lookahead.PENDING, step: int, callno: int
    ):
        try:
            for cb in lookahead.search(state=state, ret=ret):
                self.executor.submit(
                    self._run, cb.func, cb.args, cb.kwargs, cb.state, step, callno
                )
        except Exception:
            pass


__all__ = [
    "jit",
    "cacheable",
    "inline",
    "Teel",
]
