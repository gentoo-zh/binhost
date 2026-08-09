#!/bin/bash

set -uo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
pass=0
fail=0

ok() {
    if [[ $2 == "$3" ]]; then
        printf '  ✓ %s\n' "$1"
        pass=$((pass + 1))
    else
        printf '  ✗ %s\n      得到 %s，应为 %s\n' "$1" "$2" "$3"
        fail=$((fail + 1))
    fi
}

# The lock lives on the mirror and is taken over ssh, so ssh is replaced with a
# stub running the same script locally. Under test is the take-or-refuse logic,
# not the transport. The probe is cut out of build/publish.sh so the assertions
# bind to the real file.
setup() {
    local d
    d=$(mktemp -d)
    mkdir -p "${d}/bin" "${d}/root"
    cat > "${d}/bin/ssh" <<'EOF'
#!/bin/bash
shift
exec /bin/sh -c "$*"
EOF
    chmod +x "${d}/bin/ssh"

    cat > "${d}/probe.sh" <<'PROBE'
#!/bin/bash
set -uo pipefail
LOCK_DIR="${REMOTE_ROOT}/.publish.lock"
PROBE
    sed -n '/^held=.(ssh/,/^trap release_lock EXIT/p' \
        "${ROOT}/build/publish.sh" >> "${d}/probe.sh"
    cat >> "${d}/probe.sh" <<'TAIL'
echo "${held}"
TAIL

    cat > "${d}/release.sh" <<'RELEASE'
#!/bin/bash
set -uo pipefail
LOCK_DIR="${REMOTE_ROOT}/.publish.lock"
RELEASE
    sed -n '/^release_lock() {/,/^}/p' \
        "${ROOT}/build/publish.sh" >> "${d}/release.sh"
    cat >> "${d}/release.sh" <<'TAIL'
release_lock
TAIL
    echo "${d}"
}

take() {
    local d="$1" run="$2"
    PATH="${d}/bin:${PATH}" REMOTE=x REMOTE_ROOT="${d}/root" \
        RUN_ID="${run}" LOCK_STALE_H="${LOCK_STALE_H:-6}" \
        bash "${d}/probe.sh" 2>&1
}

# Someone else is publishing right now: the directory exists and is not ours.
held_by() {
    local d="$1" owner="$2" age="$3"
    rm -rf "${d}/root/.publish.lock"
    mkdir -p "${d}/root/.publish.lock"
    printf '%s\n' "${owner}" > "${d}/root/.publish.lock/owner"
    touch -d "${age}" "${d}/root/.publish.lock"
}

echo "== 没有人持有时取得"
d=$(setup)
ok "取得锁" "$(take "${d}" runA)" "taken"
ok "结束时释放自己的锁" \
   "$(test -d "${d}/root/.publish.lock" && echo 在 || echo 已释放)" "已释放"

echo
echo "== 别人正在发布时暂缓"
held_by "${d}" runA now
out=$(take "${d}" runB)
ok "第二个发布者暂缓" "$([[ ${out} == *已有发布进行中* ]] && echo yes)" "yes"
ok "说出锁的持有者" "$([[ ${out} == *runA* ]] && echo yes)" "yes"
ok "不夺走别人的锁" \
   "$(cat "${d}/root/.publish.lock/owner" 2>/dev/null)" "runA"

echo
echo "== 陈旧的锁会被接管"
held_by "${d}" runA '10 hours ago'
out=$(take "${d}" runC)
ok "超过期限就接管" "$([[ ${out} == *stale-taken* ]] && echo yes)" "yes"

echo
echo "== 未到期限的锁不接管"
held_by "${d}" runA '1 hour ago'
out=$(take "${d}" runD)
ok "一小时的锁仍然暂缓" "$([[ ${out} == *已有发布进行中* ]] && echo yes)" "yes"
ok "持有者没有被改写" \
   "$(cat "${d}/root/.publish.lock/owner" 2>/dev/null)" "runA"

echo
echo "== 接管之后原来的持有者不会移除新锁"
# A stalls past the deadline, B takes over, then A finally exits. Without the
# owner check A would remove the lock B is publishing under.
held_by "${d}" runB now
PATH="${d}/bin:${PATH}" REMOTE=x REMOTE_ROOT="${d}/root" RUN_ID=runA \
    bash "${d}/release.sh" >/dev/null 2>&1
ok "旧持有者收尾时不动别人的锁" \
   "$(cat "${d}/root/.publish.lock/owner" 2>/dev/null)" "runB"
PATH="${d}/bin:${PATH}" REMOTE=x REMOTE_ROOT="${d}/root" RUN_ID=runB \
    bash "${d}/release.sh" >/dev/null 2>&1
ok "自己的锁收尾时会释放" \
   "$(test -d "${d}/root/.publish.lock" && echo 在 || echo 已释放)" "已释放"

echo
echo "== 暂存名称带上本次执行的编号"
d1='$'
ok "六个暂存档都带 RUN_ID" \
   "$(grep -c "REMOTE_ROOT}/\.[A-Za-z.]*\.${d1}{RUN_ID}\.new" \
      "${ROOT}/build/publish.sh")" "6"
ok "替换时用同一个编号还原" \
   "$(grep -c "\.${d1}name\.${d1}run\.prev" "${ROOT}/build/publish.sh")" "1"
rm -rf "${d}"

echo
if (( fail )); then
    echo ">>> ${fail} 项未通过，${pass} 项通过"
    exit 1
fi
echo ">>> ${pass} 项全部通过"
