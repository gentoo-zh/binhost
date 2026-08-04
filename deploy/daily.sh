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
    step "distfiles 对账" python3 "${LIB}/audit-distfiles.py" "${OVERLAY}" "${DISTDIR}"
    step "distfiles 索引" /usr/local/bin/binhost-distfiles-index
    step "包列表" env LIST="${LIB}/packages.txt" EXCLUDED="${LIB}/excluded.txt" \
        OUT=/srv/mirrors/packages.json INDEX=/srv/pub/binpkgs/x86-64/Packages \
        python3 "${LIB}/gen-packages.py" "${OVERLAY}"
fi

# generation.json arrives with the first index created by the generation-aware
# builder. Older public indexes predate this check and are skipped, while any
# existing entry, including a broken symlink, must still pass verification.
BINPKGS="${BINPKGS:-/srv/pub/binpkgs/x86-64}"
GENERATION="${BINPKGS}/generation.json"
if [[ ! -e ${GENERATION} && ! -L ${GENERATION} ]]; then
    echo "跳过同代清单与依赖反向验证：${GENERATION} 尚未发布，下一轮构建会带上它"
elif step "同代清单验证" python3 "${LIB}/generation.py" verify "${BINPKGS}"; then
    step "依赖反向验证" python3 "${LIB}/verify-deps.py" \
        "${BINPKGS}/Packages" --installed "${BINPKGS}/installed.txt" \
        --available "${BINPKGS}/official.txt" --source "${BINPKGS}/source.txt"
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
