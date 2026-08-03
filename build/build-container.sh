#!/bin/bash

set -euo pipefail

main() {
TAG="${TAG:-x86-64}"
BASE="${BASE:-gentoo-zh/binhost-base:${TAG}}"
BASE_MAX_AGE_DAYS="${BASE_MAX_AGE_DAYS:-7}"
OVERLAY="${OVERLAY:-/var/lib/binhost/overlay}"
TREE="${TREE:-/var/db/repos/gentoo}"
DISTDIR="${DISTDIR:-/var/cache/distfiles}"
PKGDIR="${PKGDIR:-/var/cache/binhost/${TAG}}"
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

empty=$(find "${PKGDIR}" -name '*.gpkg.tar' -size 0 -print -delete | wc -l)
(( empty )) && echo ">>> 移除 ${empty} 个 0 字节的缓存包" 


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

mkdir -p /run/lock

cat >> /etc/portage/make.conf <<EOF
FEATURES="\${FEATURES} binpkg-signing gpg-keepalive"
BINPKG_GPG_SIGNING_KEY="${SIGNING_KEY}"
BINPKG_GPG_SIGNING_GPG_HOME="/root/.gnupg"
PORTAGE_BINHOST_TTL="3600"
EOF

mkdir -p /etc/portage/package.use
cat > /etc/portage/package.use/binhost-deps <<'EOF'
dev-libs/marisa        python
sys-libs/minizip-ng    compat
sys-libs/libsolv       conda
dev-util/mamba         python
app-i18n/opencc        python
media-video/pipewire   gstreamer
app-shells/gitstatus   zsh-completion
EOF

mapfile -t atoms < <(grep -E '^[a-z0-9-]+/[A-Za-z0-9._+-]+$' /tmp/packages.txt)
echo ">>> ${#atoms[@]} packages"

EMERGE=(emerge --usepkg --changed-use --with-bdeps=y --quiet-build)

echo "::: 整体解析"
failed=()
if "${EMERGE[@]}" "${atoms[@]}" > /var/log/binhost/whole.log 2>&1; then
    echo ">>> 整体一次完成，未逐包重新执行"
    rm -f /var/log/binhost/whole.log
else
    echo "!!! 整体失败，退回逐包（每包一份日志）"
    tail -5 /var/log/binhost/whole.log | sed 's/^/    /'
    i=0
    for atom in "${atoms[@]}"; do
        i=$(( i + 1 ))
        printf '%s %s %s\n' "${i}" "${#atoms[@]}" "${atom}" \
            > /var/log/binhost/progress
        echo "::: ${atom}"
        log=/var/log/binhost/${atom//\//_}.log
        if ! "${EMERGE[@]}" "${atom}" > "${log}" 2>&1; then
            failed+=("${atom}")
            echo "${atom}" >> /var/log/binhost/failed.txt
            tail -3 "${log}" | sed 's/^/    /'
        else
            rm -f "${log}"
        fi
    done
    rm -f /var/log/binhost/progress
fi

emaint binhost --fix

# What the root already provides, as CPVs. A dependency the index does not
# carry is only acceptable when it is in here. Read straight from the vdb so
# this does not depend on portage-utils being installed.
( cd /var/db/pkg && ls -d ./*/* 2>/dev/null | sed 's:^\./::' ) | sort -u \
    > /var/log/binhost/installed.txt

if (( ${#failed[@]} )); then
    printf '!!! %d failed:\n' "${#failed[@]}"
    printf '      %s\n' "${failed[@]}"
fi
INNER


rm -rf "${STAGE}.new"
install -dm755 "${STAGE}.new"

OVERLAY_REV="$(git -C "${OVERLAY}" rev-parse HEAD 2>/dev/null || echo '')" \
    GENTOO_TREE="${TREE}" \
    python3 "$(dirname "$0")/stage-index.py" "${PKGDIR}" "${STAGE}.new" "${OVERLAY}"

install -m644 "${LOGDIR}/installed.txt" "${STAGE}.new/installed.txt" 2>/dev/null ||
    die "容器没有写出 installed.txt，无法判定哪些依赖由基础系统提供"

# The staged index has to satisfy its own runtime dependencies before it can
# replace the public one. Verifying after publishing means a broken generation
# is already reachable.
python3 "$(dirname "$0")/verify-deps.py" "${STAGE}.new/Packages" \
    --installed "${STAGE}.new/installed.txt" ||
    die "staged 索引没有通过依赖验证，本轮不发布"

gzip -kf "${STAGE}.new/Packages"

rm -rf "${STAGE}.old"
[[ -d ${STAGE} ]] && mv "${STAGE}" "${STAGE}.old"
mv "${STAGE}.new" "${STAGE}"
echo ">>> staged at ${STAGE} (previous generation kept at ${STAGE}.old)"

if [[ -s ${LOGDIR}/failed.txt ]]; then
    python3 "$(dirname "$0")/classify-failures.py" "${LOGDIR}" | tee "${LOGDIR}/report.txt"
else
    rm -f "${LOGDIR}/report.txt"
fi

}

main "$@"
