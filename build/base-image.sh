#!/bin/bash
# Build the base image the package builds run in.
#
# A fresh stage3 is a snapshot from release day: its installed set is older
# than the tree, which produces slot conflicts and links new packages against
# old libraries. Aligning it with @world fixes that but costs over an hour,
# and a throwaway container pays that cost on every run.
#
# So the alignment happens here once and is committed to an image. Refresh it
# when it is older than BASE_MAX_AGE_DAYS; the rest of the time package builds
# start from an already-current root.

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

# Not --rm: the whole point is to commit this container afterwards.
# -i or the heredoc below never reaches bash and the container exits silently.
${DOCKER} run -i --privileged --name "${container}" \
    -v "${TREE}:/var/db/repos/gentoo:ro" \
    -v "${OVERLAY}:/var/db/repos/gentoo-zh:ro" \
    -v "${DISTDIR}:/var/cache/distfiles" \
    -v "${PKGDIR}:/var/cache/binpkgs" \
    -v "${SIGNING_GNUPGHOME}:/root/.gnupg" \
    -e "MAKEOPTS=${MAKEOPTS}" -e "JOBS=${JOBS}" -e "SIGNING_KEY=${SIGNING_KEY}" \
    "${STAGE3}" /bin/bash -euo pipefail -s <<'INNER'

# The signing command is flock /run/lock/portage-binpkg-gpg.lock ...; stage3
# has no /run/lock, so flock fails and portage reports the unlock as failed.
mkdir -p /run/lock /etc/portage/repos.conf

cat > /etc/portage/repos.conf/gentoo-zh.conf <<EOF
[gentoo-zh]
location = /var/db/repos/gentoo-zh
auto-sync = no
EOF

# The official binhost builds amd64 with -march=x86-64 -mtune=generic. Portage
# does not compare CFLAGS when accepting a binary package, so this is the one
# setting standing between a user on an older CPU and an illegal instruction.
cat >> /etc/portage/make.conf <<EOF

CFLAGS="-O2 -pipe -march=x86-64 -mtune=generic"
CXXFLAGS="\${CFLAGS}"
MAKEOPTS="${MAKEOPTS}"

ACCEPT_KEYWORDS="~amd64"
ACCEPT_LICENSE="-* @BINARY-REDISTRIBUTABLE"

# Signing configuration does not belong here. Baking it into the base image
# would make the image usable only by whoever holds the key, and the image is
# just as useful for autobump trial builds and the overlay's CI. Signing is part
# of publishing, so build-container.sh appends it at build time.
FEATURES="buildpkg getbinpkg binpkg-multi-instance parallel-fetch -news"

EMERGE_DEFAULT_OPTS="--jobs=${JOBS} --load-average=$(nproc) --quiet-build"
EOF

# Gentoo's release keys, for verify-signature against the official binhost.
getuto

# Signing uses /root/.gnupg, verification uses /etc/portage/gnupg. Without our
# public key in the latter, portage refuses the packages it just signed itself.
# --quick-lsign-key wants a tty even with --batch --yes, hence ownertrust.
gpg --homedir /root/.gnupg --armor --export "${SIGNING_KEY}" > /tmp/binhost.asc
gpg --homedir /etc/portage/gnupg --batch --import /tmp/binhost.asc
echo "${SIGNING_KEY}:6:" | gpg --homedir /etc/portage/gnupg --batch --import-ownertrust

# After importing, the trustdb has to be recomputed and left readable -- the two
# steps getuto performs for its own key. Verification runs as the portage user,
# which cannot write the trustdb; with no trust chain to compute, even a GOODSIG
# comes back as [unknown] and portage refuses the package.
gpg --homedir /etc/portage/gnupg --batch --check-trustdb
chmod ugo+r /etc/portage/gnupg/trustdb.gpg

echo ">>> aligning @world with the tree"
# --keep-going skips what cannot be installed and carries on, so a non-zero exit
# does not mean the round was worthless -- but it cannot be waved off either:
# packages built against a root that was never fully aligned link to the old
# libraries. Leave a marker so the host side can decide whether to commit.
if ! emerge --update --deep --newuse --usepkg --keep-going --quiet-build @world; then
    echo "!!! @world 未能完全对齐"
    touch /tmp/world-incomplete
fi

# A perl major upgrade leaves XS modules installed under the old
# vendor_perl/<version>/<arch>/ outside @INC: the package is still there but the
# module will not load. configure finds intltool-update and then fails to find
# XML::Parser, with an error indistinguishable from a missing dependency. This
# is how app-i18n/libkkc broke across 5.42 to 5.44; after perl-cleaner
# XML::Parser loaded immediately.
echo ">>> perl-cleaner"
perl-cleaner --all -- --quiet-build || echo "!!! perl-cleaner 未跑完"

# Drop binary packages for versions the tree no longer has. Without this the
# cache only ever grows, and a stale version could still be published.
eclean-pkg --deep 2>/dev/null || true

# getuto generates a "Portage Local Trust Key" and writes its passphrase in
# clear text into pass, to locally sign the Gentoo release keys it imports. That
# step is already done and its result lives in trustdb.gpg; verification
# afterwards reads only pubring and trustdb, and the private key is never needed
# again -- with it removed, gpg --verify still reports Good signature
# [ultimate].
#
# Left in place, an image pushed to ghcr with PUBLISH=1 would carry a private
# key and its clear-text passphrase.
rm -rf /etc/portage/gnupg/private-keys-v1.d \
       /etc/portage/gnupg/pass \
       /etc/portage/gnupg/openpgp-revocs.d
INNER

# Record the generation before last before committing: the current one is about
# to be tagged -prev, which leaves the one before it without a name.
previous=$(${DOCKER} image inspect "${BASE}-prev" --format '{{.Id}}' 2>/dev/null || true)

# Do not overwrite the existing image when @world was not aligned: better to
# keep using the previous generation, at worst a little stale, than to build 180
# packages against a root that links to the old libraries.
#
# The container has stopped by now, so this can only cp, not exec.
if ${DOCKER} cp "${container}:/tmp/world-incomplete" - >/dev/null 2>&1; then
    ${DOCKER} rm -f "${container}" >/dev/null
    die "@world 未能对齐，保留原有的 ${BASE} 不动"
fi

echo ">>> committing ${BASE}"
# Keep the previous generation as -prev, so a problem with the new image does
# not cost another hour of rebuilding.
if ${DOCKER} image inspect "${BASE}" >/dev/null 2>&1; then
    ${DOCKER} tag "${BASE}" "${BASE}-prev"
fi
${DOCKER} commit "${container}" "${BASE}" >/dev/null
${DOCKER} rm -f "${container}" >/dev/null

# The generation before that, displaced from -prev, is now dangling. At roughly
# 4 GB a week it accumulates. Remove that one by ID rather than running image
# prune, which would also take away anyone else's dangling images on this
# machine.
if [[ -n ${previous} ]]; then
    current=$(${DOCKER} image inspect "${BASE}" --format '{{.Id}}')
    if [[ ${previous} != "${current}" ]]; then
        ${DOCKER} rmi "${previous}" >/dev/null 2>&1 || true
    fi
fi

echo ">>> ${BASE} ready"

# --- optional publish ---------------------------------------------------------
# Worth doing for two reasons: it is a backup of an environment that costs an
# hour to rebuild, and it lets anyone see exactly what the packages were built
# in.
#
# Safe to publish: docker commit does not capture mount points, so the signing
# key under /root/.gnupg is not in the image, and the local trust key getuto
# generated was removed above. What remains is an aligned @world plus the public
# keyring and fingerprints used for verification, all of which are public
# already. Each of those was checked, not assumed.

if [[ -n ${PUBLISH:-} ]]; then
    remote="${REGISTRY:-ghcr.io/gentoo-zh}/binhost-base:${TAG}"
    echo ">>> pushing ${remote}"
    ${DOCKER} tag "${BASE}" "${remote}"
    ${DOCKER} push "${remote}"
fi
