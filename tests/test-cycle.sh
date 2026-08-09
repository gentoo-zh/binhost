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

cycle_probe() {
    local publish_rc="$1" with_report="$2" d out rc
    d=$(mktemp -d)
    mkdir -p "${d}/build" "${d}/ops" "${d}/bin" "${d}/logs" "${d}/overlay"
    cp "${ROOT}/build/cycle.sh" "${d}/build/cycle.sh"
    cp "${ROOT}/build/channel.sh" "${d}/build/channel.sh"
    cat > "${d}/ops/alert.sh" <<'EOF'
ALERT_SENT=0
alert() { printf '%s\n' "$1" >> "${ALERT_LOG}"; }
alert_exit() { exit "${1:-1}"; }
EOF
    cat > "${d}/build/build-progress.sh" <<'EOF'
#!/bin/bash
exit 0
EOF
    cat > "${d}/build/run-full.sh" <<'EOF'
#!/bin/bash
exit 0
EOF
    cat > "${d}/build/publish.sh" <<EOF
#!/bin/bash
exit ${publish_rc}
EOF
    cat > "${d}/bin/git" <<'EOF'
#!/bin/bash
case "$*" in *rev-parse*) echo deadbeef;; esac
exit 0
EOF
    chmod +x "${d}/build/"*.sh "${d}/bin/git"
    if [[ ${with_report} == yes ]]; then
        printf 'app-misc/example\n' > "${d}/logs/failed.txt"
        printf '构建失败（1 个）\n    app-misc/example\n' > "${d}/logs/report.txt"
    fi
    set +e
    out=$(cd "${d}" && PATH="${d}/bin:${PATH}" OVERLAY="${d}/overlay" \
        LOGDIR="${d}/logs" STAGE="${d}/stage" LOCK="${d}/lock" \
        ALERT_LOG="${d}/alert.log" bash build/cycle.sh 2>&1)
    rc=$?
    set -e
    printf '%s|%s|%s\n' "${rc}" "$(tr '\n' ' ' < "${d}/alert.log")" "${out}"
    rm -rf "${d}"
}

echo "== cycle.sh 区分发布与清理失败"

IFS='|' read -r rc message out <<< "$(cycle_probe 3 no)"
ok "发布后清理受阻时保留退出码 3" "${rc}" "3"
ok "退出码 3 的通知说明索引已经发布" \
   "$([[ ${message} == *已发布到镜像机* ]] && echo yes)" "yes"
ok "退出码 3 的通知不会声称未发布" \
   "$([[ ${message} != *未发布到镜像机* ]] && echo yes)" "yes"

IFS='|' read -r rc message out <<< "$(cycle_probe 1 yes)"
ok "发布失败时保留原退出码" "${rc}" "1"
ok "发布失败时明确说明未发布" \
   "$([[ ${message} == *未发布到镜像机* ]] && echo yes)" "yes"
ok "目标套件失败摘要会附在发布告警中" \
   "$([[ ${message} == *构建失败*app-misc/example* ]] && echo yes)" "yes"

echo "== cycle.sh 被信号中止时不会报告成功"

# The traps come out of cycle.sh itself so this binds to the real file: remove
# them there and the run below reports done again.
signal_probe() {
    local d
    d=$(mktemp -d)
    cat > "${d}/probe.sh" <<'PROBE'
on_exit() { local rc=$1 state; state=done; (( rc )) && state=failed
            echo "${state}" > "${STATE_FILE}"; }
PROBE
    grep -E '^trap ' "${ROOT}/build/cycle.sh" >> "${d}/probe.sh"
    printf 'true\nsleep 30\n' >> "${d}/probe.sh"
    STATE_FILE="${d}/state" bash "${d}/probe.sh" & local pid=$!
    sleep 0.5
    kill -TERM "${pid}" 2>/dev/null
    wait "${pid}" 2>/dev/null
    cat "${d}/state" 2>/dev/null
    rm -rf "${d}"
}

ok "收到 SIGTERM 时写出 failed" "$(signal_probe)" "failed"

echo
if (( fail )); then
    echo ">>> ${fail} 项未通过，${pass} 项通过"
    exit 1
fi
echo ">>> ${pass} 项全部通过"
