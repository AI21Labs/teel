from __future__ import annotations

import copy
import functools
from types import FunctionType
from typing import Any, Callable


class Memo(dict):
    def __init__(self, *, shadows: dict[int, Any]):
        super().__init__()
        self.shadows: dict[int, Any] = shadows


def wrap_deepcopy(wrapped: Callable) -> Callable:

    @functools.wraps(wrapped)
    def wrapper(x: Any, memo: Memo, **kwargs: Any) -> Any:
        x = memo.shadows.get(id(x), x)
        return wrapped(x, memo, **kwargs)

    return wrapper


def _copy_func(src: FunctionType, globals_: dict[str, Any]) -> FunctionType:
    dst = FunctionType(
        src.__code__,
        globals_,
        name=src.__name__,
        argdefs=src.__defaults__,
        closure=src.__closure__,
    )
    dst.__kwdefaults__ = src.__kwdefaults__
    dst.__annotations__ = src.__annotations__
    dst.__doc__ = src.__doc__
    dst.__module__ = src.__module__
    dst.__qualname__ = src.__qualname__
    dst.__dict__.update(src.__dict__)
    return dst


def build_shadow_deepcopy() -> Callable:
    m_globals: dict[str, Any] = {}
    m_funcs: dict[FunctionType, FunctionType] = {}
    m_dicts: list[dict] = []

    for key, old_v in copy.__dict__.items():
        if (
            not key.startswith("__")
            and callable(old_v)
            and isinstance(old_v, FunctionType)
        ):
            new_v = _copy_func(old_v, m_globals)
            if key == "deepcopy":
                new_v = wrap_deepcopy(new_v)
            m_funcs[old_v] = new_v
        elif isinstance(old_v, dict):
            new_v = dict(old_v)
            m_dicts.append(new_v)
        else:
            new_v = old_v
        m_globals[key] = new_v

    def convert(x: Any) -> Any:
        return m_funcs.get(x) if isinstance(x, FunctionType) else x

    for func in m_funcs.values():
        if func.__defaults__:
            func.__defaults__ = tuple(convert(x) for x in func.__defaults__)
        if func.__kwdefaults__:
            func.__kwdefaults__ = {
                k: convert(v) for k, v in func.__kwdefaults__.items()
            }

    for d in m_dicts:
        contents = {k: convert(v) for k, v in d.items()}
        d.clear()
        d.update(contents)

    return m_globals["deepcopy"]


shadow_deepcopy: Callable = build_shadow_deepcopy()
