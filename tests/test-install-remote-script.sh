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

has() {
    if grep -qF -- "$2" "$3"; then
        printf '  ✓ %s\n' "$1"
        pass=$((pass + 1))
    else
        printf '  ✗ %s\n      远端脚本里找不到：%s\n' "$1" "$2"
        fail=$((fail + 1))
    fi
}

lacks() {
    if grep -qF -- "$2" "$3"; then
        printf '  ✗ %s\n      远端脚本里不该出现：%s\n' "$1" "$2"
        fail=$((fail + 1))
    else
        printf '  ✓ %s\n' "$1"
        pass=$((pass + 1))
    fi
}

tmp=$(mktemp -d)
trap 'rm -rf "${tmp}"' EXIT

render() {
    local script="$1" out="$2"
    # shellcheck disable=SC2016  # the sed patterns match ${VAR} literally
    sed -e "s|^cd \"\$(dirname \"\$0\")/..\"|cd ${ROOT}|" \
        -e 's|^tmp=$(ssh "${REMOTE}" .mktemp -d.)|tmp=/tmp/fake|' \
        -e 's|^rsync -a |: rsync -a |' \
        -e 's|^ssh "${REMOTE}" "set -euo pipefail|printf "%s" "set -euo pipefail|' \
        "${ROOT}/${script}" > "${tmp}/render.sh"
    ( bash "${tmp}/render.sh" > "${out}" 2>/dev/null ) || true
}

echo "== install.sh 送到远端的脚本"

render deploy/install.sh "${tmp}/remote.sh"
n=$(wc -l < "${tmp}/remote.sh")
ok "渲染得出内容" "$(( n > 50 ))" "1"

if bash -n "${tmp}/remote.sh" 2>"${tmp}/err"; then
    echo "  ✓ 远端脚本语法正确"
    pass=$((pass + 1))
else
    printf '  ✗ 远端脚本语法错误\n%s\n' "$(sed 's/^/      /' "${tmp}/err")"
    fail=$((fail + 1))
fi

# shellcheck disable=SC2016  # we grep for a literal ${VAR}, not its value
lacks "没有留下未展开的本地变量" '${REMOTE_ROOT}' "${tmp}/remote.sh"
# shellcheck disable=SC2016  # we grep for a literal ${VAR}, not its value
lacks "没有留下未展开的 SSH_PORT" '__SSH_PORT__/${SSH_PORT}' "${tmp}/remote.sh"
has "端口已代换成实际值" "s/__SSH_PORT__/60001/g" "${tmp}/remote.sh"

echo
echo "== 防火墙的自动回滚"

has "先备份现有规则" "nft list ruleset > /run/binhost-firewall-rollback.rules" "${tmp}/remote.sh"
has "回滚定时器已武装" "sleep 300" "${tmp}/remote.sh"
has "本轮确认过就不回滚" '/run/binhost-firewall-confirmed 2>/dev/null)" = "' "${tmp}/remote.sh"
has "回滚会还原备份" "nft -f /run/binhost-firewall-rollback.rules" "${tmp}/remote.sh"
has "回滚脚本与会话脱钩" "setsid" "${tmp}/remote.sh"
has "日志里的中文没有被反斜线破坏" 'logger -t binhost "防火墙在 300 秒内未确认' "${tmp}/remote.sh"
lacks "远端脚本里不保存规则，留给确认之后" "rc-service nftables save" "${tmp}/remote.sh"

grep -n 'nft -f /etc/nftables.conf' "${tmp}/remote.sh" > "${tmp}/apply" || true
grep -n 'setsid' "${tmp}/remote.sh" > "${tmp}/arm" || true
armed=$(cut -d: -f1 < "${tmp}/arm" | head -1)
applied=$(cut -d: -f1 < "${tmp}/apply" | head -1)
ok "先武装回滚再套用规则" "$(( armed < applied ))" "1"

echo
echo "== 回滚定时器的世代判定"

# the timer body, lifted out and run without the sleep
timer() {
    local mygen="$1" genfile="$2" confirm="$3" out="$4"
    sh -c "
        [ \"\$(cat ${genfile} 2>/dev/null)\" = \"${mygen}\" ] || exit 0
        [ \"\$(cat ${confirm} 2>/dev/null)\" = \"${mygen}\" ] && exit 0
        echo rolled-back > ${out}"
    if [ -s "${out}" ]; then echo rolled-back; else echo left-alone; fi
}

td=$(mktemp -d)
: > "${td}/out"; echo A > "${td}/gen"; rm -f "${td}/confirm"
ok "本轮且未确认时回滚" "$(timer A "${td}/gen" "${td}/confirm" "${td}/out")" "rolled-back"

: > "${td}/out"; echo A > "${td}/gen"; echo A > "${td}/confirm"
ok "本轮且已确认时不动" "$(timer A "${td}/gen" "${td}/confirm" "${td}/out")" "left-alone"

: > "${td}/out"; echo B > "${td}/gen"; rm -f "${td}/confirm"
ok "已被新一轮取代时不动，哪怕没确认" \
   "$(timer A "${td}/gen" "${td}/confirm" "${td}/out")" "left-alone"

: > "${td}/out"; echo B > "${td}/gen"; echo A > "${td}/confirm"
ok "上一轮的确认档不会让新一轮误判" \
   "$(timer B "${td}/gen" "${td}/confirm" "${td}/out")" "rolled-back"
rm -rf "${td}"

has "武装时写下本轮世代" "sudo install -m644 /dev/stdin '/run/binhost-firewall-generation'" "${tmp}/remote.sh"
has "定时器先比对世代" '/run/binhost-firewall-generation 2>/dev/null)" = "' "${tmp}/remote.sh"

echo
echo "== 确认动作在本地执行，不在远端脚本里"
# shellcheck disable=SC2016  # we grep for a literal ${VAR}, not its value
has "本地会另开一条连线确认" "sudo install -m644 /dev/stdin '\${CONFIRM}'" "${ROOT}/deploy/install.sh"
has "确认之后才保存规则" "rc-service nftables save" "${ROOT}/deploy/install.sh"

echo
if (( fail )); then
    echo ">>> ${fail} 项未通过，${pass} 项通过"
    exit 1
fi
echo ">>> ${pass} 项全部通过"
