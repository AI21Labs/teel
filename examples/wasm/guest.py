"""Runs inside python.wasm; f1..f4 are implemented by the host (host.py)."""

import time

from teel import jit
from teel.guest import Session, host_function


@host_function
def f1(): ...


@host_function
def f2(x): ...


@host_function
def f3(x): ...


@host_function
def f4(y, z): ...


@jit
def g():
    x = f1()
    y = f2(x)
    z = f3(x)
    return f4(y, z)


def time_it():
    before = time.perf_counter()
    assert g() == "f4(f2(f1()), f3(f1()))"
    return time.perf_counter() - before


print(f"Without lookahead: {time_it():.1f}s")
with Session():
    print(f"With lookahead: {time_it():.1f}s")
