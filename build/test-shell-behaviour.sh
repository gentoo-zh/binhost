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
        printf '  ✗ %s\n      输出里没有 %s\n' "$1" "$3"
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

echo "== publish.sh"

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
ok "索引列出但暂存区里没有该包时中止" "$?" "1"
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
    cat > "$1/bin/gpg" <<EOF
#!/bin/bash
echo "fpr:::::::::$2:"
EOF
    chmod +x "$1/bin/gpg"
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
