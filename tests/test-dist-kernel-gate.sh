#!/bin/bash

set -uo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
pass=0
fail=0

ok() {
    if [[ $2 == "$3" ]]; then
        printf '  ✓ %s\n' "$1"; pass=$((pass + 1))
    else
        printf '  ✗ %s\n      得到 %s，应为 %s\n' "$1" "$2" "$3"; fail=$((fail + 1))
    fi
}

# The gate as it appears in build-container.sh, with the resolver stubbed. A
# resolver that fails is routine -- one slot conflict is enough -- so its exit
# status must not decide whether the output gets matched.
gate() {
    local rc="$1" out="$2" d
    d=$(mktemp -d)
    cat > "${d}/emerge" <<STUB
#!/bin/bash
printf '%s\n' "${out}"
exit ${rc}
STUB
    chmod +x "${d}/emerge"
    (
        set -euo pipefail
        cd "${d}"
        EMERGE=("${d}/emerge")
        "${EMERGE[@]}" --pretend --quiet foo > "${d}/pretend.txt" 2>/dev/null ||
            echo "    解析未完成，仍按已有输出检查"
        if grep -E '^\[[^]]*\] +virtual/dist-kernel' "${d}/pretend.txt" \
                > "${d}/pull.txt"; then
            echo BLOCKED
            exit 1
        fi
        echo PASSED
    ) > "${d}/result" 2>&1
    grep -qx BLOCKED "${d}/result" && echo blocked || echo passed
    rm -rf "${d}"
}

echo "== 分发内核闸门"
ok "解析成功且命中，拦下"     "$(gate 0 '[binary  N  ] virtual/dist-kernel-6.12')" blocked
ok "解析失败但命中，仍拦下"   "$(gate 1 '[binary  N  ] virtual/dist-kernel-6.12')" blocked
ok "解析成功未命中，放行"     "$(gate 0 '[binary  N  ] app-misc/foo-1')"           passed
ok "解析失败也未命中，放行"   "$(gate 1 '[binary  N  ] app-misc/foo-1')"           passed

echo "== 部署顺序"
# The key check has to run before rsync --delete replaces the deployed scripts:
# a failing check after replacement leaves new scripts with old units.
key_line=$(grep -n "^echo '--- 签名密钥'" "${ROOT}/deploy/install-builder.sh" | cut -d: -f1)
script_line=$(grep -n "^echo '--- 构建脚本'" "${ROOT}/deploy/install-builder.sh" | cut -d: -f1)
ok "私钥检查在替换脚本之前" "$((key_line < script_line))" 1

echo
if (( fail )); then
    echo ">>> ${pass} 过，${fail} 不过"; exit 1
fi
echo ">>> ${pass} 项全过"
