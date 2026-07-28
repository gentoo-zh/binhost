#!/bin/bash
# Post to Telegram when a systemd unit fails. Called by binhost-alert@.service.
#
# When systemd kills a unit (timeout, OOM) the script's own trap never runs and
# this is the only layer left that can say anything. So assume nothing about
# what the failed script left behind: take everything from systemd and the log.
#
#   usage: alert-failed.sh <unit>

set -uo pipefail

UNIT="${1:?需要单元名}"
ALERT_CONF="${ALERT_CONF:-/etc/binhost/alert.conf}"

[[ -r ${ALERT_CONF} ]] || exit 0
# shellcheck source=/dev/null
. "${ALERT_CONF}"
# Exit quietly when the file is there but incomplete (half-written, emptied).
# Under set -u an unset variable would take down the alerting script itself,
# and then nobody hears anything at all.
[[ -n ${TELEGRAM_TOKEN:-} && -n ${TELEGRAM_CHAT:-} ]] || exit 0

field() { systemctl show "${UNIT}" -p "$1" --value 2>/dev/null; }

result=$(field Result)
code=$(field ExecMainStatus)

# Only send on a real failure. Running this by hand against a unit that is
# still going, or that succeeded, must not produce a message saying it failed.
# FORCE=1 is for testing the alert path itself.
if [[ ${FORCE:-0} != 1 && ${result} == success ]]; then
    echo "${UNIT} 的结果是 success，不发告警" >&2
    exit 0
fi
started=$(field ExecMainStartTimestamp)
finished=$(field ExecMainExitTimestamp)

# How long it ran. Skip the line if either timestamp is missing rather than
# show a made-up zero.
elapsed=""
if [[ -n ${started} && -n ${finished} ]]; then
    s=$(date -d "${started}" +%s 2>/dev/null) || s=""
    f=$(date -d "${finished}" +%s 2>/dev/null) || f=""
    # Only worth saying past a minute; a zero-length duration takes more room
    # than leaving it out.
    if [[ -n ${s} && -n ${f} && $(( f - s )) -ge 60 ]]; then
        d=$(( f - s ))
        if (( d >= 3600 )); then
            elapsed=$(printf '，跑了 %d 小时 %d 分' $(( d / 3600 )) $(( d % 3600 / 60 )))
        else
            elapsed=$(printf '，跑了 %d 分' $(( d / 60 )))
        fi
    fi
fi

# The last few log lines are the only clue about where it stopped. Leave them
# out if they cannot be read rather than lose the alert over it.
#
# systemd's own lines -- Starting, Failed to start, Triggering OnFailure -- all
# say that it failed, which the first line of the alert already said. What is
# left after filtering them is the failed command's own output.
tail_lines=$(journalctl -u "${UNIT}" -n 40 --no-pager -o cat 2>/dev/null |
             grep -vE '^\s*$' |
             grep -vE '^(Starting|Started|Stopping|Stopped|Finished|Failed to start) ' |
             grep -vE '^[^ ]+\.service: ' |
             tail -4)

# UTC+8: whoever reads these is in mainland China, Taiwan, Singapore or
# Malaysia.
now=$(TZ=Asia/Shanghai date '+%m-%d %H:%M')

# Mark a FORCE run so nobody reads a channel test as a real failure.
prefix=""
[[ ${FORCE:-0} == 1 && ${result} == success ]] && prefix="[测试] "

# Drop the .service suffix: the task is what matters, the suffix says nothing.
text="${prefix}${UNIT%.service} 失败
$(hostname) · ${now} UTC+8
结果 ${result:-未知}，退出码 ${code:-未知}${elapsed}"

if [[ -n ${tail_lines} ]]; then
    text+="

最后几行：
${tail_lines}"
fi

curl -fsS --max-time 20 -o /dev/null \
    "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT}" \
    --data-urlencode "text=${text}" || true
