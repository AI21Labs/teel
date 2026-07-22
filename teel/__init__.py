from __future__ import annotations

from functools import wraps
from types import FunctionType
from typing import Any, Callable, Optional
from concurrent.futures import ThreadPoolExecutor, Future
import threading
import json

from . import lookahead
from .timeline import Timeline

_local = threading.local()


def _callback_key(func: Callable, args: list, kwargs: dict[str, Any]):
    return (func, json.dumps([args, kwargs], sort_keys=True))


def cacheable(wrapped: Callable) -> Callable:

    @wraps(wrapped)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        teel = getattr(_local, "t", None)

        if teel is None:
            return wrapped(*args, **kwargs)

        return teel._run(wrapper, args, kwargs)

    lookahead.add_target(wrapper)

    return wrapper


def jit(func: FunctionType) -> FunctionType:
    lookahead.add_source(func)
    return func


def inline(func: Callable) -> Callable:
    lookahead.add_inline(func)
    return func


def _should_retry(future: Future) -> bool:
    if not future.done():
        return False
    try:
        future.result()
    except Exception:
        return True
    else:
        return False


class Teel:
    def __init__(
        self, max_workers: Optional[int] = None, *, trace_path: Optional[str] = None
    ):
        self.calls: dict[Any, Future] = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.lock = threading.Lock()
        self.trace_path = trace_path
        self.timeline = Timeline() if trace_path is not None else None
        self.step: int = 0
        self.callno: int = 0

    def __enter__(self) -> Teel:
        self.executor.__enter__()
        _local.t = self
        return self

    def __exit__(self, *exc: Any) -> None:
        _local.t = None
        self.executor.__exit__(*exc)
        if (self.timeline is not None) and self.trace_path:
            self.timeline.save(self.trace_path)

    def _get_future(
        self, func: Callable, args: list, kwargs: dict[str, Any]
    ) -> tuple[Future, bool]:
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

    def _inc_callno(self) -> int:
        with self.lock:
            self.callno += 1
            return self.callno

    def _run(
        self,
        func: Callable,
        args: list,
        kwargs: dict[str, Any],
        state: Optional[lookahead.State] = None,
        step: Optional[int] = None,
        parent_callno: Optional[int] = None,
    ) -> Any:
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
        self,
        /,
        *,
        state: Optional[lookahead.State] = None,
        ret: Any = lookahead.PENDING,
        step: int,
        callno: int,
    ) -> None:
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
