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
for a in "\$@"; do
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

run() {
    local d="$1"
    ( cd "${ROOT}" && PATH="${d}/bin:${PATH}" \
        BINHOST_ALERT=1 ALERT_CONF="${d}/alert.conf" \
        STATE_FILE="${d}/state" VERSION_FILE="${d}/VERSION" \
        SIGNING_GNUPGHOME="${d}/nokey" DISK_PATH="${d}/nodisk" \
        HEARTBEAT="${d}/nowhere/.health" SITE_WORK="${d}/nowork" \
        SITE_DEST="${d}/nodest" MONITORS_FILE="${d}/nomon" \
        bash build/status.sh >/dev/null 2>&1 )
}

sent_count() { wc -l < "$1/sent.log" 2>/dev/null || echo 0; }

echo "== 相同故障不重复通知"
d=$(setup)
echo aaaaaaaa > "${d}/VERSION"
run "${d}"
ok "第一轮发出通知" "$(sent_count "${d}")" "1"
run "${d}"
ok "第二轮同样的故障不再发" "$(sent_count "${d}")" "1"
run "${d}"
ok "第三轮仍然不发" "$(sent_count "${d}")" "1"
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
ok "第一轮发出通知" "$(sent_count "${d}")" "1"
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
ok "读不出时间戳仍会发" "$(sent_count "${d}")" "1"
rm -rf "${d}"

echo
if (( fail )); then
    echo ">>> ${fail} 项未通过，${pass} 项通过"
    exit 1
fi
echo ">>> ${pass} 项全部通过"
