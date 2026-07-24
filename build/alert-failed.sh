#!/bin/bash
# systemd 单元失败时推一条到 Telegram。由 binhost-alert@.service 调用。
#
# 单元被 systemd 杀掉时（超时、OOM），脚本自己的 trap 跑不到，只有这一层还能
# 说话。所以这里不假设失败的那个脚本留下了什么，全部信息从 systemd 和日志取。
#
#   用法: alert-failed.sh <单元名>

set -uo pipefail

UNIT="${1:?需要单元名}"
ALERT_CONF="${ALERT_CONF:-/etc/binhost/alert.conf}"

[[ -r ${ALERT_CONF} ]] || exit 0
# shellcheck source=/dev/null
. "${ALERT_CONF}"
# 文件在但内容不全（写坏了、被清空了）也要安静退出。set -u 之下直接引用
# 未定义的变量会让告警脚本自己崩掉，那就彻底没人知道了。
[[ -n ${TELEGRAM_TOKEN:-} && -n ${TELEGRAM_CHAT:-} ]] || exit 0

field() { systemctl show "${UNIT}" -p "$1" --value 2>/dev/null; }

result=$(field Result)
code=$(field ExecMainStatus)

# 只有真失败了才发。手工对着正在跑或者跑成功的单元执行这个脚本，不该推出
# 一条说它失败的消息。FORCE=1 留给验证告警通道本身用。
if [[ ${FORCE:-0} != 1 && ${result} == success ]]; then
    echo "${UNIT} 的结果是 success，不发告警" >&2
    exit 0
fi
started=$(field ExecMainStartTimestamp)
finished=$(field ExecMainExitTimestamp)

# 跑了多久。两个时间戳里任意一个取不到就不写这一行，别显示一个假的 0 秒。
elapsed=""
if [[ -n ${started} && -n ${finished} ]]; then
    s=$(date -d "${started}" +%s 2>/dev/null) || s=""
    f=$(date -d "${finished}" +%s 2>/dev/null) || f=""
    # 只在跑够一分钟时才写。「跑了 0 小时 0 分」比不写还占地方。
    if [[ -n ${s} && -n ${f} && $(( f - s )) -ge 60 ]]; then
        d=$(( f - s ))
        if (( d >= 3600 )); then
            elapsed=$(printf '，跑了 %d 小时 %d 分' $(( d / 3600 )) $(( d % 3600 / 60 )))
        else
            elapsed=$(printf '，跑了 %d 分' $(( d / 60 )))
        fi
    fi
fi

# 日志的最后几行是唯一能看出在哪里中断的线索。取不到就留空，
# 不要因为日志读取失败而连告警都发不出去。
# systemd 自己那几行（Starting/Failed to start/Triggering OnFailure）说的都是
# 「它失败了」，而告警的第一行已经写了。滤掉之后剩下的才是失败的那个命令
# 自己的输出。
tail_lines=$(journalctl -u "${UNIT}" -n 40 --no-pager -o cat 2>/dev/null |
             grep -vE '^\s*$' |
             grep -vE '^(Starting|Started|Stopping|Stopped|Finished|Failed to start) ' |
             grep -vE '^[^ ]+\.service: ' |
             tail -4)

# UTC+8：看告警的人在中国大陆、台湾、新加坡、马来西亚。
now=$(TZ=Asia/Shanghai date '+%m-%d %H:%M')

# FORCE 是验证通道用的，标出来，免得看的人以为真出事了。
prefix=""
[[ ${FORCE:-0} == 1 && ${result} == success ]] && prefix="[测试] "

# 单元名去掉 .service：需要看的是哪个任务，后缀不带信息。
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
