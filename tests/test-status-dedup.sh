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

setup() {
    local d
    d=$(mktemp -d)
    mkdir -p "${d}/bin"
    cat > "${d}/bin/curl" <<EOF
#!/bin/bash
body=""
for a in "\$@"; do
    [ "\$a" = "--config" ] && { body=\$(cat); break; }
done
for a in "\$@" "\${body}"; do
    case "\$a" in
        *api.telegram.org*) echo CALL >> "${d}/sent.log"; exit 0 ;;
    esac
done
exit 22
EOF
    cat > "${d}/bin/sudo" <<'EOF'
#!/bin/bash
exit 1
EOF
    cat > "${d}/bin/openssl" <<'EOF'
#!/bin/bash
exit 1
EOF
    chmod +x "${d}/bin/curl" "${d}/bin/sudo" "${d}/bin/openssl"
    printf 'TELEGRAM_TOKEN=t\nTELEGRAM_CHAT=c\n' > "${d}/alert.conf"
    echo "${d}"
}

rc=0
run() {
    local d="$1"
    ( cd "${ROOT}" && PATH="${d}/bin:${PATH}" \
        BINHOST_ALERT=1 ALERT_CONF="${d}/alert.conf" \
        STATE_FILE="${d}/state" VERSION_FILE="${d}/VERSION" \
        SIGNING_GNUPGHOME="${d}/nokey" DISK_PATH="${d}/nodisk" \
        HEARTBEAT="${d}/nowhere/.health" SITE_WORK="${d}/nowork" \
        SITE_DEST="${d}/nodest" MONITORS_FILE="${d}/nomon" \
        bash ops/status.sh >/dev/null 2>&1 )
    rc=$?
}

sent_count() { wc -l < "$1/sent.log" 2>/dev/null || echo 0; }

echo "== 相同故障不重复通知"
d=$(setup)
echo aaaaaaaa > "${d}/VERSION"
run "${d}"
ok "第一次发出通知" "$(sent_count "${d}")" "1"
ok "第一次退出码表示已自行告警" "${rc}" "10"
run "${d}"
ok "第二次同样的故障不再发" "$(sent_count "${d}")" "1"
ok "第二次退出码表示已被冷却抑制" "${rc}" "11"
run "${d}"
ok "第三次仍然不发" "$(sent_count "${d}")" "1"
ok "第三次退出码仍是抑制" "${rc}" "11"
ok "状态档已写入" "$(test -s "${d}/state" && echo 有 || echo 无)" "有"

echo
echo "== 冷却期到了会提醒一次"
printf '%s %s\n' "$(cut -d' ' -f1 < "${d}/state")" "$(( $(date +%s) - 25 * 3600 ))" > "${d}/state"
run "${d}"
ok "超过 24 小时后再发一次" "$(sent_count "${d}")" "2"
run "${d}"
ok "刚发过之后又静下来" "$(sent_count "${d}")" "2"
rm -rf "${d}"

echo
echo "== 故障内容改变时立刻发新的"
d=$(setup)
echo aaaaaaaa > "${d}/VERSION"
run "${d}"
ok "第一次发出通知" "$(sent_count "${d}")" "1"
printf 'deadbeef 0\n' > "${d}/state"
run "${d}"
ok "指纹不同就发新的一条" "$(sent_count "${d}")" "2"
rm -rf "${d}"

echo
echo "== 状态档损坏时不静默"
d=$(setup)
echo aaaaaaaa > "${d}/VERSION"
printf 'not-a-fingerprint\n' > "${d}/state"
run "${d}"
ok "时间戳无法解析时仍会发" "$(sent_count "${d}")" "1"
rm -rf "${d}"

echo
echo "== 发送失败与被抑制必须区分开"
d=$(setup)
echo aaaaaaaa > "${d}/VERSION"
cat > "${d}/bin/curl" <<'EOF'
#!/bin/bash
exit 7
EOF
chmod +x "${d}/bin/curl"
run "${d}"
ok "发送失败时退出码不是抑制码" "${rc}" "1"
ok "发送失败时不记录已通知" "$(test -s "${d}/state" && echo 有 || echo 无)" "无"
rm -rf "${d}"

echo
echo "== 手动执行不得污染定时任务的去重状态"
d=$(setup)
echo aaaaaaaa > "${d}/VERSION"
( cd "${ROOT}" && PATH="${d}/bin:${PATH}" \
    ALERT_CONF="${d}/alert.conf" STATE_FILE="${d}/state" \
    VERSION_FILE="${d}/VERSION" SIGNING_GNUPGHOME="${d}/nokey" \
    DISK_PATH="${d}/nodisk" HEARTBEAT="${d}/nowhere/.health" \
    SITE_WORK="${d}/nowork" SITE_DEST="${d}/nodest" \
    MONITORS_FILE="${d}/nomon" bash ops/status.sh >/dev/null 2>&1 )
ok "没有 BINHOST_ALERT 时不写状态" "$(test -s "${d}/state" && echo 有 || echo 无)" "无"
run "${d}"
ok "随后的定时执行仍会正常发出" "$(sent_count "${d}")" "1"
rm -rf "${d}"

echo
echo "== systemd 备援通道按退出码决定发不发"
fallback() {
    local d="$1" code="$2"
    cat > "${d}/bin/systemctl" <<EOF
#!/bin/bash
case "\$4" in Result) echo failed;; ExecMainStatus) echo ${code};; *) echo;; esac
EOF
    chmod +x "${d}/bin/systemctl"
    : > "${d}/sent.log"
    PATH="${d}/bin:${PATH}" ALERT_CONF="${d}/alert.conf" \
        bash "${ROOT}/ops/alert-failed.sh" binhost-status.service >/dev/null 2>&1
    sent_count "${d}"
}
d=$(setup)
ok "已自行告警（10）时略过重复告警" "$(fallback "${d}" 10)" "0"
ok "冷却期内被抑制（11）时同样略过" "$(fallback "${d}" 11)" "0"
ok "发送失败（1）仍要备援发出" "$(fallback "${d}" 1)" "1"
ok "脚本异常（2）仍要备援发出" "$(fallback "${d}" 2)" "1"
rm -rf "${d}"

echo
if (( fail )); then
    echo ">>> ${fail} 项未通过，${pass} 项通过"
    exit 1
fi
echo ">>> ${pass} 项全部通过"
