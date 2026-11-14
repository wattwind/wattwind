#!/usr/bin/env bash
# Build MicroPython v1.29.0 for the WattWind.
#
# The release file is "WattWind MicroPython 2": stock MicroPython 1.29.0 plus
#   - room for 6 Bluetooth connections (stock: 1); the radio itself takes 4 sensors (strap, trainer, CORE) plus one
#     Share heart rate receiver (measured) (btstack-3-connections.patch sets 3; this script raises it to CONNECTIONS)
#   - Bluetooth pairing, so a Garmin Edge can use Share heart rate (btstack-pairing.patch, see the notes in it)
#   - its label in the board name: os.uname().machine ends in "(WattWind MicroPython 2)"; the firmware reads it
#     (mpbuild.py) to know what this file can do, and the updater refuses an update that needs a newer file.
# Raise MP_BUILD whenever the patches or settings change, and add the new number to firmware/mpbuild.py FEATURES.
#
# Runs the standard MicroPython build inside a throwaway Ubuntu 24.04 container (the same setup as MicroPython's
# own CI). Needs only Docker (Docker Desktop on Windows, run from Git Bash):
#     micropython/build.sh RPI_PICO2_W     # the release file (the Pico 2 W is the supported board)
#     micropython/build.sh                 # Pico W and Pico 2 W
# Experiments (these get NO label: the firmware treats them as an old file, basics only):
#     PAIRING=0 CONNECTIONS=3 micropython/build.sh RPI_PICO2_W   # = the 1.0 file (no pairing, 3 connections)
#     TRACE=1 micropython/build.sh RPI_PICO2_W                   # + a Bluetooth packet trace on the USB serial
#     CONNECTIONS=7 micropython/build.sh RPI_PICO2_W             # another connection count (2.4 KB of RAM each)
# The UF2s land in micropython/firmware/.
set -euo pipefail

VERSION=v1.29.0
MP_BUILD=2                      # the release file's build number (firmware/mpbuild.py FEATURES)
BOARDS="${*:-RPI_PICO_W RPI_PICO2_W}"
PAIRING="${PAIRING-1}"
CONNECTIONS="${CONNECTIONS-6}"
TRACE="${TRACE-}"

if [ "${IN_CONTAINER:-}" != 1 ]; then
    docker info > /dev/null 2>&1 || { echo "Docker is not running: start Docker Desktop and try again"; exit 1; }
    cd "$(dirname "$0")"
    HOST_DIR="$(pwd -W 2>/dev/null || pwd)"      # Git Bash: Windows path for docker -v
    mkdir -p firmware
    # MSYS_NO_PATHCONV: stop Git Bash rewriting the /work paths into Windows paths
    MSYS_NO_PATHCONV=1 exec docker run --rm -e IN_CONTAINER=1 -e PAIRING="$PAIRING" -e TRACE="$TRACE" \
        -e CONNECTIONS="$CONNECTIONS" -v "$HOST_DIR:/work" ubuntu:24.04 bash /work/build.sh $BOARDS
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
SUFFIX=ble3
if [ "$PAIRING" = 1 ]; then
    # gap_pair / gap_passkey, ble.config(bond=, io=, mitm=), _IRQ_GET/SET_SECRET for storing bonds
    sed -i 's/^\(\s*\)MICROPY_BLUETOOTH_BTSTACK=1$/&\n\1MICROPY_PY_BLUETOOTH_ENABLE_PAIRING_BONDING=1/' ports/rp2/CMakeLists.txt
    grep -q 'MICROPY_PY_BLUETOOTH_ENABLE_PAIRING_BONDING=1' ports/rp2/CMakeLists.txt || { echo 'pairing flag not applied'; exit 1; }
    git apply /work/btstack-pairing.patch      # SM handler, bonds kept by Python, GAP Appearance
    SUFFIX=ble3-pair
    if [ "$TRACE" = 1 ]; then
        sed -i 's/^\(\s*\)MICROPY_BLUETOOTH_BTSTACK=1$/&\n\1WATTWIND_BT_TRACE=1/' ports/rp2/CMakeLists.txt
        SUFFIX=ble3-pair-trace
    fi
fi
if [ -n "$CONNECTIONS" ] && [ "$CONNECTIONS" != 3 ]; then
    CFG=ports/rp2/btstack_inc/btstack_config.h
    sed -i "s/^#define MAX_NR_HCI_CONNECTIONS .*/#define MAX_NR_HCI_CONNECTIONS $CONNECTIONS/; s/^#define MAX_NR_GATT_CLIENTS .*/#define MAX_NR_GATT_CLIENTS $CONNECTIONS/" $CFG
    grep -q "MAX_NR_HCI_CONNECTIONS $CONNECTIONS" $CFG || { echo 'connection count not applied'; exit 1; }
    SUFFIX="$SUFFIX-c$CONNECTIONS"
fi
# The label only on the exact release combination; anything else is an experiment without a label.
LABEL=""
if [ "$PAIRING" = 1 ] && [ "$CONNECTIONS" = 6 ] && [ -z "$TRACE" ]; then
    LABEL=" (WattWind MicroPython $MP_BUILD)"
    SUFFIX="mp$MP_BUILD"
fi
make -s -C mpy-cross -j"$(nproc)"
for B in $BOARDS; do
    if [ -n "$LABEL" ]; then
        H="ports/rp2/boards/$B/mpconfigboard.h"
        sed -i "s/^\(#define MICROPY_HW_BOARD_NAME *\"[^\"]*\)\"/\1$LABEL\"/" "$H"
        grep -q "WattWind MicroPython $MP_BUILD" "$H" || { echo "label not applied to $B"; exit 1; }
    fi
    make -s -C ports/rp2 BOARD="$B" submodules
    make -C ports/rp2 BOARD="$B" -j"$(nproc)" > "/tmp/$B.log" 2>&1 || { tail -30 "/tmp/$B.log"; exit 1; }
    cp "ports/rp2/build-$B/firmware.uf2" "/work/firmware/$B-$VERSION-wattwind-$SUFFIX.uf2"
    echo "built micropython/firmware/$B-$VERSION-wattwind-$SUFFIX.uf2"
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
