#!/bin/bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=build/channel.sh
. "${SCRIPT_DIR}/channel.sh"

STAGE3="${STAGE3:-gentoo/stage3@sha256:7f523210aa362e429cf47742c408400a0b8f8e4b618c39ab7dd691ef56f04d3a}"  # gentoo/stage3:amd64-desktop-openrc
BASE="${BASE:-gentoo-zh/binhost-base:${CHANNEL_IMAGE_TAG}}"
TREE="${TREE:-/var/db/repos/gentoo}"
OVERLAY="${OVERLAY:-/var/lib/binhost/overlay}"
DISTDIR="${DISTDIR:-/var/cache/distfiles}"
PKGDIR="${PKGDIR:-/var/cache/binhost/${CHANNEL_STORAGE}}"
SIGNING_KEY="${SIGNING_KEY:-}"
SIGNING_GNUPGHOME="${SIGNING_GNUPGHOME:-/var/lib/binhost/gnupg}"
MAKEOPTS="${MAKEOPTS:--j12}"
JOBS="${JOBS:-8}"

DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

die() { echo "!!! $*" >&2; exit 1; }
[[ -n ${SIGNING_KEY} ]] || die "SIGNING_KEY unset"
[[ ${SIGNING_KEY} =~ ^[0-9A-Fa-f]{40}$ ]] ||
    die "SIGNING_KEY must be a 40-character fingerprint, got: ${SIGNING_KEY}"
for p in "${TREE}" "${OVERLAY}" "${DISTDIR}" "${SIGNING_GNUPGHOME}"; do
    [[ -d ${p} ]] || die "missing: ${p}"
done

PUBLIC_KEY=$(mktemp)
trap 'rm -f "${PUBLIC_KEY}"' EXIT
gpg --homedir "${SIGNING_GNUPGHOME}" --batch --armor --export "${SIGNING_KEY}" \
    > "${PUBLIC_KEY}"
[[ -s ${PUBLIC_KEY} ]] || die "cannot export SIGNING_KEY"

sudo install -dm755 -o "$(id -u)" -g "$(id -g)" "${PKGDIR}"

container="binhost-base-build-${CHANNEL_IMAGE_TAG}"
${DOCKER} rm -f "${container}" >/dev/null 2>&1 || true

echo ">>> preparing ${BASE} from ${STAGE3}"
${DOCKER} pull -q "${STAGE3}" >/dev/null

${DOCKER} run -i --security-opt=no-new-privileges --name "${container}" \
    -v "${TREE}:/var/db/repos/gentoo:ro" \
    -v "${OVERLAY}:/var/db/repos/gentoo-zh:ro" \
    -v "${DISTDIR}:/var/cache/distfiles" \
    -v "${PKGDIR}:/var/cache/binpkgs" \
    -v "${PUBLIC_KEY}:/tmp/binhost.asc:ro" \
    -v "$(dirname "$0")/rebuild-preserved.sh:/usr/local/bin/rebuild-preserved:ro" \
    -v "$(dirname "$0")/preserved-consumers.py:/usr/local/bin/preserved-consumers:ro" \
    -e "MAKEOPTS=${MAKEOPTS}" -e "JOBS=${JOBS}" -e "SIGNING_KEY=${SIGNING_KEY}" \
    -e "BINHOST_ACCEPT_KEYWORDS=${CHANNEL_ACCEPT_KEYWORDS}" \
    -e "BINHOST_OVERLAY_KEYWORDS=${CHANNEL_OVERLAY_KEYWORDS}" \
    "${STAGE3}" /bin/bash -euo pipefail -s <<'INNER'

mkdir -p /run/lock /etc/portage/repos.conf

cat > /etc/portage/repos.conf/gentoo-zh.conf <<EOF
[gentoo-zh]
location = /var/db/repos/gentoo-zh
auto-sync = no
EOF

cat >> /etc/portage/make.conf <<EOF

CFLAGS="-O2 -pipe -march=x86-64 -mtune=generic"
CXXFLAGS="\${CFLAGS}"
CPU_FLAGS_X86="mmx sse sse2"
MAKEOPTS="${MAKEOPTS}"

ACCEPT_KEYWORDS="${BINHOST_ACCEPT_KEYWORDS}"
ACCEPT_LICENSE="-* @BINARY-REDISTRIBUTABLE"

FEATURES="buildpkg getbinpkg binpkg-multi-instance parallel-fetch -news"

EMERGE_DEFAULT_OPTS="--jobs=${JOBS} --load-average=$(nproc) --quiet-build"
EOF

if [[ -n ${BINHOST_OVERLAY_KEYWORDS} ]]; then
    mkdir -p /etc/portage/package.accept_keywords
    cat > /etc/portage/package.accept_keywords/gentoo-zh <<EOF
*/*::gentoo-zh ${BINHOST_OVERLAY_KEYWORDS}
EOF
fi

getuto

gpg --homedir /etc/portage/gnupg --batch --import /tmp/binhost.asc
echo "${SIGNING_KEY}:6:" | gpg --homedir /etc/portage/gnupg --batch --import-ownertrust

gpg --homedir /etc/portage/gnupg --batch --check-trustdb
chmod ugo+r /etc/portage/gnupg/trustdb.gpg

echo ">>> aligning @world with the tree"
if ! emerge --update --deep --newuse --usepkg --keep-going --quiet-build @world; then
    echo "!!! @world 未能完全对齐"
    touch /tmp/world-incomplete
fi

echo ">>> perl-cleaner"
perl-cleaner --all -- --quiet-build || echo "!!! perl-cleaner 未完成"

if command -v eclean-pkg >/dev/null; then
    eclean-pkg || echo "!! eclean-pkg 未完成，本次未清理缓存"
else
    emerge -q app-portage/gentoolkit && eclean-pkg ||
        echo "!! gentoolkit 安装失败，本次未清理缓存"
fi

echo ">>> rebuilding preserved library consumers"
if ! /usr/local/bin/rebuild-preserved /tmp/preserved-rebuild.log; then
    touch /tmp/preserved-rebuild-incomplete
fi

rm -rf /etc/portage/gnupg/private-keys-v1.d \
       /etc/portage/gnupg/pass \
       /etc/portage/gnupg/openpgp-revocs.d
INNER

previous=$(${DOCKER} image inspect "${BASE}-prev" --format '{{.Id}}' 2>/dev/null || true)

if ${DOCKER} cp "${container}:/tmp/world-incomplete" - >/dev/null 2>&1; then
    ${DOCKER} rm -f "${container}" >/dev/null
    die "@world 未能对齐，保留现有的 ${BASE}"
fi

if ${DOCKER} cp "${container}:/tmp/preserved-rebuild-incomplete" - >/dev/null 2>&1; then
    ${DOCKER} rm -f "${container}" >/dev/null
    die "@preserved-rebuild 未完成，保留现有的 ${BASE}"
fi

echo ">>> committing ${BASE}"
if ${DOCKER} image inspect "${BASE}" >/dev/null 2>&1; then
    ${DOCKER} tag "${BASE}" "${BASE}-prev"
fi
${DOCKER} commit "${container}" "${BASE}" >/dev/null
${DOCKER} rm -f "${container}" >/dev/null

if [[ -n ${previous} ]]; then
    current=$(${DOCKER} image inspect "${BASE}" --format '{{.Id}}')
    if [[ ${previous} != "${current}" ]]; then
        ${DOCKER} rmi "${previous}" >/dev/null 2>&1 || true
    fi
fi

echo ">>> ${BASE} ready"


if [[ -n ${PUBLISH:-} ]]; then
    remote="${REGISTRY:-ghcr.io/gentoo-zh}/binhost-base:${CHANNEL_IMAGE_TAG}"
    echo ">>> pushing ${remote}"
    ${DOCKER} tag "${BASE}" "${remote}"
    ${DOCKER} push "${remote}"
fi
