#!/bin/bash

# The unstable defaults preserve every existing path until the public migration.
CHANNEL="${CHANNEL:-unstable}"
TAG="${TAG:-x86-64}"

case "${CHANNEL}" in
unstable)
    CHANNEL_STORAGE="${TAG}"
    CHANNEL_IMAGE_TAG="${TAG}"
    CHANNEL_ACCEPT_KEYWORDS="~amd64"
    CHANNEL_OVERLAY_KEYWORDS=""
    CHANNEL_REMOTE_ROOT="/srv/pub/binpkgs/${TAG}"
    CHANNEL_PROGRESS_OUT="build-status.json"
    ;;
stable)
    CHANNEL_STORAGE="stable/${TAG}"
    CHANNEL_IMAGE_TAG="stable-${TAG}"
    CHANNEL_ACCEPT_KEYWORDS="amd64"
    CHANNEL_OVERLAY_KEYWORDS="~amd64"
    CHANNEL_REMOTE_ROOT="/srv/binhost-staging/stable/${TAG}"
    CHANNEL_PROGRESS_OUT="build-status-stable.json"
    ;;
*)
    echo "!!! unsupported CHANNEL: ${CHANNEL}" >&2
    exit 2
    ;;
esac

export CHANNEL TAG CHANNEL_STORAGE CHANNEL_IMAGE_TAG
export CHANNEL_ACCEPT_KEYWORDS CHANNEL_OVERLAY_KEYWORDS
export CHANNEL_REMOTE_ROOT CHANNEL_PROGRESS_OUT
