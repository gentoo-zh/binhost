#!/bin/bash
# Build the overlay's binary packages and stage them for publication.
#
# The build runs in a container, not on the build machine, because the machine
# has CFLAGS="-O2 -pipe -march=native" on a Skylake-SP Xeon. Portage does not
# compare CFLAGS when it decides whether a binary package is usable, so those
# packages would reach users on older CPUs and die on an illegal instruction,
# with nothing in portage's output pointing back here.
#
# Layout follows the official binhost: split by CPU baseline, not init system.
# Only a handful of the listed packages mention `systemd` in IUSE.

set -euo pipefail

# The body is a function so the last line is the only thing that runs it. bash
# reads a script by byte offset as it executes, so replacing the file mid-run --
# an rsync deploy, say -- makes it resume at the same offset in the new file.
# Wrapped in a function, bash parses the whole thing first and editing the file
# afterwards cannot affect the run in progress.
main() {
TAG="${TAG:-x86-64}"
BASE="${BASE:-gentoo-zh/binhost-base:${TAG}}"
BASE_MAX_AGE_DAYS="${BASE_MAX_AGE_DAYS:-7}"
OVERLAY="${OVERLAY:-/var/lib/binhost/overlay}"
TREE="${TREE:-/var/db/repos/gentoo}"
DISTDIR="${DISTDIR:-/var/cache/distfiles}"
PKGDIR="${PKGDIR:-/var/cache/binhost/${TAG}}"
# Where portage lands what it fetches from the official binhost. The path comes
# from binrepos.conf inside the image; mounting it keeps the download across
# runs. Without the mount the container starts with an empty one and pulls the
# same ~1 GB of ::gentoo binaries again every round.
GENTOO_BINPKGS="${GENTOO_BINPKGS:-/var/cache/binhost/gentoo}"
STAGE="${STAGE:-/var/lib/binhost/stage/${TAG}}"
LOGDIR="${LOGDIR:-/var/lib/binhost/logs/${TAG}}"
LIST="${LIST:-$(dirname "$0")/packages.txt}"
SIGNING_KEY="${SIGNING_KEY:-}"
SIGNING_GNUPGHOME="${SIGNING_GNUPGHOME:-/var/lib/binhost/gnupg}"
JOBS="${JOBS:-8}"
MAKEOPTS="${MAKEOPTS:--j12}"

DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

die() { echo "!!! $*" >&2; exit 1; }

# Two rounds at once would write the same PKGDIR and STAGE. The lock lives here
# rather than in the caller because a manual run, a timer run, and a rerun of a
# few packages all go through this layer.
#
# The lock file follows STAGE instead of /var/lock: the build runs as an
# ordinary user with no write access there.
# cycle.sh 已经持有同一个锁并把 fd 传了下来，此时再抢会被自己挡住。单独运行
# 这支脚本时没有那个变量，照旧自己上锁。
if [[ -z ${BINHOST_LOCKED:-} ]]; then
    LOCK="${LOCK:-$(dirname "${STAGE}")/build.lock}"
    mkdir -p "$(dirname "${LOCK}")"
    exec 9>"${LOCK}"
    flock -n 9 || die "另一轮构建正在进行（${LOCK}）"
fi

[[ -s ${LIST} ]] || die "package list not found or empty: ${LIST}"
[[ -n ${SIGNING_KEY} ]] || die "SIGNING_KEY unset; unsigned packages are not publishable"
for p in "${OVERLAY}" "${TREE}" "${DISTDIR}" "${SIGNING_GNUPGHOME}"; do
    [[ -d ${p} ]] || die "missing: ${p}"
done

# --- base image --------------------------------------------------------------
# Refreshed on age rather than every run: aligning @world takes over an hour
# and the tree does not move far in a week.

created=$(${DOCKER} image inspect "${BASE}" --format '{{.Created}}' 2>/dev/null || true)
stale=1
if [[ -n ${created} ]]; then
    age_days=$(( ( $(date +%s) - $(date -d "${created}" +%s) ) / 86400 ))
    (( age_days < BASE_MAX_AGE_DAYS )) && stale=0
    echo ">>> base image ${BASE} is ${age_days}d old"
fi
if (( stale )); then
    echo ">>> refreshing base image"
    TAG="${TAG}" BASE="${BASE}" SIGNING_KEY="${SIGNING_KEY}" \
    TREE="${TREE}" OVERLAY="${OVERLAY}" DISTDIR="${DISTDIR}" PKGDIR="${PKGDIR}" \
    SIGNING_GNUPGHOME="${SIGNING_GNUPGHOME}" JOBS="${JOBS}" MAKEOPTS="${MAKEOPTS}" \
        "$(dirname "$0")/base-image.sh"
fi

sudo install -dm755 -o "$(id -u)" -g "$(id -g)" \
    "${PKGDIR}" "$(dirname "${STAGE}")" "${LOGDIR}" "${GENTOO_BINPKGS}"
rm -f "${LOGDIR}"/*.log "${LOGDIR}"/failed.txt

# A full disk or an interrupted build leaves zero-byte gpkg files in the cache.
# Portage reports Invalid binary package for each of them every round and then
# rebuilds as if there were no cache at all. Seventy of them accumulated once.
empty=$(find "${PKGDIR}" -name '*.gpkg.tar' -size 0 -print -delete | wc -l)
(( empty )) && echo ">>> 清掉 ${empty} 个 0 字节的缓存包" 

# --- build -------------------------------------------------------------------

echo ">>> building from ${BASE}"

${DOCKER} run --rm -i --privileged \
    -v "${TREE}:/var/db/repos/gentoo:ro" \
    -v "${OVERLAY}:/var/db/repos/gentoo-zh:ro" \
    -v "${DISTDIR}:/var/cache/distfiles" \
    -v "${PKGDIR}:/var/cache/binpkgs" \
    -v "${GENTOO_BINPKGS}:/var/cache/binhost/gentoo" \
    -v "${LIST}:/tmp/packages.txt:ro" \
    -v "${SIGNING_GNUPGHOME}:/root/.gnupg" \
    -v "${LOGDIR}:/var/log/binhost" \
    -e "SIGNING_KEY=${SIGNING_KEY}" \
    -e "OVERLAY_REV=$(git -C "${OVERLAY}" rev-parse HEAD 2>/dev/null || echo '')" \
    "${BASE}" /bin/bash -euo pipefail -s <<'INNER'

# The signing command is flock /run/lock/portage-binpkg-gpg.lock ...; the image
# has no /run/lock.
mkdir -p /run/lock

# Signing belongs to publishing, not to the environment, so it is configured
# here rather than baked into the base image -- that keeps the image usable by
# anyone who does not hold the key.
#
# binpkg-signing embeds the signature inside the .gpkg.tar, which is the only
# form portage's verify-signature checks. gpg-keepalive is needed because
# gpg-agent drops cached credentials after two hours and a full run is longer
# than that.
cat >> /etc/portage/make.conf <<EOF
FEATURES="\${FEATURES} binpkg-signing gpg-keepalive"
BINPKG_GPG_SIGNING_KEY="${SIGNING_KEY}"
BINPKG_GPG_SIGNING_GPG_HOME="/root/.gnupg"
EOF

# USE flags the dependencies need. On the first full run these all failed at
# autounmask: portage refuses to change configuration on its own, and nothing is
# wrong with the ebuilds -- every line here is a dependency some ebuild states
# outright.
#
# Set on the dependencies, never on our own packages: ours build with default
# USE so that what users receive matches what they would emerge themselves.
mkdir -p /etc/portage/package.use
cat > /etc/portage/package.use/binhost-deps <<'EOF'
dev-libs/marisa        python      # app-i18n/fcitx-kkc
sys-libs/minizip-ng    compat      # app-text/goldendict
sys-libs/libsolv       conda       # dev-util/mamba, dev-python/conda
dev-util/mamba         python      # dev-python/conda
app-i18n/opencc        python      # dev-python/mw2fcitx
media-video/pipewire   gstreamer   # net-misc/rustdesk
EOF

mapfile -t atoms < <(grep -E '^[a-z0-9-]+/[A-Za-z0-9._+-]+$' /tmp/packages.txt)
echo ">>> ${#atoms[@]} packages"

# --changed-use rebuilds when a dependency's USE changed; without it the copy in
# PKGDIR built against the old USE would be published again as is. An ebuild
# edited without a version change is invisible to portage -- that needs a
# revbump.
EMERGE=(emerge --usepkg --changed-use --with-bdeps=y --quiet-build)

# One whole-list emerge first. Portage resolves once and knows what needs
# rebuilding: 183 packages resolved in 171 seconds, against a median of 19
# seconds each when run one at a time, an hour and a half in total. That hour
# and a half is the same dependency tree, resolved 183 times.
#
# The cost is that the first unsatisfiable dependency aborts everything, so a
# failure falls back to one emerge per package, which keeps a broken package
# costing one package and keeps a log per package. The fallback does not happen
# in normal operation.
echo "::: 整体解析"
failed=()
if "${EMERGE[@]}" "${atoms[@]}" > /var/log/binhost/whole.log 2>&1; then
    echo ">>> 整体一次完成，未逐包重跑"
    rm -f /var/log/binhost/whole.log
else
    echo "!!! 整体失败，退回逐包（每包一份日志）"
    tail -5 /var/log/binhost/whole.log | sed 's/^/    /'
    for atom in "${atoms[@]}"; do
        echo "::: ${atom}"
        log=/var/log/binhost/${atom//\//_}.log
        if ! "${EMERGE[@]}" "${atom}" > "${log}" 2>&1; then
            failed+=("${atom}")
            echo "${atom}" >> /var/log/binhost/failed.txt
            tail -3 "${log}" | sed 's/^/    /'
        else
            rm -f "${log}"    # 成功的不留，否则一百多份日志里找不到重点
        fi
    done
fi

emaint binhost --fix

if (( ${#failed[@]} )); then
    printf '!!! %d failed:\n' "${#failed[@]}"
    printf '      %s\n' "${failed[@]}"
fi
INNER

# --- stage -------------------------------------------------------------------
# PKGDIR also holds every dependency built or fetched along the way. Those are
# not ours to publish and of no use to our users.

rm -rf "${STAGE}.new"
install -dm755 "${STAGE}.new"

# The filter that decides what leaves this machine lives in its own file, with
# its own cases: it is the last thing standing between the build cache and what
# users install.
OVERLAY_REV="$(git -C "${OVERLAY}" rev-parse HEAD 2>/dev/null || echo '')" \
    python3 "$(dirname "$0")/stage-index.py" "${PKGDIR}" "${STAGE}.new" "${OVERLAY}"

# Packages are already signed -- portage did that during the build. Only the
# gzipped index is left; the official binhost ships Packages and Packages.gz
# and nothing else.
gzip -kf "${STAGE}.new/Packages"

rm -rf "${STAGE}.old"
[[ -d ${STAGE} ]] && mv "${STAGE}" "${STAGE}.old"
mv "${STAGE}.new" "${STAGE}"
echo ">>> staged at ${STAGE} (previous generation kept at ${STAGE}.old)"

# --- classify failures -------------------------------------------------------
if [[ -s ${LOGDIR}/failed.txt ]]; then
    python3 "$(dirname "$0")/classify-failures.py" "${LOGDIR}" | tee "${LOGDIR}/report.txt"
fi

}

main "$@"
