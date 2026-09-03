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
    local publish_rc="$1" with_report="$2" with_smoke="${3:-no}"
    local progress_rc="${4:-0}" orphan="${5:-no}" d out rc
    d=$(mktemp -d)
    mkdir -p "${d}/build" "${d}/ops" "${d}/bin" "${d}/logs" "${d}/overlay"
    cp "${ROOT}/build/cycle.sh" "${d}/build/cycle.sh"
    cp "${ROOT}/build/channel.sh" "${d}/build/channel.sh"
    cat > "${d}/ops/alert.sh" <<'EOF'
ALERT_SENT=0
alert() { printf '%s\n' "$1" >> "${ALERT_LOG}"; }
alert_exit() { exit "${1:-1}"; }
EOF
    cat > "${d}/build/build-progress.sh" <<EOF
#!/bin/bash
printf '%s OUT=%s\n' "\$1" "\${OUT:-unset}" >> "${d}/progress.log"
[ "\$1" = finish ] && exit ${progress_rc}
( sleep 0.4; echo late >> "${d}/late.log" ) &
sleep 30
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
    if [[ ${with_smoke} == yes ]]; then
        printf 'gpkg 安装失败 1 个，测试环境失败 0 项\n' \
            > "${d}/logs/smoke-alert.txt"
    fi
    set +e
    out=$(cd "${d}" && PATH="${d}/bin:${PATH}" OVERLAY="${d}/overlay" \
        LOGDIR="${d}/logs" STAGE="${d}/stage" LOCK="${d}/lock" \
        ALERT_LOG="${d}/alert.log" bash build/cycle.sh 2>&1)
    rc=$?
    set -e
    [[ ${orphan} == yes ]] && sleep 0.6
    # 2>/dev/null goes before the input redirection: the shell reports a missing
    # file itself, and by then its own stderr must already be discarded.
    printf '%s|%s|%s|%s|%s\n' \
        "$(cat 2>/dev/null "${d}/late.log")" \
        "${rc}" \
        "$(tr '\n' ' ' 2>/dev/null < "${d}/alert.log")" \
        "$(tr '\n' ' ' 2>/dev/null < "${d}/progress.log")" \
        "${out}"
    rm -rf "${d}"
}

echo "== cycle.sh 区分发布与清理失败"

IFS='|' read -r late rc message progress out <<< "$(cycle_probe 3 no)"
ok "发布后清理受阻时保留退出码 3" "${rc}" "3"
ok "退出码 3 的通知说明索引已经发布" \
   "$([[ ${message} == *已发布到镜像机* ]] && echo yes)" "yes"
ok "退出码 3 的通知不会声称未发布" \
   "$([[ ${message} != *未发布到镜像机* ]] && echo yes)" "yes"

IFS='|' read -r late rc message progress out <<< "$(cycle_probe 1 yes)"
ok "发布失败时保留原退出码" "${rc}" "1"
ok "发布失败时明确说明未发布" \
   "$([[ ${message} == *未发布到镜像机* ]] && echo yes)" "yes"
ok "目标软件包失败摘要会附在发布告警中" \
   "$([[ ${message} == *构建失败*app-misc/example* ]] && echo yes)" "yes"

IFS='|' read -r late rc message progress out <<< "$(cycle_probe 0 no yes)"
ok "冒烟测试告警不改变成功退出码" "${rc}" "0"
ok "安装失败进入既有告警路径" \
   "$([[ ${message} == *gpkg*安装冒烟测试*安装失败* ]] && echo yes)" "yes"

echo "== 进度回报不左右这一轮的成败"

# The publish succeeded on 2026-08-12 and the run still reported failure: the
# final progress push lost a race, and set -e inside the EXIT trap turned that
# into the service exit code.
IFS='|' read -r late rc message progress out <<< "$(cycle_probe 0 no no 1)"
ok "回报推送失败不改变成功退出码" "${rc}" "0"
ok "回报推送失败不产生告警" "${message}" ""
ok "仍然尝试写出结束状态" \
   "$([[ ${progress} == *"finish OUT="* ]] && echo yes)" "yes"

IFS='|' read -r late rc message progress out <<< "$(cycle_probe 0 no)"
ok "成功时结束状态是 done" \
   "$([[ ${out} == *"finish"* || ${progress} == *"finish OUT="* ]] && echo yes)" "yes"
ok "看守进程拿得到本频道的输出档名" \
   "$([[ ${progress} == *"watch OUT=build-status.json"* ]] && echo yes)" "yes"

CHANNEL=unstable
export CHANNEL
IFS='|' read -r late rc message progress out <<< "$(cycle_probe 0 no)"
unset CHANNEL
ok "unstable 的看守进程写的是 unstable 的档名" \
   "$([[ ${progress} == *"watch OUT=build-status-unstable.json"* ]] && echo yes)" "yes"

# A plain kill fells the watcher and leaves its ssh running, which then lands a
# running snapshot on top of the final state.
IFS='|' read -r late rc message progress out <<< "$(cycle_probe 0 no no 0 yes)"
ok "看守进程留下的子进程一并收掉" "${late}" ""

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
