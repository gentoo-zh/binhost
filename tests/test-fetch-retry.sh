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

# Portage gives up on a fetch after three attempts within seconds. One brief
# upstream outage then leaves the index short, and the version check refuses to
# publish the whole channel. The retry block is cut out of build-container.sh
# and driven against stubs so the assertions bind to the deployed file.
extract() {
    sed -n '/^    # Portage gives up after three attempts/,/^    fi$/p' \
        "${ROOT}/build/build-container.sh"
}

probe() {
    local mode="$1" d
    d=$(mktemp -d)
    mkdir -p "${d}/log"

    # The first attempt already happened before the block runs; failed.txt below
    # stands in for it. So this stub answers the retry attempt only.
    cat > "${d}/emerge" <<EOF
#!/bin/bash
echo "\$*" >> "${d}/calls"
if [ "${mode}" = recovers ]; then
    echo "success"
    exit 0
fi
echo "Connecting to example.invalid|1.2.3.4|:443... connected."
echo "HTTP request sent, awaiting response... No data received."
echo "!!! Couldn't download 'thing.tar.gz'. Aborting."
exit 1
EOF
    chmod +x "${d}/emerge"

    {
        printf 'set -uo pipefail\n'
        printf 'EMERGE=("%s/emerge")\n' "${d}"
        printf 'FETCH_RETRY_WAIT=0\n'
        printf 'failed=(net-misc/one net-misc/two)\n'
        printf 'mkdir -p /var/log/binhost 2>/dev/null || true\n'
        extract
        cat <<'TAIL'

printf '%s\n' ${failed[@]+"${failed[@]}"} > "${AFTER}"
TAIL
    } > "${d}/probe.sh"

    # /var/log/binhost is the hardcoded path in the block; give the probe its own.
    sed -i "s|/var/log/binhost|${d}/log|g" "${d}/probe.sh"

    printf 'net-misc/one\nnet-misc/two\n' > "${d}/log/failed.txt"
    for a in one two; do
        printf "Connecting to host... connected.\nHTTP request sent, awaiting response... No data received.\n!!! Couldn't download 'x.tar.gz'. Aborting.\n" \
            > "${d}/log/net-misc_${a}.log"
    done

    AFTER="${d}/after" bash "${d}/probe.sh" > "${d}/out" 2>&1
    printf '%s|%s|%s|%s\n' \
        "$(tr -d ' \n' < "${d}/log/failed.txt" 2>/dev/null)" \
        "$(tr -d ' \n' < "${d}/after" 2>/dev/null)" \
        "$(grep -c '重试成功' "${d}/out")" \
        "$(wc -l < "${d}/calls" 2>/dev/null || echo 0)"
    rm -rf "${d}"
}

echo "== 上游恢复时重试会移除失败记录"
IFS='|' read -r left arr recovered calls <<< "$(probe recovers)"
ok "两个都真的重新执行了 emerge" "${calls}" "2"
ok "failed.txt 清空" "${left}" ""
ok "failed 数组也清空" "${arr}" ""
ok "两个都报了重试成功" "${recovered}" "2"

echo
echo "== 上游仍然不通时保持失败"
IFS='|' read -r left arr recovered calls <<< "$(probe stays-down)"
ok "仍然重新执行了 emerge" "${calls}" "2"
ok "failed.txt 两个都保留" "${left}" "net-misc/onenet-misc/two"
ok "failed 数组两个都保留" "${arr}" "net-misc/onenet-misc/two"
ok "没有谎报重试成功" "${recovered}" "0"

echo
# The pattern names a shell variable, so the dollar sign is injected instead
# of being written inside single quotes.
d1='$'
echo "== build-container.sh 按这个形状使用它"
ok "等待秒数可覆盖" \
   "$(grep -c '^FETCH_RETRY_WAIT=' "${ROOT}/build/build-container.sh")" "1"
ok "只重试取源失败的包" \
   "$(grep -c "grep -qE \"Unable to fetch|Couldn't download\"" \
      "${ROOT}/build/build-container.sh")" "1"
ok "重试只做一轮" \
   "$(grep -c "等待 ${d1}{FETCH_RETRY_WAIT} 秒后重试一次" \
      "${ROOT}/build/build-container.sh")" "1"

echo
if (( fail )); then
    echo ">>> ${fail} 项未通过，${pass} 项通过"
    exit 1
fi
echo ">>> ${pass} 项全部通过"
