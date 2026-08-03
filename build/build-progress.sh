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

emit() {
    printf '{"state":"running","phase":"%s","done":%s,"total":%s,"plan":%s,' \
        "$1" "$2" "$3" "$4"
    printf '"now":"%s","kind":"%s","progress_at":%s,"generated":%s}\n' \
        "$5" "$6" "$7" "$(date +%s)"
}

snapshot() {
    local log="$1" line now kind done_ total plan progress at
    progress="$(dirname "${log}")/progress"
    if [[ -s ${progress} ]]; then
        read -r done_ total now < "${progress}"
        at=$(stat -c %Y "${progress}" 2>/dev/null || date +%s)
        emit per-package "${done_:-0}" "${total:-0}" 0 "${now:-}" source "${at}"
        return
    fi
    if [[ ! -e ${log} ]]; then
        emit prepare 0 0 0 "" prepare "$(date +%s)"
        return
    fi
    at=$(stat -c %Y "${log}" 2>/dev/null || date +%s)
    line=$(grep -E '^>>> Emerging' "${log}" 2>/dev/null | tail -1)
    now=$(sed -E 's/.*\) ([^:]+).*/\1/' <<< "${line}")
    kind=source
    [[ ${line} == *"Emerging binary"* ]] && kind=binary
    done_=$(grep -c '^>>> Installing' "${log}" 2>/dev/null)
    total=$(grep -oE '\([0-9]+ of ([0-9]+)\)' "${log}" 2>/dev/null | tail -1 |
            sed -E 's/.* of ([0-9]+)\)/\1/')
    plan=$(grep -cE '^\[ebuild' "${log}" 2>/dev/null)
    emit whole "${done_:-0}" "${total:-0}" "${plan:-0}" "${now:-}" "${kind}" "${at}"
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
        *) echo "用法： $0 finish [done|failed]" >&2; exit 1 ;;
    esac
    printf '{"state":"%s","phase":"%s","progress_at":%s,"generated":%s}\n' \
        "${state}" "${state}" "$(date +%s)" "$(date +%s)" | push
    ;;
*)
    echo "用法： $0 watch <log> | $0 finish [done|failed]" >&2
    exit 1
    ;;
esac
