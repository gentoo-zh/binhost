#!/bin/bash

set -euo pipefail

main() {
cd "$(dirname "$0")/.."

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=build/channel.sh
. "${SCRIPT_DIR}/channel.sh"

OVERLAY="${OVERLAY:-/var/lib/binhost/overlay}"
LOGDIR="${LOGDIR:-/var/lib/binhost/logs/${CHANNEL_STORAGE}}"
STAGE="${STAGE:-/var/lib/binhost/stage/${CHANNEL_STORAGE}}"
PROGRESS_OUT="${PROGRESS_OUT:-${CHANNEL_PROGRESS_OUT}}"
ALERT_CONF="${ALERT_CONF:-/etc/binhost/alert.conf}"

# shellcheck source=ops/alert.sh
. "$(dirname "$0")/../ops/alert.sh"

on_error() {
    local rc=$1 line=$2 cmd=$3
    echo "!!! 第 ${line} 行失败（退出码 ${rc}）：${cmd}" >&2
    alert "binhost 本次失败（$(hostname)）
第 ${line} 行，退出码 ${rc}
${cmd}"
    alert_exit "${rc}"
}
trap 'on_error "$?" "${LINENO}" "${BASH_COMMAND}"' ERR

echo "=== $(date '+%F %T') 开始 ==="

LOCK="${LOCK:-/var/lib/binhost/stage/build.lock}"
mkdir -p "$(dirname "${LOCK}")"
exec 9>"${LOCK}"
if ! flock -n 9; then
    echo "另一次构建正在执行（${LOCK}），这次跳过" >&2
    alert "binhost 这次被上一次阻塞（$(hostname)）：上一次已超过一个调度间隔"
    alert_exit
fi

BUILD_STARTED=$(date +%s)
export BUILD_STARTED

git -C "${OVERLAY}" fetch --quiet origin master
git -C "${OVERLAY}" reset --quiet --hard origin/master
echo "overlay $(git -C "${OVERLAY}" rev-parse --short HEAD)"

export BINHOST_LOCKED=1

rm -f "${LOGDIR}/whole.log" "${LOGDIR}/progress"
OUT="${PROGRESS_OUT}" ./build/build-progress.sh watch "${LOGDIR}/whole.log" &
progress=$!
on_exit() {
    local rc=$1 state
    state='done'
    (( rc )) && state='failed'
    kill "${progress}" 2>/dev/null || true
    wait "${progress}" 2>/dev/null || true
    OUT="${PROGRESS_OUT}" ./build/build-progress.sh finish "${state}"
}
# Without this the EXIT trap reads $? from the last completed command, so a
# run killed part way through reports done. It happened: a stable build was
# stopped at 12:30 and the site showed it as a three minute success.
trap 'exit 143' TERM INT HUP
trap 'on_exit "$?"' EXIT

if ! ./build/run-full.sh; then
    alert "binhost 构建阶段失败（$(hostname)）"
    alert_exit
fi

if [[ -s ${LOGDIR}/smoke-alert.txt ]]; then
    alert "binhost gpkg 安装冒烟测试发现问题（$(hostname)）：
$(cat "${LOGDIR}/smoke-alert.txt")"
fi

publish_rc=0
./build/publish.sh || publish_rc=$?
if (( publish_rc )); then
    if (( publish_rc == 3 )); then
        message="binhost 已发布到镜像机，但退休清理被上限阻止（$(hostname)）"
    else
        message="binhost 发布阶段失败（$(hostname)）：包已构建，未发布到镜像机"
        if [[ -s ${LOGDIR}/report.txt ]]; then
            message="${message}
$(cat "${LOGDIR}/report.txt")"
        fi
    fi
    alert "${message}"
    alert_exit "${publish_rc}"
fi

if [[ -s ${LOGDIR}/failed.txt ]]; then
    n=$(wc -l < "${LOGDIR}/failed.txt")
    report=$(python3 ./build/classify-failures.py "${LOGDIR}")
    echo "${report}"
    alert "binhost 构建失败 ${n} 个（$(hostname)）:
${report}"
fi

echo "=== $(date '+%F %T') 结束 ==="

}

main "$@"
