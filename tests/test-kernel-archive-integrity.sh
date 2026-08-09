#!/bin/bash

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "${WORK}"' EXIT

mkdir -p "${WORK}/bin" "${WORK}/overlay" "${WORK}/tree" \
    "${WORK}/pkgdir/sys-kernel/gentoo-cjk-kernel" "${WORK}/metadata/metadata"
REAL_PYTHON=$(command -v python3)
NAME=gentoo-cjk-kernel-7.1.7-1.amd64.gpkg.tar
printf 'cjk\n' > "${WORK}/metadata/metadata/USE"
tar -C "${WORK}/metadata" -cf - metadata | zstd -q -o "${WORK}/metadata.tar.zst"
mkdir -p "${WORK}/outer/gentoo-cjk-kernel-7.1.7-1"
cp "${WORK}/metadata.tar.zst" \
    "${WORK}/outer/gentoo-cjk-kernel-7.1.7-1/metadata.tar.zst"
tar -C "${WORK}/outer" -cf "${WORK}/built.gpkg.tar" \
    gentoo-cjk-kernel-7.1.7-1

SIZE=$(stat -c %s "${WORK}/built.gpkg.tar")
SHA512=$(sha512sum "${WORK}/built.gpkg.tar" | awk '{print $1}')
printf 'DIST %s %s SHA512 %s\n' "${NAME}" "${SIZE}" "${SHA512}" \
    > "${WORK}/Manifest"

cat > "${WORK}/bin/python3" <<EOF
#!/bin/bash
if [[ \$1 == */kernel-series.py ]]; then
    echo '7.1 7.1.7'
else
    exec '${REAL_PYTHON}' "\$@"
fi
EOF

cat > "${WORK}/bin/ssh" <<'EOF'
#!/bin/bash
command=$2
case "${command}" in
    bash)
        case "${REMOTE_MODE}" in
            good) printf '%s\n%s  archive\n' "${EXPECTED_SIZE}" "${EXPECTED_SHA512}" ;;
            corrupt) printf '1\n%s  archive\n' "${EXPECTED_SHA512}" ;;
            missing) exit 1 ;;
        esac
        ;;
    *'ls -1 */*.gpkg.tar'*) printf '7.1/%s\n' "${EXPECTED_NAME}" ;;
    *'ls -1 '*) echo 7.1 ;;
    *'install -dm755'*) exit 0 ;;
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
: > "${RSYNC_MARKER}"
EOF
chmod +x "${WORK}/bin"/*

run_archive() {
    PATH="${WORK}/bin:${PATH}" OVERLAY="${WORK}/overlay" TREE="${WORK}/tree" \
        PKGDIR="${WORK}/pkgdir" MANIFEST="${WORK}/Manifest" \
        LOCK="${WORK}/lock" REMOTE=test REMOTE_ROOT=/archive \
        DOCKER=docker MAX_BUILDS="$1" REMOTE_MODE="$2" \
        EXPECTED_SIZE="${SIZE}" EXPECTED_SHA512="${SHA512}" \
        EXPECTED_NAME="${NAME}" TEST_PKGDIR="${WORK}/pkgdir" \
        TEST_BUILT="${WORK}/built.gpkg.tar" RSYNC_MARKER="${WORK}/rsync-called" \
        bash "${ROOT}/build/kernel-archive.sh"
}

good=$(run_archive 0 good)
grep -q '已发布，跳过' <<< "${good}"
echo "  ✓ 完整的远端文件按已发布处理"

corrupt=$(run_archive 0 corrupt)
grep -q '要建置' <<< "${corrupt}"
echo "  ✓ 同名但损坏的远端文件不按已发布处理"

printf 'DIST %s %s SHA512 %0128d\n' "${NAME}" "${SIZE}" 0 > "${WORK}/Manifest"
rm -f "${WORK}/rsync-called"
if run_archive 1 missing >/dev/null 2>&1; then
    echo "  ✗ 新产物与 Manifest 不符时应当失败"
    exit 1
fi
[[ ! -e ${WORK}/rsync-called ]]
echo "  ✓ 新产物与 Manifest 不符时不上传"
