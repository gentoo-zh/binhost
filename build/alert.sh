# shellcheck shell=bash

alert() {
    local conf="${ALERT_CONF:-/etc/binhost/alert.conf}"

    if [[ -e ${conf} && ! -r ${conf} ]]; then
        echo "!! ${conf} 无法读取（当前用户 $(id -un)），告警传送失败" >&2
        return 0
    fi
    [[ -r ${conf} ]] || return 0

    local token chat
    # shellcheck source=/dev/null
    token=$(. "${conf}" 2>/dev/null; printf '%s' "${TELEGRAM_TOKEN:-}")
    # shellcheck source=/dev/null
    chat=$(. "${conf}" 2>/dev/null; printf '%s' "${TELEGRAM_CHAT:-}")

    if [[ -z ${token} || -z ${chat} ]]; then
        echo "!! ${conf} 缺 TELEGRAM_TOKEN 或 TELEGRAM_CHAT，告警传送失败" >&2
        return 0
    fi

    local text=$1
    if (( ${#text} > 3500 )); then
        text="${text:0:3500}
…（超过 3500 字，已截断，完整内容见构建日志）"
    fi

    if ! curl -fsS --max-time 20 -o /dev/null \
        "https://api.telegram.org/bot${token}/sendMessage" \
        --data-urlencode "chat_id=${chat}" \
        --data-urlencode "text=${text}"
    then
        echo "!! 告警发送失败（${#text} 字）" >&2
    fi
}
