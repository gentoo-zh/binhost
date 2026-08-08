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


setup_publish() {
    d=$(mktemp -d)
    mkdir -p "${d}/stage" "${d}/remote" "${d}/bin"
    cat > "${d}/bin/ssh" <<'EOF'
#!/bin/bash
shift
exec bash -c "$*"
EOF
    cat > "${d}/bin/rsync" <<'EOF'
#!/bin/bash
from_stdin=0
args=()
for a in "$@"; do
    case "$a" in
        --files-from=-) from_stdin=1 ;;
        -*) ;;
        *) args+=("${a#*:}") ;;
    esac
done
src=${args[-2]}
dst=${args[-1]}
if (( from_stdin )); then
    while IFS= read -r rel; do
        mkdir -p "${dst}/$(dirname "${rel}")"
        cp -f "${src}/${rel}" "${dst}/${rel}"
    done
else
    mkdir -p "$(dirname "${dst}")"
    cp -f "${src}" "${dst}"
fi
EOF
    chmod +x "${d}/bin/ssh" "${d}/bin/rsync"
    echo "${d}"
}

stage_index() {
    local dir="$1" n="$2" declared="${3:-$2}"
    mkdir -p "${dir}/stage/app-misc"
    {
        echo "PACKAGES: ${declared}"
        echo "TIMESTAMP: 1754150400"
        echo
        for ((i = 0; i < n; i++)); do
            echo x > "${dir}/stage/app-misc/p${i}-1.0-1.gpkg.tar"
            printf 'CPV: app-misc/p%d-1.0\nPATH: app-misc/p%d-1.0-1.gpkg.tar\nSIZE: 2\n\n' "$i" "$i"
        done
    } > "${dir}/stage/Packages"
    gzip -c "${dir}/stage/Packages" > "${dir}/stage/Packages.gz"
    printf 'PACKAGES: 0\nVERSION: 1\n\n' > "${dir}/stage/installed.txt"
    printf 'PACKAGES: 0\nVERSION: 1\n\n' > "${dir}/stage/official.txt"
    printf 'PACKAGES: 0\nVERSION: 1\n\n' > "${dir}/stage/source.txt"
    python3 "${ROOT}/build/generation.py" create "${dir}/stage"
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
    local d src dest
    d=$(mktemp -d)
    src="${d}/site"; dest="${d}/dest"
    mkdir -p "${src}/assets" "${dest}/assets"
    printf 'KEY\n' > "${src}/gentoo-zh-binhost.asc"
    printf '<p>new</p>\n' > "${src}/index.html"
    printf 'ua\n' > "${src}/robots.txt"
    printf 'css\n' > "${src}/assets/site.css"
    printf '<p>old</p>\n' > "${dest}/gone.html"
    printf 'stale\n' > "${dest}/assets/removed.css"
    mkdir -p "${dest}/binpkgs/x86-64" "${dest}/distfiles/ab"
    printf 'pkg\n' > "${dest}/binpkgs/x86-64/a.gpkg.tar"
    printf 'idx\n' > "${dest}/binpkgs/x86-64/Packages"
    printf 'src\n' > "${dest}/distfiles/ab/a.tar.gz"
    printf 'AAAA\n' > "${src}/same.html"
    printf 'BBBB\n' > "${dest}/same.html"
    touch -d '2026-01-01 00:00:00' "${src}/same.html" "${dest}/same.html"
    mkdir -p "${d}/bin"
    cat > "${d}/bin/gpg" <<'EOF'
#!/bin/bash
printf 'pub:u:255:22::::::::scSC:\nfpr:::::::::AAAA0000000000000000000000000000000000AA:\n'
EOF
    chmod +x "${d}/bin/gpg"
    echo AAAA0000000000000000000000000000000000AA > "${d}/fpr"
    PATH="${d}/bin:${PATH}" FPR_FILE="${d}/fpr" \
        bash "${ROOT}/deploy/publish-site.sh" "${src}" "${dest}" >/dev/null 2>&1
    printf '%s %s %s %s %s %s\n' \
        "$(test -e "${dest}/gentoo-zh-binhost.asc" && echo asc || echo noasc)" \
        "$(test -e "${dest}/gone.html" && echo kept || echo removed)" \
        "$(test -e "${dest}/assets/removed.css" && echo kept || echo removed)" \
        "$(tr -d '\n' < "${dest}/index.html" 2>/dev/null)" \
        "$(tr -d '\n' < "${dest}/same.html" 2>/dev/null)" \
        "$(find "${dest}/binpkgs" "${dest}/distfiles" -type f 2>/dev/null | wc -l)"
    rm -rf "${d}"
}
read -r a b c dd ee ff <<< "$(pubsite)"
ok "公钥会发布" "${a}" "asc"
ok "来源中已不存在的页面会一并移除" "${b}" "removed"
ok "assets 里多余的文件也会移除" "${c}" "removed"
ok "页面内容已更新" "${dd}" "<p>new</p>"
ok "同大小同 mtime 但内容不同时仍然更新" "${ee}" "AAAA"
ok "已发布的包与 distfiles 不受删除影响" "${ff}" "3"

pubsite_interrupted() {
    local d rc
    d=$(mktemp -d)
    mkdir -p "${d}/site" "${d}/dest" "${d}/bin"
    printf 'KEY\n' > "${d}/site/gentoo-zh-binhost.asc"
    printf '<p>old</p>\n' > "${d}/dest/old.html"
    cat > "${d}/bin/gpg" <<'EOF'
#!/bin/bash
printf 'pub:u:255:22::::::::scSC:\nfpr:::::::::AAAA0000000000000000000000000000000000AA:\n'
EOF
    cat > "${d}/bin/rsync" <<EOF
#!/bin/bash
case " \$* " in
  *' --delete-delay '*) exit 23 ;;
  *) rm -f '${d}/dest/old.html'; exit 23 ;;
esac
EOF
    chmod +x "${d}/bin/gpg" "${d}/bin/rsync"
    echo AAAA0000000000000000000000000000000000AA > "${d}/fpr"
    PATH="${d}/bin:${PATH}" FPR_FILE="${d}/fpr" \
        bash "${ROOT}/deploy/publish-site.sh" "${d}/site" "${d}/dest" \
        >/dev/null 2>&1
    rc=$?
    printf '%s %s\n' "${rc}" "$(test -e "${d}/dest/old.html" && echo 保留 || echo 删除)"
    rm -rf "${d}"
}

read -r rc old_state <<< "$(pubsite_interrupted)"
ok "站点传输中断时退出码非零" "$((rc != 0))" "1"
ok "站点传输中断时延迟删除旧文件" "${old_state}" "保留"

echo "== publish.sh 的索引替换"

swap_probe() {
    local mode="$1" d
    d=$(mktemp -d)
    sed -n "/<<'SWAP'/,/^SWAP\$/p" "${ROOT}/build/publish.sh" |
        sed -e "1d" -e "\$d" > "${d}/swap.sh"
    printf 'old\n' > "${d}/Packages"
    printf 'oldgz\n' > "${d}/Packages.gz"
    printf 'oldinstalled\n' > "${d}/installed.txt"
    printf 'oldofficial\n' > "${d}/official.txt"
    printf 'oldsource\n' > "${d}/source.txt"
    printf 'oldgeneration\n' > "${d}/generation.json"
    printf 'new\n' > "${d}/.Packages.new"
    printf 'newinstalled\n' > "${d}/.installed.txt.new"
    printf 'newofficial\n' > "${d}/.official.txt.new"
    printf 'newsource\n' > "${d}/.source.txt.new"
    printf 'newgeneration\n' > "${d}/.generation.json.new"
    if [ "${mode}" != "gzmissing" ]; then
        printf 'newgz\n' > "${d}/.Packages.gz.new"
    fi
    sh "${d}/swap.sh" "${d}" >/dev/null 2>&1
    printf '%s %s %s %s %s %s %s %s\n' "$?" \
        "$(tr -d '\n' < "${d}/Packages")" \
        "$(tr -d '\n' < "${d}/Packages.gz")" \
        "$(tr -d '\n' < "${d}/installed.txt")" \
        "$(tr -d '\n' < "${d}/official.txt")" \
        "$(tr -d '\n' < "${d}/source.txt")" \
        "$(tr -d '\n' < "${d}/generation.json")" \
        "$(find "${d}" -maxdepth 1 \( -name '.*.prev' -o -name '.*.absent' -o -name '.*.new' \) | wc -l)"
    rm -rf "${d}"
}

read -r rc pk gz installed official source generation leftover <<< "$(swap_probe ok)"
ok "索引与快照都换成新的" \
   "${pk} ${gz} ${installed} ${official} ${source} ${generation}" \
   "new newgz newinstalled newofficial newsource newgeneration"
ok "换完不留临时文件" "${leftover}" "0"
ok "正常情况下退出码为零" "${rc}" "0"

read -r rc pk gz installed official source generation leftover <<< "$(swap_probe gzmissing)"
ok "Packages.gz 换不成时报错" "${rc}" "1"
ok "Packages.gz 换不成时把 Packages 还原回旧的" "${pk}" "old"
ok "还原之后所有文件仍是同一代" \
   "${pk} ${gz} ${installed} ${official} ${source} ${generation}" \
   "old oldgz oldinstalled oldofficial oldsource oldgeneration"
ok "还原之后不留临时文件" "${leftover}" "0"

echo "== daily.sh 的旧代过渡"

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
    sed -n '/^if step "distfiles 同步"/,/^# generation.json/p' "${ROOT}/deploy/daily.sh" |
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
   "${calls[*]}" "distfiles 同步 stable 包列表 unstable 包列表 服务器状态"

mapfile -t calls < <(daily_list_probe success)
ok "distfiles 同步成功时先对账并重建索引" \
   "${calls[*]}" \
   "distfiles 同步 distfiles 对账 distfiles 索引 stable 包列表 unstable 包列表 服务器状态"

daily_generation_probe() {
    local mode="$1" d out calls
    d=$(mktemp -d)
    mkdir -p "${d}/stable" "${d}/unstable" "${d}/lib"
    # shellcheck disable=SC2016  # Match ${FAILURES} literally in the source.
    sed -n '/^verify_channel()/,/^if \[\[ -s \${FAILURES}/p' "${ROOT}/deploy/daily.sh" |
        sed '$d' > "${d}/block.sh"
    cat > "${d}/lib/generation.py" <<'PY'
import os
import pathlib
import sys
label = pathlib.Path(sys.argv[-1]).name
pathlib.Path(os.environ["CALLS"]).open("a").write(f"generation:{label}\n")
sys.exit(int(os.environ.get(f"{label.upper()}_GENERATION_RC", "0")))
PY
    cat > "${d}/lib/verify-deps.py" <<'PY'
import os
import pathlib
import sys
label = pathlib.Path(sys.argv[1]).parent.name
pathlib.Path(os.environ["CALLS"]).open("a").write(f"deps:{label}\n")
PY
    case ${mode} in
        valid|stable-invalid|unstable-invalid)
            : > "${d}/stable/generation.json"
            : > "${d}/unstable/generation.json"
            ;;
        unstable-broken)
            : > "${d}/stable/generation.json"
            ln -s missing "${d}/unstable/generation.json"
            ;;
    esac
    out=$(
        # shellcheck disable=SC2317,SC2329  # The sourced block invokes this function.
        step() { shift; "$@"; }
        export CALLS="${d}/calls" STABLE_GENERATION_RC=0 UNSTABLE_GENERATION_RC=0
        [[ ${mode} == stable-invalid ]] && STABLE_GENERATION_RC=1
        [[ ${mode} == unstable-invalid || ${mode} == unstable-broken ]] && \
            UNSTABLE_GENERATION_RC=1
        # shellcheck disable=SC1091  # block.sh is generated above.
        LIB="${d}/lib" STABLE_BINPKGS="${d}/stable" \
            UNSTABLE_BINPKGS="${d}/unstable" . "${d}/block.sh"
    )
    if [[ -f ${d}/calls ]]; then
        calls=$(tr '\n' ' ' < "${d}/calls")
    else
        calls=""
    fi
    out=${out//$'\n'/;}
    printf '%s|%s\n' "${out}" "${calls% }"
    rm -rf "${d}"
}

IFS='|' read -r out calls <<< "$(daily_generation_probe missing)"
ok "两个频道缺少 generation.json 时不执行验证" "${calls}" ""
ok "旧代缺少清单时分别说明略过原因" \
   "$([[ ${out} == *stable*尚未发布* && ${out} == *unstable*尚未发布* ]] && echo yes)" "yes"

IFS='|' read -r out calls <<< "$(daily_generation_probe valid)"
ok "两个频道的同代清单有效时都执行反向验证" "${calls}" \
   "generation:stable deps:stable generation:unstable deps:unstable"

IFS='|' read -r out calls <<< "$(daily_generation_probe stable-invalid)"
ok "stable 清单损坏不妨碍 unstable 完成验证" "${calls}" \
   "generation:stable generation:unstable deps:unstable"

IFS='|' read -r out calls <<< "$(daily_generation_probe unstable-invalid)"
ok "unstable 清单损坏时不执行它的反向验证" "${calls}" \
   "generation:stable deps:stable generation:unstable"

IFS='|' read -r out calls <<< "$(daily_generation_probe unstable-broken)"
ok "unstable 的断开符号链接仍进入验证" "${calls}" \
   "generation:stable deps:stable generation:unstable"

echo "== build-container.sh 交回 PKGDIR 属主"

owner_line=$(grep -n 'chown -R' "${ROOT}/build/build-container.sh" | head -1 | cut -d: -f1)
inner_end=$(grep -n '^INNER$' "${ROOT}/build/build-container.sh" | tail -1 | cut -d: -f1)
# shellcheck disable=SC2016  # matching the literal text of the script
persist=$(grep -n 'python3 "$(dirname "$0")/persist-packages.py"' "${ROOT}/build/build-container.sh" | head -1 | cut -d: -f1)
ok "构建容器结束后交回 PKGDIR 属主" "$(( owner_line > inner_end ))" "1"
ok "交回属主排在持久化之前" "$(( owner_line < persist ))" "1"
# shellcheck disable=SC2016  # matching the literal text of the script
handback=$(grep -c 'chown -R "$(id -u):$(id -g)" "${PKGDIR}"' "${ROOT}/build/build-container.sh")
ok "交回的是 PKGDIR 而不是别的目录" "${handback}" "1"

echo "== 构建频道使用隔离路径"

channel_probe() {
    # shellcheck disable=SC2016  # The child shell expands the probe variables.
    env -u CHANNEL TAG=x86-64 bash -c '
        [ "$1" = default ] || export CHANNEL="$1"
        . "$2"
        printf "%s|%s|%s|%s|%s|%s\n" \
            "$CHANNEL" "$CHANNEL_STORAGE" "$CHANNEL_IMAGE_TAG" \
            "$CHANNEL_ACCEPT_KEYWORDS" "$CHANNEL_OVERLAY_KEYWORDS" \
            "$CHANNEL_REMOTE_ROOT"
    ' _ "$1" "${ROOT}/build/channel.sh"
}

IFS='|' read -r channel storage image keywords overlay_keywords remote_root <<< \
    "$(channel_probe default)"
ok "未指定频道时默认使用 stable" "${channel}" "stable"
ok "stable 默认使用独立缓存与暂存路径" "${storage}" "stable/x86-64"
ok "stable 默认使用独立基础镜像标签" "${image}" "stable-x86-64"
ok "stable 默认只接受主树稳定关键字" "${keywords}" "amd64"
ok "stable 默认只对 gentoo-zh 接受测试关键字" "${overlay_keywords}" "~amd64"
ok "stable 默认发布到兼容路径" \
   "${remote_root}" "/srv/pub/binpkgs/x86-64"

IFS='|' read -r channel storage image keywords overlay_keywords remote_root <<< \
    "$(channel_probe unstable)"
ok "unstable 继续使用原有缓存与暂存路径" "${storage}" "x86-64"
ok "unstable 继续使用原有基础镜像标签" "${image}" "x86-64"
ok "unstable 继续接受全局测试关键字" "${keywords}" "~amd64"
ok "unstable 不增加仓库级关键字覆盖" "${overlay_keywords}" ""
ok "unstable 发布到明确的测试频道路径" \
   "${remote_root}" "/srv/pub/unstable/binpkgs/x86-64"

IFS='|' read -r channel storage image keywords overlay_keywords remote_root <<< \
    "$(channel_probe stable)"
ok "stable 使用独立缓存与暂存路径" "${storage}" "stable/x86-64"
ok "stable 使用独立基础镜像标签" "${image}" "stable-x86-64"
ok "stable 的 Gentoo 主树只接受稳定关键字" "${keywords}" "amd64"
ok "stable 只对 gentoo-zh 接受测试关键字" "${overlay_keywords}" "~amd64"
ok "stable 发布到既有兼容路径" \
   "${remote_root}" "/srv/pub/binpkgs/x86-64"

CHANNEL=other bash -c '. "$1"' _ "${ROOT}/build/channel.sh" >/dev/null 2>&1
channel_rc=$?
ok "未知频道会立即失败" "${channel_rc}" "2"

stable_unit=$(<"${ROOT}/deploy/systemd/binhost-build.service")
unstable_unit=$(<"${ROOT}/deploy/systemd/binhost-build-unstable.service")
stable_timer=$(<"${ROOT}/deploy/systemd/binhost-build.timer")
unstable_timer=$(<"${ROOT}/deploy/systemd/binhost-build-unstable.timer")
installer=$(<"${ROOT}/deploy/install-builder.sh")
ok "默认构建服务明确选择 stable" \
   "$(grep -c '^Environment=CHANNEL=stable$' <<< "${stable_unit}")" "1"
ok "测试频道服务明确选择 unstable" \
   "$(grep -c '^Environment=CHANNEL=unstable$' <<< "${unstable_unit}")" "1"
ok "两个频道错开十二小时调度" \
   "$(grep -c '16:00:00 Asia/Shanghai' <<< "${stable_timer}")-$(grep -c '04:00:00 Asia/Shanghai' <<< "${unstable_timer}")" "1-1"
ok "安装脚本同时启用两个频道的定时器" \
   "$(grep -c 'binhost-build-unstable.timer' <<< "${installer}")" "1"

shared_lock=$(grep -c "LOCK=\"\${LOCK:-/var/lib/binhost/stage/build.lock}\"" \
    "${ROOT}/build/build-container.sh")
ok "两个频道共用全局构建锁" "${shared_lock}" "1"

for script in base-image.sh build-container.sh cycle.sh run-full.sh publish.sh; do
    sourced=$(grep -c 'source=build/channel.sh' "${ROOT}/build/${script}")
    ok "${script} 读取统一频道配置" "${sourced}" "1"
done

run_full_probe() {
    local cores="$1" override="${2:-}" d out
    d=$(mktemp -d)
    mkdir -p "${d}/build" "${d}/bin"
    cp "${ROOT}/build/run-full.sh" "${ROOT}/build/channel.sh" "${d}/build/"
    cat > "${d}/bin/nproc" <<EOF
#!/bin/bash
echo ${cores}
EOF
    cat > "${d}/build/build-container.sh" <<'EOF'
#!/bin/bash
printf '%s|%s\n' "${JOBS}" "${MAKEOPTS}"
EOF
    chmod +x "${d}/bin/nproc" "${d}/build/build-container.sh"
    if [[ -n ${override} ]]; then
        out=$(cd "${d}" && PATH="${d}/bin:${PATH}" SIGNING_KEY=test \
            MAKEOPTS="${override}" bash build/run-full.sh)
    else
        out=$(cd "${d}" && env -u MAKEOPTS PATH="${d}/bin:${PATH}" \
            SIGNING_KEY=test bash build/run-full.sh)
    fi
    rm -rf "${d}"
    printf '%s\n' "${out}"
}

echo "== run-full.sh 按主机资源设置编译并发"

ok "76 核主机默认使用 32 个编译任务" \
   "$(run_full_probe 76)" "24|-j32 -l76"
ok "少于 32 核时不超过主机核数" \
   "$(run_full_probe 6)" "24|-j6 -l6"
ok "显式 MAKEOPTS 不被默认值覆盖" \
   "$(run_full_probe 76 '-j12 -l20')" "24|-j12 -l20"

base_image=$(<"${ROOT}/build/base-image.sh")
ok "基础镜像把频道的全局关键字传入容器" \
   "$(grep -Fc "BINHOST_ACCEPT_KEYWORDS=\${CHANNEL_ACCEPT_KEYWORDS}" <<< "${base_image}")" "1"
ok "基础镜像把 overlay 关键字传入容器" \
   "$(grep -Fc "BINHOST_OVERLAY_KEYWORDS=\${CHANNEL_OVERLAY_KEYWORDS}" <<< "${base_image}")" "1"
ok "基础镜像只按频道要求写入 overlay 关键字" \
   "$(grep -Fc "*/*::gentoo-zh \${BINHOST_OVERLAY_KEYWORDS}" <<< "${base_image}")" "1"

container=$(<"${ROOT}/build/build-container.sh")
ok "MAKEOPTS 传入实际构建容器" \
   "$(grep -Fc -- "-e \"MAKEOPTS=\${MAKEOPTS}\"" <<< "${container}")" "1"
ok "JOBS 传入实际构建容器" \
   "$(grep -Fc -- "-e \"JOBS=\${JOBS}\"" <<< "${container}")" "1"
ok "依赖验证使用频道的主树关键字" \
   "$(grep -Fc "source_policy=(--source-keywords \"\${CHANNEL_ACCEPT_KEYWORDS}\")" \
       <<< "${container}")" "1"
ok "依赖验证可单独接受 overlay 测试关键字" \
   "$(grep -Fc "source_policy+=(--source-overlay-keywords \"\${CHANNEL_OVERLAY_KEYWORDS}\")" \
       <<< "${container}")" "1"
ok "stable 构建生成频道有效清单" \
   "$(grep -Fc "python3 \"\$(dirname \"\$0\")/channel_packages.py\"" \
       <<< "${container}")" "1"
ok "stable 发布只以有效清单中的包作为种子" \
   "$(grep -Fc "stage_policy+=(--seeds \"\${LIST}\" --exclude-file \"\${STABLE_EXCLUDED}\")" \
       <<< "${container}")" "1"
ok "stable 专用 USE 设置只在 stable 条件中载入" \
   "$(grep -Fc 'cat /tmp/package.use.stable >> /etc/portage/package.use/binhost-deps' \
       <<< "${container}")" "1"
ok "stable 专用 USE 设置有明确频道条件" \
   "$(grep -Fc "if [[ \${BINHOST_CHANNEL} == stable ]]; then" \
       <<< "${container}")" "1"
ok "unstable 不无条件挂载 stable 专用 USE 设置" \
   "$(grep -Ec '^[[:space:]]+-v "\$\{STABLE_PACKAGE_USE\}:/tmp/package.use.stable:ro"' \
       <<< "${container}")" "0"
ok "stable 专用 USE 设置通过频道挂载数组传入" \
   "$(grep -Fc "channel_mounts=(-v \"\${STABLE_PACKAGE_USE}:/tmp/package.use.stable:ro\")" \
       <<< "${container}")" "1"

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

ok "抓取源清单为空时算故障" "$(exporter_probe "")" "failed"
ok "有抓取源时才算通过" \
   "$(exporter_probe " elements = { 1.2.3.4, 5.6.7.8 }")" "passed"

echo "== 构建进度是真实进度，不是监控进程的心跳"

snap() {
    local d out
    d=$(mktemp -d)
    [ -n "$1" ] && printf '%s\n' "$1" > "${d}/progress"
    [ -n "$2" ] && printf '%s\n' "$2" > "${d}/whole.log"
    out=$( cd "${ROOT}" && BUILD_STARTED=100 bash -c \
        'source <(sed -n "/^emit()/,/^}/p;/^snapshot()/,/^}/p" build/build-progress.sh)
         snapshot "'"${d}"'/whole.log"' )
    rm -rf "${d}"
    echo "${out}"
}

phase_of() { grep -o '"phase":"[a-z-]*"' <<< "$1" | cut -d'"' -f4; }
field_of() { grep -o "\"$2\":[0-9]*" <<< "$1" | cut -d: -f2; }

s=$(snap "42 173 app-misc/foo" "")
ok "逐包阶段报出真实完成数" "$(field_of "${s}" "done")" "42"
ok "逐包阶段报出总数" "$(field_of "${s}" total)" "173"
ok "逐包阶段标出 phase" "$(phase_of "${s}")" "per-package"
ok "逐包阶段保留本次开始时间" "$(field_of "${s}" started)" "100"
case "${s}" in *'"now":"app-misc/foo"'*) ok "逐包阶段报出当前套件" yes yes ;;
               *) ok "逐包阶段报出当前套件" no yes ;; esac

s=$(snap "" ">>> Emerging (5 of 10) app-misc/bar
>>> Installing (5 of 10) app-misc/bar")
ok "整体阶段仍按 whole.log 计数" "$(field_of "${s}" "done")" "1"
ok "整体阶段标出 phase" "$(phase_of "${s}")" "whole"

s=$(snap "" "")
ok "两者都没有时是 prepare" "$(phase_of "${s}")" "prepare"

s=$(snap "7 9 app-misc/x" "")
gen=$(field_of "${s}" generated); prog=$(field_of "${s}" progress_at)
ok "progress_at 与 generated 分开输出" \
   "$([ -n "${gen}" ] && [ -n "${prog}" ] && echo both || echo missing)" "both"

finish_status() {
    local d
    d=$(mktemp -d); mkdir -p "${d}/bin"
    cat > "${d}/bin/ssh" <<'EOF'
#!/bin/bash
cat > "${CAPTURE}"
EOF
    chmod +x "${d}/bin/ssh"
    ( cd "${ROOT}" && PATH="${d}/bin:${PATH}" CAPTURE="${d}/status.json" \
        BUILD_STARTED=100 bash build/build-progress.sh finish "done" >/dev/null )
    cat "${d}/status.json"
    rm -rf "${d}"
}

s=$(finish_status)
started=$(field_of "${s}" started)
finished=$(field_of "${s}" finished)
duration=$(field_of "${s}" duration)
ok "完成状态保留开始与结束时间" \
   "$([ -n "${started}" ] && [ -n "${finished}" ] && echo both || echo missing)" "both"
ok "完成状态的用时由同一次起止时间计算" "$(( finished - started ))" "${duration}"

start_line=$(grep -n '^BUILD_STARTED=' build/cycle.sh | head -1 | cut -d: -f1)
watch_line=$(grep -n 'build-progress.sh watch' build/cycle.sh | cut -d: -f1)
ok "取得构建锁后先记录开始时间再启动监控" \
   "$([ -n "${start_line}" ] && [ "${start_line}" -lt "${watch_line}" ] && echo yes || echo no)" "yes"

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
ok "监控持续刷新但构建无进展时判为故障" \
   "$(build_status_probe "${STALE_JSON}")" \
   "failed"
ok "两者都新时正常" \
   "$(build_status_probe "${FRESH_JSON}")" \
   "passed"
ok "旧格式没有 progress_at 时退回看 generated" \
   "$(build_status_probe "{\"state\":\"running\",\"generated\":${NOW}}")" \
   "passed"
ok "unstable 构建无进展时同样判为故障" \
   "$(build_status_probe "${FRESH_JSON}" "${STALE_JSON}")" \
   "failed"
ok "监控同时检查两个频道的索引" \
   "$(grep -c '^check_channel_index \(stable\|unstable\) ' ops/status.sh)" "2"
ok "监控同时检查两个频道的构建状态" \
   "$(grep -c '^check_build_status \(stable\|unstable\) ' ops/status.sh)" "2"

echo "== 逐包阶段确实公布进度"

percpkg_probe() {
    local d out
    d=$(mktemp -d); mkdir -p "${d}/bin" "${d}/log"
    printf '#!/bin/bash\nexit 0\n' > "${d}/bin/emerge"
    chmod +x "${d}/bin/emerge"
    # Run build-container.sh's per-package loop verbatim, with emerge stubbed
    sed -n '/^    done_count=0$/,/^    rm -f \/var\/log\/binhost\/progress$/p' \
        "${ROOT}/build/build-container.sh" > "${d}/loop.sh"
    ( cd "${d}" && PATH="${d}/bin:${PATH}" bash -c '
        atoms=(app-misc/a app-misc/b app-misc/c)
        EMERGE=(emerge)
        failed=()
        mkdir -p /tmp/binhost-probe-log
        sed "s|/var/log/binhost|/tmp/binhost-probe-log|g" '"${d}"'/loop.sh > '"${d}"'/loop2.sh
        # Capture the progress file while the second package is building
        cat > '"${d}"'/bin/emerge <<EOF
#!/bin/bash
case "\$*" in *app-misc/b*) cat /tmp/binhost-probe-log/progress > '"${d}"'/seen ;; esac
exit 0
EOF
        chmod +x '"${d}"'/bin/emerge
        source '"${d}"'/loop2.sh' >/dev/null 2>&1 )
    out=$(cat "${d}/seen" 2>/dev/null)
    local left
    left=$(test -e /tmp/binhost-probe-log/progress && echo 有 || echo 无)
    rm -rf "${d}" /tmp/binhost-probe-log
    printf '%s|%s\n' "${out}" "${left}"
}

IFS='|' read -r seen left <<< "$(percpkg_probe)"
ok "循环中会写出已完成数量、总数和当前套件" "${seen}" "1 3 app-misc/b"
ok "循环结束后移除进度文件" "${left}" "无"

echo "== preserved-rebuild 是发布前的硬闸门"

preserved_probe() {
    local emerge_rc="$1" portageq_rc="$2" preserved="$3" d rc out calls log_state
    d=$(mktemp -d); mkdir -p "${d}/bin"
    cat > "${d}/bin/emerge" <<EOF
#!/bin/bash
printf 'emerge %s\n' "\$*" >> "${d}/calls"
exit ${emerge_rc}
EOF
    cat > "${d}/bin/portageq" <<EOF
#!/bin/bash
printf 'portageq %s\n' "\$*" >> "${d}/calls"
printf '%s\n' '${preserved}'
exit ${portageq_rc}
EOF
    chmod +x "${d}/bin/emerge" "${d}/bin/portageq"
    out=$(PATH="${d}/bin:${PATH}" bash "${ROOT}/build/rebuild-preserved.sh" \
        "${d}/rebuild.log" 2>&1)
    rc=$?
    calls=$(tr '\n' '|' < "${d}/calls" 2>/dev/null)
    log_state=$(test -e "${d}/rebuild.log" && echo kept || echo removed)
    printf '%s;%s;%s;%s\n' "${rc}" "${calls}" "${log_state}" "${out//$'\n'/|}"
    rm -rf "${d}"
}

IFS=';' read -r rc calls log_state out <<< "$(preserved_probe 0 1 '')"
ok "没有保留库时闸门通过" "${rc}" "0"
contains "执行 Portage 的重建集合" "${calls}" \
    "emerge --usepkg --changed-use --with-bdeps=y --keep-going --quiet-build @preserved-rebuild"
contains "重建后查询保留库" "${calls}" "portageq list_preserved_libs /"
ok "成功日志不会残留" "${log_state}" "removed"

IFS=';' read -r rc calls log_state out <<< "$(preserved_probe 2 1 '')"
ok "重建失败时闸门失败" "$(( rc != 0 ))" "1"
ok "重建失败后不执行不可靠的残留检查" \
   "$(grep -c 'portageq' <<< "${calls}")" "0"
ok "重建失败日志保留" "${log_state}" "kept"

IFS=';' read -r rc calls log_state out <<< \
    "$(preserved_probe 0 0 'dev-libs/example: /usr/lib64/libexample.so.1')"
ok "仍有保留库时闸门失败" "$(( rc != 0 ))" "1"
contains "输出残留库的具体路径" "${out}" "/usr/lib64/libexample.so.1"

IFS=';' read -r rc calls log_state out <<< "$(preserved_probe 0 13 'permission denied')"
ok "无法查询保留库时闸门失败" "$(( rc != 0 ))" "1"
contains "查询错误不会被当成空集合" "${out}" "无法检查保留库"

base_rebuild_line=$(grep -n '/usr/local/bin/rebuild-preserved' \
    "${ROOT}/build/base-image.sh" | tail -1 | cut -d: -f1)
base_last_ebuild_line=$(grep -nE 'emerge |perl-cleaner ' \
    "${ROOT}/build/base-image.sh" | tail -1 | cut -d: -f1)
ok "基础镜像在全部 ebuild 操作后处理保留库" \
   "$(( base_rebuild_line > base_last_ebuild_line ))" "1"

container_rebuild_line=$(grep -n '^/usr/local/bin/rebuild-preserved' \
    "${ROOT}/build/build-container.sh" | cut -d: -f1)
emaint_line=$(grep -n '^emaint binhost --fix' \
    "${ROOT}/build/build-container.sh" | cut -d: -f1)
ok "完整构建在修复索引前处理保留库" \
   "$(( container_rebuild_line < emaint_line ))" "1"

echo "== publish.sh"

d=$(setup_publish)
stage_index "${d}" 2
mkdir -p "${d}/remote/app-misc"
for ((i = 0; i < 30; i++)); do echo x > "${d}/remote/app-misc/old${i}-1.0-1.gpkg.tar"; done
echo x > "${d}/remote/app-misc/banned-1.0-1.gpkg.tar"
echo "app-misc/banned-1.0-1.gpkg.tar" > "${d}/stage/quarantine.txt"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "清理仍被上限拦下" "$?" "3"
ok "但不可再散布的那个已经移除" \
   "$(test -e "${d}/remote/app-misc/banned-1.0-1.gpkg.tar" && echo 在 || echo 不在)" "不在"
ok "受上限保护的旧包一个没动" "$(find "${d}/remote" -name 'old*.gpkg.tar' | wc -l)" "30"
contains "输出说明先执行隔离" "${out}" "先从公开路径移除"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 1
mkdir -p "${d}/remote/app-misc"
printf 'old index\n' > "${d}/remote/Packages"
printf 'restricted\n' > "${d}/remote/app-misc/restricted.gpkg.tar"
printf 'app-misc/restricted.gpkg.tar\n' > "${d}/stage/quarantine.txt"
printf '目标版本检查失败\n' > "${d}/stage/publish-blocked.txt"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "发布闸门失败时退出码非零" "$?" "1"
ok "发布闸门失败时仍执行隔离" \
   "$(test -e "${d}/remote/app-misc/restricted.gpkg.tar" && echo 在 || echo 不在)" "不在"
ok "发布闸门失败时保留公开索引" "$(tr -d '\n' < "${d}/remote/Packages")" "old index"
contains "发布闸门失败时输出具体原因" "${out}" "目标版本检查失败"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 2
mkdir -p "${d}/remote/app-misc"
echo x > "${d}/remote/app-misc/banned-1.0-1.gpkg.tar"
printf '../../etc/passwd\n' > "${d}/stage/quarantine.txt"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "隔离清单里的越界路径被拒绝" "$?" "1"
contains "并且说明隔离失败" "${out}" "产物未能移除"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 2
printf '2\n7\n' > "${d}/stage/counts.txt"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "有 counts.txt 时正常发布" "$?" "0"
ok "status.json 分开记 overlay 与依赖数" \
   "$(python3 -c "import json;d=json.load(open('${d}/remote/status.json'));print(d['overlay'],d['deps'])" 2>/dev/null)" \
   "2 7"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 2
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "没有 counts.txt 时不中止" "$?" "0"
ok "并且退回把全部算成 overlay" \
   "$(python3 -c "import json;d=json.load(open('${d}/remote/status.json'));print(d['overlay'],d['deps'])" 2>/dev/null)" \
   "2 0"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 4 9
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "头部数量与实际不符时中止" "$?" "1"
contains "并且说明原因" "${out}" "索引头部写 9 个，实际列出 4 个"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 3
rm -f "${d}/stage/app-misc/p1-1.0-1.gpkg.tar"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "索引列出但暂存区不存在该包时中止" "$?" "1"
contains "并且指出是哪一个" "${out}" "p1-1.0-1.gpkg.tar"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 2
mkdir -p "${d}/remote/app-misc"
for ((i = 0; i < 20; i++)); do echo x > "${d}/remote/app-misc/old${i}-1.0-1.gpkg.tar"; done
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "清理比例超上限时以 3 退出" "$?" "3"
ok "并且一个旧包都没删" "$(find "${d}/remote" -name 'old*.gpkg.tar' | wc -l)" "20"
contains "并且说明如何强制" "${out}" "FORCE_RETIRE=1"

out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" FORCE_RETIRE=1 bash build/publish.sh 2>&1)
ok "FORCE_RETIRE=1 时正常清理" "$?" "0"
ok "清理后只剩索引里的那两个" "$(find "${d}/remote" -name '*.gpkg.tar' | wc -l)" "2"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 10
mkdir -p "${d}/remote/app-misc"
for ((i = 0; i < 10; i++)); do echo x > "${d}/remote/app-misc/p${i}-1.0-1.gpkg.tar"; done
echo x > "${d}/remote/app-misc/gone-1.0-1.gpkg.tar"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "正常一次退役少量包时正常执行" "$?" "0"
ok "退役的那一个已删除" "$(test -e "${d}/remote/app-misc/gone-1.0-1.gpkg.tar" && echo 在 || echo 无)" "无"
ok "索引里的仍然存在" "$(find "${d}/remote" -name 'p*.gpkg.tar' | wc -l)" "10"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 3
sed -i 's/^PACKAGES: 3$/PACKAGES: broken/' "${d}/stage/Packages"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "头部不是数字时中止" "$?" "1"
contains "并且说明原因" "${out}" "不是正整数"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 3
sed -i '/^PACKAGES: 3$/d' "${d}/stage/Packages"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "头部缺失时中止" "$?" "1"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 3
sed -i '2a PACKAGES: 3' "${d}/stage/Packages"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "头部出现两次时中止" "$?" "1"
contains "并且说明原因" "${out}" "应恰好一行"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 3
printf 'truncated' > "${d}/stage/app-misc/p1-1.0-1.gpkg.tar"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "暂存区文件大小与索引不符时中止" "$?" "1"
contains "并且指出是哪一个" "${out}" "p1-1.0-1.gpkg.tar"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 3
printf 'PACKAGES: 3\n' | gzip -c > "${d}/stage/Packages.gz"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "两份索引不同代时中止" "$?" "1"
contains "并且说明原因" "${out}" "内容不一致"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 8
mkdir -p "${d}/remote/app-misc"
for ((i = 0; i < 8; i++)); do echo x > "${d}/remote/app-misc/p${i}-1.0-1.gpkg.tar"; done
for ((i = 0; i < 2; i++)); do echo x > "${d}/remote/app-misc/old${i}-1.0-1.gpkg.tar"; done
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "恰好等于比例上限时也拦下" "$?" "3"
ok "并且未删除任何旧包" "$(find "${d}/remote" -name 'old*.gpkg.tar' | wc -l)" "2"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 400
mkdir -p "${d}/remote/app-misc"
for ((i = 0; i < 400; i++)); do echo x > "${d}/remote/app-misc/p${i}-1.0-1.gpkg.tar"; done
for ((i = 0; i < 70; i++)); do echo x > "${d}/remote/app-misc/old${i}-1.0-1.gpkg.tar"; done
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "比例没超但绝对数量超时仍拦下" "$?" "3"
ok "并且未删除任何旧包" "$(find "${d}/remote" -name 'old*.gpkg.tar' | wc -l)" "70"
rm -rf "${d}"

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

d=$(setup_mirror)
mirror_index "${d}" 3 9
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "头部数量与实际不符时中止" "$?" "1"
contains "并且说明原因" "${out}" "索引不完整"
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
mkdir -p "${d}/dest/app-misc"
for ((i = 0; i < 20; i++)); do echo x > "${d}/dest/app-misc/old${i}-1.0-1.gpkg.tar"; done
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      bash deploy/mirror-sync.sh 2>&1)
ok "清理比例超上限时以 3 退出" "$?" "3"
ok "并且未删除任何旧包" "$(find "${d}/dest" -name 'old*.gpkg.tar' | wc -l)" "20"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      FORCE_REMOVE=1 bash deploy/mirror-sync.sh 2>&1)
ok "FORCE_REMOVE=1 时正常清理" "$?" "0"
ok "清理后旧包不再存在" "$(find "${d}/dest" -name 'old*.gpkg.tar' | wc -l)" "0"
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
ok "恰好等于比例上限时也拦下" "$?" "3"
ok "并且未删除任何旧包" "$(find "${d}/dest" -name 'old*.gpkg.tar' | wc -l)" "2"
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
ok "大量新档不会把删除比例稀释掉" "$?" "3"
ok "并且旧文件均保留" "$(find "${d}/dest" -name 'old*.gpkg.tar' | wc -l)" "10"
rm -rf "${d}"

echo
echo "== site-sync.sh"

setup_site() {
    d=$(mktemp -d)
    mkdir -p "${d}/work/site/assets" "${d}/work/.git" "${d}/dest" "${d}/bin"
    echo "<html>" > "${d}/work/site/index.html"
    echo "body{}" > "${d}/work/site/assets/site.css"
    printf 'KEY\n' > "${d}/work/site/gentoo-zh-binhost.asc"
    cat > "${d}/bin/git" <<'EOF'
#!/bin/bash
case "$*" in
    *rev-parse*) echo 1111111111111111111111111111111111111111 ;;
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
ok "并且写下 DONE" "$(cat "${d}/work/.synced" 2>/dev/null)" "1111111111111111111111111111111111111111"
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
ok "页面也没有发布，本次不切换任何内容" "$(test -e "${d}/dest/index.html" && echo 有 || echo 无)" "无"
ok "assets 也没有发布" "$(test -d "${d}/dest/assets" && echo 有 || echo 无)" "无"
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
