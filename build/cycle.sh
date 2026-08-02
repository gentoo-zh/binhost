#!/bin/bash

set -euo pipefail

main() {
cd "$(dirname "$0")/.."

OVERLAY="${OVERLAY:-/var/lib/binhost/overlay}"
LOGDIR="${LOGDIR:-/var/lib/binhost/logs/x86-64}"
STAGE="${STAGE:-/var/lib/binhost/stage/x86-64}"
ALERT_CONF="${ALERT_CONF:-/etc/binhost/alert.conf}"

# shellcheck source=build/alert.sh
. "$(dirname "$0")/alert.sh"

on_error() {
    local rc=$1 line=$2 cmd=$3
    echo "!!! 第 ${line} 行失败（退出码 ${rc}）：${cmd}" >&2
    alert "binhost 本轮失败（$(hostname)）
第 ${line} 行，退出码 ${rc}
${cmd}"
    exit "${rc}"
}
trap 'on_error "$?" "${LINENO}" "${BASH_COMMAND}"' ERR

echo "=== $(date '+%F %T') 开始 ==="

LOCK="${LOCK:-/var/lib/binhost/stage/build.lock}"
mkdir -p "$(dirname "${LOCK}")"
exec 9>"${LOCK}"
if ! flock -n 9; then
    echo "另一轮构建正在进行（${LOCK}），这一轮跳过" >&2
    alert "binhost 这一轮被上一轮阻塞（$(hostname)）：上一轮已超过一个调度间隔"
    exit 1
fi

git -C "${OVERLAY}" fetch --quiet origin master
git -C "${OVERLAY}" reset --quiet --hard origin/master
echo "overlay $(git -C "${OVERLAY}" rev-parse --short HEAD)"

export BINHOST_LOCKED=1

rm -f "${LOGDIR}/whole.log"
./build/build-progress.sh watch "${LOGDIR}/whole.log" &
progress=$!
on_exit() {
    local rc=$1 state
    state='done'
    (( rc )) && state='failed'
    kill "${progress}" 2>/dev/null || true
    ./build/build-progress.sh finish "${state}"
}
trap 'on_exit "$?"' EXIT

if ! ./build/run-full.sh; then
    alert "binhost 构建阶段失败（$(hostname)）"
    exit 1
fi

if ! ./build/publish.sh; then
    alert "binhost 发布阶段失败（$(hostname)）：包已构建，未同步到镜像机"
    exit 1
fi

if ! python3 ./build/check-versions.py \
        "${OVERLAY}" "${STAGE}/Packages" ./build/packages.txt > "${LOGDIR}/versions.txt" 2>&1; then
    cat "${LOGDIR}/versions.txt"
    alert "binhost 版本核对不一致（$(hostname)）:
$(head -20 "${LOGDIR}/versions.txt")"
else
    cat "${LOGDIR}/versions.txt"
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
