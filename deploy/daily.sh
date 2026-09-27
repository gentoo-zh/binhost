#!/bin/bash

set -uo pipefail

LOCK="${LOCK:-/run/lock/binhost-daily.lock}"
if ! exec 9>"${LOCK}"; then
    echo "!! 打不开锁文件 ${LOCK}" >&2
    exit 1
fi
if ! command -v flock >/dev/null; then
    echo "!! 没有 flock，无法保证同时只有一次在执行" >&2
    exit 1
fi
if ! flock -n 9; then
    echo "上一次尚未结束（${LOCK}），本次跳过" >&2
    exit 0
fi

main() {
ALERT_CONF="${ALERT_CONF:-/etc/binhost/alert.conf}"
LIB="${LIB:-/usr/local/lib/binhost}"
OVERLAY="${OVERLAY:-/var/lib/binhost-overlay}"
DISTDIR="${DISTDIR:-/srv/pub/distfiles}"
FAILURES="${FAILURES:-/var/log/emirrordist/failures.log}"

rc=0

# shellcheck source=ops/alert.sh
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
    echo "!! overlay 更新失败，本次终止" >&2
    exit 1
fi

: > "${FAILURES}"

if step "distfiles 同步" /usr/local/bin/binhost-distfiles-sync; then
    step "distfiles 对账" python3 "${LIB}/audit-distfiles.py" "${OVERLAY}" "${DISTDIR}"
    step "distfiles 索引" /usr/local/bin/binhost-distfiles-index
fi

step "stable 包列表" env LIST="${LIB}/packages.txt" EXCLUDED="${LIB}/excluded.txt" \
    CHANNEL_EXCLUDED="${LIB}/stable-excluded.txt" \
    OUT=/srv/mirrors/packages.json PACKAGE_TEXT=/srv/mirrors/packages.txt \
    DEPS_TEXT=/srv/mirrors/deps.txt INDEX=/srv/pub/binpkgs/x86-64/Packages \
    python3 "${LIB}/gen-packages.py" "${OVERLAY}"
step "unstable 包列表" env LIST="${LIB}/packages.txt" EXCLUDED="${LIB}/excluded.txt" \
    OUT=/srv/mirrors/packages-unstable.json \
    PACKAGE_TEXT=/srv/mirrors/packages-unstable.txt \
    DEPS_TEXT=/srv/mirrors/deps-unstable.txt \
    INDEX=/srv/pub/unstable/binpkgs/x86-64/Packages \
    python3 "${LIB}/gen-packages.py" "${OVERLAY}"

step "服务器状态" /usr/local/bin/binhost-server-status

verify_channel() {
    local label=$1 binpkgs=$2
    step "${label} 索引验证" python3 - "${binpkgs}" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
header, *entries = [dict(line.partition(": ")[::2] for line in block.splitlines())
                    for block in (root / "Packages").read_text().strip().split("\n\n")]
paths = [entry["PATH"] for entry in entries if "PATH" in entry]
missing = [path for path in paths if not (root / path).is_file()]
if header.get("PACKAGES") != str(len(paths)):
    sys.exit(f"PACKAGES 为 {header.get('PACKAGES', '缺失')}，PATH 有 {len(paths)} 条")
if missing:
    sys.exit(f"{len(missing)} 个 PATH 在本地不存在：" + " ".join(missing[:20]))
print(f"{len(paths)} 个包，PATH 都在本地")
PY
}

verify_channel stable "${STABLE_BINPKGS:-/srv/pub/binpkgs/x86-64}"
verify_channel unstable "${UNSTABLE_BINPKGS:-/srv/pub/unstable/binpkgs/x86-64}"

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
