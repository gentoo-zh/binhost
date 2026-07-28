#!/bin/bash
# 一轮完整的构建与发布。定时任务跑的就是这个。
#
# 顺序：更新 overlay → 构建 → 发布 → 报告失败。
#
# 并发由 build-container.sh 那层的锁挡住：手工调、定时器调、只重跑几个包，
# 走的都是那一层。

set -euo pipefail

# 主体放进函数：bash 按字节偏移边读边执行，脚本在运行中被替换会让执行路径错乱。
main() {
cd "$(dirname "$0")/.."

OVERLAY="${OVERLAY:-/var/lib/binhost/overlay}"
LOGDIR="${LOGDIR:-/var/lib/binhost/logs/x86-64}"
STAGE="${STAGE:-/var/lib/binhost/stage/x86-64}"
ALERT_CONF="${ALERT_CONF:-/etc/binhost/alert.conf}"

# shellcheck source=build/alert.sh
. "$(dirname "$0")/alert.sh"

# set -e 之下任何一步失败都直接退出。没有这个 trap，git fetch 半夜取不到就是
# 悄无声息地结束，第二天才发现索引还停在前一天。下面几处 if ! 有各自更具体的
# 说法，它们不触发 ERR，两者不重复。
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

# 构建按 overlay 的当前状态来，先取最新的
git -C "${OVERLAY}" fetch --quiet origin master
git -C "${OVERLAY}" reset --quiet --hard origin/master
echo "overlay $(git -C "${OVERLAY}" rev-parse --short HEAD)"

if ! ./build/run-full.sh; then
    alert "binhost 构建阶段失败（$(hostname)）"
    exit 1
fi

if ! ./build/publish.sh; then
    alert "binhost 发布阶段失败（$(hostname)）：包已构建，未同步到镜像机"
    exit 1
fi

# 发布之后核对版本：overlay bump 了新版就该编出新版，drop 了旧版索引里也不该
# 再留着。对不上说明这个包这一轮没编出来，或者被按 REPO 过滤掉了——后一种
# 单看失败清单发现不了。
if ! python3 ./build/check-versions.py \
        "${OVERLAY}" "${STAGE}/Packages" ./build/packages.txt > "${LOGDIR}/versions.txt" 2>&1; then
    cat "${LOGDIR}/versions.txt"
    alert "binhost 版本核对对不上（$(hostname)）:
$(head -20 "${LOGDIR}/versions.txt")"
else
    cat "${LOGDIR}/versions.txt"
fi

# 单包失败不影响本轮其余部分，但需要通知。分类报告区分了
# 「ebuild 需修改」与「构建环境需调整」，前者才涉及 overlay。
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
