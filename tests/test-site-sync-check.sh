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
    mkdir -p "${d}/bin" "${d}/work/site/assets" "${d}/dest/assets"

    cat > "${d}/bin/curl" <<'EOF'
#!/bin/bash
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
    cat > "${d}/bin/git" <<EOF
#!/bin/bash
for a in "\$@"; do
    [ "\$a" = rev-parse ] && echo rev-parse >> "${d}/git.log"
done
exec /usr/bin/git "\$@"
EOF
    chmod +x "${d}/bin"/*

    /usr/bin/git init -q "${d}/work"
    /usr/bin/git -C "${d}/work" -c user.email=t@t -c user.name=t \
        commit -q --allow-empty -m t
    touch "${d}/work/.git/FETCH_HEAD"

    printf 'x\n' > "${d}/work/site/index.html"
    printf 'x\n' > "${d}/dest/index.html"
    printf 'k\n' > "${d}/work/site/gentoo-zh-binhost.asc"
    printf 'k\n' > "${d}/dest/gentoo-zh-binhost.asc"
    /usr/bin/git -C "${d}/work" rev-parse HEAD > "${d}/work/.synced"
    echo "${d}"
}

run() {
    local d="$1"
    ( cd "${ROOT}" && PATH="${d}/bin:${PATH}" \
        STATE_FILE="${d}/state" VERSION_FILE="${d}/VERSION" \
        SIGNING_GNUPGHOME="${d}/nokey" DISK_PATH="${d}/nodisk" \
        HEARTBEAT="${d}/nowhere/.health" MONITORS_FILE="${d}/nomon" \
        SITE_WORK="${d}/work" SITE_DEST="${d}/dest" \
        SITE_LOCK="${d}/work.lock" \
        bash ops/status.sh 2>&1 )
}

line() { grep '站点同步' <<< "$1" | head -1; }

echo "== 一致时不报站点同步"
d=$(setup)
out=$(run "${d}")
ok "一致时不是故障" "$([[ $(line "${out}") != *'!'* ]] && echo yes)" "yes"
rm -rf "${d}"

echo
echo "== 同步进行中不读取仓库副本"
d=$(setup)
: > "${d}/work.lock"
exec {fd}>"${d}/work.lock"
flock -n "${fd}"
out=$(run "${d}")
exec {fd}>&-
ok "说明同步正在执行" \
   "$([[ $(line "${out}") == *同步正在执行* ]] && echo yes)" "yes"
ok "锁被持有时一次 rev-parse 都不执行" \
   "$( [ -s "${d}/git.log" ] && wc -l < "${d}/git.log" || echo 0 )" "0"
rm -rf "${d}"

echo
echo "== 版本无法解析时如实说明，不说版本不一致"
# Two ways it goes wrong: rev-parse echoes the literal HEAD for a dangling
# ref, and prints nothing at all when the copy is not a repository.
d=$(setup)
printf 'ref: refs/heads/nowhere\n' > "${d}/work/.git/HEAD"
out=$(run "${d}")
ok "悬空 ref 时指出无法解析版本" \
   "$([[ $(line "${out}") == *无法解析* ]] && echo yes)" "yes"
ok "悬空 ref 时不谎称最近一次未完成" \
   "$([[ $(line "${out}") != *最近一次未完成* ]] && echo yes)" "yes"
rm -rf "${d}"

d=$(setup)
rm -f "${d}/work/.git/HEAD"
out=$(run "${d}")
ok "无输出时指出无法解析版本" \
   "$([[ $(line "${out}") == *无法解析* ]] && echo yes)" "yes"
rm -rf "${d}"

echo
if (( fail )); then
    echo ">>> ${fail} 项未通过，${pass} 项通过"
    exit 1
fi
echo ">>> ${pass} 项全部通过"
