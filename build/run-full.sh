#!/bin/bash

set -euo pipefail

cd "$(dirname "$0")/.."

exec env \
    SIGNING_KEY="${SIGNING_KEY:?需要签名密钥指纹}" \
    OVERLAY="${OVERLAY:-/var/lib/binhost/overlay}" \
    TREE="${TREE:-/var/db/repos/gentoo}" \
    LIST="${LIST:-$(pwd)/build/packages.txt}" \
    JOBS="${JOBS:-24}" \
    MAKEOPTS="${MAKEOPTS:--j8}" \
    ./build/build-container.sh
