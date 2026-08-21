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

# The five-minute site sync and this check start in the same cron minute, so a
# check that tests the lock and then reads can be reading while the sync
# rewrites the tree. The tree below is left unreadable on purpose: only a
# reader that ignored the lock gets far enough to report on it.
probe() {
    local hold="$1" d out
    d=$(mktemp -d)
    mkdir -p "${d}/bin" "${d}/work/.git" "${d}/work/site/assets" "${d}/dest/assets"
    : > "${d}/work/.git/FETCH_HEAD"
    printf 'ref: refs/heads/nowhere\n' > "${d}/work/.git/HEAD"
    : > "${d}/dest/gentoo-zh-binhost.asc"
    : > "${d}/work/site/gentoo-zh-binhost.asc"
    for stub in curl sudo openssl; do
        printf '#!/bin/bash\nexit 1\n' > "${d}/bin/${stub}"
        chmod +x "${d}/bin/${stub}"
    done

    if [[ ${hold} == held ]]; then
        flock "${d}/work.lock" sleep 30 &
        local holder=$!
        sleep 0.4
    fi

    out=$( cd "${ROOT}" && PATH="${d}/bin:${PATH}" \
        STATE_FILE="${d}/state" VERSION_FILE="${d}/VERSION" \
        SIGNING_GNUPGHOME="${d}/nokey" DISK_PATH="${d}/nodisk" \
        HEARTBEAT="${d}/nowhere/.health" MONITORS_FILE="${d}/nomon" \
        SITE_WORK="${d}/work" SITE_DEST="${d}/dest" \
        bash ops/status.sh 2>&1 | grep -E '站点同步' | head -1 )

    [[ ${hold} == held ]] && { kill "${holder}" 2>/dev/null; wait "${holder}" 2>/dev/null; }
    printf '%s\n' "${out}"
    rm -rf "${d}"
}

echo "== 站点同步检查与五分钟同步抢同一把锁"

held=$(probe held)
ok "锁被占住时报同步进行中" \
   "$([[ ${held} == *同步正在执行* ]] && echo yes)" "yes"
ok "锁被占住时不读取仓库，也就不会报无法解析" \
   "$([[ ${held} != *无法解析* ]] && echo yes)" "yes"

free=$(probe free)
ok "锁空闲时才真的读取" \
   "$([[ ${free} == *无法解析* ]] && echo yes)" "yes"

echo
if (( fail )); then
    echo ">>> ${fail} 项未通过，${pass} 项通过"
    exit 1
fi
echo ">>> ${pass} 项全部通过"
