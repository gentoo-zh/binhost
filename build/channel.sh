#!/bin/bash

# Stable is the recommended channel; each service still sets its channel explicitly.
CHANNEL="${CHANNEL:-stable}"
TAG="${TAG:-x86-64}"

case "${CHANNEL}" in
unstable)
    CHANNEL_STORAGE="${TAG}"
    CHANNEL_IMAGE_TAG="${TAG}"
    CHANNEL_ACCEPT_KEYWORDS="~amd64"
    CHANNEL_OVERLAY_KEYWORDS=""
    CHANNEL_REMOTE_ROOT="/srv/pub/binpkgs/unstable/${TAG}"
    CHANNEL_PROGRESS_OUT="build-status-unstable.json"
    ;;
stable)
    CHANNEL_STORAGE="stable/${TAG}"
    CHANNEL_IMAGE_TAG="stable-${TAG}"
    CHANNEL_ACCEPT_KEYWORDS="amd64"
    CHANNEL_OVERLAY_KEYWORDS="~amd64"
    CHANNEL_REMOTE_ROOT="/srv/pub/binpkgs/stable/${TAG}"
    CHANNEL_PROGRESS_OUT="build-status.json"
    ;;
*)
    echo "!!! unsupported CHANNEL: ${CHANNEL}" >&2
    exit 2
    ;;
esac

export CHANNEL TAG CHANNEL_STORAGE CHANNEL_IMAGE_TAG
export CHANNEL_ACCEPT_KEYWORDS CHANNEL_OVERLAY_KEYWORDS
export CHANNEL_REMOTE_ROOT CHANNEL_PROGRESS_OUT
