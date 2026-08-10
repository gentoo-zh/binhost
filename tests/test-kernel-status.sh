#!/bin/bash

set -uo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
pass=0
fail=0

ok() {
    if [[ $2 == "$3" ]]; then
        printf '  ✓ %s\n' "$1"
        pass=$((pass + 1))
    else
        printf '  ✗ %s\n      得到 %s，应为 %s\n' "$1" "$2" "$3"
        fail=$((fail + 1))
    fi
}

setup() {
    local d
    d=$(mktemp -d)
    mkdir -p "${d}/bin" "${d}/overlay" "${d}/tree"
    : > "${d}/kernel-series.py"
    cat > "${d}/bin/python3" <<'EOF'
#!/bin/bash
case "${RESOLVER_MODE:-good}" in
    good) printf '6.18 6.18.43\n7.1 7.1.7\n' ;;
    invalid) printf 'not-a-version\n' ;;
    failed) echo 'metadata unavailable' >&2; exit 2 ;;
esac
EOF
    cat > "${d}/bin/curl" <<EOF
#!/bin/bash
url=""
for arg in "\$@"; do
    case "\${arg}" in http*) url="\${arg}" ;; esac
done
case "\${url}" in
    *gentoo-cjk-kernel*)
        printf '%s\n' "\${url}" >> "${d}/urls"
        case "\${url}" in
            *"\${MISSING_VERSION:-never}"*) printf 404 ;;
            *) printf 200 ;;
        esac
        ;;
    *) exit 22 ;;
esac
EOF
    cat > "${d}/bin/openssl" <<'EOF'
#!/bin/bash
exit 1
EOF
    cat > "${d}/bin/sudo" <<'EOF'
#!/bin/bash
exit 1
EOF
    chmod +x "${d}/bin"/*
    echo "${d}"
}

run() {
    local d=$1
    PATH="${d}/bin:${PATH}" COMPONENT=builder VERSION_FILE="${d}/missing-version" \
        SITE=https://mirror.invalid DISK_PATH="${d}/missing-disk" \
        SIGNING_GNUPGHOME="${d}/missing-keyring" HEARTBEAT="${d}/missing/.health" \
        SITE_WORK="${d}/missing-site" SITE_DEST="${d}/missing-dest" \
        MONITORS_FILE="${d}/missing-monitors" \
        KERNEL_OVERLAY="${d}/overlay" KERNEL_TREE="${d}/tree" \
        KERNEL_SERIES_TOOL="${d}/kernel-series.py" \
        RESOLVER_MODE="${RESOLVER_MODE:-good}" \
        MISSING_VERSION="${MISSING_VERSION:-never}" \
        bash "${ROOT}/ops/status.sh" 2>&1 || true
}

echo "== 公开归档与 overlay 版本一致"
d=$(setup)
out=$(run "${d}")
ok "两个版本都存在时通过" \
   "$([[ ${out} == *'2 个 overlay 版本均可下载'* ]] && echo yes)" "yes"
ok "按精确版本检查两条 URL" "$(wc -l < "${d}/urls")" "2"
ok "URL 包含 6.18 的归档名" \
   "$(grep -c '/6.18/gentoo-cjk-kernel-6.18.43-1.amd64.gpkg.tar$' "${d}/urls")" "1"
ok "URL 包含 7.1 的归档名" \
   "$(grep -c '/7.1/gentoo-cjk-kernel-7.1.7-1.amd64.gpkg.tar$' "${d}/urls")" "1"
rm -rf "${d}"

echo
echo "== 新版本尚未发布时告警"
d=$(setup)
MISSING_VERSION=7.1.7 out=$(run "${d}")
ok "指出缺少的精确版本" \
   "$([[ ${out} == *'缺少 overlay 版本：7.1/7.1.7 HTTP 404'* ]] && echo yes)" "yes"
rm -rf "${d}"

echo
echo "== 无法解析 overlay 时不当成没有更新"
d=$(setup)
RESOLVER_MODE=failed out=$(run "${d}")
ok "解析失败会成为故障" \
   "$([[ ${out} == *'无法取得 overlay 版本：metadata unavailable'* ]] && echo yes)" "yes"
rm -rf "${d}"

echo
if (( fail )); then
    echo ">>> ${fail} 项未通过，${pass} 项通过"
    exit 1
fi
echo ">>> ${pass} 项全部通过"
