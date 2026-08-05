#!/bin/bash

set -euo pipefail

cd "$(dirname "$0")/.."

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=build/channel.sh
. "${SCRIPT_DIR}/channel.sh"

exec env \
    CHANNEL="${CHANNEL}" \
    TAG="${TAG}" \
    SIGNING_KEY="${SIGNING_KEY:?需要签名密钥指纹}" \
    OVERLAY="${OVERLAY:-/var/lib/binhost/overlay}" \
    TREE="${TREE:-/var/db/repos/gentoo}" \
    LIST="${LIST:-$(pwd)/build/packages.txt}" \
    JOBS="${JOBS:-24}" \
    MAKEOPTS="${MAKEOPTS:--j8}" \
    ./build/build-container.sh
