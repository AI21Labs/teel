from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from functools import wraps
from typing import Optional, Callable


@dataclass
class _Event:
    name: str
    tid: int
    thread_name: str
    ts_us: float
    dur_us: float
    callno: int
    parent_callno: Optional[int]
    success: str


bool


class Timeline:
    def __init__(self):
        self._events: list[_Event] = []
        self._lock = threading.Lock()
        self._t0: float = time.perf_counter()

    def _now_us(self) -> float:
        return (time.perf_counter() - self._t0) * 1e6

    def measure(
        self,
        wrapped: Callable,
        /,
        *,
        name: Optional[str] = None,
        callno: int,
        parent_callno: Optional[int],
    ):
        if name is None:
            name = wrapped.__name__

        @wraps(wrapped)
        def wrapper(*args, **kwargs):
            tid = threading.get_ident()
            thread_name = threading.current_thread().name
            start = self._now_us()
            success = True
            try:
                return wrapped(*args, **kwargs)
            except BaseException:
                success = False
                raise
            finally:
                dur = self._now_us() - start
                event = _Event(
                    name=name,
                    tid=tid,
                    thread_name=thread_name,
                    ts_us=start,
                    dur_us=dur,
                    callno=callno,
                    parent_callno=parent_callno,
                    success=success,
                )
                with self._lock:
                    self._events.append(event)

        return wrapper

    def trace_events(self) -> list[dict]:
        with self._lock:
            events = list(self._events)

        trace: list[dict] = [
            {
                "name": "process_name",
                "ph": "M",
                "pid": 1,
                "tid": 0,
                "args": {"name": "teel"},
            }
        ]

        seen_threads: dict[int, int] = {}
        for e in events:
            if (
                tid := seen_threads.setdefault(e.tid, new_tid := len(seen_threads) + 1)
            ) == new_tid:
                trace.append(
                    {
                        "name": "thread_name",
                        "ph": "M",
                        "pid": 1,
                        "tid": tid,
                        "args": {"name": e.thread_name},
                    }
                )
            trace.append(
                {
                    "name": e.name,
                    "ph": "X",
                    "ts": e.ts_us,
                    "dur": e.dur_us,
                    "pid": 1,
                    "tid": tid,
                    "args": {
                        "callno": e.callno,
                        "parent_callno": e.parent_callno,
                        "success": e.success,
                    },
                }
            )
        return trace

    def save(self, path: str):
        doc = {"traceEvents": self.trace_events(), "displayTimeUnit": "ms"}
        with open(path, "w") as f:
            json.dump(doc, f)
        return path
