#!/bin/bash
# 镜像机每天跑一次：更新 overlay 副本、同步 distfiles、重算索引与包列表。
#
# 每一步都判退出码。只写进日志不会有人主动去看。

set -uo pipefail

# 主体放进函数：bash 按字节偏移边读边执行，脚本在运行中被替换会让执行路径错乱。
main() {
ALERT_CONF="${ALERT_CONF:-/etc/binhost/alert.conf}"
LIB="${LIB:-/usr/local/lib/binhost}"
OVERLAY="${OVERLAY:-/var/lib/binhost-overlay}"
MODE="${MODE:-upstream}"
DISTDIR="${DISTDIR:-/srv/pub/distfiles}"
FAILURES="${FAILURES:-/var/log/emirrordist/failures.log}"

rc=0

alert() {
    # 文件在却读不到，和没配过是两回事：前者说明属主与跑它的用户对不上，
    # 告警会一直发不出去而没有任何迹象。
    if [[ -e ${ALERT_CONF} && ! -r ${ALERT_CONF} ]]; then
        echo "!! ${ALERT_CONF} 读不到（当前用户 $(id -un)），告警发不出去" >&2
        return 0
    fi
    [[ -r ${ALERT_CONF} ]] || return 0
    # shellcheck source=/dev/null
    . "${ALERT_CONF}"
    curl -fsS --max-time 20 -o /dev/null \
        "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TELEGRAM_CHAT}" \
        --data-urlencode "text=$1" || true
}

step() {
    local name=$1; shift
    local out
    if ! out=$("$@" 2>&1); then
        echo "!! ${name} 失败"
        printf '   %s\n' "${out}"
        alert "${name} 失败（$(hostname)）:
${out}"
        rc=1
        return 1
    fi
    echo "${out}"
}

# overlay 副本要先更新，后面两步都读它：distfiles 按 Manifest 取，
# 包列表按目录和 ebuild 生成。放进同步脚本会让它只在 upstream 模式下更新。
step "overlay 更新" git -C "${OVERLAY}" fetch --quiet origin master &&
    step "overlay 切换" git -C "${OVERLAY}" reset --quiet --hard origin/master

# 每次跑之前清空，否则判断不出这一轮有没有新失败
: > "${FAILURES}"

if step "distfiles 同步" env MODE="${MODE}" /usr/local/bin/binhost-distfiles-sync; then
    step "distfiles 索引" /usr/local/bin/binhost-distfiles-index
    # INDEX 让生成器认得构建时被依赖带出来的包（acct-user、virtual 这类），
    # 它们不在清单里也没有源码文件，不提供索引则页面上查不到。
    step "包列表" env LIST="${LIB}/packages.txt" EXCLUDED="${LIB}/excluded.txt" \
        OUT=/srv/mirrors/packages.json INDEX=/srv/pub/binpkgs/x86-64/Packages \
        python3 "${LIB}/gen-packages.py" "${OVERLAY}"

    # 独立复核 emirrordist 的结果：该有的都有，不该有的没有。
    # 它自己不报这件事，出了偏差没有任何迹象。
    step "distfiles 对账" python3 "${LIB}/audit-distfiles.py" "${OVERLAY}" "${DISTDIR}"
fi

# emirrordist 取不到某个文件时不会让整条命令失败，只写进 failure-log。
# 不单独查这份日志，镜像会逐渐缺失内容而无人知晓。
if [[ ${MODE} == upstream && -s ${FAILURES} ]]; then
    n=$(wc -l < "${FAILURES}")
    echo "!! ${n} 个文件取不到"
    sed 's/^/   /' "${FAILURES}"
    alert "distfiles 有 ${n} 个文件取不到（$(hostname)）:
$(head -20 "${FAILURES}")"
    rc=1
fi

exit "${rc}"

}

main "$@"
