#!/bin/bash

set -uo pipefail

UNIT="${1:?需要单元名}"
ALERT_CONF="${ALERT_CONF:-/etc/binhost/alert.conf}"

[[ -r ${ALERT_CONF} ]] || exit 0
# shellcheck source=/dev/null
. "${ALERT_CONF}"
[[ -n ${TELEGRAM_TOKEN:-} && -n ${TELEGRAM_CHAT:-} ]] || exit 0

field() { systemctl show "${UNIT}" -p "$1" --value 2>/dev/null; }

result=$(field Result)
code=$(field ExecMainStatus)

if [[ ${FORCE:-0} != 1 && ${result} == success ]]; then
    echo "${UNIT} 的结果是 success，跳过告警" >&2
    exit 0
fi
for handled in ${HANDLED_EXITS:-10 11}; do
    if [[ ${FORCE:-0} != 1 && ${code} == "${handled}" ]]; then
        echo "${UNIT} 已自行发出告警（退出码 ${code}），跳过重复告警" >&2
        exit 0
    fi
done
started=$(field ExecMainStartTimestamp)
finished=$(field ExecMainExitTimestamp)

elapsed=""
if [[ -n ${started} && -n ${finished} ]]; then
    s=$(date -d "${started}" +%s 2>/dev/null) || s=""
    f=$(date -d "${finished}" +%s 2>/dev/null) || f=""
    if [[ -n ${s} && -n ${f} && $(( f - s )) -ge 60 ]]; then
        d=$(( f - s ))
        if (( d >= 3600 )); then
            elapsed=$(printf '，耗时 %d 小时 %d 分' $(( d / 3600 )) $(( d % 3600 / 60 )))
        else
            elapsed=$(printf '，耗时 %d 分' $(( d / 60 )))
        fi
    fi
fi

tail_lines=$(journalctl -u "${UNIT}" -n 40 --no-pager -o cat 2>/dev/null |
             grep -vE '^\s*$' |
             grep -vE '^(Starting|Started|Stopping|Stopped|Finished|Failed to start) ' |
             grep -vE '^[^ ]+\.service: ' |
             tail -4)

now=$(TZ=Asia/Shanghai date '+%m-%d %H:%M')

prefix=""
[[ ${FORCE:-0} == 1 && ${result} == success ]] && prefix="[测试] "

text="${prefix}${UNIT%.service} 失败
$(hostname) · ${now} UTC+8
结果 ${result:-未知}，退出码 ${code:-未知}${elapsed}"

if [[ -n ${tail_lines} ]]; then
    text+="

日志末尾：
${tail_lines}"
fi

if (( ${#text} > 3500 )); then
    text="${text:0:3500}
…（超过 3500 字，已截断，完整内容见 journalctl -u ${UNIT}）"
fi

if ! curl -fsS --max-time 20 -o /dev/null \
    --data-urlencode "chat_id=${TELEGRAM_CHAT}" \
    --data-urlencode "text=${text}" \
    --config - <<EOF
url = "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage"
EOF
then
    echo "!! 告警发送失败（${#text} 字）" >&2
fi
