#!/bin/bash

set -uo pipefail

LOCK="${LOCK:-/run/lock/binhost-daily.lock}"
if ! exec 9>"${LOCK}"; then
    echo "!! 打不开锁文件 ${LOCK}" >&2
    exit 1
fi
if ! command -v flock >/dev/null; then
    echo "!! 没有 flock，无法保证一轮只执行一次" >&2
    exit 1
fi
if ! flock -n 9; then
    echo "上一轮尚未结束（${LOCK}），本轮跳过" >&2
    exit 0
fi

main() {
ALERT_CONF="${ALERT_CONF:-/etc/binhost/alert.conf}"
LIB="${LIB:-/usr/local/lib/binhost}"
OVERLAY="${OVERLAY:-/var/lib/binhost-overlay}"
DISTDIR="${DISTDIR:-/srv/pub/distfiles}"
FAILURES="${FAILURES:-/var/log/emirrordist/failures.log}"

rc=0

# shellcheck source=build/alert.sh
. "${LIB}/alert.sh"

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

if ! step "overlay 更新" git -C "${OVERLAY}" fetch --quiet origin master ||
   ! step "overlay 切换" git -C "${OVERLAY}" reset --quiet --hard origin/master; then
    echo "!! overlay 更新失败，本轮终止" >&2
    exit 1
fi

: > "${FAILURES}"

if step "distfiles 同步" /usr/local/bin/binhost-distfiles-sync; then
    step "distfiles 索引" /usr/local/bin/binhost-distfiles-index
    step "包列表" env LIST="${LIB}/packages.txt" EXCLUDED="${LIB}/excluded.txt" \
        OUT=/srv/mirrors/packages.json INDEX=/srv/pub/binpkgs/x86-64/Packages \
        python3 "${LIB}/gen-packages.py" "${OVERLAY}"

    step "distfiles 对账" python3 "${LIB}/audit-distfiles.py" "${OVERLAY}" "${DISTDIR}"
fi

# The base system list arrives with the index. An index published before this
# check existed does not have one, and that is not a dependency problem, so it
# is reported and skipped. An unreadable list is still a failure: verify-deps
# refuses to guess.
BASELINE=/srv/pub/binpkgs/x86-64/installed.txt
if [[ -e ${BASELINE} ]]; then
    step "依赖反向验证" python3 "${LIB}/verify-deps.py" \
        /srv/pub/binpkgs/x86-64/Packages --installed "${BASELINE}"
else
    echo "跳过依赖反向验证：${BASELINE} 尚未发布，下一轮建置会带上它"
fi

if [[ -s ${FAILURES} ]]; then
    n=$(wc -l < "${FAILURES}")
    echo "!! ${n} 个文件无法获取"
    sed 's/^/   /' "${FAILURES}"
    alert "distfiles 有 ${n} 个文件无法获取（$(hostname)）:
$(head -20 "${FAILURES}")"
    rc=1
fi

exit "${rc}"

}

main "$@"
