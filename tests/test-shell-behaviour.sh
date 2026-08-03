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
    printf '%s %s %s %s %s\n' \
        "$(test -e "${dest}/gentoo-zh-binhost.asc" && echo asc || echo noasc)" \
        "$(test -e "${dest}/gone.html" && echo kept || echo removed)" \
        "$(test -e "${dest}/assets/removed.css" && echo kept || echo removed)" \
        "$(tr -d '\n' < "${dest}/index.html" 2>/dev/null)" \
        "$(tr -d '\n' < "${dest}/same.html" 2>/dev/null)"
    rm -rf "${d}"
}
read -r a b c dd ee <<< "$(pubsite)"
ok "公钥会发布" "${a}" "asc"
ok "来源中已不存在的页面会一并移除" "${b}" "removed"
ok "assets 里多余的文件也会移除" "${c}" "removed"
ok "页面内容已更新" "${dd}" "<p>new</p>"
ok "同大小同 mtime 但内容不同时仍然更新" "${ee}" "AAAA"

echo "== status.sh 的部署版本核对"

version_probe() {
    local ver="$1" sha_out="$2" d out
    d=$(mktemp -d); mkdir -p "${d}/bin"
    cat > "${d}/bin/curl" <<EOF
#!/bin/bash
case "\$*" in
  *commits/master*) ${sha_out} ;;
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
        SITE_DEST="${d}/nodest" MONITORS_FILE="${d}/nomon" \
        bash build/status.sh 2>&1 | grep '部署版本' )
    rm -rf "${d}"
    case "${out}" in *'<--'*) echo failed ;; *) echo passed ;; esac
}

SHA40=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
SAME='echo "  \"sha\": \"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\","'
ok "VERSION 带 -dirty 时算故障" "$(version_probe "${SHA40}-dirty" 'exit 22')" "failed"
ok "VERSION 不是提交号时算故障" "$(version_probe not-a-sha 'exit 22')" "failed"
ok "无法获取目标版本时算故障，不再当成通过" "$(version_probe "${SHA40}" 'exit 22')" "failed"
ok "版本一致时才算通过" "$(version_probe "${SHA40}" "${SAME}")" "passed"

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
contains "输出说明它不受上限约束" "${out}" "不受清理上限约束"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 2
mkdir -p "${d}/remote/app-misc"
echo x > "${d}/remote/app-misc/banned-1.0-1.gpkg.tar"
printf '../../etc/passwd\n' > "${d}/stage/quarantine.txt"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "隔离清单里的越界路径被拒绝" "$?" "1"
contains "并且说明本轮不继续" "${out}" "本轮不再继续"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 2
printf '2\n7\n' > "${d}/stage/counts.txt"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "有 counts.txt 时照常发布" "$?" "0"
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
ok "FORCE_RETIRE=1 时照常清理" "$?" "0"
ok "清理后只剩索引里的那两个" "$(find "${d}/remote" -name '*.gpkg.tar' | wc -l)" "2"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 10
mkdir -p "${d}/remote/app-misc"
for ((i = 0; i < 10; i++)); do echo x > "${d}/remote/app-misc/p${i}-1.0-1.gpkg.tar"; done
echo x > "${d}/remote/app-misc/gone-1.0-1.gpkg.tar"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "正常一轮退役少量包时照常执行" "$?" "0"
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
ok "并且一个都没删" "$(find "${d}/remote" -name 'old*.gpkg.tar' | wc -l)" "2"
rm -rf "${d}"

d=$(setup_publish)
stage_index "${d}" 400
mkdir -p "${d}/remote/app-misc"
for ((i = 0; i < 400; i++)); do echo x > "${d}/remote/app-misc/p${i}-1.0-1.gpkg.tar"; done
for ((i = 0; i < 70; i++)); do echo x > "${d}/remote/app-misc/old${i}-1.0-1.gpkg.tar"; done
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" STAGE="${d}/stage" REMOTE=x \
      REMOTE_ROOT="${d}/remote" bash build/publish.sh 2>&1)
ok "比例没超但绝对数量超时仍拦下" "$?" "3"
ok "并且一个都没删" "$(find "${d}/remote" -name 'old*.gpkg.tar' | wc -l)" "70"
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
ok "并且一个都没删" "$(find "${d}/dest" -name 'old*.gpkg.tar' | wc -l)" "20"
out=$(cd "${ROOT}" && PATH="${d}/bin:${PATH}" BASE="https://x/x86-64" DEST="${d}/dest" \
      FORCE_REMOVE=1 bash deploy/mirror-sync.sh 2>&1)
ok "FORCE_REMOVE=1 时照常清理" "$?" "0"
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
ok "并且一个都没删" "$(find "${d}/dest" -name 'old*.gpkg.tar' | wc -l)" "2"
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
ok "并且旧档一个都没删" "$(find "${d}/dest" -name 'old*.gpkg.tar' | wc -l)" "10"
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
ok "并且不写 DONE，下一轮会重试" "$(test -e "${d}/work/.synced" && echo 有 || echo 无)" "无"
ok "公钥没有发布" "$(test -e "${d}/dest/gentoo-zh-binhost.asc" && echo 有 || echo 无)" "无"
ok "页面也没有发布，本轮不切换任何内容" "$(test -e "${d}/dest/index.html" && echo 有 || echo 无)" "无"
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
