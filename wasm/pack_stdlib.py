"""Pack the guest's stdlib and teel into one zip of compiled modules.

CPython imports from `<prefix>/lib/python312.zip` out of the box, so build.sh
embeds this file in `python.wasm` at /usr/local. Must run on the same CPython
version as the guest, since it writes that version's bytecode.

    python pack_stdlib.py <installed lib/python3.12> <teel package dir> <out.zip>
"""

import sys
import zipfile
from pathlib import Path

# Development tooling and build artifacts the guest never imports.
EXCLUDE = {
    "__phello__",
    "__pycache__",
    "ensurepip",
    "idlelib",
    "lib-dynload",
    "lib2to3",
    "pydoc_data",
    "site-packages",
    "test",
    "tkinter",
    "turtledemo",
    "venv",
}


def pack(stdlib: Path, teel: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    # Stored, not deflated: python.wasm has no zlib, and zipimport needs it to
    # decompress.
    with zipfile.PyZipFile(out, "w", compression=zipfile.ZIP_STORED) as zf:
        for entry in sorted(stdlib.iterdir()):
            if entry.name in EXCLUDE or entry.name.startswith("config-"):
                continue
            if entry.suffix == ".py" or (entry / "__init__.py").is_file():
                zf.writepy(entry)
        zf.writepy(teel)


if __name__ == "__main__":
    pack(*(Path(arg) for arg in sys.argv[1:4]))
