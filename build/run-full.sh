#!/bin/bash
# Full build: every package in packages.txt, staged for publication.
#
# No @world alignment happens here when the base image is current; that step
# lives in base-image.sh and is triggered by the image's age.
#
# JOBS and MAKEOPTS reach base-image.sh only. build-container.sh does not pass
# them into the build container, which uses the make.conf baked into the image,
# so what is set here governs how the base image is built and nothing else.

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
