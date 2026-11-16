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

contains() {
    if [[ $2 == *"$3"* ]]; then
        printf '  ✓ %s\n' "$1"
        pass=$((pass + 1))
    else
        printf '  ✗ %s\n      输出中未包含 %s\n' "$1" "$3"
        fail=$((fail + 1))
    fi
}

echo "== 两条发布路径确实执行同一支 publish-site.sh"

site_sync_calls() {
    local d args rc
    d=$(mktemp -d)
    printf '#!/bin/bash\nprintf "%%s\\n" "$@" > "%s/args"\nexit %s\n' "${d}" "$1" \
        > "${d}/pub"
    chmod +x "${d}/pub"
    git init -q -b master "${d}/repo"
    mkdir -p "${d}/repo/site" "${d}/dest"
    printf 'KEY\n' > "${d}/repo/site/gentoo-zh-binhost.asc"
    ( cd "${d}/repo" && git add -A &&
      git -c user.email=t@t -c user.name=t commit -q -m x )
    PUBLISH="${d}/pub" WORK="${d}/work" DEST="${d}/dest" REPO="${d}/repo" \
        DONE="${d}/done" LOCK="${d}/lock" \
        bash "${ROOT}/deploy/site-sync.sh" >/dev/null 2>&1
    rc=$?
    args=$(tr '\n' ' ' < "${d}/args" 2>/dev/null)
    printf '%s|%s|%s\n' "${rc}" "${args}" \
        "$(test -e "${d}/done" && echo recorded || echo missing)"
    rm -rf "${d}"
}

IFS='|' read -r rc args done_state <<< "$(site_sync_calls 0)"
ok "site-sync 真的执行了 publisher" "$(grep -c '/site' <<< "${args}")" "1"
ok "并且把来源与目标一起传进去" "$(grep -c 'dest' <<< "${args}")" "1"
ok "publisher 成功时记下已完成" "${done_state}" "recorded"

IFS='|' read -r rc args done_state <<< "$(site_sync_calls 7)"
ok "publisher 失败时 site-sync 也失败" "$((rc != 0))" "1"
ok "publisher 失败时不记已完成" "${done_state}" "missing"

deploy_site_cmd() {
    local d
    d=$(mktemp -d); mkdir -p "${d}/bin"
    cat > "${d}/bin/ssh" <<EOF
#!/bin/bash
for a in "\$@"; do last="\$a"; done
case "\${last}" in
  *mktemp*) echo /tmp/stage ;;
  *publish-site*) printf '%s\n' "\${last}" >> "${d}/cmds" ;;
  *) : ;;
esac
EOF
    printf '#!/bin/bash\nexit 0\n' > "${d}/bin/rsync"
    chmod +x "${d}/bin/ssh" "${d}/bin/rsync"
    ( cd "${ROOT}" && PATH="${d}/bin:${PATH}" bash deploy-site.sh >/dev/null 2>&1 )
    cat "${d}/cmds" 2>/dev/null
    rm -rf "${d}"
}

cmd=$(deploy_site_cmd)
ok "deploy-site 真的调用了 publisher" \
   "$(grep -c '/usr/local/lib/binhost/publish-site.sh' <<< "${cmd}")" "1"
ok "并且传的是暂存目录与发布目录" "$(grep -c '/tmp/stage /srv/mirrors' <<< "${cmd}")" "1"
ok "调用包在站点锁里" "$(grep -c 'flock' <<< "${cmd}")" "1"

echo
echo "== publish-site.sh 本身"

pubsite() {
    local d src dest f
    d=$(mktemp -d)
    src="${d}/site"; dest="${d}/dest"
    mkdir -p "${src}/assets" "${dest}"
    printf 'KEY\n' > "${src}/gentoo-zh-binhost.asc"
    printf '<p>new</p>\n' > "${src}/index.html"
    printf 'css\n' > "${src}/assets/site.css"
    printf 'AAAA\n' > "${src}/robots.txt"
    printf 'BBBB\n' > "${dest}/robots.txt"
    touch -d '2026-01-01 00:00:00' "${src}/robots.txt" "${dest}/robots.txt"
    # The daily jobs write these next to the site files.
    for f in packages.json packages.txt packages-unstable.json packages-unstable.txt \
        deps.txt deps-unstable.txt distfiles-index.json distfiles-status.json .health; do
        printf 'data\n' > "${dest}/${f}"
    done
    mkdir -p "${dest}/binpkgs/x86-64" "${dest}/distfiles/ab"
    printf 'pkg\n' > "${dest}/binpkgs/x86-64/a.gpkg.tar"
    printf 'idx\n' > "${dest}/binpkgs/x86-64/Packages"
    printf 'src\n' > "${dest}/distfiles/ab/a.tar.gz"
    mkdir -p "${d}/bin"
    cat > "${d}/bin/gpg" <<'EOF'
#!/bin/bash
printf 'pub:u:255:22::::::::scSC:\nfpr:::::::::AAAA0000000000000000000000000000000000AA:\n'
EOF
    chmod +x "${d}/bin/gpg"
    echo AAAA0000000000000000000000000000000000AA > "${d}/fpr"
    PATH="${d}/bin:${PATH}" FPR_FILE="${d}/fpr" \
        bash "${ROOT}/deploy/publish-site.sh" "${src}" "${dest}" >/dev/null 2>&1
    printf '%s %s %s %s %s\n' \
        "$(test -e "${dest}/gentoo-zh-binhost.asc" && echo asc || echo noasc)" \
        "$(tr -d '\n' < "${dest}/robots.txt" 2>/dev/null)" \
        "$(find "${dest}" -maxdepth 1 \( -name '*.html' -o -name assets \) | wc -l)" \
        "$(cat "${dest}"/packages* "${dest}"/deps* "${dest}"/distfiles-* "${dest}/.health" \
            2>/dev/null | grep -c '^data$')" \
        "$(find "${dest}/binpkgs" "${dest}/distfiles" -type f 2>/dev/null | wc -l)"
    rm -rf "${d}"
}
read -r a b c dd ee <<< "$(pubsite)"
ok "公钥会发布" "${a}" "asc"
ok "robots.txt 同大小同 mtime 但内容不同时仍然更新" "${b}" "AAAA"
ok "来源中的页面与 assets 不再发布" "${c}" "0"
ok "每日任务的数据档一个不少" "${dd}" "9"
ok "已发布的包与 distfiles 不受删除影响" "${ee}" "3"

pubsite_interrupted() {
    local d rc
    d=$(mktemp -d)
    mkdir -p "${d}/site" "${d}/dest" "${d}/bin"
    printf 'fresh\n' > "${d}/site/gentoo-zh-binhost.asc"
    printf 'old\n' > "${d}/dest/gentoo-zh-binhost.asc"
    cat > "${d}/bin/gpg" <<'EOF'
#!/bin/bash
printf 'pub:u:255:22::::::::scSC:\nfpr:::::::::AAAA0000000000000000000000000000000000AA:\n'
EOF
    # A transfer that dies part way leaves an incomplete generation directory.
    # Nothing published may change, because the switch never happens.
    cat > "${d}/bin/rsync" <<EOF
#!/bin/bash
for a in "\$@"; do dest="\$a"; done
mkdir -p "\${dest}"
printf 'half\n' > "\${dest}/gentoo-zh-binhost.asc"
exit 23
EOF
    chmod +x "${d}/bin/gpg" "${d}/bin/rsync"
    echo AAAA0000000000000000000000000000000000AA > "${d}/fpr"
    PATH="${d}/bin:${PATH}" FPR_FILE="${d}/fpr" \
        bash "${ROOT}/deploy/publish-site.sh" "${d}/site" "${d}/dest" \
        >/dev/null 2>&1
    rc=$?
    printf '%s %s %s %s\n' "${rc}" \
        "$(tr -d '\n' < "${d}/dest/gentoo-zh-binhost.asc" 2>/dev/null)" \
        "$(readlink "${d}/dest/.site" | grep -c seed)" \
        "$(grep -q half "${d}/dest/gentoo-zh-binhost.asc" && echo 上线 || echo 没上线)"
    rm -rf "${d}"
}

read -r rc old_state on_seed half <<< "$(pubsite_interrupted)"
ok "站点传输中断时退出码非零" "$((rc != 0))" "1"
ok "站点传输中断时已发布的内容不变" "${old_state}" "old"
ok "站点传输中断时读的是转换前那一份" "${on_seed}" "1"
ok "半份产物不会上线" "${half}" "没上线"

echo "== daily.sh 的包列表与索引验证"

audit_line=$(grep -n 'step "distfiles 对账"' "${ROOT}/deploy/daily.sh" | cut -d: -f1)
index_line=$(grep -n 'step "distfiles 索引"' "${ROOT}/deploy/daily.sh" | cut -d: -f1)
packages_line=$(grep -n 'step "stable 包列表"' "${ROOT}/deploy/daily.sh" | cut -d: -f1)
ok "distfiles 回收完成后才重建公开索引" "$((audit_line < index_line))" "1"
ok "包列表使用回收后的 distfiles 索引" "$((index_line < packages_line))" "1"
ok "每日任务分别生成两个频道的包列表" \
   "$(grep -c 'gen-packages.py' "${ROOT}/deploy/daily.sh")" "2"
ok "每日任务为 stable 生成独立的纯文本清单" \
   "$(grep -c 'PACKAGE_TEXT=/srv/mirrors/packages.txt' "${ROOT}/deploy/daily.sh")" "1"
ok "每日任务为 stable 生成独立的依赖清单" \
   "$(grep -c 'DEPS_TEXT=/srv/mirrors/deps.txt' "${ROOT}/deploy/daily.sh")" "1"
ok "unstable 网页数据使用独立输出" \
   "$(grep -c 'OUT=/srv/mirrors/packages-unstable.json' "${ROOT}/deploy/daily.sh")" "1"

daily_list_probe() {
    local mode=$1 d
    d=$(mktemp -d)
    sed -n '/^if step "distfiles 同步"/,/^verify_channel()/p' "${ROOT}/deploy/daily.sh" |
        sed '$d' > "${d}/block.sh"
    (
        # shellcheck disable=SC2317,SC2329  # The sourced block invokes this function.
        step() {
            printf '%s\n' "$1"
            [[ $1 != "distfiles 同步" || ${mode} != failed ]]
        }
        # shellcheck disable=SC1091  # block.sh is generated above.
        LIB="${d}" OVERLAY="${d}/overlay" DISTDIR="${d}/distfiles" \
            . "${d}/block.sh"
    )
    rm -rf "${d}"
}

mapfile -t calls < <(daily_list_probe failed)
ok "distfiles 同步失败时仍刷新两个频道的包列表" \
   "${calls[*]}" "distfiles 同步 stable 包列表 unstable 包列表"

mapfile -t calls < <(daily_list_probe success)
ok "distfiles 同步成功时先对账并重建索引" \
   "${calls[*]}" \
   "distfiles 同步 distfiles 对账 distfiles 索引 stable 包列表 unstable 包列表"

daily_channel_probe() {
    local d
    d=$(mktemp -d)
    cat > "${d}/gen-packages.py" <<'PY'
import os

print(f'{os.environ["OUT"]}|{os.environ["INDEX"]}')
PY
    sed -n '/^step "stable 包列表"/,/^$/p' "${ROOT}/deploy/daily.sh" > "${d}/block.sh"
    (
        # shellcheck disable=SC2317,SC2329  # The sourced block invokes this function.
        step() {
            shift
            "$@"
        }
        # shellcheck disable=SC1091  # block.sh is generated above.
        LIB="${d}" OVERLAY="${d}/overlay" . "${d}/block.sh"
    )
    rm -rf "${d}"
}

mapfile -t channel_inputs < <(daily_channel_probe)
ok "stable 包列表实际读取 stable 索引" "${channel_inputs[0]}" \
   "/srv/mirrors/packages.json|/srv/pub/binpkgs/x86-64/Packages"
ok "unstable 包列表实际读取 unstable 索引" "${channel_inputs[1]}" \
   "/srv/mirrors/packages-unstable.json|/srv/pub/unstable/binpkgs/x86-64/Packages"

daily_lists_probe() {
    local mode=$1 d f
    d=$(mktemp -d)
    mkdir -p "${d}/site/build" "${d}/lib"
    for f in packages.txt excluded.txt stable-excluded.txt; do
        printf 'master/%s\n' "${f}" > "${d}/site/build/${f}"
        printf 'old/%s\n' "${f}" > "${d}/lib/${f}"
    done
    [[ ${mode} == missing ]] && rm "${d}/site/build/stable-excluded.txt"
    git -C "${d}/site" init -q
    git -C "${d}/site" add -A
    git -C "${d}/site" -c user.name=t -c user.email=t@t commit -qm t
    # The working tree is not what the mirror reads; only the commit counts.
    printf 'uncommitted\n' > "${d}/site/build/packages.txt"
    sed -n '/^refresh_lists() {/,/^}/p' "${ROOT}/deploy/daily.sh" > "${d}/fn.sh"
    (
        # shellcheck disable=SC1091  # fn.sh is generated above.
        . "${d}/fn.sh"
        LIB="${d}/lib" SITE_WORK="${d}/site" refresh_lists 2>/dev/null
        echo "rc=$?"
    )
    cat "${d}/lib/packages.txt" "${d}/lib/excluded.txt" "${d}/lib/stable-excluded.txt"
    find "${d}/lib" -name '*.new' -printf 'left %f\n'
    rm -rf "${d}"
}

ok "每日任务从站点 checkout 的提交更新三份包清单" "$(daily_lists_probe ok | tr '\n' ' ')" \
   "rc=0 master/packages.txt master/excluded.txt master/stable-excluded.txt "
ok "缺一份清单时整组不换，也不留下 .new" "$(daily_lists_probe missing | tr '\n' ' ')" \
   "rc=1 old/packages.txt old/excluded.txt old/stable-excluded.txt "
daily_gentoo_probe() {
    local mode=$1 d
    d=$(mktemp -d)
    mkdir -p "${d}/gentoo/metadata" "${d}/bin"
    cat > "${d}/bin/emaint" <<EOF
#!/bin/bash
echo "\$*" >> "${d}/calls"
date -u > "${d}/gentoo/metadata/timestamp.chk"
exit \${EMAINT_RC:-0}
EOF
    chmod +x "${d}/bin/emaint"
    case ${mode} in
        fresh) touch "${d}/gentoo/metadata/timestamp.chk" ;;
        stale|failed) touch -d '-2 days' "${d}/gentoo/metadata/timestamp.chk" ;;
    esac
    sed -n '/^refresh_gentoo() {/,/^}/p' "${ROOT}/deploy/daily.sh" > "${d}/fn.sh"
    (
        # shellcheck disable=SC1091  # fn.sh is generated above.
        . "${d}/fn.sh"
        [[ ${mode} == failed ]] && export EMAINT_RC=1
        PATH="${d}/bin:${PATH}" GENTOO="${d}/gentoo" refresh_gentoo >/dev/null 2>&1
        echo "rc=$?"
    )
    cat "${d}/calls" 2>/dev/null || echo "no sync"
    rm -rf "${d}"
}

ok "::gentoo 不到 23 小时就不同步" "$(daily_gentoo_probe fresh | tr '\n' ' ')" "rc=0 no sync "
ok "::gentoo 过期就同步" "$(daily_gentoo_probe stale | tr '\n' ' ')" "rc=0 sync -r gentoo "
ok "没有 timestamp.chk 也同步" "$(daily_gentoo_probe missing | tr '\n' ' ')" "rc=0 sync -r gentoo "
ok "同步失败时步骤失败" "$(daily_gentoo_probe failed | tr '\n' ' ')" "rc=1 sync -r gentoo "
gentoo_line=$(grep -n '^step "gentoo 更新"' "${ROOT}/deploy/daily.sh" | cut -d: -f1)
overlay_line=$(grep -n '^if ! step "overlay 更新"' "${ROOT}/deploy/daily.sh" | cut -d: -f1)
ok "::gentoo 在 overlay 之前更新" "$(( ${gentoo_line:-999999} < ${overlay_line:-0} ))" "1"

lists_line=$(grep -n '^step "包清单更新"' "${ROOT}/deploy/daily.sh" | cut -d: -f1)
ok "包清单在两个频道生成之前更新" \
   "$(( ${lists_line:-999999} < ${packages_line:-0} ))" "1"

daily_index_probe() {
    local mode="$1" d out channel
    d=$(mktemp -d)
    for channel in stable unstable; do
        mkdir -p "${d}/${channel}/app-misc/a" "${d}/${channel}/app-misc/b"
        : > "${d}/${channel}/app-misc/a/a-1-1.gpkg.tar"
        : > "${d}/${channel}/app-misc/b/b-1-1.gpkg.tar"
        printf '%s\n' 'PACKAGES: 2' 'TIMESTAMP: 1' '' 'CPV: app-misc/a-1' \
            'PATH: app-misc/a/a-1-1.gpkg.tar' '' 'CPV: app-misc/b-1' \
            'PATH: app-misc/b/b-1-1.gpkg.tar' > "${d}/${channel}/Packages"
    done
    case ${mode} in
        stable-count) sed -i 's/^PACKAGES: 2$/PACKAGES: 3/' "${d}/stable/Packages" ;;
        stable-missing) rm "${d}/stable/app-misc/b/b-1-1.gpkg.tar" ;;
        stable-unparsable) printf 'garbage\n' > "${d}/stable/Packages" ;;
    esac
    # shellcheck disable=SC2016  # Match ${FAILURES} literally in the source.
    sed -n '/^verify_channel()/,/^if \[\[ -s \${FAILURES}/p' "${ROOT}/deploy/daily.sh" |
        sed '$d' > "${d}/block.sh"
    out=$(
        # shellcheck disable=SC2317,SC2329  # The sourced block invokes this function.
        step() {
            local name=$1; shift
            if "$@" >/dev/null 2>&1; then echo "${name}:ok"; else echo "${name}:failed"; fi
        }
        # shellcheck disable=SC1091  # block.sh is generated above.
        STABLE_BINPKGS="${d}/stable" UNSTABLE_BINPKGS="${d}/unstable" . "${d}/block.sh"
    )
    rm -rf "${d}"
    echo "${out//$'\n'/ }"
}

ok "两个频道的索引都通过验证" "$(daily_index_probe valid)" \
   "stable 索引验证:ok unstable 索引验证:ok"
ok "PACKAGES 与 PATH 条数不符时 stable 失败，unstable 照常验证" \
   "$(daily_index_probe stable-count)" "stable 索引验证:failed unstable 索引验证:ok"
ok "PATH 指向的文件不在本地时失败" \
   "$(daily_index_probe stable-missing)" "stable 索引验证:failed unstable 索引验证:ok"
ok "Packages 无法解析时失败" \
   "$(daily_index_probe stable-unparsable)" "stable 索引验证:failed unstable 索引验证:ok"

echo "== install-builder.sh 的定时器"

installer=$(<"${ROOT}/deploy/install-builder.sh")
ok "安装脚本停用旧构建机的内核与健康检查定时器" \
   "$(grep -c '^sudo systemctl disable --now binhost-kernel.timer binhost-status.timer$' <<< "${installer}")" "1"
ok "安装脚本不再在旧构建机启用任何定时器" \
   "$(grep -c '^sudo systemctl enable' <<< "${installer}")" "0"

echo "== 构建锁"

update_lock=$(sed -n 's/^LOCKFILE=//p' "${ROOT}/builders/binhost-update")
# shellcheck disable=SC2016  # we match the literal ${LOCK:-...}, not its value
archive_lock=$(sed -n 's/^LOCK="\${LOCK:-\(.*\)}"$/\1/p' "${ROOT}/build/kernel-archive.sh")
ok "内核归档与新构建机的频道更新共用构建锁" "${archive_lock:-无}" "${update_lock:-缺}"
# shellcheck disable=SC2016  # we match the literal ${BUILD_LOCK:-...}, not its value
status_lock=$(sed -n 's/^BUILD_LOCK="\${BUILD_LOCK:-\(.*\)}"$/\1/p' "${ROOT}/ops/status.sh")
ok "健康检查按新构建机的构建锁判断内核归档是否在执行" "${status_lock:-无}" "${update_lock:-缺}"

echo "== provision.sh 的主机密钥核对"

hostkey_probe() {
    local want="$1" d out
    d=$(mktemp -d); mkdir -p "${d}/bin"
    touch "${d}/pub"
    cat > "${d}/bin/ssh-keyscan" <<'EOF'
#!/bin/bash
echo "# probe:22 SSH-2.0-test"
echo "probe ssh-rsa AAAARSAKEY"
echo "# probe:22 SSH-2.0-test"
echo "probe ssh-ed25519 AAAAED25519KEY"
EOF
    cat > "${d}/bin/ssh-keygen" <<'EOF'
#!/bin/bash
if [ "$1" = "-F" ]; then exit 1; fi
line=$(cat)
case "${line}" in
  *AAAARSAKEY*)     echo "3072 SHA256:RSAFPR probe (RSA)" ;;
  *AAAAED25519KEY*) echo "256 SHA256:EDFPR probe (ED25519)" ;;
  *)                exit 1 ;;
esac
EOF
    printf '#!/bin/bash\nexit 0\n' > "${d}/bin/ssh"
    chmod +x "${d}/bin"/*
    ( cd "${ROOT}" && PATH="${d}/bin:${PATH}" KNOWN_HOSTS="${d}/kh" PUBKEY="${d}/pub" \
        HOST_KEY="${want}" TARGET=root@probe SSH_PORT=60001 \
        bash deploy/provision.sh >/dev/null 2>&1 ) || true
    out=$(awk '{print $1" "$2}' "${d}/kh" 2>/dev/null | tr '\n' ',')
    rm -rf "${d}"
    echo "${out}"
}

ok "只写通过核对的那一把，并附 [host]:port 形式" \
   "$(hostkey_probe SHA256:EDFPR)" \
   "probe ssh-ed25519,[probe]:60001 ssh-ed25519,"
ok "另一把算法即使扫到也不写入" \
   "$(hostkey_probe SHA256:RSAFPR)" \
   "probe ssh-rsa,[probe]:60001 ssh-rsa,"
ok "指纹均不匹配时不写 known_hosts" "$(hostkey_probe SHA256:NOMATCH)" ""

echo "== status.sh 的部署版本核对"

version_probe() {
    local ver="$1" sha_out="$2" compare_out="${3:-exit 22}" d out
    d=$(mktemp -d); mkdir -p "${d}/bin"
    cat > "${d}/bin/curl" <<EOF
#!/bin/bash
case "\$*" in
  *commits/master*) ${sha_out} ;;
  *compare/*) ${compare_out} ;;
esac
exit 22
EOF
    printf '#!/bin/bash\nexit 1\n' > "${d}/bin/sudo"
    printf '#!/bin/bash\nexit 1\n' > "${d}/bin/openssl"
    chmod +x "${d}/bin"/*
    printf '%s\n' "${ver}" > "${d}/VERSION"
    out=$( cd "${ROOT}" && PATH="${d}/bin:${PATH}" ALERT_CONF=/nonexistent \
        STATE_FILE="${d}/state" VERSION_FILE="${d}/VERSION" \
        SIGNING_GNUPGHOME="${d}/nokey" DISK_PATH="${d}/nodisk" \
        HEARTBEAT="${d}/nowhere/.health" SITE_WORK="${d}/nowork" \
        SITE_DEST="${d}/nodest" MONITORS_FILE="${d}/nomon" COMPONENT=mirror \
        bash ops/status.sh 2>&1 | grep '部署版本' )
    rm -rf "${d}"
    case "${out}" in *'<--'*) echo failed ;; *) echo passed ;; esac
}

SHA40=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
SAME='echo "  \"sha\": \"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\","'
NEW='echo "  \"sha\": \"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\","'
GENERATION_CHANGED='echo "      \"filename\": \"build/generation.py\","'
ok "VERSION 带 -dirty 时算故障" "$(version_probe "${SHA40}-dirty" 'exit 22')" "failed"
ok "VERSION 不是提交号时算故障" "$(version_probe not-a-sha 'exit 22')" "failed"
ok "无法获取目标版本时算故障，不再当成通过" "$(version_probe "${SHA40}" 'exit 22')" "failed"
ok "版本一致时才算通过" "$(version_probe "${SHA40}" "${SAME}")" "passed"
ok "只修改 generation.py 时镜像机仍判定部署落后" \
   "$(version_probe "${SHA40}" "${NEW}" "${GENERATION_CHANGED}")" "failed"

# The builder: its code trails master between runs by design, so only the installed unit files are compared
# with the checkout. mode: same (installed copy matches), differ, absent (unit not installed there).
builder_version_probe() {
    local ver="$1" mode="$2" d out
    d=$(mktemp -d); mkdir -p "${d}/bin" "${d}/repo/deploy/systemd" "${d}/units"
    cat > "${d}/bin/curl" <<EOF
#!/bin/bash
case "\$*" in
  *commits/master*) ${NEW} ;;
  *compare/*) ${GENERATION_CHANGED} ;;
esac
exit 22
EOF
    printf '#!/bin/bash\nexit 1\n' > "${d}/bin/sudo"
    printf '#!/bin/bash\nexit 1\n' > "${d}/bin/openssl"
    chmod +x "${d}/bin"/*
    printf '[Unit]\nDescription=a\n' > "${d}/repo/deploy/systemd/binhost-update@.service"
    printf '[Unit]\nDescription=old\n' > "${d}/repo/deploy/systemd/binhost-kernel.service"
    case ${mode} in
        same)   cp "${d}/repo/deploy/systemd/binhost-update@.service" "${d}/units/" ;;
        differ) printf '[Unit]\nDescription=b\n' > "${d}/units/binhost-update@.service" ;;
    esac
    [[ -n ${ver} ]] && printf '%s\n' "${ver}" > "${d}/VERSION"
    out=$( cd "${ROOT}" && PATH="${d}/bin:${PATH}" ALERT_CONF=/nonexistent \
        STATE_FILE="${d}/state" VERSION_FILE="${d}/VERSION" \
        SIGNING_GNUPGHOME="${d}/nokey" DISK_PATH="${d}/nodisk" \
        HEARTBEAT="${d}/nowhere/.health" SITE_WORK="${d}/nowork" \
        SITE_DEST="${d}/nodest" MONITORS_FILE="${d}/nomon" COMPONENT=builder \
        BUILDER_REPO="${d}/repo" UNIT_DIR="${d}/units" \
        bash ops/status.sh 2>&1 | grep '部署版本' )
    rm -rf "${d}"
    case "${out}" in *'<--'*) echo failed ;; *) echo passed ;; esac
}

ok "构建机代码落后 master、build 已变更时不算故障，下一轮构建会拉取" \
   "$(builder_version_probe "${SHA40}" same)" "passed"
ok "构建机已安装的单元文件与仓库不一致时算故障" "$(builder_version_probe "${SHA40}" differ)" "failed"
ok "构建机未安装的单元文件不参与比对" "$(builder_version_probe "${SHA40}" absent)" "passed"
ok "构建机缺少 VERSION 时算故障" "$(builder_version_probe "" same)" "failed"
ok "构建机 VERSION 不是提交号时算故障" "$(builder_version_probe not-a-sha same)" "failed"

d=$(mktemp -d); mkdir -p "${d}/bin" "${d}/gnupg"
# shellcheck disable=SC2016  # binhost-update carries the literal ${SIGNING_KEY:-...}
printf 'SIGNING_KEY=${SIGNING_KEY:-%s}\n' "${SHA40}" > "${d}/binhost-update"
printf '#!/bin/bash\nexec "$@"\n' > "${d}/bin/sudo"
printf '#!/bin/bash\necho "$*" > "%s/gpg.args"\necho sec:u:255:22:K:1:::u:::scESC:\n' \
    "${d}" > "${d}/bin/gpg"
printf '#!/bin/bash\nexit 22\n' > "${d}/bin/curl"
printf '#!/bin/bash\nexit 1\n' > "${d}/bin/openssl"
chmod +x "${d}/bin"/*
key_out=$( cd "${ROOT}" && env -u SIGNING_KEY PATH="${d}/bin:${PATH}" ALERT_CONF=/nonexistent \
    STATE_FILE="${d}/state" VERSION_FILE="${d}/VERSION" SIGNING_GNUPGHOME="${d}/gnupg" \
    BINHOST_UPDATE="${d}/binhost-update" DISK_PATH="${d}/nodisk" \
    HEARTBEAT="${d}/nowhere/.health" SITE_WORK="${d}/nowork" SITE_DEST="${d}/nodest" \
    MONITORS_FILE="${d}/nomon" COMPONENT=mirror bash ops/status.sh 2>&1 | grep '签名密钥' )
ok "没有 binhost-build.service 时从 binhost-update 取得签名密钥指纹" \
   "$([[ ${key_out} == *"${SHA40:0:8}，无过期时间"* && ${key_out} != *'<--'* ]] &&
      grep -c -- "--list-secret-keys ${SHA40}" "${d}/gpg.args")" "1"
rm -rf "${d}"

site_lock_probe() {
    local d hold out
    hold="$1"
    d=$(mktemp -d)
    mkdir -p "${d}/work" "${d}/dest"
    git -C "${d}/work" init -q
    git -C "${d}/work" -c user.email=t@example.com -c user.name=t \
        commit -q --allow-empty -m x
    : > "${d}/work/.git/FETCH_HEAD"
    printf '%s' 0000000000000000000000000000000000000000 > "${d}/work/.synced"
    : > "${d}/lock"
    if [ "${hold}" = hold ]; then
        flock "${d}/lock" sleep 5 &
        sleep 0.5
    fi
    out=$( cd "${ROOT}" && ALERT_CONF=/nonexistent STATE_FILE="${d}/state" \
        SITE_WORK="${d}/work" SITE_DEST="${d}/dest" SITE_LOCK="${d}/lock" \
        COMPONENT=mirror bash ops/status.sh 2>&1 | grep '站点同步' )
    wait 2>/dev/null
    rm -rf "${d}"
    case "${out}" in
        *'同步正在执行'*) echo in-progress ;;
        *'最近一次未完成'*) echo failed ;;
        *) echo "other:${out}" ;;
    esac
}

ok "同步进行中时不当作故障" "$(site_lock_probe hold)" "in-progress"
ok "同步没在执行时不一致仍是故障" "$(site_lock_probe free)" "failed"

echo "== kernel-archive 的 localversion"
ok "写出 config.d 片段" \
   "$(grep -c 'kernel/config.d/90-binpkg-localversion.config' \
      "${ROOT}/build/kernel-archive.sh")" "1"
# shellcheck disable=SC2016  # a grep pattern, expansion is not wanted
ok "后缀带 -bin" \
   "$(grep -c 'LOCALVERSION="\${LOCALVERSION:--gentoo-cjk-dist-bin}"' \
      "${ROOT}/build/kernel-archive.sh")" "1"

echo "== kernel-archive 解开 overlay 对 virtual/dist-kernel 的 mask"
# Every gentoo-cjk-kernel PDEPENDs on that virtual and the overlay masks it, so
# without the unmask the resolve stops before anything is compiled.
ok "容器里写出 unmask" \
   "$(grep -c "package.unmask/binhost-dist-kernel" \
      "${ROOT}/build/kernel-archive.sh")" "1"
unmask_line=$(grep -n 'package.unmask/binhost-dist-kernel' \
              "${ROOT}/build/kernel-archive.sh" | cut -d: -f1)
emerge_line=$(grep -n 'emerge --quiet-build -1 --buildpkg --usepkg' \
              "${ROOT}/build/kernel-archive.sh" | cut -d: -f1)
ok "unmask 排在 emerge 之前" \
   "$(( ${unmask_line:-0} > 0 && ${unmask_line:-0} < ${emerge_line:-0} ))" "1"

echo "== kernel-archive 的每轮上限与 USE 要求"
ok "超过上限时说明留了几个" \
   "$(grep -cF -- '- MAX_BUILDS )) 个留到下一轮' "${ROOT}/build/kernel-archive.sh")" "1"
ok "发布前回读产物的 USE" \
   "$(grep -c 'tar -xO metadata/USE' "${ROOT}/build/kernel-archive.sh")" "1"

echo "== kernel-archive 的保留策略"
ok "按 overlay 保留，不按数量" \
   "$(grep -cE 'KEEP_(LAST|VERSIONS|COUNT|N)' "${ROOT}/build/kernel-archive.sh")" "0"

echo "== kernel-archive 取产物的方式"
# shellcheck disable=SC2016  # we grep for the literal ${VAR}, not its value
ok "构建前移除这个版本的旧产物" \
   "$(grep -c 'rm -f /var/cache/binpkgs/${PACKAGE}/${PACKAGE#\*/}-${version}-' \
      "${ROOT}/build/kernel-archive.sh")" "1"
ok "移除之后重建索引" \
   "$(grep -c 'emaint binhost --fix' "${ROOT}/build/kernel-archive.sh")" "1"
# shellcheck disable=SC2016  # we grep for the literal ${VAR}, not its value
ok "只认 build id 为 1 的产物" \
   "$(grep -c '${version}-1.gpkg.tar"$' "${ROOT}/build/kernel-archive.sh")" "1"
# shellcheck disable=SC2016  # we grep for the literal ${VAR}, not its value
ok "发布名固定是 -1，变体后缀跟在架构后面" \
   "$(grep -c 'name="\${PACKAGE#\*/}-\${version}-1\.\${ARCH}\${suffix}\.gpkg\.tar"' \
      "${ROOT}/build/kernel-archive.sh")" "2"

echo "== status.sh 对 node_exporter 抓取源的判定"

exporter_probe() {
    local elements="$1" d out
    d=$(mktemp -d); mkdir -p "${d}/bin"
    cat > "${d}/bin/nft" <<EOF
#!/bin/bash
case "\$*" in
  *"chain inet filter input"*) echo "  tcp dport 9100 ip saddr @monitor_hosts accept" ;;
  *"set inet filter monitor_hosts"*) printf "set monitor_hosts {\n type ipv4_addr\n${elements}\n}\n" ;;
esac
EOF
    cat > "${d}/bin/sudo" <<'EOF'
#!/bin/bash
while [ "${1#-}" != "$1" ]; do shift; done
exec "$@"
EOF
    printf '#!/bin/bash\nexit 0\n' > "${d}/bin/node_exporter"
    cat > "${d}/bin/curl" <<'EOF'
#!/bin/bash
for a in "$@"; do case "$a" in *127.0.0.1:9100*) exit 0;; esac; done
exit 22
EOF
    chmod +x "${d}/bin"/*
    out=$( cd "${ROOT}" && PATH="${d}/bin:${PATH}" ALERT_CONF=/nonexistent \
        STATE_FILE="${d}/s" VERSION_FILE="${d}/v" SIGNING_GNUPGHOME="${d}/nokey" \
        DISK_PATH="${d}/nodisk" HEARTBEAT="${d}/nowhere/.health" \
        SITE_WORK="${d}/nowork" SITE_DEST="${d}/nodest" MONITORS_FILE="${d}/nomon" \
        bash ops/status.sh 2>&1 | grep node_exporter )
    rm -rf "${d}"
    case "${out}" in *'<--'*) echo failed ;; *) echo passed ;; esac
}

# status.sh writes the heartbeat itself. The scheduled run on the mirror is root
# and owns the file; anyone else can create files in that directory but cannot
# overwrite root's, so testing the directory answered yes and the write failed.
heartbeat_probe() {
    local mode="$1" d out state
    d=$(mktemp -d); mkdir -p "${d}/bin" "${d}/site"
    printf '#!/bin/bash\nexit 22\n' > "${d}/bin/curl"
    chmod +x "${d}/bin/curl"
    case "${mode}" in
        writable) : ;;
        unwritable) : > "${d}/site/.health"; chmod 444 "${d}/site/.health"; chmod 555 "${d}/site" ;;
        absent)    rm -rf "${d}/site" ;;
    esac
    out=$( cd "${ROOT}" && PATH="${d}/bin:${PATH}" ALERT_CONF=/nonexistent \
        STATE_FILE="${d}/s" VERSION_FILE="${d}/v" SIGNING_GNUPGHOME="${d}/nokey" \
        DISK_PATH="${d}/nodisk" HEARTBEAT="${d}/site/.health" \
        SITE_WORK="${d}/nowork" SITE_DEST="${d}/nodest" MONITORS_FILE="${d}/nomon" \
        bash ops/status.sh 2>&1 )
    state=$(grep -c '心跳写入' <<< "${out}")
    printf '%s %s %s\n' "${state}" \
        "$(grep -ci 'permission denied' <<< "${out}")" \
        "$(test -s "${d}/site/.health" && echo 有 || echo 无)"
    chmod 755 "${d}/site" 2>/dev/null
    rm -rf "${d}"
}

read -r said denied written <<< "$(heartbeat_probe writable)"
ok "能写时写出心跳" "${written}" "有"
ok "能写时不多说一句" "${said}" "0"

read -r said denied written <<< "$(heartbeat_probe unwritable)"
ok "写不进去时说出来" "${said}" "1"
ok "写不进去时不留裸的权限错误" "${denied}" "0"

read -r said denied written <<< "$(heartbeat_probe absent)"
ok "没有这个目录的机器不提心跳写入" "${said}" "0"

ok "抓取源清单为空时算故障" "$(exporter_probe "")" "failed"
ok "有抓取源时才算通过" \
   "$(exporter_probe " elements = { 1.2.3.4, 5.6.7.8 }")" "passed"

echo "== 构建进度是真实进度，不是监控进程的心跳"

build_status_probe() {
    local stable_json="$1" unstable_json="${2:-$1}" d out
    d=$(mktemp -d); mkdir -p "${d}/bin"
    cat > "${d}/bin/curl" <<EOF
#!/bin/bash
for a in "\$@"; do
  case "\$a" in
    *build-status-unstable.json*) printf '%s' '${unstable_json}'; exit 0 ;;
    *build-status.json*) printf '%s' '${stable_json}'; exit 0 ;;
  esac
done
exit 22
EOF
    printf '#!/bin/bash\nexit 1\n' > "${d}/bin/sudo"
    printf '#!/bin/bash\nexit 1\n' > "${d}/bin/openssl"
    chmod +x "${d}/bin"/*
    out=$( cd "${ROOT}" && PATH="${d}/bin:${PATH}" ALERT_CONF=/nonexistent \
        STATE_FILE="${d}/s" VERSION_FILE="${d}/v" SIGNING_GNUPGHOME="${d}/n" \
        DISK_PATH="${d}/n" HEARTBEAT="${d}/n/.h" SITE_WORK="${d}/n" \
        SITE_DEST="${d}/n" MONITORS_FILE="${d}/n" \
        bash ops/status.sh 2>&1 | grep 构建状态 )
    rm -rf "${d}"
    case "${out}" in *'<--'*) echo failed ;; *) echo passed ;; esac
}

NOW=$(date +%s); STALE=$(( NOW - 4 * 3600 ))
FRESH_JSON="{\"state\":\"running\",\"phase\":\"per-package\",\"progress_at\":${NOW},\"generated\":${NOW}}"
STALE_JSON="{\"state\":\"running\",\"phase\":\"per-package\",\"progress_at\":${STALE},\"generated\":${NOW}}"
DONE_JSON="{\"state\":\"done\",\"phase\":\"done\",\"generated\":${NOW}}"
ok "监控持续刷新但构建无进展时判为故障" \
   "$(build_status_probe "${STALE_JSON}")" \
   "failed"
ok "两者都新时正常" \
   "$(build_status_probe "${FRESH_JSON}")" \
   "passed"
ok "旧格式没有 progress_at 时退回看 generated" \
   "$(build_status_probe "{\"state\":\"running\",\"generated\":${NOW}}")" \
   "passed"
ok "完成状态仍然正常" "$(build_status_probe "${DONE_JSON}")" "passed"
ok "上次完成在 30 小时前仍在一轮构建的时限内" \
   "$(build_status_probe "{\"state\":\"done\",\"generated\":$(( NOW - 30 * 3600 ))}")" "passed"
ok "上次完成超过 44 小时判为故障" \
   "$(build_status_probe "{\"state\":\"done\",\"generated\":$(( NOW - 45 * 3600 ))}")" "failed"
ok "未知状态直接判为无法解析" \
   "$(build_status_probe "{\"state\":\"garbage\",\"generated\":${NOW}}")" \
   "failed"
ok "缺少状态同样判为无法解析" \
   "$(build_status_probe "{\"generated\":${NOW}}")" \
   "failed"
ok "unstable 构建无进展时同样判为故障" \
   "$(build_status_probe "${FRESH_JSON}" "${STALE_JSON}")" \
   "failed"

index_health_probe() {
    local mode="$1" d channel root out
    d=$(mktemp -d)
    mkdir -p "${d}/bin"
    for channel in stable unstable; do
        if [[ ${channel} == stable ]]; then
            root="${d}/site/binpkgs/x86-64"
        else
            root="${d}/site/unstable/binpkgs/x86-64"
        fi
        mkdir -p "${root}"
        cat > "${root}/Packages" <<EOF
TIMESTAMP: ${NOW}
PACKAGES: 2

CPV: app-misc/example-1
PATH: app-misc/example/example-1.gpkg.tar

CPV: app-misc/missing-2
PATH: app-misc/missing/missing-2.gpkg.tar
EOF
        [[ ${mode} != count ]] || sed -i 's/^PACKAGES: 2$/PACKAGES: 3/' "${root}/Packages"
        gzip -c "${root}/Packages" > "${root}/Packages.gz"
    done
    [[ ${mode} != stale-gz ]] || printf '\n' >> "${d}/site/binpkgs/x86-64/Packages"

    cat > "${d}/bin/curl" <<EOF
#!/bin/bash
url=''
for arg in "\$@"; do
    case \${arg} in https://*) url=\${arg};; esac
done
case \${url} in
  *api.github.com/repos/gentoo-zh/binhost/commits/master*)
    echo '  "sha": "${SHA40}",'; exit 0 ;;
  https://test/distfiles-status.json)
    echo '{"generated":${NOW},"files":1}'; exit 0 ;;
  https://test/build-status.json|https://test/build-status-unstable.json)
    echo '${DONE_JSON}'; exit 0 ;;
  https://test/.health)
    echo '${NOW}'; exit 0 ;;
esac
if [[ "\$*" == *"%{http_code}"* ]]; then
    if [[ '${mode}' == missing && \${url} == *missing-2.gpkg.tar ]]; then
        printf 404
    else
        printf 200
    fi
    exit 0
fi
cat "${d}/site\${url#https://test}"
EOF
    printf '#!/bin/bash\nexit 1\n' > "${d}/bin/sudo"
    printf '#!/bin/bash\nexit 1\n' > "${d}/bin/openssl"
    chmod +x "${d}/bin"/*
    printf '%s\n' "${SHA40}" > "${d}/VERSION"
    out=$( cd "${ROOT}" && PATH="${d}/bin:${PATH}" SITE=https://test \
        ALERT_CONF=/nonexistent STATE_FILE="${d}/state" VERSION_FILE="${d}/VERSION" \
        SIGNING_GNUPGHOME="${d}/nokey" DISK_PATH="${d}/nodisk" \
        HEARTBEAT="${d}/nowhere/.health" SITE_WORK="${d}/nowork" \
        SITE_DEST="${d}/nodest" MONITORS_FILE="${d}/nomon" \
        bash ops/status.sh 2>&1 )
    rm -rf "${d}"
    printf '%s\n' "${out}"
}

echo "== status.sh 核对索引并轮替抽查"
out=$(index_health_probe healthy)
ok "两个频道的索引都通过" "$(grep -c '索引.*2 个包' <<< "${out}")" "2"
ok "索引正常时不报故障" "$(grep -c '索引.*<--' <<< "${out}")" "0"
ok "两个频道都明确标出抽查数量" \
   "$(grep -c '取包抽查.*2 个均可下载' <<< "${out}")" "2"
out=$(index_health_probe stale-gz)
ok "Packages.gz 与 Packages 不一致时判为故障" \
   "$([[ $(grep 'stable 索引' <<< "${out}") == *'Packages.gz'*'<--'* ]] && echo failed)" \
   "failed"
out=$(index_health_probe count)
ok "PACKAGES 与 PATH 条数不符时判为故障" \
   "$([[ $(grep 'stable 索引' <<< "${out}") == *'PATH 有 2 条'*'<--'* ]] && echo failed)" \
   "failed"
out=$(index_health_probe missing)
ok "第二个 PATH 返回 404 时抽查会发现" \
   "$([[ $(grep 'stable 取包抽查' <<< "${out}") == *'missing-2.gpkg.tar'*'<--'* ]] && echo failed)" \
   "failed"

ok "监控同时检查两个频道的索引" \
   "$(grep -c '^check_channel_index \(stable\|unstable\) ' ops/status.sh)" "2"
ok "监控同时检查两个频道的构建状态" \
   "$(grep -c '^check_build_status \(stable\|unstable\) ' ops/status.sh)" "2"

echo
echo "== mirror-sync.sh"

setup_mirror() {
    d=$(mktemp -d)
    mkdir -p "${d}/src" "${d}/dest" "${d}/bin"
    cat > "${d}/bin/curl" <<EOF
#!/bin/bash
# Only -o <path> and the trailing URL matter here
out=""
url=""
while [ \$# -gt 0 ]; do
    case "\$1" in
        -o) out="\$2"; shift 2 ;;
        http*) url="\$1"; shift ;;
        *) shift ;;
    esac
done
src="${d}/src/\${url##*/x86-64/}"
[ -f "\${src}" ] || exit 22
cp "\${src}" "\${out}"
EOF
    chmod +x "${d}/bin/curl"
    echo "${d}"
}

mirror_index() {
    local dir="$1" n="$2" declared="${3:-$2}"
    {
        echo "PACKAGES: ${declared}"
        echo "TIMESTAMP: 1754150400"
        echo
        for ((i = 0; i < n; i++)); do
            printf 'CPV: app-misc/p%d-1.0\nPATH: app-misc/p%d-1.0-1.gpkg.tar\nSIZE: 2\n\n' "$i" "$i"
            mkdir -p "${dir}/src/app-misc"
            echo x > "${dir}/src/app-misc/p${i}-1.0-1.gpkg.tar"
        done
    } > "${dir}/src/Packages"
    gzip -c "${dir}/src/Packages" > "${dir}/src/Packages.gz"
}

# activate_index_generation refuses an incomplete generation. Nothing exercised
# that branch, so removing the check left every test green.
index_guard_probe() {
    local d out
    d=$(setup_mirror)
    mirror_index "${d}" 1
    ( cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" \
      DEST="${d}/dest" bash deploy/mirror-sync.sh ) >/dev/null 2>&1
    sed -n '/^activate_index_generation() {/,/^}/p' "${ROOT}/deploy/mirror-sync.sh" \
        > "${d}/probe.sh"
    cat >> "${d}/probe.sh" <<'PROBE'
activate_index_generation "$1"
PROBE
    mkdir -p "${d}/dest/.index-gen-empty"
    : > "${d}/dest/.index-gen-empty/Packages"
    : > "${d}/dest/.index-gen-empty/Packages.gz"
    out=$(DEST="${d}/dest" INDEX_FILES="Packages Packages.gz" \
          bash -c 'INDEX_FILES=(Packages Packages.gz); source "$0"; ' \
          "${d}/probe.sh" .index-gen-empty 2>&1)
    printf '%s|%s|%s\n' "$?" "${out}" \
        "$(readlink "${d}/dest/.index" 2>/dev/null)"
    rm -rf "${d}"
}

IFS='|' read -r rc out active <<< "$(index_guard_probe)"
ok "空的索引代际不会被启用" "$((rc != 0))" "1"
ok "并说明索引保持原样" "$([[ ${out} == *索引保持原样* ]] && echo yes)" "yes"
ok "仍指向先前那一代" "$([[ ${active} == .index-gen-* && ${active} != .index-gen-empty ]] && echo yes)" "yes"

d=$(setup_mirror)
mirror_index "${d}" 3 9
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "头部数量与实际不符时中止" "$?" "1"
contains "并且说明原因" "${out}" "索引不完整"
rm -rf "${d}"

d=$(setup_mirror)
mirror_index "${d}" 1
rm -rf "${d}/dest"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "目标目录尚不存在时可以完成首次同步" "$?" "0"
ok "首次同步会建立索引代际" \
   "$([[ -L ${d}/dest/.index && -s ${d}/dest/Packages ]] && echo 已建立 || echo 未建立)" \
   "已建立"
rm -rf "${d}"

d=$(setup_mirror)
mirror_index "${d}" 1
exec {mirror_lock_fd}>"${d}/dest/.mirror-sync.lock"
flock -n "${mirror_lock_fd}"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "另一次同步持有锁时立即中止" "$?" "1"
contains "并且说明锁仍被占用" "${out}" "仍在执行"
flock -u "${mirror_lock_fd}"
exec {mirror_lock_fd}>&-
rm -rf "${d}"

d=$(setup_mirror)
mirror_index "${d}" 3
printf 'PACKAGES: 3\n\nCPV: 别的\n' | gzip -c > "${d}/src/Packages.gz"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "两份索引内容不一致时中止" "$?" "1"
contains "并且说明原因" "${out}" "不是同一代"
rm -rf "${d}"

d=$(setup_mirror)
mirror_index "${d}" 3
mkdir -p "${d}/dest/app-misc"
printf 'truncated' > "${d}/dest/app-misc/p1-1.0-1.gpkg.tar"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "本地文件大小与索引不符时重新下载" "$?" "0"
ok "重新下载后内容正确" "$(cat "${d}/dest/app-misc/p1-1.0-1.gpkg.tar")" "x"
contains "并且报出该情况" "${out}" "大小与索引不符"
rm -rf "${d}"

d=$(setup_mirror)
mirror_index "${d}" 2
cp "${d}/src/Packages" "${d}/dest/Packages"
cp "${d}/src/Packages.gz" "${d}/dest/Packages.gz"
sed -i 's/TIMESTAMP: 1754150400/TIMESTAMP: 1754150401/' "${d}/src/Packages"
gzip -c "${d}/src/Packages" > "${d}/src/Packages.gz"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "普通索引文件会迁移为同一代链接" \
   "$(readlink "${d}/dest/Packages") $(readlink "${d}/dest/Packages.gz")" \
   ".index/Packages .index/Packages.gz"
first_gen=$(readlink "${d}/dest/.index")
ok "首次同步公开完整的新索引" \
   "$(awk '/^TIMESTAMP: /{print $2}' "${d}/dest/Packages")" "1754150401"
sed -i 's/TIMESTAMP: 1754150401/TIMESTAMP: 1754150402/' "${d}/src/Packages"
gzip -c "${d}/src/Packages" > "${d}/src/Packages.gz"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
second_gen=$(readlink "${d}/dest/.index")
ok "下一次同步切到新的索引代际" \
   "$([[ ${first_gen} != "${second_gen}" ]] && echo 已切换 || echo 未切换)" "已切换"
ok "切换后只保留当前索引代际" \
   "$(find "${d}/dest" -maxdepth 1 -type d -name '.index-gen-*' | wc -l)" "1"
ok "索引迁移没有留下种子目录" \
   "$(find "${d}/dest" -maxdepth 1 -type d -name '.index-seed-*' | wc -l)" "0"
ok "两种索引入口始终来自同一代" \
   "$(cmp -s <(gzip -dc "${d}/dest/Packages.gz") "${d}/dest/Packages" && echo 一致 || echo 不一致)" \
   "一致"
printf 'truncated' > "${d}/dest/app-misc/p1-1.0-1.gpkg.tar"
rm -f "${d}/src/app-misc/p1-1.0-1.gpkg.tar"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "包下载失败时不切换索引代际" "$(readlink "${d}/dest/.index")" "${second_gen}"
rm -rf "${d}"

# Downstream mirrors carry the same rate limit, for the same reason.
d=$(setup_mirror)
mirror_index "${d}" 20
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "先同步二十个包的索引" "$?" "0"
mkdir -p "${d}/dest/app-misc"
for ((i = 0; i < 20; i++)); do echo x > "${d}/dest/app-misc/old${i}-1.0-1.gpkg.tar"; done
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      REMOVE_PER_RUN=5 bash deploy/mirror-sync.sh 2>&1)
ok "超出限速时同步仍然成功" "$?" "0"
ok "本轮清理数量等于限速" "$(find "${d}/dest" -name 'old*.gpkg.tar' | wc -l)" "15"
contains "并且说明剩余由后续轮次清理" "${out}" "还有 15 个由后续轮次清理"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      REMOVE_PER_RUN=5 bash deploy/mirror-sync.sh 2>&1)
ok "下一轮同样以 0 结束" "$?" "0"
ok "下一轮继续清理，积压不再增长" \
   "$(find "${d}/dest" -name 'old*.gpkg.tar' | wc -l)" "10"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      REMOVE_PER_RUN=5 FORCE_REMOVE=1 bash deploy/mirror-sync.sh 2>&1)
ok "FORCE_REMOVE=1 时忽略限速一次清理全部" "$?" "0"
ok "清理后旧包不再存在" "$(find "${d}/dest" -name 'old*.gpkg.tar' | wc -l)" "0"
rm -rf "${d}"

# The downstream mirror carries the same floor: an upstream index that lost
# most of its packages must not take the local copies with it.
d=$(setup_mirror)
mirror_index "${d}" 20
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "先同步一份完整索引" "$?" "0"
mirror_index "${d}" 2
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "上游索引包数骤减时以 3 退出" "$?" "3"
ok "并且未删除任何旧包" "$(find "${d}/dest" -name '*.gpkg.tar' | wc -l)" "20"
contains "并且说明两份的包数" "${out}" "本次索引 2 个包，上一份 20 个"
rm -rf "${d}"

d=$(setup_mirror)
mirror_index "${d}" 3
sed -i 's/^SIZE: 2$/SIZE: 999/' "${d}/src/Packages"
gzip -c "${d}/src/Packages" > "${d}/src/Packages.gz"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "新下载的大小与索引不符时以非零结束" "$?" "1"
ok "并且不留下半截文件" "$(find "${d}/dest" -name '*.part' -o -name '*.gpkg.tar' | wc -l)" "0"
ok "并且不换入新索引" "$(test -e "${d}/dest/Packages" && echo 有 || echo 无)" "无"
rm -rf "${d}"

d=$(setup_mirror)
mirror_index "${d}" 3
sed -i '/^SIZE: /d' "${d}/src/Packages"
gzip -c "${d}/src/Packages" > "${d}/src/Packages.gz"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "索引没有 SIZE 时以非零结束" "$?" "1"
contains "并且说明原因" "${out}" "没有给出"
rm -rf "${d}"

d=$(setup_mirror)
mirror_index "${d}" 3
sed -i 's/^PACKAGES: 3$/PACKAGES: broken/' "${d}/src/Packages"
gzip -c "${d}/src/Packages" > "${d}/src/Packages.gz"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "头部不是数字时中止" "$?" "1"
contains "并且说明原因" "${out}" "不是正整数"
rm -rf "${d}"

d=$(setup_mirror)
mirror_index "${d}" 8
mkdir -p "${d}/dest/app-misc"
for ((i = 0; i < 2; i++)); do echo x > "${d}/dest/app-misc/old${i}-1.0-1.gpkg.tar"; done
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "日常汰换在当轮完成" "$?" "0"
ok "并且旧包已删除" "$(find "${d}/dest" -name 'old*.gpkg.tar' | wc -l)" "0"
rm -rf "${d}"

d=$(setup_mirror)
mirror_index "${d}" 3
mkdir -p "${d}/dest/app-misc"
printf 'truncated' > "${d}/dest/app-misc/p1-1.0-1.gpkg.tar"
rm -f "${d}/src/app-misc/p1-1.0-1.gpkg.tar"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "重新下载失败时以非零结束" "$?" "1"
ok "旧档仍然保留，索引仍指得到它" \
   "$(test -s "${d}/dest/app-misc/p1-1.0-1.gpkg.tar" && echo 在 || echo 无)" "在"
rm -rf "${d}"

d=$(setup_mirror)
mirror_index "${d}" 100
mkdir -p "${d}/dest/app-misc"
for ((i = 0; i < 10; i++)); do echo x > "${d}/dest/app-misc/old${i}-1.0-1.gpkg.tar"; done
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "索引变大时旧文件照常清理" "$?" "0"
ok "并且旧文件都已删除" "$(find "${d}/dest" -name 'old*.gpkg.tar' | wc -l)" "0"
rm -rf "${d}"

echo
echo "== site-sync.sh"

setup_site() {
    d=$(mktemp -d)
    mkdir -p "${d}/work/site" "${d}/work/.git" "${d}/dest" "${d}/bin"
    echo "User-agent: *" > "${d}/work/site/robots.txt"
    printf 'KEY\n' > "${d}/work/site/gentoo-zh-binhost.asc"
    cat > "${d}/bin/git" <<'EOF'
#!/bin/bash
case "$*" in
    *rev-parse*)
        if [[ -e ${WORK}/.git/reset-done ]]; then
            echo 2222222222222222222222222222222222222222
        else
            echo 1111111111111111111111111111111111111111
        fi
        ;;
    *reset*) : > "${WORK}/.git/reset-done" ;;
    *) exit 0 ;;
esac
EOF
    chmod +x "${d}/bin/git"
    echo "${d}"
}

fake_gpg() {
    local d="$1"
    shift
    : > "${d}/keys"
    for f in "$@"; do
        printf 'pub:u:255:22::::::::scSC:\nfpr:::::::::%s:\n' "${f}" >> "${d}/keys"
        printf 'sub:u:255:22::::::::s:\nfpr:::::::::%sSUB:\n' "${f:0:37}" >> "${d}/keys"
    done
    cat > "${d}/bin/gpg" <<EOF
#!/bin/bash
cat "${d}/keys"
EOF
    chmod +x "${d}/bin/gpg"
}

d=$(setup_site)
fake_gpg "${d}" AAAA0000000000000000000000000000000000AA
echo AAAA0000000000000000000000000000000000AA > "${d}/fpr"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" WORK="${d}/work" DEST="${d}/dest" \
      FPR_FILE="${d}/fpr" LOCK="${d}/lock" bash deploy/site-sync.sh 2>&1)
ok "指纹相符时正常结束" "$?" "0"
ok "并且写下更新后的 DONE" "$(cat "${d}/work/.synced" 2>/dev/null)" \
   "2222222222222222222222222222222222222222"
ok "公钥已发布" "$(cat "${d}/dest/gentoo-zh-binhost.asc" 2>/dev/null)" "KEY"
rm -rf "${d}"

d=$(setup_site)
fake_gpg "${d}" AAAA0000000000000000000000000000000000AA \
                BBBB0000000000000000000000000000000000BB
printf '%s\n%s\n' AAAA0000000000000000000000000000000000AA \
                   BBBB0000000000000000000000000000000000BB > "${d}/fpr"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" WORK="${d}/work" DEST="${d}/dest" \
      FPR_FILE="${d}/fpr" LOCK="${d}/lock" bash deploy/site-sync.sh 2>&1)
ok "轮替重叠期两把主公钥都在记录里就放行" "$?" "0"
ok "重叠期公钥已发布" "$(cat "${d}/dest/gentoo-zh-binhost.asc" 2>/dev/null)" "KEY"
rm -rf "${d}"

d=$(setup_site)
fake_gpg "${d}" AAAA0000000000000000000000000000000000AA \
                BBBB0000000000000000000000000000000000BB
echo AAAA0000000000000000000000000000000000AA > "${d}/fpr"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" WORK="${d}/work" DEST="${d}/dest" \
      FPR_FILE="${d}/fpr" LOCK="${d}/lock" bash deploy/site-sync.sh 2>&1)
ok "混入一把未登记的主公钥就拒绝" "$?" "1"
ok "混入时公钥不发布" "$(test -e "${d}/dest/gentoo-zh-binhost.asc" && echo 有 || echo 无)" "无"
rm -rf "${d}"

d=$(setup_site)
fake_gpg "${d}" BBBB0000000000000000000000000000000000BB
echo AAAA0000000000000000000000000000000000AA > "${d}/fpr"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" WORK="${d}/work" DEST="${d}/dest" \
      FPR_FILE="${d}/fpr" LOCK="${d}/lock" bash deploy/site-sync.sh 2>&1)
ok "指纹不符时以非零结束" "$?" "1"
ok "并且不写 DONE，下次会重试" "$(test -e "${d}/work/.synced" && echo 有 || echo 无)" "无"
ok "公钥没有发布" "$(test -e "${d}/dest/gentoo-zh-binhost.asc" && echo 有 || echo 无)" "无"
ok "robots.txt 也没有发布，本次不切换任何内容" "$(test -e "${d}/dest/robots.txt" && echo 有 || echo 无)" "无"
contains "输出分开列出两侧指纹" "${out}" "本机记录的指纹"
rm -rf "${d}"

d=$(setup_site)
fake_gpg "${d}" AAAA0000000000000000000000000000000000AA
echo AAAA0000000000000000000000000000000000AA > "${d}/fpr"
rm -rf "${d}/work"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" WORK="${d}/work" DEST="${d}/dest" \
      FPR_FILE="${d}/fpr" LOCK="${d}/work.lock" bash deploy/site-sync.sh 2>&1)
ok "锁不在 WORK 里，首次 clone 不会撞到非空目录" \
   "$(test -e "${d}/work/.lock" && echo 在 || echo 无)" "无"
rm -rf "${d}"

d=$(setup_site)
fake_gpg "${d}" AAAA0000000000000000000000000000000000AA
echo AAAA0000000000000000000000000000000000AA > "${d}/fpr"
: > "${d}/lock"
exec {held}>"${d}/lock"
flock -n "${held}"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" WORK="${d}/work" DEST="${d}/dest" \
      FPR_FILE="${d}/fpr" LOCK="${d}/lock" bash deploy/site-sync.sh 2>&1)
ok "锁被占用时直接退出，不改发布目录" "$?" "0"
ok "并且没有发布任何页面" "$(test -e "${d}/dest/index.html" && echo 有 || echo 无)" "无"
exec {held}>&-
rm -rf "${d}"

echo
if (( fail )); then
    echo ">>> ${fail} 项未通过，${pass} 项通过"
    exit 1
fi
echo ">>> ${pass} 项全部通过"
