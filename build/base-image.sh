#!/bin/bash

set -euo pipefail

TAG="${TAG:-x86-64}"
STAGE3="${STAGE3:-gentoo/stage3:amd64-desktop-openrc}"
BASE="${BASE:-gentoo-zh/binhost-base:${TAG}}"
TREE="${TREE:-/var/db/repos/gentoo}"
OVERLAY="${OVERLAY:-/var/lib/binhost/overlay}"
DISTDIR="${DISTDIR:-/var/cache/distfiles}"
PKGDIR="${PKGDIR:-/var/cache/binhost/${TAG}}"
SIGNING_KEY="${SIGNING_KEY:-}"
SIGNING_GNUPGHOME="${SIGNING_GNUPGHOME:-/var/lib/binhost/gnupg}"
MAKEOPTS="${MAKEOPTS:--j12}"
JOBS="${JOBS:-8}"

DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

die() { echo "!!! $*" >&2; exit 1; }
[[ -n ${SIGNING_KEY} ]] || die "SIGNING_KEY unset"
for p in "${TREE}" "${OVERLAY}" "${DISTDIR}" "${SIGNING_GNUPGHOME}"; do
    [[ -d ${p} ]] || die "missing: ${p}"
done

sudo install -dm755 -o "$(id -u)" -g "$(id -g)" "${PKGDIR}"

container="binhost-base-build-${TAG}"
${DOCKER} rm -f "${container}" >/dev/null 2>&1 || true

echo ">>> preparing ${BASE} from ${STAGE3}"
${DOCKER} pull -q "${STAGE3}" >/dev/null

${DOCKER} run -i --privileged --name "${container}" \
    -v "${TREE}:/var/db/repos/gentoo:ro" \
    -v "${OVERLAY}:/var/db/repos/gentoo-zh:ro" \
    -v "${DISTDIR}:/var/cache/distfiles" \
    -v "${PKGDIR}:/var/cache/binpkgs" \
    -v "${SIGNING_GNUPGHOME}:/root/.gnupg" \
    -e "MAKEOPTS=${MAKEOPTS}" -e "JOBS=${JOBS}" -e "SIGNING_KEY=${SIGNING_KEY}" \
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
MAKEOPTS="${MAKEOPTS}"

ACCEPT_KEYWORDS="~amd64"
ACCEPT_LICENSE="-* @BINARY-REDISTRIBUTABLE"

FEATURES="buildpkg getbinpkg binpkg-multi-instance parallel-fetch -news"

EMERGE_DEFAULT_OPTS="--jobs=${JOBS} --load-average=$(nproc) --quiet-build"
EOF

getuto

gpg --homedir /root/.gnupg --armor --export "${SIGNING_KEY}" > /tmp/binhost.asc
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

rm -rf /etc/portage/gnupg/private-keys-v1.d \
       /etc/portage/gnupg/pass \
       /etc/portage/gnupg/openpgp-revocs.d
INNER

previous=$(${DOCKER} image inspect "${BASE}-prev" --format '{{.Id}}' 2>/dev/null || true)

if ${DOCKER} cp "${container}:/tmp/world-incomplete" - >/dev/null 2>&1; then
    ${DOCKER} rm -f "${container}" >/dev/null
    die "@world 未能对齐，保留现有的 ${BASE}"
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
    remote="${REGISTRY:-ghcr.io/gentoo-zh}/binhost-base:${TAG}"
    echo ">>> pushing ${remote}"
    ${DOCKER} tag "${BASE}" "${remote}"
    ${DOCKER} push "${remote}"
fi
