#!/bin/bash
# Runs hourly on the mirror: update the overlay copy, sync distfiles, rebuild
# the index and the package list.
#
# Every step's exit code is checked. Writing to a log alone means nobody looks.

set -uo pipefail

# One round at a time. Cron fires hourly and a round can take longer than that
# when the overlay has just added a batch of large distfiles. Two rounds share
# emirrordist's three databases, truncate each other's failure log, and reap in
# parallel -- and reaping is the part that removes files. The build machine has
# had this lock from the start; the mirror had none.
#
# -n rather than waiting: a queued round would fire the moment the first
# finished, against the same overlay commit, with nothing to do.
LOCK="${LOCK:-/run/lock/binhost-daily.lock}"
# 打不开锁文件与「上一轮还运行中」要分开。exec 重导向失败不会中止 bash，flock
# 接着报 Bad file descriptor，原来这两种都走同一个分支 exit 0——锁路径写错时
# 镜像每小时安静跳过、退出 0，而此时 alert.sh 还没 source，没有任何人会知道。
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

# The body is a function so the last line is the only thing that runs it. bash
# reads a script by byte offset as it executes, so replacing the file mid-run
# makes it resume at the same offset in the new file.
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

# The overlay copy is updated first because both later steps read it: distfiles
# are fetched by Manifest, and the package list is generated from directories
# and ebuilds.
#
# A failure here ends the round. The copy is the only source of truth for what
# is still referenced, and audit-distfiles.py retires whatever it does not find
# there. A fetch that failed leaves the tree at yesterday's commit -- harmless.
# A reset that stopped halfway leaves it at neither, and that half tree would be
# read as though the missing packages had been treecleaned.
if ! step "overlay 更新" git -C "${OVERLAY}" fetch --quiet origin master ||
   ! step "overlay 切换" git -C "${OVERLAY}" reset --quiet --hard origin/master; then
    echo "!! overlay 没有更新成功，这一轮到此为止" >&2
    exit 1
fi

# Truncate before each run, otherwise this round's failures cannot be told
# apart from earlier ones.
: > "${FAILURES}"

if step "distfiles 同步" /usr/local/bin/binhost-distfiles-sync; then
    step "distfiles 索引" /usr/local/bin/binhost-distfiles-index
    # INDEX lets the generator see packages pulled in as dependencies during
    # the build -- acct-user, virtual and the like. They are not on the list and
    # have no source files, so without the index they do not appear on the page.
    step "包列表" env LIST="${LIB}/packages.txt" EXCLUDED="${LIB}/excluded.txt" \
        OUT=/srv/mirrors/packages.json INDEX=/srv/pub/binpkgs/x86-64/Packages \
        python3 "${LIB}/gen-packages.py" "${OVERLAY}"

    # Check emirrordist's result independently: everything that should be here
    # is, and nothing that should not. It does not report this itself, and a
    # drift leaves no trace.
    step "distfiles 对账" python3 "${LIB}/audit-distfiles.py" "${OVERLAY}" "${DISTDIR}"
fi

# A file emirrordist cannot fetch does not fail the command; it goes into the
# failure log. Without checking that log separately the mirror loses content a
# piece at a time with nobody the wiser.
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
