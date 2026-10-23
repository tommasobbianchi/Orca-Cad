#!/usr/bin/env bash
# TaglIAtelle L3 kernel service build + verify.
# Builds the `l3_service` target (standalone headless JSON-RPC over a Unix socket)
# in the same Docker environment as the kernel-suite contract, with the same OOM
# guard. Exit 0 => the service linked against libslic3r and built successfully.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${IMAGE:-snaporca-deps}"
VOL="${BUILD_VOL:-snaporca_buildcache_l3_service}"
JOBS="${JOBS:-12}"
MEM="${MEM:-40g}"
LOCK=/tmp/orca-rig-build.lock

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "FATAL: image '$IMAGE' not present" >&2
    exit 3
fi

if ! docker volume inspect "$VOL" >/dev/null 2>&1; then
    echo "=== $VOL: new volume, clean configure + full build (one-off, slow) ==="
    docker volume create "$VOL" >/dev/null
fi

exec 9>"$LOCK"
if ! flock -n 9; then
    echo "another build holds $LOCK — waiting (OOM guard, not a hang)"
    flock 9
fi

docker run --rm \
  --memory="$MEM" --memory-swap="$MEM" \
  -v "$REPO/src":/OrcaSlicer/src \
  -v "$REPO/tests":/OrcaSlicer/tests \
  -v "$REPO/resources":/OrcaSlicer/resources \
  -v "$REPO/CMakeLists.txt":/OrcaSlicer/CMakeLists.txt \
  -v "$REPO/cmake":/OrcaSlicer/cmake \
  -v "$VOL":/OrcaSlicer/build \
  "$IMAGE" \
  bash -lc "set -e
    cd /OrcaSlicer
    DESTDIR=/OrcaSlicer/deps/build/destdir/usr/local
    export PATH=\$DESTDIR/bin:\$PATH
    cmake -S . -B build -G 'Ninja Multi-Config' \
      -DCMAKE_PREFIX_PATH=\$DESTDIR \
      -DwxWidgets_CONFIG_EXECUTABLE=\$DESTDIR/bin/wx-config \
      -DSLIC3R_GTK=3 -DBUILD_TESTS=ON \
      -DSLIC3R_CAD=ON -DSLIC3R_STATIC=1 -DORCA_TOOLS=ON -DCMAKE_BUILD_TYPE=Release
    cmake --build build --config Release --target l3_service -- -j$JOBS
    echo '=== l3_service built OK ==='
    ls -la build/src/L3Service/Release/l3_service"
