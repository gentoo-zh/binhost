#!/bin/bash
# 把 distfiles 同步到本地。镜像机上按天跑。
#
# distfiles 和 binpkg 的性质不同：binpkg 是衍生物，丢了重编就有；distfiles 是
# 原件，上游消失了就永远没了。所以这份存在的意义是留存，不是省带宽。
#
# 两种来源，由 MODE 选：
#
#   mirror（默认）  从 distfiles.gentoozh.org rsync。观察期用这个：两份保持位元
#                   一致，出现任何差异就是真问题。而且上游已经消失的文件只有那台
#                   还留着，从各上游重抓是抓不回来的。
#
#   upstream        用 emirrordist 按 overlay 的 Manifest 直接从各上游取。等这台
#                   接管 distfiles.gentoozh.org 之后切到这个。emirrordist 会校验
#                   摘要、维护镜像布局，并且**原生跳过 RESTRICT=mirror**
#                   （FetchIterator.py 里显式判断），不需要我们额外把关。
#
# 深夜跑：这台一个核，摘要校验会和白天发文件抢 CPU。

set -euo pipefail

# 主体放进函数：bash 按字节偏移边读边执行，脚本在运行中被替换会让执行路径错乱。
main() {
MODE="${MODE:-mirror}"
DEST="${DEST:-/srv/pub/distfiles}"
# 钉在旧机的地址上，不用 distfiles.gentoozh.org 这个名字：那个名字迁过来之后
# 会指向本机，mirror 模式就变成自己 rsync 自己，对账当然也永远一致。
UPSTREAM_RSYNC="${UPSTREAM_RSYNC:-rsync://23.19.231.68/gentoo-zh/distfiles/}"
REPO="${REPO:-gentoo-zh}"
OVERLAY="${OVERLAY:-/var/lib/binhost-overlay}"
STATE="${STATE:-/var/lib/emirrordist}"
# 并发按上游定，不按 CPU：这台单核算 BLAKE2B 有 600 MB/s，而从上游拉一个
# distfile 只有 2.4 MB/s，等的是网络不是处理器。6 条聚合约 15 MB/s，对
# GitHub 这类上游也不至于触发限速。
JOBS="${JOBS:-6}"
# 一周：ebuild 从 overlay 移除后，它的 distfile 过这么久才删，留出回滚窗口
DELETION_DELAY="${DELETION_DELAY:-604800}"

install -dm755 "${DEST}" "${STATE}" "${STATE}/tmp" /var/log/emirrordist

case "${MODE}" in
mirror)
    # 来源解析到本机就是拉自己，那样 --delete 会按自己的内容删自己，
    # 而对账比的两边是同一份，什么都发现不了。
    src_host=${UPSTREAM_RSYNC#rsync://}; src_host=${src_host%%/*}
    for ip in $(getent ahostsv4 "${src_host}" | awk '{print $1}' | sort -u); do
        if ip -4 -o addr show scope global | grep -qw "${ip}"; then
            echo "!! 同步来源 ${src_host} 解析到本机 ${ip}，拒绝执行" >&2
            exit 1
        fi
    done
    # 布局跟着上游走，layout.conf 也一起同步，两份完全一致
    rsync -a --delete "${UPSTREAM_RSYNC}" "${DEST}/"
    ;;
upstream)
    # overlay 副本由 daily.sh 更新：包列表那步也要读它，放在这里
    # mirror 模式下它永远停在最初 clone 的那一版。
    # DELETE=0 只抓不删。从 mirror 模式切过来的第一次要用它：本地有一批文件是
    # 当前 overlay 已不引用的旧版本，只有旧机那份留着，从上游重抓不回来。先确认
    # 自主抓取跑得通，再决定这些留不留。
    delete=(--delete
            --deletion-db "${STATE}/deletion.db"
            --deletion-delay "${DELETION_DELAY}"
            --scheduled-deletion-log /var/log/emirrordist/deletions.log)
    [[ ${DELETE:-1} == 0 ]] && delete=()

    emirrordist \
        --mirror \
        --repo "${REPO}" \
        --distfiles "${DEST}" \
        --jobs "${JOBS}" \
        "${delete[@]}" \
        --distfiles-db "${STATE}/distfiles.db" \
        --failure-log /var/log/emirrordist/failures.log \
        --success-log /var/log/emirrordist/successes.log \
        --temp-dir "${STATE}/tmp"
    ;;
*)
    echo "MODE 只能是 mirror 或 upstream" >&2
    exit 1
    ;;
esac

n=$(find "${DEST}" -type f ! -name layout.conf | wc -l)
echo "$(date '+%F %T') ${MODE}: ${n} 个文件，$(du -sh "${DEST}" | cut -f1)"

# 观察期对账：和来源逐项比。只说「同步跑过了」没有意义，要能看出有没有漂移。
if [[ ${MODE} == mirror ]]; then
    read -r rn _ < <(
        rsync --list-only -r "${UPSTREAM_RSYNC}" 2>/dev/null |
        awk '$1 !~ /^d/ && $5 != "layout.conf" { n++; gsub(",","",$2); s+=$2 } END { print n, s }'
    )
    if [[ -n ${rn:-} && ${rn} -gt 0 ]]; then
        if [[ ${n} == "${rn}" ]]; then
            # 数量相同不代表是同一批文件。名字集合也比一次。
            diff <(find "${DEST}" -type f ! -name layout.conf -printf '%f\n' | sort) \
                 <(rsync --list-only -r "${UPSTREAM_RSYNC}" 2>/dev/null |
                   awk '$1 !~ /^d/ {print $5}' | sed 's|.*/||' |
                   grep -vx layout.conf | sort) > /tmp/binhost-dist-diff || {
                echo "  !! 文件数相同但名字对不上：" >&2
                head -10 /tmp/binhost-dist-diff >&2
                exit 1
            }
            echo "  对账一致：${n} 个文件"
        else
            echo "  !! 文件数不一致：本地 ${n}，来源 ${rn}" >&2
            exit 1
        fi
    else
        echo "  !! 来源列不出内容，无法对账" >&2
        exit 1
    fi
fi

}

main "$@"
