#!/bin/bash
# Cases for alert.sh.
#
# The one that matters: under set -euo pipefail an alert.conf missing a variable
# used to take the caller down at the exact moment it had something to report.
# Two of the four call sites had that bug and two did not, which is what a
# copied function does over time.

set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "${tmp}"' EXIT

# Stand in for curl so nothing leaves the machine and the call can be inspected.
mkdir -p "${tmp}/bin"
cat > "${tmp}/bin/curl" <<'EOF'
#!/bin/bash
printf '%s\n' "$@" >> "${CURL_LOG}"
EOF
chmod +x "${tmp}/bin/curl"
export PATH="${tmp}/bin:${PATH}"

pass=0 fail=0
check() {
    local name=$1 want=$2 got=$3
    if [[ ${want} == "${got}" ]]; then
        echo "  ✓ ${name}"; pass=$((pass + 1))
    else
        echo "  ✗ ${name}: 期望 ${want}，实际 ${got}"; fail=$((fail + 1))
    fi
}

# Each case runs in its own bash -euo pipefail, which is how the callers run.
# A subshell would not reproduce it: set -u aborts the shell, and the point is
# whether the caller survives.
caller() {
    local conf=$1
    CURL_LOG="${tmp}/curl.log" ALERT_CONF="${conf}" \
    bash -euo pipefail -c '
        . "'"${HERE}"'/alert.sh"
        alert "test message"
        echo REACHED_END
    ' 2>"${tmp}/err.txt"
}

: > "${tmp}/curl.log"

out=$(caller "${tmp}/nonexistent.conf"); rc=$?
check "没有 alert.conf 时不影响调用者" "0 REACHED_END" "${rc} ${out}"

printf 'TELEGRAM_CHAT=123\n' > "${tmp}/no-token.conf"
out=$(caller "${tmp}/no-token.conf"); rc=$?
check "conf 缺 TELEGRAM_TOKEN 时调用者不受影响" "0 REACHED_END" "${rc} ${out}"
if grep -q "缺 TELEGRAM_TOKEN" "${tmp}/err.txt"; then
    echo "  ✓ 缺变量时有提示"; pass=$((pass + 1))
else
    echo "  ✗ 缺变量时无提示"; fail=$((fail + 1))
fi

printf 'TELEGRAM_TOKEN=t\n' > "${tmp}/no-chat.conf"
out=$(caller "${tmp}/no-chat.conf"); rc=$?
check "conf 缺 TELEGRAM_CHAT 时调用者不受影响" "0 REACHED_END" "${rc} ${out}"

: > "${tmp}/curl.log"
printf 'TELEGRAM_TOKEN=tok\nTELEGRAM_CHAT=42\n' > "${tmp}/full.conf"
out=$(caller "${tmp}/full.conf"); rc=$?
check "凭据完整时调用者继续执行" "0 REACHED_END" "${rc} ${out}"
if grep -q "bot tok/sendMessage\|bottok/sendMessage" "${tmp}/curl.log"; then
    echo "  ✓ 使用 conf 中的 token"; pass=$((pass + 1))
else
    echo "  ✗ token 未传给 curl"; fail=$((fail + 1))
fi
if grep -q "chat_id=42" "${tmp}/curl.log"; then
    echo "  ✓ 使用 conf 中的 chat"; pass=$((pass + 1))
else
    echo "  ✗ chat 未传给 curl"; fail=$((fail + 1))
fi
if grep -q "text=test message" "${tmp}/curl.log"; then
    echo "  ✓ 正文原样传出"; pass=$((pass + 1))
else
    echo "  ✗ 正文未传出"; fail=$((fail + 1))
fi

# Credentials must not survive the call: a later `set -x` or an env dump in the
# caller would otherwise print the token.
out=$(CURL_LOG="${tmp}/curl.log" ALERT_CONF="${tmp}/full.conf" \
      bash -euo pipefail -c '
        . "'"${HERE}"'/alert.sh"
        alert "x"
        echo "${TELEGRAM_TOKEN:-unset}"
      ' 2>/dev/null)
check "调用后凭据不残留在环境中" "unset" "${out}"

chmod 000 "${tmp}/full.conf"
if [[ $(id -u) -eq 0 ]]; then
    echo "  - 跳过 conf 不可读一项：root 不受权限位限制"
else
    out=$(caller "${tmp}/full.conf"); rc=$?
    check "conf 不可读时调用者不受影响" "0 REACHED_END" "${rc} ${out}"
    if grep -q "读不到" "${tmp}/err.txt"; then
        echo "  ✓ 不可读时有提示"; pass=$((pass + 1))
    else
        echo "  ✗ 不可读时无提示"; fail=$((fail + 1))
    fi
fi
chmod 644 "${tmp}/full.conf"

echo "  通过 ${pass}，未通过 ${fail}"
exit $(( fail > 0 ))
