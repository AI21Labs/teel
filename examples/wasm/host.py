"""Run guest.py in the teel WASI interpreter, serving f1..f4 from the host.

WASI_SDK_PATH=/path/to/wasi-sdk WASI_VFS_PATH=/path/to/wasi-vfs ./wasm/build.sh
uv run --with wasmtime python examples/wasm/host.py
"""

import sys
import time
from pathlib import Path

from teel import wasmtime_host

DELAY = 0.5
REPO = Path(__file__).resolve().parents[2]
BUILD = REPO / "build" / "wasi"


def slow(fmt):
    def run(*args):
        time.sleep(DELAY)
        return fmt.format(*args)

    return run


FUNCTIONS = {
    "f1": slow("f1()"),
    "f2": slow("f2({})"),
    "f3": slow("f3({})"),
    "f4": slow("f4({}, {})"),
}

if __name__ == "__main__":
    sys.exit(
        wasmtime_host.run(
            BUILD / "python.wasm",
            ["/app/examples/wasm/guest.py"],
            FUNCTIONS,
            dirs={REPO: "/app"},
            env={"PYTHONPATH": "/app", "PYTHONDONTWRITEBYTECODE": "1"},
        )
    )
