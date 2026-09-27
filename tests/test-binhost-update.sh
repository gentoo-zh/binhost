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

# Every host command is a stub: nspawn, systemd-run and rsync exit with the code
# the case asks for, and ssh runs its command locally so the status files land
# in the temp tree. The script's fixed host paths are rewritten into the same tree.
setup() {
    d=$(mktemp -d)
    mkdir -p "${d}/bin" "${d}/repo/ops" "${d}/pkgdir" "${d}/remote" "${d}/site"
    sed -e "s|^LOCKFILE=.*|LOCKFILE=${d}/lock|" -e "s|^TMPFILE=.*|TMPFILE=${d}/log|" \
        -e "s|^PKGDIR=.*|PKGDIR=${d}/pkgdir|" \
        "${ROOT}/builders/binhost-update" > "${d}/binhost-update"
    cat > "${d}/bin/systemd-nspawn" <<'EOF'
#!/bin/bash
case "$*" in
    */run-update) exit "${RUN_RC:-0}" ;;
    */prune-unpublishable) exit "${PRUNE_RC:-0}" ;;
    *emaint*) exit "${EMAINT_RC:-0}" ;;
esac
EOF
    # shellcheck disable=SC2016  # The stubs expand these when they run.
    {
        printf '#!/bin/bash\nexit "${SIGN_RC:-0}"\n' > "${d}/bin/systemd-run"
        printf '#!/bin/bash\nexit "${RSYNC_RC:-0}"\n' > "${d}/bin/rsync"
        printf '#!/bin/bash\nshift\n[[ -z ${SSH_FAIL:-} ]] || exit 255\nexec bash -c "$*"\n' > "${d}/bin/ssh"
    }
    printf '#!/bin/bash\n' | tee "${d}/bin/zfs" > "${d}/bin/emerge"
    printf '#!/bin/bash\ncat >/dev/null\necho '"'"'{"path":"/x"}'"'"'\n' > "${d}/bin/curl"
    chmod +x "${d}/bin"/*
    cat > "${d}/repo/ops/alert.sh" <<EOF
alert() { printf '%s\n' "\$1" > "${d}/alert"; }
alert_exit() { exit "\${1:-1}"; }
EOF
    cat > "${d}/pkgdir/Packages" <<'EOF'
PACKAGES: 3
TIMESTAMP: 1700000000

CPV: app-misc/a-1
REPO: gentoo-zh

CPV: dev-libs/b-1
REPO: gentoo

CPV: dev-libs/c-1
REPO: gentoo
EOF
}

run() {
    PATH="${d}/bin:${PATH}" REPO="${d}/repo" REMOTE_ROOT="${d}/remote" SITE_ROOT="${d}/site" \
        bash "${d}/binhost-update" "${1:-stable}" > "${d}/out" 2>&1
}

field() { grep -o "\"$2\":\"*[a-z0-9]*" "$1" 2>/dev/null | sed 's/.*[:"]//'; }

echo "== binhost-update 的结果矩阵"

setup; run; rc=$?
ok "全部成功时退出码为 0" "${rc}" "0"
ok "status.json 按 Packages 计数" "$(cat "${d}/remote/status.json")" \
   '{"packages":3,"overlay":1,"deps":2,"generated":1700000000}'
ok "build-status.json 记为 done" "$(field "${d}/site/build-status.json" state)" "done"
ok "用时由开始与结束时间计算" \
   "$(( $(field "${d}/site/build-status.json" finished) - $(field "${d}/site/build-status.json" started) ))" \
   "$(field "${d}/site/build-status.json" duration)"
ok "全部成功时不告警" "$([[ -e ${d}/alert ]] && echo sent)" ""
rm -rf "${d}"

setup; RUN_RC=1 run; rc=$?
ok "run-update 失败时退出码为 1" "${rc}" "1"
ok "run-update 失败但已发布时仍写 status.json" "$([[ -s ${d}/remote/status.json ]] && echo yes)" "yes"
ok "run-update 失败时 build-status.json 记为 failed" "$(field "${d}/site/build-status.json" state)" "failed"
ok "run-update 失败时告警" "$(grep -c 'run-update' "${d}/alert" 2>/dev/null)" "1"
rm -rf "${d}"

for step in PRUNE SIGN EMAINT RSYNC; do
    setup; export "${step}_RC=1"; run; rc=$?; unset "${step}_RC"
    ok "${step} 失败时退出码为 1" "${rc}" "1"
    ok "${step} 失败时不写 status.json" "$([[ -e ${d}/remote/status.json ]] && echo written)" ""
    ok "${step} 失败时 build-status.json 记为 failed" "$(field "${d}/site/build-status.json" state)" "failed"
    rm -rf "${d}"
done

setup; SSH_FAIL=1 run; rc=$?
ok "状态写入失败不改变退出码" "${rc}" "0"
ok "状态写入失败时记入日志" "$(grep -c '未能写入' "${d}/out")" "2"
rm -rf "${d}"

setup; SSH_FAIL=1 RUN_RC=1 run; rc=$?
ok "状态写入失败不影响告警" "$([[ -s ${d}/alert ]] && echo sent)" "sent"
ok "状态写入失败时仍以失败退出" "${rc}" "1"
rm -rf "${d}"

setup; run unstable
ok "unstable 写入自己的构建状态文件" "$(field "${d}/site/build-status-unstable.json" state)" "done"
ok "unstable 不覆盖 stable 的构建状态" "$([[ -e ${d}/site/build-status.json ]] && echo written)" ""
rm -rf "${d}"

echo "== binhost-update 的锁与频道"

setup; echo "上一轮日志" > "${d}/log"
( flock -n 9 && run ) 9>"${d}/lock"; rc=$?
ok "锁被占用时跳过并以 0 退出" "${rc}" "0"
ok "锁被占用时不覆盖上一轮日志" "$(cat "${d}/log")" "上一轮日志"
ok "锁被占用时不告警" "$([[ -e ${d}/alert ]] && echo sent)" ""
ok "锁被占用时说明原因" "$(grep -c '已被占用' "${d}/out")" "1"
ok "锁被占用时不写任何状态" "$(find "${d}/remote" "${d}/site" -type f | wc -l)" "0"
rm -rf "${d}"

setup; run testing; rc=$?
ok "未知频道被拒绝" "${rc}" "2"
ok "未知频道不写任何状态" "$(find "${d}/remote" "${d}/site" -type f | wc -l)" "0"
rm -rf "${d}"

echo
if (( fail )); then
    echo ">>> ${fail} 项未通过，${pass} 项通过"
    exit 1
fi
echo ">>> ${pass} 项全部通过"
