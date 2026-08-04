#!/bin/bash

set -euo pipefail

main() {
TAG="${TAG:-x86-64}"
BASE="${BASE:-gentoo-zh/binhost-base:${TAG}}"
SIGNING_IMAGE="${SIGNING_IMAGE:-gentoo/stage3@sha256:7f523210aa362e429cf47742c408400a0b8f8e4b618c39ab7dd691ef56f04d3a}"
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

if [[ -z ${BINHOST_LOCKED:-} ]]; then
    LOCK="${LOCK:-$(dirname "${STAGE}")/build.lock}"
    mkdir -p "$(dirname "${LOCK}")"
    exec 9>"${LOCK}"
    flock -n 9 || die "另一轮构建正在进行（${LOCK}）"
fi

[[ -s ${LIST} ]] || die "package list not found or empty: ${LIST}"
[[ -n ${SIGNING_KEY} ]] || die "SIGNING_KEY unset; unsigned packages are not publishable"
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
    TAG="${TAG}" BASE="${BASE}" SIGNING_KEY="${SIGNING_KEY}" \
    TREE="${TREE}" OVERLAY="${OVERLAY}" DISTDIR="${DISTDIR}" PKGDIR="${PKGDIR}" \
    SIGNING_GNUPGHOME="${SIGNING_GNUPGHOME}" JOBS="${JOBS}" MAKEOPTS="${MAKEOPTS}" \
        "$(dirname "$0")/base-image.sh"
fi

sudo install -dm755 -o "$(id -u)" -g "$(id -g)" \
    "${PKGDIR}" "$(dirname "${STAGE}")" "${LOGDIR}" "${GENTOO_BINPKGS}"
rm -f "${LOGDIR}"/*.log "${LOGDIR}"/failed.txt "${LOGDIR}"/gentoo-Packages

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
    -v "$(dirname "$0")/snapshot-binrepo.py:/usr/local/bin/snapshot-binrepo:ro" \
    -v "$(dirname "$0")/snapshot-vdb.py:/usr/local/bin/snapshot-vdb:ro" \
    -v "${LOGDIR}:/var/log/binhost" \
    -e "OVERLAY_REV=$(git -C "${OVERLAY}" rev-parse HEAD 2>/dev/null || echo '')" \
    "${BASE}" /bin/bash -euo pipefail -s <<'INNER'

mkdir -p /run/lock

cat >> /etc/portage/make.conf <<EOF
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

python3 /usr/local/bin/snapshot-vdb /var/db/pkg /var/log/binhost/installed.txt

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
fi

emaint binhost --fix
if ! python3 /usr/local/bin/snapshot-binrepo \
        /etc/portage/binrepos.conf/gentoo.conf /var/cache/edb/binhost \
        /var/log/binhost/gentoo-Packages; then
    echo "!! 无法记录 Gentoo binhost 索引，本轮发布闸门将阻断" >&2
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

OVERLAY_REV="$(git -C "${OVERLAY}" rev-parse HEAD 2>/dev/null || echo '')" \
    GENTOO_TREE="${TREE}" \
    python3 "$(dirname "$0")/stage-index.py" "${PKGDIR}" "${STAGE}.new" "${OVERLAY}"

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
    echo "签名失败，本轮只执行隔离，不发布新索引" \
        > "${STAGE}.new/publish-blocked.txt"
elif ! python3 "$(dirname "$0")/verify-signatures.py" "${STAGE}.new" \
        "${SIGNING_INPUT}/public.asc" "${SIGNING_KEY}"; then
    echo "宿主机独立验签失败，本轮只执行隔离，不发布新索引" \
        > "${STAGE}.new/publish-blocked.txt"
elif ! python3 "$(dirname "$0")/persist-packages.py" "${STAGE}.new" \
        "${PKGDIR}" "${STAGE}.new/.signed-packages"; then
    echo "无法持久化已验签的软件包，本轮只执行隔离，不发布新索引" \
        > "${STAGE}.new/publish-blocked.txt"
fi
cleanup_signing_input
rm -f "${STAGE}.new/.signed-packages"

if [[ ! -s ${STAGE}.new/publish-blocked.txt ]] &&
   ! python3 "$(dirname "$0")/verify-deps.py" "${STAGE}.new/Packages" \
        --installed "${STAGE}.new/installed.txt" \
        --available "${LOGDIR}/gentoo-Packages" \
        --write-available "${STAGE}.new/official.txt" \
        --source-tree "${TREE}" --source-overlay "${OVERLAY}" \
        --write-source "${STAGE}.new/source.txt"; then
    echo "暂存索引未通过运行期依赖验证，本轮只执行隔离" \
        > "${STAGE}.new/publish-blocked.txt"
fi

if [[ ! -s ${STAGE}.new/publish-blocked.txt ]] &&
   ! GENTOO_TREE="${TREE}" python3 "$(dirname "$0")/check-versions.py" \
        "${OVERLAY}" "${STAGE}.new/Packages" "${LIST}"; then
    echo "暂存索引未覆盖清单中的当前可用版本，本轮只执行隔离" \
        > "${STAGE}.new/publish-blocked.txt"
fi

if [[ ! -s ${STAGE}.new/publish-blocked.txt ]]; then
    gzip -kf "${STAGE}.new/Packages"
    python3 "$(dirname "$0")/generation.py" create "${STAGE}.new" ||
        die "无法建立同代清单"
fi

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
