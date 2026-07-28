#!/bin/bash
# Runs hourly on the mirror: update the overlay copy, sync distfiles, rebuild
# the index and the package list.
#
# Every step's exit code is checked. Writing to a log alone means nobody looks.

set -uo pipefail

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
step "overlay 更新" git -C "${OVERLAY}" fetch --quiet origin master &&
    step "overlay 切换" git -C "${OVERLAY}" reset --quiet --hard origin/master

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
    echo "!! ${n} 个文件取不到"
    sed 's/^/   /' "${FAILURES}"
    alert "distfiles 有 ${n} 个文件取不到（$(hostname)）:
$(head -20 "${FAILURES}")"
    rc=1
fi

exit "${rc}"

}

main "$@"
