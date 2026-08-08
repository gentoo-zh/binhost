#!/bin/bash

set -uo pipefail

HERE="$(cd "$(dirname "$0")/../ops" && pwd)"
tmp=$(mktemp -d)
trap 'rm -rf "${tmp}"' EXIT

mkdir -p "${tmp}/bin"
cat > "${tmp}/bin/curl" <<'EOF'
#!/bin/bash
printf '%s\n' "$@" >> "${CURL_LOG}"
printf '%s\n' "$@" >> "${CURL_LOG}.argv"
for a in "$@"; do
    [ "$a" = "--config" ] && { cat >> "${CURL_LOG}"; break; }
done
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

: > "${tmp}/curl.log"
long=$(printf 'x%.0s' $(seq 1 6000))
out=$(CURL_LOG="${tmp}/curl.log" ALERT_CONF="${tmp}/full.conf" \
      bash -euo pipefail -c '
        . "'"${HERE}"'/alert.sh"
        alert "'"${long}"'"
        echo REACHED_END
      ' 2>/dev/null); rc=$?
check "超长消息不影响调用者" "0 REACHED_END" "${rc} ${out}"
sent=$(grep -c "^text=" "${tmp}/curl.log" || true)
if [[ ${sent} -ge 1 ]]; then
    echo "  ✓ 超长消息仍然发出去了"; pass=$((pass + 1))
else
    echo "  ✗ 超长消息一条都没发"; fail=$((fail + 1))
fi
len=$(awk '/^text=/{print length($0); exit}' "${tmp}/curl.log")
if [[ -n ${len} && ${len} -le 3700 ]]; then
    echo "  ✓ 发出去的是截断过的（${len} 字）"; pass=$((pass + 1))
else
    echo "  ✗ 没有截断（${len:-?} 字）"; fail=$((fail + 1))
fi

out=$(CURL_LOG="${tmp}/curl.log" ALERT_CONF="${tmp}/full.conf" \
      bash -euo pipefail -c '
        . "'"${HERE}"'/alert.sh"
        alert "x"
        echo "${TELEGRAM_TOKEN:-unset}"
      ' 2>/dev/null)
check "调用后凭据不残留在环境中" "unset" "${out}"

chmod 000 "${tmp}/full.conf"
if [[ $(id -u) -eq 0 ]]; then
    echo "  - 跳过 conf 无法读取一项：root 不受权限位限制"
else
    out=$(caller "${tmp}/full.conf"); rc=$?
    check "conf 无法读取时调用者不受影响" "0 REACHED_END" "${rc} ${out}"
    if grep -q "无法读取" "${tmp}/err.txt"; then
        echo "  ✓ 无法读取时有提示"; pass=$((pass + 1))
    else
        echo "  ✗ 无法读取时无提示"; fail=$((fail + 1))
    fi
fi
chmod 644 "${tmp}/full.conf"

SECRET=SeCrEtToKeN0123456789
: > "${tmp}/tok.log"; : > "${tmp}/tok.log.argv"
printf 'TELEGRAM_TOKEN=%s\nTELEGRAM_CHAT=c\n' "${SECRET}" > "${tmp}/tok.conf"
CURL_LOG="${tmp}/tok.log" ALERT_CONF="${tmp}/tok.conf" bash -c '
    . "'"${HERE}"'/alert.sh"
    alert "hello"' >/dev/null 2>&1
if grep -q "${SECRET}" "${tmp}/tok.log" 2>/dev/null; then
    echo "  ✓ 令牌确实传给了 curl"; pass=$((pass + 1))
else
    echo "  ✗ 令牌没有传给 curl，这个用例本身失效了"; fail=$((fail + 1))
fi
if grep -q "${SECRET}" "${tmp}/tok.log.argv" 2>/dev/null; then
    echo "  ✗ 令牌出现在 curl 的命令行参数里，ps 可见"; fail=$((fail + 1))
else
    echo "  ✓ 令牌不在 curl 的命令行参数里"; pass=$((pass + 1))
fi

echo "  通过 ${pass}，未通过 ${fail}"
exit $(( fail > 0 ))
