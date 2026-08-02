#!/bin/bash
# 把这一轮的进度推给镜像机，页面据此显示「正在建置」。
#
#   build-progress.sh watch <log>    直到日志所属的那一轮结束
#   build-progress.sh finish         标成完成
#

set -uo pipefail

REMOTE="${REMOTE:-mirror}"
SITE_ROOT="${SITE_ROOT:-/srv/mirrors}"
OUT="${OUT:-build-status.json}"
EVERY="${EVERY:-60}"

push() {
    # shellcheck disable=SC2029  # SITE_ROOT 与 OUT 要在本地展开
    ssh "${REMOTE}" "cat > ${SITE_ROOT}/.${OUT}.new &&
                     mv -f ${SITE_ROOT}/.${OUT}.new ${SITE_ROOT}/${OUT}" || true
}

snapshot() {
    local log="$1" line now kind done_ total plan
    [[ -e ${log} ]] || { printf '{"state":"running","done":0,"total":0,"plan":0,"now":"","kind":"prepare","generated":%s}\n' "$(date +%s)"; return; }
    line=$(grep -E '^>>> Emerging' "${log}" 2>/dev/null | tail -1)
    now=$(sed -E 's/.*\) ([^:]+).*/\1/' <<< "${line}")
    kind=source
    [[ ${line} == *"Emerging binary"* ]] && kind=binary
    done_=$(grep -c '^>>> Installing' "${log}" 2>/dev/null)
    total=$(grep -oE '\([0-9]+ of ([0-9]+)\)' "${log}" 2>/dev/null | tail -1 |
            sed -E 's/.* of ([0-9]+)\)/\1/')
    plan=$(grep -cE '^\[ebuild' "${log}" 2>/dev/null)
    printf '{"state":"running","done":%s,"total":%s,"plan":%s,"now":"%s","kind":"%s","generated":%s}\n' \
        "${done_:-0}" "${total:-0}" "${plan:-0}" "${now:-}" "${kind}" "$(date +%s)"
}

case "${1:-}" in
watch)
    log="${2:?需要日志路径}"
    while :; do
        snapshot "${log}" | push
        sleep "${EVERY}"
    done
    ;;
finish)
    printf '{"state":"done","generated":%s}\n' "$(date +%s)" | push
    ;;
*)
    echo "用法: $0 watch <log> | $0 finish" >&2
    exit 1
    ;;
esac
