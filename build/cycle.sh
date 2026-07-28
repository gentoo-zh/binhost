#!/bin/bash
# One full build-and-publish round. This is what the timer runs.
#
# Order: update the overlay, build, publish, report failures.
#
# Concurrency is held off one layer down, in build-container.sh: a manual run,
# a timer run, and a rerun of a few packages all go through it.

set -euo pipefail

# The body is a function so the last line is the only thing that runs it. bash
# reads a script by byte offset as it executes, so replacing the file mid-run
# makes it resume at the same offset in the new file.
main() {
cd "$(dirname "$0")/.."

OVERLAY="${OVERLAY:-/var/lib/binhost/overlay}"
LOGDIR="${LOGDIR:-/var/lib/binhost/logs/x86-64}"
STAGE="${STAGE:-/var/lib/binhost/stage/x86-64}"
ALERT_CONF="${ALERT_CONF:-/etc/binhost/alert.conf}"

# shellcheck source=build/alert.sh
. "$(dirname "$0")/alert.sh"

# Under set -e any failed step exits. Without this trap a git fetch that fails
# overnight just ends quietly, and the index is still yesterday's in the
# morning. The `if !` blocks below say something more specific and do not fire
# ERR, so the two do not overlap.
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

# 整轮持锁，而不是只在 build-container.sh 里持。文件开头原来写着并发由下一层
# 挡住，但下一层的 flock 盖不到这里的 reset --hard 和后面的 publish.sh：第二轮
# 会在第一轮正把这棵树 bind mount 进容器、emerge 跑到一半时把它重置掉，而
# publish.sh 读的暂存目录也会被下一轮的 mv 抽走。
LOCK="${LOCK:-/var/lib/binhost/stage/build.lock}"
mkdir -p "$(dirname "${LOCK}")"
exec 9>"${LOCK}"
if ! flock -n 9; then
    echo "另一轮构建正在进行（${LOCK}），这一轮跳过" >&2
    exit 0
fi

# Build against the overlay as it is now, so take the newest first.
git -C "${OVERLAY}" fetch --quiet origin master
git -C "${OVERLAY}" reset --quiet --hard origin/master
echo "overlay $(git -C "${OVERLAY}" rev-parse --short HEAD)"

export BINHOST_LOCKED=1

if ! ./build/run-full.sh; then
    alert "binhost 构建阶段失败（$(hostname)）"
    exit 1
fi

if ! ./build/publish.sh; then
    alert "binhost 发布阶段失败（$(hostname)）：包已构建，未同步到镜像机"
    exit 1
fi

# Check versions after publishing. A bump in the overlay should produce a new
# version here, and a dropped version should leave the index. A mismatch means
# the package did not build this round, or it was filtered out by REPO -- the
# second of those does not show up in the failure list at all.
if ! python3 ./build/check-versions.py \
        "${OVERLAY}" "${STAGE}/Packages" ./build/packages.txt > "${LOGDIR}/versions.txt" 2>&1; then
    cat "${LOGDIR}/versions.txt"
    alert "binhost 版本核对对不上（$(hostname)）:
$(head -20 "${LOGDIR}/versions.txt")"
else
    cat "${LOGDIR}/versions.txt"
fi

# One failed package does not spoil the rest of the round, but someone has to
# hear about it. The classified report separates an ebuild that needs a change
# from a build environment that needs one; only the first concerns the overlay.
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
