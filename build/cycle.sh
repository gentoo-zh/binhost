#!/bin/bash

set -euo pipefail

main() {
cd "$(dirname "$0")/.."

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=build/channel.sh
. "${SCRIPT_DIR}/channel.sh"

OVERLAY="${OVERLAY:-/var/lib/binhost/overlay}"
TREE="${TREE:-/var/db/repos/gentoo}"
# A skipped round is only a fault once the channel has gone this long
# without publishing anything.
SKIP_STALE_H="${SKIP_STALE_H:-26}"
LOGDIR="${LOGDIR:-/var/lib/binhost/logs/${CHANNEL_STORAGE}}"
STAGE="${STAGE:-/var/lib/binhost/stage/${CHANNEL_STORAGE}}"
PROGRESS_OUT="${PROGRESS_OUT:-${CHANNEL_PROGRESS_OUT}}"
ALERT_CONF="${ALERT_CONF:-/etc/binhost/alert.conf}"

# shellcheck source=ops/alert.sh
. "$(dirname "$0")/../ops/alert.sh"

on_error() {
    local rc=$1 line=$2 cmd=$3
    echo "!!! 第 ${line} 行失败（退出码 ${rc}）：${cmd}" >&2
    alert "binhost 本次失败（$(hostname) ${CHANNEL}）
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
    # Both channels share this lock, so one of them running long makes the
    # other stand aside. That is the design working, not a fault, and failing
    # the unit for it puts a red mark on a healthy machine. What does need
    # someone is a channel that keeps standing aside until it stops publishing
    # at all, so the decision is made on when this channel last published.
    published=$(stat -c %Y "${STAGE}/Packages" 2>/dev/null || echo 0)
    age=$(( ( $(date +%s) - published ) / 3600 ))
    if (( published == 0 || age >= SKIP_STALE_H )); then
        alert "binhost 连续被阻塞（$(hostname) ${CHANNEL}）：已 ${age} 小时没有发布"
        alert_exit
    fi
    echo ">>> 这个频道 ${age} 小时前发布过，跳过不算故障"
    exit 0
fi

BUILD_STARTED=$(date +%s)
export BUILD_STARTED

git -C "${OVERLAY}" fetch --quiet origin master
git -C "${OVERLAY}" reset --quiet --hard origin/master
echo "overlay $(git -C "${OVERLAY}" rev-parse --short HEAD)"

# The overlay was brought up to date every round while ::gentoo was not, so the
# tree the packages were built against fell as much as a week behind whatever a
# user has. A dependency that changed subslot in that window makes every
# package built against the older one unusable on that user's system.
if ! sudo emaint sync -r gentoo > /dev/null; then
    echo "!! ::gentoo 未能同步，本轮按现有的树构建" >&2
fi
echo "::gentoo $(date -r "${TREE}/metadata/timestamp.chk" '+%F %H:%M' 2>/dev/null || echo 未知)"

export BINHOST_LOCKED=1

rm -f "${LOGDIR}/whole.log" "${LOGDIR}/progress"
# Own process group, so the kill below also reaches an ssh the watcher has in
# flight. A plain kill only fells the watcher; its child is reparented and can
# still put a running snapshot on top of the final state.
OUT="${PROGRESS_OUT}" setsid ./build/build-progress.sh watch "${LOGDIR}/whole.log" &
progress=$!
on_exit() {
    local rc=$1 state
    state='done'
    (( rc )) && state='failed'
    kill -- -"${progress}" 2>/dev/null || kill "${progress}" 2>/dev/null || true
    wait "${progress}" 2>/dev/null || true
    # The run is over either way. A progress push that fails must not turn a
    # finished build into a failed service; the site going stale is what
    # ops/status.sh watches for.
    OUT="${PROGRESS_OUT}" ./build/build-progress.sh finish "${state}" || true
}
# Preserve a nonzero status for the EXIT trap when a signal stops the run.
trap 'exit 143' TERM INT HUP
trap 'on_exit "$?"' EXIT

if ! ./build/run-full.sh; then
    alert "binhost 构建阶段失败（$(hostname) ${CHANNEL}）"
    alert_exit
fi

if [[ -s ${LOGDIR}/smoke-alert.txt ]]; then
    alert "binhost gpkg 安装冒烟测试发现问题（$(hostname) ${CHANNEL}）：
$(cat "${LOGDIR}/smoke-alert.txt")"
fi

if [[ -s ${LOGDIR}/subslot-alert.txt ]]; then
    alert "binhost 有包的依赖子槽已过期（$(hostname) ${CHANNEL}）：
$(cat "${LOGDIR}/subslot-alert.txt")"
fi

publish_rc=0
./build/publish.sh || publish_rc=$?
if (( publish_rc )); then
    if (( publish_rc == 3 )); then
        message="binhost 已发布到镜像机，但索引包数骤减，退休清理未执行（$(hostname) ${CHANNEL}）"
    else
        message="binhost 发布阶段失败（$(hostname) ${CHANNEL}）：包已构建，未发布到镜像机"
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
    alert "binhost 构建失败 ${n} 个（$(hostname) ${CHANNEL}）:
${report}"
fi

echo "=== $(date '+%F %T') 结束 ==="

}

main "$@"
