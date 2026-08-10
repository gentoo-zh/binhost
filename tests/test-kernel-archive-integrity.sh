#!/bin/bash

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
ARCHIVE_SCRIPT=${KERNEL_ARCHIVE_SCRIPT:-${ROOT}/build/kernel-archive.sh}
WORK=$(mktemp -d)
trap 'rm -rf "${WORK}"' EXIT


mkdir -p "${WORK}/bin" "${WORK}/overlay" "${WORK}/tree" \
    "${WORK}/metadata/metadata" "${WORK}/outer/gentoo-cjk-kernel-7.1.7-1"
REAL_PYTHON=$(command -v python3)
NAME=gentoo-cjk-kernel-7.1.7-1.amd64.gpkg.tar
printf 'cjk\n' > "${WORK}/metadata/metadata/USE"
tar -C "${WORK}/metadata" -cf - metadata | zstd -q -o "${WORK}/metadata.tar.zst"
cp "${WORK}/metadata.tar.zst" \
    "${WORK}/outer/gentoo-cjk-kernel-7.1.7-1/metadata.tar.zst"
tar --mtime=@1 -C "${WORK}/outer" -cf "${WORK}/built-first.gpkg.tar" \
    gentoo-cjk-kernel-7.1.7-1
tar --mtime=@2 -C "${WORK}/outer" -cf "${WORK}/built-second.gpkg.tar" \
    gentoo-cjk-kernel-7.1.7-1
cp "${WORK}/built-first.gpkg.tar" "${WORK}/corrupt.gpkg.tar"
printf X | dd of="${WORK}/corrupt.gpkg.tar" bs=1 seek=512 conv=notrunc status=none

cat > "${WORK}/bin/python3" <<EOF
#!/bin/bash
if [[ \$1 == */kernel-series.py ]]; then
    cat "${WORK}/series"
else
    exec '${REAL_PYTHON}' "\$@"
fi
EOF

cat > "${WORK}/bin/ssh" <<'EOF'
#!/bin/bash
command=$2
case "${command}" in
    bash)
        path=$5
        checksum=$6
        if [[ ${REMOTE_CHECK_MODE} == fake-good ]]; then
            printf '%s\n%s  archive\n' "${FAKE_SIZE}" "${FAKE_DIGEST}"
        else
            source="${TEST_REMOTE}${path}"
            [[ -f ${source} ]] || exit 1
            stat -c '%s' "${source}"
            "${checksum}" "${source}"
        fi
        ;;
    *'ls -1 */*.gpkg.tar'*)
        if [[ -d ${TEST_REMOTE}${TEST_REMOTE_ROOT} ]]; then
            find "${TEST_REMOTE}${TEST_REMOTE_ROOT}" -mindepth 2 -maxdepth 2 \
                -type f -name '*.gpkg.tar' -printf '%P\n'
        fi
        ;;
    "ls -1 ${TEST_REMOTE_ROOT} 2>/dev/null")
        if [[ -d ${TEST_REMOTE}${TEST_REMOTE_ROOT} ]]; then
            find "${TEST_REMOTE}${TEST_REMOTE_ROOT}" -mindepth 1 -maxdepth 1 \
                -type d -printf '%f\n'
        fi
        ;;
    'install -dm755 '*)
        path=${command#install -dm755 }
        mkdir -p "${TEST_REMOTE}${path}"
        ;;
    'rm -f '*)
        path=${command#rm -f }
        rm -f "${TEST_REMOTE}${path}"
        ;;
    'rm -rf '*)
        path=${command#rm -rf }
        rm -rf "${TEST_REMOTE}${path}"
        ;;
esac
EOF

cat > "${WORK}/bin/docker" <<'EOF'
#!/bin/bash
mkdir -p "${TEST_PKGDIR}/sys-kernel/gentoo-cjk-kernel"
cp "${TEST_BUILT}" \
    "${TEST_PKGDIR}/sys-kernel/gentoo-cjk-kernel/gentoo-cjk-kernel-7.1.7-1.gpkg.tar"
EOF

cat > "${WORK}/bin/rsync" <<'EOF'
#!/bin/bash
source=$2
destination=$3
case "${source}" in
    "${TEST_REMOTE_NAME}:"*)
        cp "${DOWNLOAD_SOURCE:-${TEST_REMOTE}${source#${TEST_REMOTE_NAME}:}}" \
            "${destination}"
        ;;
    *)
        [[ ${RSYNC_FAIL} != upload ]] || exit 23
        path=${destination#${TEST_REMOTE_NAME}:}
        cp "${source}" "${TEST_REMOTE}${path}"
        ;;
esac
EOF
chmod +x "${WORK}/bin"/*

write_manifest() {
    local name=$1 source=$2 size sha512 blake2b
    size=$(stat -c %s "${source}")
    sha512=$(sha512sum "${source}" | awk '{print $1}')
    blake2b=$(b2sum "${source}" | awk '{print $1}')
    printf 'DIST %s %s BLAKE2B %s SHA512 %s\n' \
        "${name}" "${size}" "${blake2b}" "${sha512}" > "${WORK}/Manifest"
}

reset_case() {
    rm -rf "${WORK}/pkgdir" "${WORK}/published" "${WORK}/remote"
    mkdir -p "${WORK}/pkgdir/sys-kernel/gentoo-cjk-kernel" \
        "${WORK}/published" "${WORK}/remote/archive"
    printf '7.1 7.1.7\n' > "${WORK}/series"
    TEST_BUILT="${WORK}/built-first.gpkg.tar"
    REMOTE_CHECK_MODE="file"
    RSYNC_FAIL=none
    DOWNLOAD_SOURCE=
    MAX_RETIRE=2
    write_manifest "${NAME}" "${TEST_BUILT}"
}

run_archive() {
    PATH="${WORK}/bin:${PATH}" OVERLAY="${WORK}/overlay" TREE="${WORK}/tree" \
        PKGDIR="${WORK}/pkgdir" PUBLISHED_DIR="${WORK}/published" \
        MANIFEST="${WORK}/Manifest" LOCK="${WORK}/lock" \
        REMOTE=test REMOTE_ROOT=/archive DOCKER=docker MAX_BUILDS="$1" \
        MAX_RETIRE="${MAX_RETIRE}" REMOTE_CHECK_MODE="${REMOTE_CHECK_MODE}" \
        FAKE_SIZE="${FAKE_SIZE:-}" FAKE_DIGEST="${FAKE_DIGEST:-}" \
        RSYNC_FAIL="${RSYNC_FAIL}" DOWNLOAD_SOURCE="${DOWNLOAD_SOURCE}" \
        TEST_REMOTE="${WORK}/remote" TEST_REMOTE_ROOT=/archive \
        TEST_REMOTE_NAME=test TEST_PKGDIR="${WORK}/pkgdir" \
        TEST_BUILT="${TEST_BUILT}" bash "${ARCHIVE_SCRIPT}"
}

reset_case
mkdir -p "${WORK}/remote/archive/7.1"
cp "${TEST_BUILT}" "${WORK}/remote/archive/7.1/${NAME}"
good=$(run_archive 0)
grep -q '已发布，跳过' <<< "${good}"
cmp "${TEST_BUILT}" "${WORK}/published/7.1/${NAME}"
echo "  ✓ 已发布的远端文件会核验并补齐本地副本"

reset_case
mkdir -p "${WORK}/remote/archive/7.1"
cp "${WORK}/corrupt.gpkg.tar" "${WORK}/remote/archive/7.1/${NAME}"
corrupt=$(run_archive 0)
grep -q '要建置' <<< "${corrupt}"
echo "  ✓ 同名但损坏的远端文件不按已发布处理"

reset_case
printf 'DIST %s %s SHA512 %0128d\n' \
    "${NAME}" "$(stat -c %s "${TEST_BUILT}")" 0 > "${WORK}/Manifest"
if run_archive 1 >/dev/null 2>&1; then
    echo "  ✗ 新产物与 Manifest 不符时应当失败"
    exit 1
fi
[[ ! -e ${WORK}/remote/archive/7.1/${NAME} ]]
[[ ! -e ${WORK}/published/7.1/${NAME} ]]
echo "  ✓ 新产物与 Manifest 不符时不上传也不保留"

reset_case
published=$(run_archive 1)
grep -q "已发布 7.1/${NAME}" <<< "${published}"
cmp "${TEST_BUILT}" "${WORK}/remote/archive/7.1/${NAME}"
cmp "${TEST_BUILT}" "${WORK}/published/7.1/${NAME}"
[[ ! -e ${WORK}/published/7.1/gentoo-cjk-kernel-7.1.7-1.gpkg.tar ]]
echo "  ✓ 发布成功后按发布名保留完全相同的位元组"

reset_case
RSYNC_FAIL=upload
if run_archive 1 >/dev/null 2>&1; then
    echo "  ✗ rsync 失败时发布应当失败"
    exit 1
fi
[[ ! -e ${WORK}/published/7.1/${NAME} ]]
echo "  ✓ rsync 失败时不写入保留副本"

reset_case
run_archive 1 >/dev/null
rm -f "${WORK}/remote/archive/7.1/${NAME}"
TEST_BUILT="${WORK}/built-second.gpkg.tar"
write_manifest "${NAME}" "${TEST_BUILT}"
run_archive 1 >/dev/null
cmp "${TEST_BUILT}" "${WORK}/published/7.1/${NAME}"
echo "  ✓ 再次发布同一个发布名会覆盖旧副本"

reset_case
CURRENT_NAME=gentoo-cjk-kernel-7.1.8-1.amd64.gpkg.tar
printf '7.1 7.1.8\n' > "${WORK}/series"
write_manifest "${CURRENT_NAME}" "${TEST_BUILT}"
mkdir -p "${WORK}/remote/archive/7.1" "${WORK}/published/7.1"
cp "${TEST_BUILT}" "${WORK}/remote/archive/7.1/${CURRENT_NAME}"
cp "${WORK}/corrupt.gpkg.tar" "${WORK}/remote/archive/7.1/${NAME}"
cp "${WORK}/corrupt.gpkg.tar" "${WORK}/published/7.1/${NAME}"
run_archive 0 >/dev/null
[[ ! -e ${WORK}/remote/archive/7.1/${NAME} ]]
[[ ! -e ${WORK}/published/7.1/${NAME} ]]
cmp "${TEST_BUILT}" "${WORK}/published/7.1/${CURRENT_NAME}"
echo "  ✓ overlay 移除版本后会同时清理远端档案与本地副本"

# A whole series leaving the overlay retires both sides. Without this the local
# store keeps a directory the mirror no longer serves, and recovery would put
# back a line the overlay dropped.
reset_case
printf '7.1 7.1.7\n' > "${WORK}/series"
mkdir -p "${WORK}/remote/archive/6.18" "${WORK}/published/6.18"
cp "${TEST_BUILT}" "${WORK}/remote/archive/6.18/gentoo-cjk-kernel-6.18.43-1.amd64.gpkg.tar"
cp "${TEST_BUILT}" "${WORK}/published/6.18/gentoo-cjk-kernel-6.18.43-1.amd64.gpkg.tar"
run_archive 0 >/dev/null
[[ ! -e ${WORK}/remote/archive/6.18 ]]
[[ ! -e ${WORK}/published/6.18 ]]
echo "  ✓ overlay 移除整条线后远端与本地副本一起退役"

reset_case
mkdir -p "${WORK}/remote/archive/7.1" "${WORK}/published/7.1"
cp "${TEST_BUILT}" "${WORK}/remote/archive/7.1/${NAME}"
cp "${TEST_BUILT}" "${WORK}/published/7.1/${NAME}"
for old in old-a old-b old-c; do
    printf '%s\n' "${old}" > "${WORK}/remote/archive/7.1/${old}.gpkg.tar"
    printf '%s\n' "${old}" > "${WORK}/published/7.1/${old}.gpkg.tar"
done
if run_archive 0 >"${WORK}/retire.out" 2>&1; then
    echo "  ✗ 超过 MAX_RETIRE 时应当失败"
    exit 1
fi
grep -q '超过上限 2，一个都不动' "${WORK}/retire.out"
for old in old-a old-b old-c; do
    [[ -e ${WORK}/remote/archive/7.1/${old}.gpkg.tar ]]
    [[ -e ${WORK}/published/7.1/${old}.gpkg.tar ]]
done
echo "  ✓ 超过 MAX_RETIRE 时远端与本地档案都不变"

reset_case
mkdir -p "${WORK}/remote/archive/7.1"
cp "${TEST_BUILT}" "${WORK}/remote/archive/7.1/${NAME}"
REMOTE_CHECK_MODE=fake-good
FAKE_SIZE=$(stat -c %s "${TEST_BUILT}")
FAKE_DIGEST=$(sha512sum "${TEST_BUILT}" | awk '{print $1}')
DOWNLOAD_SOURCE="${WORK}/corrupt.gpkg.tar"
if run_archive 0 >"${WORK}/backfill.out" 2>&1; then
    echo "  ✗ 补齐档案摘要不符时应当失败"
    exit 1
fi
grep -q '与 Manifest 不一致，不保留' "${WORK}/backfill.out"
[[ ! -e ${WORK}/published/7.1/${NAME} ]]
[[ -z $(find "${WORK}/published/7.1" -mindepth 1 -print -quit) ]]
echo "  ✓ 补齐档案摘要不符时不写入并报错"
