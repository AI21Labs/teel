"""Run the teel WASI interpreter under wasmtime, serving its host calls.

Requires the `wasmtime` package. Implements the `teel` imports declared in
`teel/_host.c` on top of a `teel.host.Dispatcher`:

    submit(req_ptr, req_len) -> token
    next(token_out_ptr)      -> response length (blocks)
    read(buf_ptr, buf_len)   -> bytes copied

The host only reads guest memory it was pointed at and writes into buffers the
guest provided, so the guest exports nothing beyond `memory`.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, Callable, Optional

import wasmtime

from .host import Dispatcher

# CPython's WASI build runs its tests with 8 MiB, but wasmtime-py cannot raise
# async_stack_size (2 MiB), which caps max_wasm_stack.
MAX_WASM_STACK = 2 * 1024 * 1024
ERROR = -1

_I32 = wasmtime.ValType.i32()


class _Imports:
    def __init__(self, dispatcher: Dispatcher):
        self.dispatcher = dispatcher
        self.response: Optional[bytes] = None

    @staticmethod
    def _memory(caller: wasmtime.Caller) -> wasmtime.Memory:
        memory = caller.get("memory")
        if not isinstance(memory, wasmtime.Memory):
            raise wasmtime.WasmtimeError("guest exports no memory")
        return memory

    def submit(self, caller: wasmtime.Caller, ptr: int, length: int) -> int:
        request = bytes(self._memory(caller).read(caller, ptr, ptr + length))
        return self.dispatcher.submit(request)

    def next(self, caller: wasmtime.Caller, token_out: int) -> int:
        token, self.response = self.dispatcher.next()
        self._memory(caller).write(caller, struct.pack("<i", token), token_out)
        return len(self.response)

    def read(self, caller: wasmtime.Caller, ptr: int, length: int) -> int:
        if self.response is None:
            return ERROR
        chunk, self.response = self.response[:length], None
        self._memory(caller).write(caller, chunk, ptr)
        return len(chunk)

    def define(self, linker: wasmtime.Linker) -> None:
        for name, params in (("submit", 2), ("next", 1), ("read", 2)):
            linker.define_func(
                "teel",
                name,
                wasmtime.FuncType([_I32] * params, [_I32]),
                getattr(self, name),
                access_caller=True,
            )


def run(
    python_wasm: str | Path,
    argv: list[str],
    functions: dict[str, Callable[..., Any]],
    *,
    dirs: Optional[dict[str | Path, str]] = None,
    env: Optional[dict[str, str]] = None,
    max_workers: Optional[int] = None,
) -> int:
    """Run `python.wasm argv...` and return its exit code.

    `dirs` maps host directories to guest paths (read-only).
    """
    config = wasmtime.Config()
    config.max_wasm_stack = MAX_WASM_STACK
    engine = wasmtime.Engine(config)
    module = wasmtime.Module.from_file(engine, str(python_wasm))

    wasi = wasmtime.WasiConfig()
    wasi.argv = ["python", *argv]
    # The stdlib zip is embedded at /usr/local; naming it skips getpath's
    # on-disk landmark search, which would warn about <prefix>/<exec_prefix>.
    wasi.env = list({"PYTHONHOME": "/usr/local", **(env or {})}.items())
    wasi.inherit_stdout()
    wasi.inherit_stderr()
    for host_path, guest_path in (dirs or {}).items():
        wasi.preopen_dir(str(host_path), guest_path, fs_mutable=False)

    store = wasmtime.Store(engine)
    store.set_wasi(wasi)
    linker = wasmtime.Linker(engine)
    linker.define_wasi()

    with Dispatcher(functions, max_workers=max_workers) as dispatcher:
        _Imports(dispatcher).define(linker)
        instance = linker.instantiate(store, module)
        start = instance.exports(store)["_start"]
        try:
            start(store)
        except wasmtime.ExitTrap as exit_trap:
            return exit_trap.code
    return 0
