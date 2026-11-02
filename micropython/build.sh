#!/usr/bin/env bash
# Build MicroPython v1.29.0 for the WattWind: stock firmware with the BLE connection limit
# raised from 1 to 3 (heart rate strap + trainer at the same time).
#
# Runs the standard MicroPython build inside a throwaway Ubuntu 24.04 container (the same
# setup as MicroPython's own CI). Needs only Docker (Docker Desktop on Windows, run from
# Git Bash):
#     micropython/build.sh                 # Pico W and Pico 2 W
#     micropython/build.sh RPI_PICO_W      # one board
# The UF2s land in micropython/firmware/.
set -euo pipefail

VERSION=v1.29.0
BOARDS="${*:-RPI_PICO_W RPI_PICO2_W}"

if [ "${IN_CONTAINER:-}" != 1 ]; then
    docker info > /dev/null 2>&1 || { echo "Docker is not running: start Docker Desktop and try again"; exit 1; }
    cd "$(dirname "$0")"
    HOST_DIR="$(pwd -W 2>/dev/null || pwd)"      # Git Bash: Windows path for docker -v
    mkdir -p firmware
    # MSYS_NO_PATHCONV: stop Git Bash rewriting the /work paths into Windows paths
    MSYS_NO_PATHCONV=1 exec docker run --rm -e IN_CONTAINER=1 -v "$HOST_DIR:/work" \
        ubuntu:24.04 bash /work/build.sh $BOARDS
fi

# --- inside the container ---
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git make cmake gcc g++ python3 ca-certificates \
    gcc-arm-none-eabi libnewlib-arm-none-eabi libstdc++-arm-none-eabi-newlib > /dev/null
arm-none-eabi-gcc --version | head -1

git clone -q --depth 1 --branch "$VERSION" https://github.com/micropython/micropython.git /mp
cd /mp
git apply /work/btstack-3-connections.patch
make -s -C mpy-cross -j"$(nproc)"
for B in $BOARDS; do
    make -s -C ports/rp2 BOARD="$B" submodules
    make -C ports/rp2 BOARD="$B" -j"$(nproc)" > "/tmp/$B.log" 2>&1 || { tail -30 "/tmp/$B.log"; exit 1; }
    cp "ports/rp2/build-$B/firmware.uf2" "/work/firmware/$B-$VERSION-wattwind-ble3.uf2"
    echo "built micropython/firmware/$B-$VERSION-wattwind-ble3.uf2"
done
# The licences that must travel with the UF2 (see micropython/LICENSES/README.md), from this very build
mkdir -p /work/firmware/licenses
cp LICENSE /work/firmware/licenses/MicroPython-LICENSE.txt
cp lib/btstack/LICENSE /work/firmware/licenses/BTstack-LICENSE.txt
cp lib/pico-sdk/src/rp2_common/pico_btstack/LICENSE.RP /work/firmware/licenses/BTstack-LICENSE.RP.txt
cp lib/cyw43-driver/LICENSE /work/firmware/licenses/cyw43-driver-LICENSE.txt
cp lib/cyw43-driver/LICENSE.RP /work/firmware/licenses/cyw43-driver-LICENSE.RP.txt
cp lib/pico-sdk/LICENSE.TXT /work/firmware/licenses/pico-sdk-LICENSE.txt
echo "licences in micropython/firmware/licenses/ (publish them with the UF2)"
