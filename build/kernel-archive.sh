#!/bin/bash

# Build one prebuilt kernel per series and publish it to the archive the
# -bin ebuild fetches from.
#
# virtual/dist-kernel is SLOT=0, so one root holds one distribution kernel and
# the regular cycle can only ever produce the newest. Gentoo splits the same
# way: their binhost carries one gentoo-kernel while every series lives under
# pub/proj/dist-kernel/binpkg. Each series is therefore built in its own
# container, which is what keeps the slots apart.

set -euo pipefail

main() {
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

PACKAGE="${PACKAGE:-sys-kernel/gentoo-cjk-kernel}"
OVERLAY="${OVERLAY:-/var/lib/binhost/overlay}"
TREE="${TREE:-/var/db/repos/gentoo}"
DISTDIR="${DISTDIR:-/var/cache/distfiles}"
PKGDIR="${PKGDIR:-/var/cache/binhost/kernel/x86-64}"
IMAGE="${IMAGE:-gentoo-zh/binhost-base:x86-64}"
COMMON_PACKAGE_USE="${COMMON_PACKAGE_USE:-${SCRIPT_DIR}/package.use.common}"
ARCH="${ARCH:-amd64}"
REMOTE="${REMOTE:-mirror}"
REMOTE_ROOT="${REMOTE_ROOT:-/srv/pub/gentoo-cjk-kernel/${ARCH}}"
KEEP="${KEEP:-2}"
MAX_RETIRE="${MAX_RETIRE:-1}"
if [[ -z ${DOCKER:-} ]]; then
    DOCKER="docker"
    docker info >/dev/null 2>&1 || DOCKER="sudo docker"
fi
JOBS="${JOBS:-24}"
MAKEOPTS="${MAKEOPTS:--j$(nproc) -l$(nproc)}"
LOCK="${LOCK:-/var/lib/binhost/stage/kernel-archive.lock}"

die() { echo "!!! $*" >&2; exit 1; }

for path in "${OVERLAY}" "${TREE}"; do
    [[ -d ${path} ]] || die "missing: ${path}"
done

mkdir -p "$(dirname "${LOCK}")"
exec 9>"${LOCK}"
flock -n 9 || { echo "另一次内核归档正在执行（${LOCK}）"; exit 0; }

# One newest version per major.minor series, straight from the overlay, so a
# bump inside a series needs no edit here and a new series appears on its own.
mapfile -t wanted < <(
    OVERLAY="${OVERLAY}" TREE="${TREE}" PACKAGE="${PACKAGE}" \
        python3 "${SCRIPT_DIR}/kernel-series.py"
)
[[ ${#wanted[@]} -gt 0 ]] || die "overlay 未提供 ${PACKAGE} 的任何版本"

echo ">>> overlay 提供 ${#wanted[@]} 条内核线"

# shellcheck disable=SC2029  # REMOTE_ROOT is meant to expand locally
published=$(ssh "${REMOTE}" "ls ${REMOTE_ROOT}/*/*.gpkg.tar 2>/dev/null | xargs -r -n1 basename" || true)

todo=()
for entry in "${wanted[@]}"; do
    read -r series version <<< "${entry}"
    name="${PACKAGE#*/}-${version}-1.${ARCH}.gpkg.tar"
    if grep -qxF "${name}" <<< "${published}"; then
        echo "    ${series}  ${version}  已发布，跳过"
        continue
    fi
    echo "    ${series}  ${version}  要建置"
    todo+=("${series} ${version}")
done

# Retention and retirement still run when nothing was built: a series can be
# dropped from the overlay in a cycle where every remaining line is current.
if (( ${#todo[@]} == 0 )); then
    echo ">>> 每条线都已是最新，不起容器"
    todo=()
else
    install -dm755 "${PKGDIR}"
fi

for entry in ${todo[@]+"${todo[@]}"}; do
    read -r series version <<< "${entry}"
    atom="=${PACKAGE}-${version}"
    echo "::: ${series} ${atom}"
    # --buildpkg writes the binary package and installs it in the same run, so
    # anything built against this kernel afterwards sees the one published. -B
    # cannot do this: it refuses unless every dependency is already merged, and
    # a fresh container has none of them.
    ${DOCKER} run --rm -i --security-opt=no-new-privileges \
        -v "${TREE}:/var/db/repos/gentoo:ro" \
        -v "${OVERLAY}:/var/db/repos/gentoo-zh:ro" \
        -v "${DISTDIR}:/var/cache/distfiles" \
        -v "${PKGDIR}:/var/cache/binpkgs" \
        -v "${COMMON_PACKAGE_USE}:/tmp/package.use.common:ro" \
        -e "MAKEOPTS=${MAKEOPTS}" -e "JOBS=${JOBS}" \
        "${IMAGE}" /bin/bash -euo pipefail -c "
            mkdir -p /etc/portage/package.use
            cat /tmp/package.use.common > /etc/portage/package.use/binhost-deps
            emerge --quiet-build -1 --buildpkg --usepkg '${atom}'
        " || die "${series} ${version} 建置失败"

    built="${PKGDIR}/${PACKAGE}/${PACKAGE#*/}-${version}-1.gpkg.tar"
    [[ -f ${built} ]] || die "建置完成但没有产物：${built}"

    name="${PACKAGE#*/}-${version}-1.${ARCH}.gpkg.tar"
    # shellcheck disable=SC2029  # as above
    ssh "${REMOTE}" "install -dm755 ${REMOTE_ROOT}/${series}"
    rsync -a "${built}" "${REMOTE}:${REMOTE_ROOT}/${series}/${name}"
    echo "    已发布 ${series}/${name}"
done

# Keep the newest few per series; a series with fewer files is left alone.
for entry in "${wanted[@]}"; do
    read -r series _ <<< "${entry}"
    # shellcheck disable=SC2029  # as above
    ssh "${REMOTE}" "
        cd ${REMOTE_ROOT}/${series} 2>/dev/null || exit 0
        ls -1t *.gpkg.tar 2>/dev/null | tail -n +$((KEEP + 1)) |
            while read -r old; do echo \"    清理 ${series}/\${old}\"; rm -f \"\${old}\"; done
    "
done

# A series the overlay no longer offers is retired, the same way the package
# lists treat a package that is gone. The cap is the guard: losing the overlay
# would otherwise look like every series was dropped at once.
mapfile -t remote_series < <(
    # shellcheck disable=SC2029  # as above
    ssh "${REMOTE}" "ls -1 ${REMOTE_ROOT} 2>/dev/null" || true
)
retire=()
for series in "${remote_series[@]}"; do
    [[ -n ${series} ]] || continue
    keep=no
    for entry in "${wanted[@]}"; do
        read -r have _ <<< "${entry}"
        [[ ${have} == "${series}" ]] && { keep=yes; break; }
    done
    [[ ${keep} == yes ]] || retire+=("${series}")
done

if (( ${#retire[@]} )); then
    if (( ${#retire[@]} > MAX_RETIRE )); then
        echo "!! 要退役 ${#retire[@]} 条线，超过上限 ${MAX_RETIRE}，一条都不动" >&2
        echo "   overlay 可能读取有误，确认之后再执行" >&2
    else
        for series in "${retire[@]}"; do
            echo "    退役 ${series}（overlay 已不提供）"
            # shellcheck disable=SC2029  # as above
            ssh "${REMOTE}" "rm -rf ${REMOTE_ROOT}/${series}"
        done
    fi
fi

echo ">>> 完成"
}

main "$@"
