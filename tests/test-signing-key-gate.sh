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

says() {
    if grep -qF -- "$2" <<< "$3"; then
        printf '  ✓ %s\n' "$1"
        pass=$((pass + 1))
    else
        printf '  ✗ %s\n      输出里找不到：%s\n      输出：%s\n' "$1" "$2" "$3"
        fail=$((fail + 1))
    fi
}

echo "== install-builder.sh"
# A local path is what an operator reaches for when the variable is named "key".
out=$(REMOTE="ssh nowhere" SIGNING_KEY=/home/u/.config/key.asc \
      bash "${ROOT}/deploy/install-builder.sh" 2>&1)
ok "路径被拒" "$?" 1
says "说明收到了什么" "收到：/home/u/.config/key.asc" "${out}"

# gpg accepts a 16-hex long id interactively, so it looks valid but is not what
# the status check compares against.
out=$(REMOTE="ssh nowhere" SIGNING_KEY=38A0234EC16AD42E \
      bash "${ROOT}/deploy/install-builder.sh" 2>&1)
ok "短 key id 被拒" "$?" 1

out=$(REMOTE="ssh nowhere" SIGNING_KEY=nothexnothexnothexnothexnothexnothexnoth \
      bash "${ROOT}/deploy/install-builder.sh" 2>&1)
ok "40 位非十六进制被拒" "$?" 1

echo "== 部署时验证私钥存在"
# Format alone cannot catch a typo in a real fingerprint; the deploy must ask
# gnupg whether the key is there before it replaces anything.
script=$(grep -A6 "^echo '--- 签名密钥'" "${ROOT}/deploy/install-builder.sh")
says "问 gnupg 要私钥" "--list-secret-keys" "${script}"
says "找不到就中止" "exit 1" "${script}"

# The key check has to run before rsync --delete replaces the deployed scripts:
# a failing check after replacement leaves new scripts with old units.
key_line=$(grep -n "^echo '--- 签名密钥'" "${ROOT}/deploy/install-builder.sh" | cut -d: -f1)
script_line=$(grep -n "^echo '--- 构建脚本'" "${ROOT}/deploy/install-builder.sh" | cut -d: -f1)
ok "私钥检查在替换脚本之前" "$((key_line < script_line))" 1

echo
if (( fail )); then
    echo ">>> ${pass} 过，${fail} 不过"
    exit 1
fi
echo ">>> ${pass} 项全过"
