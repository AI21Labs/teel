#!/usr/bin/env bash
# Build CPython 3.12.13 for wasm32-wasi with the teel C modules linked in.
#
# Needs uv (for the build Python), WASI_SDK_PATH (tested with wasi-sdk 21) and
# WASI_VFS_PATH, a directory holding libwasi_vfs.a and the wasi-vfs CLI
# (https://github.com/kateinoigakukun/wasi-vfs, tested with 0.6.3).
# Outputs build/wasi/python.wasm, with the stdlib and teel embedded at
# /usr/local/lib/python312.zip.
set -euo pipefail

PY_VERSION=3.12.13
PY_SHA256=c08bc65a81971c1dd5783182826503369466c7e67374d1646519adf05207b684

repo=$(cd "$(dirname "$0")/.." && pwd)
out=$repo/build/wasi
: "${WASI_SDK_PATH:?set WASI_SDK_PATH to a wasi-sdk install}"
: "${WASI_VFS_PATH:?set WASI_VFS_PATH to a dir with libwasi_vfs.a and wasi-vfs}"
export WASI_SDK_PATH

mkdir -p "$out"
cd "$out"

tarball=Python-$PY_VERSION.tar.xz
if [ ! -f "$tarball" ]; then
    curl -sSfL -o "$tarball.part" "https://www.python.org/ftp/python/$PY_VERSION/$tarball"
    mv "$tarball.part" "$tarball"
fi
echo "$PY_SHA256  $tarball" | shasum -a 256 -c -

src=$out/Python-$PY_VERSION
if [ ! -d "$src" ]; then
    tar xf "$tarball"
fi
cp "$repo/teel/frameinspect.c" "$src/Modules/_teel_frameinspect.c"
cp "$repo/teel/_host.c" "$src/Modules/_teel_host.c"

build_python=$(uv python find "$PY_VERSION" 2>/dev/null || true)
if [ -z "$build_python" ]; then
    uv python install "$PY_VERSION"
    build_python=$(uv python find "$PY_VERSION")
fi

mkdir -p cpython-build/Modules
cp "$repo/wasm/Setup.local" cpython-build/Modules/Setup.local
cd cpython-build  # object tree for the source in $src
if [ ! -f Makefile ]; then
    CONFIG_SITE="$src/Tools/wasm/config.site-wasm32-wasi" \
        "$src/Tools/wasm/wasi-env" "$src/configure" -C \
        --host=wasm32-unknown-wasi \
        --build="$("$src/config.guess")" \
        --with-build-python="$build_python" \
        --with-ensurepip=no \
        --disable-test-modules
fi
jobs=$(sysctl -n hw.ncpu 2>/dev/null || nproc)
# wasi-vfs replaces wasi-libc's filesystem imports, so link it last.
libs=$(sed -n 's/^LIBS=[[:space:]]*//p' Makefile)
rm -f python.wasm  # relink, in case WASI_VFS_PATH changed since the last build
make -j"$jobs" LIBS="$libs $WASI_VFS_PATH/libwasi_vfs.a"
make install DESTDIR="$out/install" >/dev/null

# The guest needs only compiled stdlib + teel (its C modules are linked in
# above), zipped where CPython looks by default: <prefix>/lib/python312.zip.
rm -rf "$out/prefix"
"$build_python" "$repo/wasm/pack_stdlib.py" \
    "$out/install/usr/local/lib/python3.12" "$repo/teel" \
    "$out/prefix/lib/python312.zip"
rm -rf "$out/install"

"$WASI_VFS_PATH/wasi-vfs" pack python.wasm \
    --dir "$out/prefix::/usr/local" -o "$out/python.wasm"
rm -rf "$out/prefix"
echo "built $out/python.wasm"
