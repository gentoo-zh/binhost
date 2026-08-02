#!/bin/bash

set -uo pipefail

REMOTE="${REMOTE:-mirror}"
SITE_ROOT="${SITE_ROOT:-/srv/mirrors}"
OUT="${OUT:-build-status.json}"
EVERY="${EVERY:-60}"

push() {
    # shellcheck disable=SC2029
    if ! ssh "${REMOTE}" "cat > ${SITE_ROOT}/.${OUT}.new &&
                          mv -f ${SITE_ROOT}/.${OUT}.new ${SITE_ROOT}/${OUT}"; then
        echo "!! 建置进度未能送到 ${REMOTE}" >&2
        return 1
    fi
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
    state="${2:-done}"
    case "${state}" in
        done|failed) ;;
        *) echo "用法: $0 finish [done|failed]" >&2; exit 1 ;;
    esac
    printf '{"state":"%s","generated":%s}\n' "${state}" "$(date +%s)" | push
    ;;
*)
    echo "用法: $0 watch <log> | $0 finish [done|failed]" >&2
    exit 1
    ;;
esac
