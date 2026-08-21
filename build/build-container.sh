#!/bin/bash

set -euo pipefail

main() {
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=build/channel.sh
. "${SCRIPT_DIR}/channel.sh"

BASE="${BASE:-gentoo-zh/binhost-base:${CHANNEL_IMAGE_TAG}}"
SIGNING_IMAGE="${SIGNING_IMAGE:-gentoo/stage3@sha256:7f523210aa362e429cf47742c408400a0b8f8e4b618c39ab7dd691ef56f04d3a}"
BASE_MAX_AGE_DAYS="${BASE_MAX_AGE_DAYS:-7}"
OVERLAY="${OVERLAY:-/var/lib/binhost/overlay}"
TREE="${TREE:-/var/db/repos/gentoo}"
DISTDIR="${DISTDIR:-/var/cache/distfiles}"
PKGDIR="${PKGDIR:-/var/cache/binhost/${CHANNEL_STORAGE}}"
GENTOO_BINPKGS="${GENTOO_BINPKGS:-/var/cache/binhost/gentoo}"
STAGE="${STAGE:-/var/lib/binhost/stage/${CHANNEL_STORAGE}}"
LOGDIR="${LOGDIR:-/var/lib/binhost/logs/${CHANNEL_STORAGE}}"
LIST="${LIST:-$(dirname "$0")/packages.txt}"
STABLE_EXCLUDED="${STABLE_EXCLUDED:-$(dirname "$0")/stable-excluded.txt}"
STABLE_PACKAGE_USE="${STABLE_PACKAGE_USE:-$(dirname "$0")/package.use.stable}"
COMMON_PACKAGE_USE="${COMMON_PACKAGE_USE:-$(dirname "$0")/package.use.common}"
SIGNING_KEY="${SIGNING_KEY:-}"
SIGNING_GNUPGHOME="${SIGNING_GNUPGHOME:-/var/lib/binhost/gnupg}"
SIGNING_TMP_ROOT="${SIGNING_TMP_ROOT:-/dev/shm}"
JOBS="${JOBS:-8}"
MAKEOPTS="${MAKEOPTS:--j12}"
SIGNING_INPUT=""

DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

die() { echo "!!! $*" >&2; exit 1; }
cleanup_signing_input() {
    [[ -n ${SIGNING_INPUT} ]] || return 0
    rm -f -- "${SIGNING_INPUT}/private.gpg" "${SIGNING_INPUT}/public.asc"
    rmdir -- "${SIGNING_INPUT}"
    SIGNING_INPUT=""
}
trap cleanup_signing_input EXIT

[[ -n ${SIGNING_KEY} ]] || die "SIGNING_KEY unset; unsigned packages are not publishable"
[[ ${SIGNING_KEY} =~ ^[0-9A-Fa-f]{40}$ ]] ||
    die "SIGNING_KEY must be a 40-character fingerprint, got: ${SIGNING_KEY}"

if [[ -z ${BINHOST_LOCKED:-} ]]; then
    LOCK="${LOCK:-/var/lib/binhost/stage/build.lock}"
    mkdir -p "$(dirname "${LOCK}")"
    exec 9>"${LOCK}"
    flock -n 9 || die "另一次构建正在执行（${LOCK}）"
fi

[[ -s ${LIST} ]] || die "package list not found or empty: ${LIST}"
channel_mounts=()
channel_excluded_list=""
if [[ ${CHANNEL} == stable ]]; then
    [[ -s ${STABLE_EXCLUDED} ]] || die "stable exclusion list not found: ${STABLE_EXCLUDED}"
    [[ -s ${STABLE_PACKAGE_USE} ]] || die "stable package.use not found: ${STABLE_PACKAGE_USE}"
    EFFECTIVE_LIST="${EFFECTIVE_LIST:-${STAGE}.packages.txt}"
    sudo install -dm755 -o "$(id -u)" -g "$(id -g)" \
        "$(dirname "${EFFECTIVE_LIST}")"
    python3 "$(dirname "$0")/channel_packages.py" \
        "${LIST}" "${STABLE_EXCLUDED}" "${EFFECTIVE_LIST}"
    LIST="${EFFECTIVE_LIST}"
    channel_excluded_list="${STABLE_EXCLUDED}"
    channel_mounts=(-v "${STABLE_PACKAGE_USE}:/tmp/package.use.stable:ro")
fi
[[ ${SIGNING_IMAGE} =~ @sha256:[0-9a-f]{64}$ ]] ||
    die "SIGNING_IMAGE must be pinned by sha256 digest"
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
    CHANNEL="${CHANNEL}" TAG="${TAG}" BASE="${BASE}" SIGNING_KEY="${SIGNING_KEY}" \
    TREE="${TREE}" OVERLAY="${OVERLAY}" DISTDIR="${DISTDIR}" PKGDIR="${PKGDIR}" \
    SIGNING_GNUPGHOME="${SIGNING_GNUPGHOME}" JOBS="${JOBS}" MAKEOPTS="${MAKEOPTS}" \
        "$(dirname "$0")/base-image.sh"
fi

sudo install -dm755 -o "$(id -u)" -g "$(id -g)" \
    "${PKGDIR}" "$(dirname "${STAGE}")" "${LOGDIR}" "${GENTOO_BINPKGS}"
rm -f "${LOGDIR}"/*.log "${LOGDIR}"/failed.txt "${LOGDIR}"/gentoo-Packages \
    "${LOGDIR}"/smoke-install.json "${LOGDIR}"/smoke-alert.txt

empty=$(find "${PKGDIR}" -name '*.gpkg.tar' -size 0 -print -delete | wc -l)
(( empty )) && echo ">>> 移除 ${empty} 个 0 字节的缓存包" 


echo ">>> building from ${BASE}"

${DOCKER} run --rm -i --security-opt=no-new-privileges \
    -v "${TREE}:/var/db/repos/gentoo:ro" \
    -v "${OVERLAY}:/var/db/repos/gentoo-zh:ro" \
    -v "${DISTDIR}:/var/cache/distfiles" \
    -v "${PKGDIR}:/var/cache/binpkgs" \
    -v "${GENTOO_BINPKGS}:/var/cache/binhost/gentoo" \
    -v "${LIST}:/tmp/packages.txt:ro" \
    -v "${COMMON_PACKAGE_USE}:/tmp/package.use.common:ro" \
    "${channel_mounts[@]}" \
    -v "$(dirname "$0")/rebuild-preserved.sh:/usr/local/bin/rebuild-preserved:ro" \
    -v "$(dirname "$0")/preserved-consumers.py:/usr/local/bin/preserved-consumers:ro" \
    -v "$(dirname "$0")/snapshot-binrepo.py:/usr/local/bin/snapshot-binrepo:ro" \
    -v "$(dirname "$0")/snapshot-vdb.py:/usr/local/bin/snapshot-vdb:ro" \
    -v "${LOGDIR}:/var/log/binhost" \
    -e "OVERLAY_REV=$(git -C "${OVERLAY}" rev-parse HEAD 2>/dev/null || echo '')" \
    -e "BINHOST_CHANNEL=${CHANNEL}" \
    -e "MAKEOPTS=${MAKEOPTS}" \
    -e "JOBS=${JOBS}" \
    "${BASE}" /bin/bash -euo pipefail -s <<'INNER'

mkdir -p /run/lock

cat >> /etc/portage/make.conf <<EOF
PORTAGE_BINHOST_TTL="3600"
EOF

mkdir -p /etc/portage/package.use
cat /tmp/package.use.common > /etc/portage/package.use/binhost-deps

if [[ ${BINHOST_CHANNEL} == stable ]]; then
    cat /tmp/package.use.stable >> /etc/portage/package.use/binhost-deps
fi

mapfile -t atoms < <(grep -E '^[a-z0-9-]+/[A-Za-z0-9._+-]+$' /tmp/packages.txt)
echo ">>> ${#atoms[@]} packages"

EMERGE=(emerge --usepkg --changed-use --with-bdeps=y --quiet-build)
FETCH_RETRY_WAIT="${FETCH_RETRY_WAIT:-180}"

python3 /usr/local/bin/snapshot-vdb /var/db/pkg /var/log/binhost/installed.txt

# A distribution kernel takes twenty minutes and kernel-archive.sh builds it
# separately into /gentoo-cjk-kernel/, outside this index. Match only
# virtual/dist-kernel: every dist-kernel arrives through it, while
# sys-kernel/installkernel, dracut and linux-headers belong in the container.
echo "::: 检查清单没有拉进分发内核"
if "${EMERGE[@]}" --pretend --quiet "${atoms[@]}" 2>/dev/null |
        grep -E '^\[[^]]*\] +virtual/dist-kernel' > /tmp/kernel-pull.txt; then
    echo "!!! 清单会拉进分发内核，停止构建："
    sed 's/^/    /' /tmp/kernel-pull.txt
    exit 1
fi

echo "::: 整体解析"
failed=()
if "${EMERGE[@]}" "${atoms[@]}" > /var/log/binhost/whole.log 2>&1; then
    echo ">>> 整体一次完成，未逐包重新执行"
    rm -f /var/log/binhost/whole.log
else
    echo "!!! 整体失败，退回逐包（每包一份日志）"
    tail -5 /var/log/binhost/whole.log | sed 's/^/    /'
    done_count=0
    for atom in "${atoms[@]}"; do
        printf '%s %s %s\n' "${done_count}" "${#atoms[@]}" "${atom}" \
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
        done_count=$(( done_count + 1 ))
    done
    rm -f /var/log/binhost/progress

    # Portage gives up after three attempts within seconds. A few seconds of
    # upstream flakiness then costs the whole channel a publication, because a
    # package that fails to build leaves the index short and the version check
    # refuses to publish. Retry the fetch failures once, after a pause.
    retry=()
    for atom in ${failed[@]+"${failed[@]}"}; do
        log=/var/log/binhost/${atom//\//_}.log
        grep -qE "Unable to fetch|Couldn't download" "${log}" 2>/dev/null &&
            retry+=("${atom}")
    done
    if (( ${#retry[@]} )); then
        echo "::: ${#retry[@]} 个取源失败，等待 ${FETCH_RETRY_WAIT} 秒后重试一次"
        sleep "${FETCH_RETRY_WAIT}"
        recovered=()
        for atom in "${retry[@]}"; do
            log=/var/log/binhost/${atom//\//_}.log
            echo "::: 重试 ${atom}"
            if "${EMERGE[@]}" "${atom}" > "${log}.retry" 2>&1; then
                echo "    重试成功 ${atom}"
                recovered+=("${atom}")
                rm -f "${log}" "${log}.retry"
            else
                mv -f "${log}.retry" "${log}"
            fi
        done
        if (( ${#recovered[@]} )); then
            remaining=()
            for atom in "${failed[@]}"; do
                keep=yes
                for got in "${recovered[@]}"; do
                    [[ ${atom} == "${got}" ]] && { keep=no; break; }
                done
                [[ ${keep} == yes ]] && remaining+=("${atom}")
            done
            failed=(${remaining[@]+"${remaining[@]}"})
            : > /var/log/binhost/failed.txt
            for atom in ${failed[@]+"${failed[@]}"}; do
                echo "${atom}" >> /var/log/binhost/failed.txt
            done
        fi
    fi
fi

echo "::: 重建保留库的使用者"
/usr/local/bin/rebuild-preserved /var/log/binhost/preserved-rebuild.log

emaint binhost --fix
if ! python3 /usr/local/bin/snapshot-binrepo \
        /etc/portage/binrepos.conf/gentoo.conf /var/cache/edb/binhost \
        /var/log/binhost/gentoo-Packages; then
    echo "!! 无法记录 Gentoo binhost 索引，本次发布闸门将阻断" >&2
fi

if (( ${#failed[@]} )); then
    printf '!!! %d failed:\n' "${#failed[@]}"
    printf '      %s\n' "${failed[@]}"
fi
INNER

# The build container writes PKGDIR as root, so the directories it creates are
# not writable by this user. persist-packages.py runs here, unprivileged, and
# cannot place its temporary file next to the package it replaces.
sudo chown -R "$(id -u):$(id -g)" "${PKGDIR}"

rm -rf "${STAGE}.new"
install -dm755 "${STAGE}.new"

stage_policy=()
if [[ ${CHANNEL} == stable ]]; then
    stage_policy+=(--seeds "${LIST}" --exclude-file "${STABLE_EXCLUDED}")
fi
OVERLAY_REV="$(git -C "${OVERLAY}" rev-parse HEAD 2>/dev/null || echo '')" \
    GENTOO_TREE="${TREE}" \
    python3 "$(dirname "$0")/stage-index.py" "${PKGDIR}" "${STAGE}.new" \
        "${OVERLAY}" "${stage_policy[@]}"

install -m644 "${LOGDIR}/installed.txt" "${STAGE}.new/installed.txt" 2>/dev/null ||
    die "容器没有写出 installed.txt，无法判定哪些依赖由基础系统提供"

OVERLAY_REV="$(git -C "${OVERLAY}" rev-parse HEAD 2>/dev/null || echo '')"
[[ -d ${SIGNING_TMP_ROOT} && -w ${SIGNING_TMP_ROOT} ]] ||
    die "signing tmpfs is unavailable: ${SIGNING_TMP_ROOT}"
[[ $(stat -f -c %T "${SIGNING_TMP_ROOT}") == tmpfs ]] ||
    die "signing input directory is not tmpfs: ${SIGNING_TMP_ROOT}"
${DOCKER} pull -q "${SIGNING_IMAGE}" >/dev/null ||
    die "cannot pull pinned SIGNING_IMAGE"
SIGNING_INPUT=$(mktemp -d "${SIGNING_TMP_ROOT}/binhost-signing.XXXXXX")
(
    umask 077
    gpg --homedir "${SIGNING_GNUPGHOME}" --batch --yes \
        --output "${SIGNING_INPUT}/private.gpg" --export-secret-keys "${SIGNING_KEY}"
    gpg --homedir "${SIGNING_GNUPGHOME}" --batch --yes --armor \
        --output "${SIGNING_INPUT}/public.asc" --export "${SIGNING_KEY}"
)
[[ -s ${SIGNING_INPUT}/private.gpg && -s ${SIGNING_INPUT}/public.asc ]] ||
    die "cannot export the selected signing key"
sign_uid=$(id -u)
sign_gid=$(id -g)
# shellcheck disable=SC2016  # The inner shell expands the quoted script.
if ! ${DOCKER} run --rm --network none --read-only \
        --cap-drop=ALL --security-opt=no-new-privileges \
        --user "${sign_uid}:${sign_gid}" \
        --tmpfs "/tmp:rw,noexec,nosuid,nodev,mode=1777,uid=${sign_uid},gid=${sign_gid}" \
        --tmpfs "/run/lock:rw,noexec,nosuid,nodev,mode=0755,uid=${sign_uid},gid=${sign_gid}" \
        --tmpfs "/run/gnupg:rw,noexec,nosuid,nodev,mode=0700,uid=${sign_uid},gid=${sign_gid}" \
        -v "${STAGE}.new:/var/cache/binpkgs" \
        -v "${SIGNING_INPUT}/private.gpg:/run/signing-private.gpg:ro" \
        -v "${SIGNING_INPUT}/public.asc:/run/signing-public.asc:ro" \
        -v "$(dirname "$0")/sign-packages.py:/usr/local/bin/sign-packages.py:ro" \
        -v "$(dirname "$0")/verify-signatures.py:/usr/local/bin/verify-signatures.py:ro" \
        -e "HOME=/tmp" -e "SIGNING_KEY=${SIGNING_KEY}" -e "OVERLAY_REV=${OVERLAY_REV}" \
        "${SIGNING_IMAGE}" /bin/bash -euo pipefail -c '
            gpg --homedir /run/gnupg --batch --import /run/signing-private.gpg
            gpg --homedir /run/gnupg --batch --import /run/signing-public.asc
            printf "%s:6:\n" "${SIGNING_KEY}" |
                gpg --homedir /run/gnupg --batch --import-ownertrust
            gpg --homedir /run/gnupg --batch --check-trustdb
            export FEATURES="${FEATURES:-} binpkg-signing"
            export BINPKG_GPG_SIGNING_KEY="${SIGNING_KEY}"
            export BINPKG_GPG_SIGNING_GPG_HOME=/run/gnupg
            export BINPKG_GPG_VERIFY_GPG_HOME=/run/gnupg
            python3 /usr/local/bin/sign-packages.py /var/cache/binpkgs \
                --revision "${OVERLAY_REV}" \
                --public-key /run/signing-public.asc \
                --fingerprint "${SIGNING_KEY}" \
                --changed-list /var/cache/binpkgs/.signed-packages
        '; then
    echo "签名失败，本次只执行隔离，不发布新索引" \
        > "${STAGE}.new/publish-blocked.txt"
elif ! python3 "$(dirname "$0")/verify-signatures.py" "${STAGE}.new" \
        "${SIGNING_INPUT}/public.asc" "${SIGNING_KEY}"; then
    echo "宿主机独立验签失败，本次只执行隔离，不发布新索引" \
        > "${STAGE}.new/publish-blocked.txt"
elif ! python3 "$(dirname "$0")/persist-packages.py" "${STAGE}.new" \
        "${PKGDIR}" "${STAGE}.new/.signed-packages"; then
    echo "无法持久化已验签的软件包，本次只执行隔离，不发布新索引" \
        > "${STAGE}.new/publish-blocked.txt"
fi
cleanup_signing_input

source_policy=(--source-keywords "${CHANNEL_ACCEPT_KEYWORDS}")
if [[ -n ${CHANNEL_OVERLAY_KEYWORDS} ]]; then
    source_policy+=(--source-overlay-keywords "${CHANNEL_OVERLAY_KEYWORDS}")
fi
if [[ ! -s ${STAGE}.new/publish-blocked.txt ]] &&
   ! python3 "$(dirname "$0")/verify-deps.py" "${STAGE}.new/Packages" \
        --installed "${STAGE}.new/installed.txt" \
        --available "${LOGDIR}/gentoo-Packages" \
        --write-available "${STAGE}.new/official.txt" \
        --source-tree "${TREE}" --source-overlay "${OVERLAY}" \
        "${source_policy[@]}" \
        --write-source "${STAGE}.new/source.txt"; then
    echo "暂存索引未通过运行期依赖验证，本次只执行隔离" \
        > "${STAGE}.new/publish-blocked.txt"
fi

if [[ ! -s ${STAGE}.new/publish-blocked.txt ]] &&
   ! GENTOO_TREE="${TREE}" CHANNEL_EXCLUDED="${channel_excluded_list}" \
        python3 "$(dirname "$0")/check-versions.py" \
        "${OVERLAY}" "${STAGE}.new/Packages" "${LIST}"; then
    echo "暂存索引未覆盖清单中的当前可用版本，本次只执行隔离" \
        > "${STAGE}.new/publish-blocked.txt"
fi

if [[ ! -s ${STAGE}.new/publish-blocked.txt ]]; then
    smoke_package_use="${LOGDIR}/smoke-package.use"
    cat "${COMMON_PACKAGE_USE}" > "${smoke_package_use}"
    if [[ ${CHANNEL} == stable ]]; then
        cat "${STABLE_PACKAGE_USE}" >> "${smoke_package_use}"
    fi
    # Source fallback is normal Gentoo behavior. Making it a publication gate
    # would keep this check permanently red, after which its alerts get ignored.
    smoke_rc=0
    python3 "$(dirname "$0")/smoke-install.py" \
        --channel "${CHANNEL}" --stage "${STAGE}.new" \
        --changed-list "${STAGE}.new/.signed-packages" \
        --report "${LOGDIR}/smoke-install.json" \
        --alert "${LOGDIR}/smoke-alert.txt" \
        --base "${BASE}" --tree "${TREE}" --overlay "${OVERLAY}" \
        --gentoo-binpkgs "${GENTOO_BINPKGS}" \
        --gentoo-index "${LOGDIR}/gentoo-Packages" \
        --package-use "${smoke_package_use}" --docker "${DOCKER}" || smoke_rc=$?
    # smoke-install.py writes its own report for every failure it can name, so
    # a non-zero exit here means the check itself did not run. Fabricating a
    # report for that would put the schema in two places; the alert is what has
    # to reach someone.
    if (( smoke_rc )); then
        printf '冒烟测试本身未能执行（退出码 %s），本轮没有报告\n' "${smoke_rc}" \
            > "${LOGDIR}/smoke-alert.txt"
        echo ">>> gpkg 安装冒烟测试：本身未能执行，退出码 ${smoke_rc}"
    fi
    rm -f "${smoke_package_use}"

    gzip -kf "${STAGE}.new/Packages"
    python3 "$(dirname "$0")/generation.py" create "${STAGE}.new" ||
        die "无法建立同代清单"
fi
rm -f "${STAGE}.new/.signed-packages"

rm -rf "${STAGE}.old"
[[ -d ${STAGE} ]] && mv "${STAGE}" "${STAGE}.old"
mv "${STAGE}.new" "${STAGE}"
echo ">>> staged at ${STAGE} (previous generation kept at ${STAGE}.old)"

if [[ -s ${STAGE}/publish-blocked.txt ]]; then
    cat "${STAGE}/publish-blocked.txt" >&2
fi

if [[ -s ${LOGDIR}/failed.txt ]]; then
    python3 "$(dirname "$0")/classify-failures.py" "${LOGDIR}" | tee "${LOGDIR}/report.txt"
else
    rm -f "${LOGDIR}/report.txt"
fi

}

main "$@"
