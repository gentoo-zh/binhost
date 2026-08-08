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
# The -bin ebuild reads paths inside the gpkg as lib/modules/${KV_FULL} and
# usr/src/linux-${KV_FULL}, so what is packed here has to carry the same
# suffix its KV_LOCALVERSION declares. Without it the archive holds the plain
# variant, the two collide on disk and the -bin install finds no directory.
LOCALVERSION="${LOCALVERSION:--gentoo-cjk-dist-bin}"
ARCH="${ARCH:-amd64}"
REMOTE="${REMOTE:-mirror}"
REMOTE_ROOT="${REMOTE_ROOT:-/srv/pub/gentoo-cjk-kernel/${ARCH}}"
MAX_RETIRE="${MAX_RETIRE:-2}"
# One kernel takes about twenty five minutes, so a first run over a long
# version list would hold the machine for most of a day. What is left over
# is picked up by the next run.
MAX_BUILDS="${MAX_BUILDS:-10}"
# The whole point of this kernel. IUSE has it on by default, but an upstream
# default is not a guarantee, so it is requested here and checked afterwards.
REQUIRED_USE_FLAG="${REQUIRED_USE_FLAG:-cjk}"
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

# Every version the overlay offers, so a bump needs no edit here and a new
# series appears on its own. The series only decides which directory holds it.
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
    echo ">>> 每个版本都已发布，不起容器"
    todo=()
else
    if (( ${#todo[@]} > MAX_BUILDS )); then
        echo ">>> 本轮只建前 ${MAX_BUILDS} 个，其余 $(( ${#todo[@]} - MAX_BUILDS )) 个留到下一轮"
        todo=("${todo[@]:0:MAX_BUILDS}")
    fi
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
            mkdir -p /etc/portage/package.use /etc/kernel/config.d
            cat /tmp/package.use.common > /etc/portage/package.use/binhost-deps
            printf 'CONFIG_LOCALVERSION=\"%s\"\n' '${LOCALVERSION}' \
                > /etc/kernel/config.d/90-binpkg-localversion.config
            printf '%s %s\n' '${PACKAGE}' '${REQUIRED_USE_FLAG}' \
                >> /etc/portage/package.use/binhost-deps
            rm -f /var/cache/binpkgs/${PACKAGE}/${PACKAGE#*/}-${version}-[0-9]*.gpkg.tar
            emaint binhost --fix >/dev/null
            emerge --quiet-build -1 --buildpkg --usepkg '${atom}'
        " || die "${series} ${version} 建置失败"

    # The build id has to be 1, which is why the old binpkgs of this version are
    # cleared above. It is not only the file name: the directory inside the gpkg
    # carries the id too, and the -bin ebuild resolves BINPKG=${P/-bin}-1 against
    # exactly that name. Renaming the file does not rename what is inside it, so
    # a -2 published as -1 unpacks to a directory the -bin install never finds.
    built="${PKGDIR}/${PACKAGE}/${PACKAGE#*/}-${version}-1.gpkg.tar"
    [[ -f ${built} ]] || die "建置完成但没有 -1 产物：${built}"

    inner=$(tar -tf "${built}" | head -n1 | cut -d/ -f1)
    [[ ${inner} == "${PACKAGE#*/}-${version}-1" ]] ||
        die "${version} 包内目录是 ${inner}，不是 -1，${PACKAGE#*/}-bin 无法安装"

    # A USE flag that was asked for is not proof it was applied, so the built
    # package is read back before anything is published.
    if ! tar -xOf "${built}" "$(basename "${built}" .gpkg.tar)/metadata.tar.zst" |
            zstd -dc | tar -xO metadata/USE |
            tr ' ' '\n' | grep -qx "${REQUIRED_USE_FLAG}"; then
        die "${version} 建出来的包没有 ${REQUIRED_USE_FLAG}，不发布"
    fi

    name="${PACKAGE#*/}-${version}-1.${ARCH}.gpkg.tar"
    # shellcheck disable=SC2029  # as above
    ssh "${REMOTE}" "install -dm755 ${REMOTE_ROOT}/${series}"
    rsync -a "${built}" "${REMOTE}:${REMOTE_ROOT}/${series}/${name}"
    echo "    已发布 ${series}/${name}"
done

# Every version the overlay carries has to stay: a -bin ebuild names its file
# by URL, so removing one an ebuild still references leaves that version
# unfetchable. A file goes only when its version leaves the overlay.
wanted_names=()
for entry in "${wanted[@]}"; do
    read -r series version <<< "${entry}"
    wanted_names+=("${series}/${PACKAGE#*/}-${version}-1.${ARCH}.gpkg.tar")
done

mapfile -t remote_files < <(
    # shellcheck disable=SC2029  # as above
    ssh "${REMOTE}" "cd ${REMOTE_ROOT} 2>/dev/null && ls -1 */*.gpkg.tar 2>/dev/null" || true
)
stale=()
for f in ${remote_files[@]+"${remote_files[@]}"}; do
    [[ -n ${f} ]] || continue
    keep=no
    for want in "${wanted_names[@]}"; do
        [[ ${want} == "${f}" ]] && { keep=yes; break; }
    done
    [[ ${keep} == yes ]] || stale+=("${f}")
done

if (( ${#stale[@]} )); then
    if (( ${#stale[@]} > MAX_RETIRE )); then
        echo "!! 要清理 ${#stale[@]} 个档案，超过上限 ${MAX_RETIRE}，一个都不动" >&2
        echo "   overlay 可能读取有误，确认之后再执行" >&2
    else
        for f in "${stale[@]}"; do
            echo "    清理 ${f}（overlay 已不提供这个版本）"
            # shellcheck disable=SC2029  # as above
            ssh "${REMOTE}" "rm -f ${REMOTE_ROOT}/${f}"
        done
    fi
fi

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
