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
# Enough entries that `tar -tf | head -n1` reliably takes SIGPIPE. A real gpkg
# lists tens of thousands of paths; a two-entry fixture hid that for weeks.
mkdir -p "${WORK}/outer/gentoo-cjk-kernel-7.1.7-1/image"
for i in $(seq 1 3000); do
    : > "${WORK}/outer/gentoo-cjk-kernel-7.1.7-1/image/f${i}"
done
tar -C "${WORK}/metadata" -cf - metadata | zstd -q -o "${WORK}/metadata.tar.zst"
cp "${WORK}/metadata.tar.zst" \
    "${WORK}/outer/gentoo-cjk-kernel-7.1.7-1/metadata.tar.zst"
tar --mtime=@1 -C "${WORK}/outer" -cf "${WORK}/built-first.gpkg.tar" \
    gentoo-cjk-kernel-7.1.7-1
tar --mtime=@2 -C "${WORK}/outer" -cf "${WORK}/built-second.gpkg.tar" \
    gentoo-cjk-kernel-7.1.7-1
mkdir -p "${WORK}/outer-wrong/gentoo-cjk-kernel-7.1.7-3"
cp "${WORK}/metadata.tar.zst" \
    "${WORK}/outer-wrong/gentoo-cjk-kernel-7.1.7-3/metadata.tar.zst"
tar --mtime=@1 -C "${WORK}/outer-wrong" -cf "${WORK}/wrong-inner.gpkg.tar" \
    gentoo-cjk-kernel-7.1.7-3
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
printf '%s\n' docker >> "${DOCKER_CALLS}"
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
    rm -rf "${WORK}/pkgdir" "${WORK}/published" "${WORK}/remote" "${WORK}/docker.calls"
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
        DOCKER_CALLS="${WORK}/docker.calls" \
        EXTRA_VARIANTS="${EXTRA_VARIANTS-}" \
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
mkdir -p "${WORK}/published/7.1"
cp "${WORK}/corrupt.gpkg.tar" "${WORK}/published/7.1/${NAME}"
if run_archive 0 >"${WORK}/corrupt.out" 2>&1; then
    echo "  ✗ 远端与保留副本都损坏时应当失败"
    exit 1
fi
grep -q "${NAME}" "${WORK}/corrupt.out"
[[ ! -s ${WORK}/docker.calls ]]
echo "  ✓ 远端与保留副本都损坏时不重建也不发布"

reset_case
: > "${WORK}/Manifest"
pending=$(run_archive 1)
grep -q "已发布 7.1/${NAME}" <<< "${pending}"
[[ $(grep -c "^DIST ${NAME} " "${WORK}/published/pending-manifest.txt") == 1 ]]
python3 "${ROOT}/build/kernel-manifest.py" entry \
    "${WORK}/published/pending-manifest.txt" "${NAME}" > "${WORK}/pending.entry"
read -r pending_size pending_algorithm pending_digest < "${WORK}/pending.entry"
[[ ${pending_size} == "$(stat -c %s "${TEST_BUILT}")" ]]
[[ ${pending_algorithm} == SHA512 ]]
[[ ${pending_digest} == "$(sha512sum "${TEST_BUILT}" | awk '{print $1}')" ]]
echo "  ✓ Manifest 没有普通变体时构建发布并记录待加入条目"

run_archive 1 >/dev/null
[[ $(grep -c "^DIST ${NAME} " "${WORK}/published/pending-manifest.txt") == 1 ]]
[[ $(wc -l < "${WORK}/docker.calls") == 1 ]]
echo "  ✓ 待加入 Manifest 条目会去重"

printf X | dd of="${WORK}/remote/archive/7.1/${NAME}" bs=1 seek=512 conv=notrunc status=none
recovered_pending=$(run_archive 1)
grep -q '从保留副本恢复' <<< "${recovered_pending}"
[[ $(wc -l < "${WORK}/docker.calls") == 1 ]]
cmp "${WORK}/built-first.gpkg.tar" "${WORK}/remote/archive/7.1/${NAME}"
echo "  ✓ pending 条目对应的远端损坏时从保留副本恢复且不重建"

reset_case
: > "${WORK}/Manifest"
run_archive 1 >/dev/null
printf X | dd of="${WORK}/remote/archive/7.1/${NAME}" bs=1 seek=512 conv=notrunc status=none
printf X | dd of="${WORK}/published/7.1/${NAME}" bs=1 seek=512 conv=notrunc status=none
TEST_BUILT="${WORK}/built-second.gpkg.tar"
run_archive 1 >/dev/null
python3 "${ROOT}/build/kernel-manifest.py" entry \
    "${WORK}/published/pending-manifest.txt" "${NAME}" > "${WORK}/pending.entry"
read -r _ _ updated_digest < "${WORK}/pending.entry"
[[ ${updated_digest} == "$(sha512sum "${TEST_BUILT}" | awk '{print $1}')" ]]
[[ ${updated_digest} != "$(sha512sum "${WORK}/built-first.gpkg.tar" | awk '{print $1}')" ]]
[[ $(wc -l < "${WORK}/docker.calls") == 2 ]]
echo "  ✓ pending 条目两侧损坏时重建并更新摘要"

reset_case
mkdir -p "${WORK}/remote/archive/7.1" "${WORK}/published/7.1"
cp "${WORK}/corrupt.gpkg.tar" "${WORK}/remote/archive/7.1/${NAME}"
cp "${TEST_BUILT}" "${WORK}/published/7.1/${NAME}"
recovered=$(run_archive 0)
grep -q "从保留副本恢复" <<< "${recovered}"
cmp "${TEST_BUILT}" "${WORK}/remote/archive/7.1/${NAME}"
[[ ! -s ${WORK}/docker.calls ]]
echo "  ✓ 远端损坏时会从正确的保留副本恢复且不起容器"

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
: > "${WORK}/Manifest"
published=$(run_archive 1)
grep -q "已发布 7.1/${NAME}" <<< "${published}"
cmp "${TEST_BUILT}" "${WORK}/remote/archive/7.1/${NAME}"
cmp "${TEST_BUILT}" "${WORK}/published/7.1/${NAME}"
[[ ! -e ${WORK}/published/7.1/gentoo-cjk-kernel-7.1.7-1.gpkg.tar ]]
echo "  ✓ 发布成功后按发布名保留完全相同的字节"

# The -bin ebuild resolves BINPKG=${P/-bin}-1 against the directory inside the
# gpkg. Renaming the file does not rename what is inside it, so an artifact with
# the right file name and the wrong inner directory has to be refused.
reset_case
TEST_BUILT="${WORK}/wrong-inner.gpkg.tar"
: > "${WORK}/Manifest"
if run_archive 1 >"${WORK}/inner.out" 2>&1; then
    echo "  ✗ 包内目录不是 -1 时应当失败"
    exit 1
fi
grep -q '不是 -1' "${WORK}/inner.out"
[[ ! -e ${WORK}/remote/archive/7.1/${NAME} ]]
[[ ! -e ${WORK}/published/7.1/${NAME} ]]
echo "  ✓ 包内目录不是 -1 时不发布也不保留"

reset_case
: > "${WORK}/Manifest"
RSYNC_FAIL=upload
if run_archive 1 >/dev/null 2>&1; then
    echo "  ✗ rsync 失败时发布应当失败"
    exit 1
fi
[[ ! -e ${WORK}/published/7.1/${NAME} ]]
echo "  ✓ rsync 失败时不写入保留副本"

reset_case
: > "${WORK}/Manifest"
run_archive 1 >/dev/null
rm -f "${WORK}/remote/archive/7.1/${NAME}"
TEST_BUILT="${WORK}/built-second.gpkg.tar"
rm -f "${WORK}/published/pending-manifest.txt"
run_archive 1 >/dev/null
cmp "${TEST_BUILT}" "${WORK}/published/7.1/${NAME}"
echo "  ✓ 再次发布同一个发布名会覆盖旧副本"

reset_case
CURRENT_NAME=gentoo-cjk-kernel-7.1.8-1.amd64.gpkg.tar
printf '7.1 7.1.8\n' > "${WORK}/series"
write_manifest "${CURRENT_NAME}" "${TEST_BUILT}"
mkdir -p "${WORK}/remote/archive/7.1" "${WORK}/published/7.1"
cp "${TEST_BUILT}" "${WORK}/remote/archive/7.1/${CURRENT_NAME}"
printf old > "${WORK}/remote/archive/7.1/${NAME}"
printf old > "${WORK}/published/7.1/${NAME}"
run_archive 0 >/dev/null
[[ ! -e ${WORK}/remote/archive/7.1/${NAME} ]]
[[ ! -e ${WORK}/published/7.1/${NAME} ]]
cmp "${TEST_BUILT}" "${WORK}/published/7.1/${CURRENT_NAME}"
echo "  ✓ overlay 移除版本后会同时清理远端文件与本地副本"

# A whole series leaving the overlay retires both sides. Without this the local
# store keeps a directory the mirror no longer serves, and recovery would put
# back a line the overlay dropped.
reset_case
printf '7.1 7.1.7\n' > "${WORK}/series"
: > "${WORK}/Manifest"
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
grep -q '超过上限 2，未执行清理' "${WORK}/retire.out"
for old in old-a old-b old-c; do
    [[ -e ${WORK}/remote/archive/7.1/${old}.gpkg.tar ]]
    [[ -e ${WORK}/published/7.1/${old}.gpkg.tar ]]
done
echo "  ✓ 超过 MAX_RETIRE 时远端与本地文件都不变"

reset_case
mkdir -p "${WORK}/remote/archive/7.1"
cp "${TEST_BUILT}" "${WORK}/remote/archive/7.1/${NAME}"
REMOTE_CHECK_MODE=fake-good
FAKE_SIZE=$(stat -c %s "${TEST_BUILT}")
FAKE_DIGEST=$(sha512sum "${TEST_BUILT}" | awk '{print $1}')
DOWNLOAD_SOURCE="${WORK}/corrupt.gpkg.tar"
if run_archive 0 >"${WORK}/backfill.out" 2>&1; then
    echo "  ✗ 补齐文件摘要不符时应当失败"
    exit 1
fi
grep -q '与 Manifest 不一致，不保留' "${WORK}/backfill.out"
[[ ! -e ${WORK}/published/7.1/${NAME} ]]
[[ -z $(find "${WORK}/published/7.1" -mindepth 1 -print -quit) ]]
echo "  ✓ 补齐文件摘要不符时不写入并报错"

# cjk32 is a different kernel image, so it is a second build under a second
# name. The two land on the same path in PKGDIR, which is why what comes back
# is read for the flags that were asked for and for the ones that were not.
CJK32_NAME=gentoo-cjk-kernel-7.1.7-1.amd64.cjk32.gpkg.tar
mkdir -p "${WORK}/meta32/metadata"
printf 'cjk cjk32\n' > "${WORK}/meta32/metadata/USE"
tar -C "${WORK}/meta32" -cf - metadata | zstd -q -o "${WORK}/meta32.tar.zst"
mkdir -p "${WORK}/outer32/gentoo-cjk-kernel-7.1.7-1/image"
for i in $(seq 1 3000); do
    : > "${WORK}/outer32/gentoo-cjk-kernel-7.1.7-1/image/f${i}"
done
cp "${WORK}/meta32.tar.zst" \
    "${WORK}/outer32/gentoo-cjk-kernel-7.1.7-1/metadata.tar.zst"
tar --mtime=@3 -C "${WORK}/outer32" -cf "${WORK}/built-cjk32.gpkg.tar" \
    gentoo-cjk-kernel-7.1.7-1

# The container command carries the package.use line, so the stub answers with
# the variant that was actually requested.
cat > "${WORK}/bin/docker" <<'STUB'
#!/bin/bash
mkdir -p "${TEST_PKGDIR}/sys-kernel/gentoo-cjk-kernel"
built="${TEST_BUILT}"
if [[ ${TEST_ANSWER_MODE} == honest && $* == *"'cjk cjk32'"* ]]; then
    built="${TEST_BUILT32}"
elif [[ ${TEST_ANSWER_MODE} == always-plain ]]; then
    built="${TEST_BUILT}"
elif [[ ${TEST_ANSWER_MODE} == always-cjk32 ]]; then
    built="${TEST_BUILT32}"
fi
cp "${built}" \
    "${TEST_PKGDIR}/sys-kernel/gentoo-cjk-kernel/gentoo-cjk-kernel-7.1.7-1.gpkg.tar"
STUB
chmod +x "${WORK}/bin/docker"

write_manifest_both() {
    write_manifest "${NAME}" "${WORK}/built-first.gpkg.tar"
    local size sha512 blake2b
    size=$(stat -c %s "${WORK}/built-cjk32.gpkg.tar")
    sha512=$(sha512sum "${WORK}/built-cjk32.gpkg.tar" | awk '{print $1}')
    blake2b=$(b2sum "${WORK}/built-cjk32.gpkg.tar" | awk '{print $1}')
    printf 'DIST %s %s BLAKE2B %s SHA512 %s\n' \
        "${CJK32_NAME}" "${size}" "${blake2b}" "${sha512}" >> "${WORK}/Manifest"
}

run_variants() {
    TEST_BUILT32="${WORK}/built-cjk32.gpkg.tar" \
        TEST_ANSWER_MODE="$2" EXTRA_VARIANTS='.cjk32 cjk32' run_archive "$1"
}

reset_case
write_manifest_both
mkdir -p "${WORK}/remote/archive/7.1" "${WORK}/published/7.1"
cp "${WORK}/built-first.gpkg.tar" "${WORK}/remote/archive/7.1/${NAME}"
cp "${WORK}/built-cjk32.gpkg.tar" "${WORK}/remote/archive/7.1/${CJK32_NAME}"
cp "${WORK}/built-first.gpkg.tar" "${WORK}/published/7.1/${NAME}"
cp "${WORK}/built-cjk32.gpkg.tar" "${WORK}/published/7.1/${CJK32_NAME}"
run_variants 0 honest > "${WORK}/out" 2>&1
grep -q '已发布，跳过' "${WORK}/out"
echo "  ✓ Manifest 与远端一致时两个变体都跳过构建"

# A version the -bin ebuild does not name yet is being bootstrapped, and the
# extra variant has no entry for the same reason the plain one has none.
reset_case
: > "${WORK}/Manifest"
TEST_BUILT32="${WORK}/built-cjk32.gpkg.tar" TEST_ANSWER_MODE=honest \
    EXTRA_VARIANTS='.cjk32 cjk32' run_archive 2 > "${WORK}/out" 2>&1
[[ -e ${WORK}/remote/archive/7.1/${NAME} ]]
[[ -e ${WORK}/remote/archive/7.1/${CJK32_NAME} ]]
[[ $(grep -c "^DIST " "${WORK}/published/pending-manifest.txt") == 2 ]]
echo "  ✓ 版本尚未列入 -bin 时两个变体一起自举"

# A version the -bin ebuild does name, without this variant, leaves it out on
# purpose.
reset_case
write_manifest "${NAME}" "${WORK}/built-first.gpkg.tar"
mkdir -p "${WORK}/remote/archive/7.1"
cp "${WORK}/built-first.gpkg.tar" "${WORK}/remote/archive/7.1/${NAME}"
TEST_BUILT32="${WORK}/built-cjk32.gpkg.tar" TEST_ANSWER_MODE=honest \
    EXTRA_VARIANTS='.cjk32 cjk32' run_archive 2 > "${WORK}/out" 2>&1
grep -q '\-bin 未提供这个变体，跳过' "${WORK}/out"
[[ -e ${WORK}/remote/archive/7.1/${NAME} ]]
[[ ! -e ${WORK}/remote/archive/7.1/${CJK32_NAME} ]]
echo "  ✓ -bin 提供了这版却没这个变体时才跳过"
