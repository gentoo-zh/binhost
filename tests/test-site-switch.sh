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

OWNED=(gentoo-zh-binhost.asc robots.txt)

# Both owned files carry the generation's mark, so files from different runs
# show up as a mismatch. The page and assets stand in for anything else a
# source holds: none of it is published.
site() {
    local d="$1" mark="$2"
    mkdir -p "${d}/assets"
    printf 'key %s\n' "${mark}" > "${d}/gentoo-zh-binhost.asc"
    printf 'user-agent: %s\n' "${mark}" > "${d}/robots.txt"
    printf '<p>%s</p>\n' "${mark}" > "${d}/index.html"
    printf '/* %s */\n' "${mark}" > "${d}/assets/site.css"
}

# The publisher refuses to run without a fingerprint file and a key that
# matches it, so both are supplied. Only the switch is under test here.
setup() {
    local d
    d=$(mktemp -d)
    mkdir -p "${d}/bin" "${d}/src" "${d}/dest"
    cat > "${d}/bin/gpg" <<'EOF'
#!/bin/bash
printf 'pub:u:255:22::::::::scSC:\nfpr:::::::::AAAA0000000000000000000000000000000000AA:\n'
EOF
    chmod +x "${d}/bin/gpg"
    echo AAAA0000000000000000000000000000000000AA > "${d}/fpr"
    echo "${d}"
}

publish() {
    local d="$1"
    PATH="${d}/bin:${PATH}" FPR_FILE="${d}/fpr" \
        bash "${ROOT}/deploy/publish-site.sh" "${d}/src" "${d}/dest" 2>&1
}

# Every mark the owned files carry, collapsed. Two marks means they came from
# different runs.
marks() {
    local d="$1" f out=""
    for f in "${OWNED[@]}"; do
        out+=$(grep -ho '[A-Z]' "${d}/dest/${f}" 2>/dev/null | head -1)
    done
    fold -w1 <<< "${out}" | sort -u | tr -d '\n'
}

linked() {
    local d="$1" name n=0
    for name in "${OWNED[@]}"; do
        [[ $(readlink "${d}/dest/${name}" 2>/dev/null) == ".site/${name}" ]] &&
            n=$((n + 1))
    done
    echo "${n}"
}

leftovers() {
    find "$1/dest" -maxdepth 1 \
        \( -name '.switch-*' -o -name '.site-seed-*' -o -name '.replaced-*' \) | wc -l
}

# The daily jobs write these into the same directory; the publisher must
# never copy or delete them.
DATA=(packages.json packages.txt packages-unstable.json packages-unstable.txt
      deps.txt deps-unstable.txt distfiles-index.json distfiles-status.json .health)

data_intact() {
    local d="$1" f n=0
    for f in "${DATA[@]}"; do
        [[ ! -L ${d}/dest/${f} && $(cat "${d}/dest/${f}" 2>/dev/null) == "data ${f}" ]] &&
            n=$((n + 1))
    done
    echo "${n}"
}

echo "== 首次发布：目标里已经有普通文件"
d=$(setup)
site "${d}/src" A
printf 'key A\n' > "${d}/dest/gentoo-zh-binhost.asc"
printf 'user-agent: A\n' > "${d}/dest/robots.txt"
out=$(publish "${d}")
ok "退出码为零" "$?" "0"
ok "读到的还是同一代" "$(marks "${d}")" "A"
ok "两个名称都指向 .site" "$(linked "${d}")" "2"
ok "页面与 assets 不发布" \
   "$(find "${d}/dest" \( -name '*.html' -o -name assets -o -name '*.css' \) | wc -l)" "0"
ok "不留临时档" "$(leftovers "${d}")" "0"

echo
echo "== 再次发布：公钥与 robots.txt 一起换代"
site "${d}/src" B
publish "${d}" >/dev/null
ok "两份同为新一代" "$(marks "${d}")" "B"
ok "两个名称仍然指向 .site" "$(linked "${d}")" "2"
ok "上一代目录已移除" \
   "$(find "${d}/dest" -maxdepth 1 -name '.site-*' -type d | wc -l)" "1"
ok "不留临时档" "$(leftovers "${d}")" "0"

echo
echo "== 每日任务写在同一个目录里的文件不受影响"
for f in "${DATA[@]}"; do printf 'data %s\n' "${f}" > "${d}/dest/${f}"; done
site "${d}/src" C
# A source that happens to hold a data file's name must not overwrite it.
printf 'from site\n' > "${d}/src/packages.json"
publish "${d}" >/dev/null
ok "数据档全部原样保留" "$(data_intact "${d}")" "${#DATA[@]}"
ok "站点仍然换到新一代" "$(marks "${d}")" "C"

echo
echo "== 仓库中移除 robots.txt 后它一并下线"
rm -f "${d}/src/robots.txt"
publish "${d}" >/dev/null
ok "robots.txt 已下线" \
   "$(find "${d}/dest" -maxdepth 1 -name robots.txt | wc -l)" "0"
ok "公钥照常" "$(cat "${d}/dest/gentoo-zh-binhost.asc")" "key C"
ok "数据档仍然没被动" "$(data_intact "${d}")" "${#DATA[@]}"
rm -rf "${d}"

echo
echo "== 半转换的目录：种子取每个名称当下解析到的内容"
# One name gets replaced by hand after a normal publication, so the tree is part
# links and part plain files. The transfer is then made to fail, which leaves the
# seed serving the site: everything has to still read, links included.
d=$(setup)
site "${d}/src" A
publish "${d}" >/dev/null
rm -f "${d}/dest/robots.txt"
printf 'user-agent: D\n' > "${d}/dest/robots.txt"
cat > "${d}/bin/rsync" <<'EOF'
#!/bin/bash
exit 23
EOF
chmod +x "${d}/bin/rsync"
site "${d}/src" B
out=$(publish "${d}")
rc=$?
ok "退出码非零" "$((rc != 0))" "1"
ok "读的是种子那一代" \
   "$([[ $(readlink "${d}/dest/.site") == .site-seed-* ]] && echo 是 || echo 否)" "是"
ok "两个名称都读得到" \
   "$(for n in "${OWNED[@]}"; do [[ -s ${d}/dest/${n} ]] || echo x; done | wc -l)" "0"
ok "手动放的那份没有被换掉" "$(marks "${d}")" "AD"
rm -rf "${d}"

echo
echo "== .site 不是链接时拒绝动手"
d=$(setup)
site "${d}/src" A
site "${d}/dest" Z
mkdir "${d}/dest/.site"
out=$(publish "${d}")
rc=$?
ok "退出码非零" "$((rc != 0))" "1"
ok "说明 .site 不是链接" "$([[ ${out} == *符号链接* ]] && echo yes)" "yes"
ok "一个名称都没有改成链接" "$(linked "${d}")" "0"
ok "内容没有被换掉" "$(marks "${d}")" "Z"
rm -rf "${d}"

echo
echo "== 来源不是站点目录时不发布"
d=$(setup)
site "${d}/src" A
publish "${d}" >/dev/null
rm -f "${d}/src/gentoo-zh-binhost.asc"
out=$(publish "${d}")
rc=$?
ok "退出码非零" "$((rc != 0))" "1"
ok "说明来源缺公钥" \
   "$([[ ${out} == *未包含\ gentoo-zh-binhost.asc* ]] && echo yes)" "yes"
ok "已发布的站点原样保留" "$(marks "${d}")" "A"
ok "两个名称仍然指向 .site" "$(linked "${d}")" "2"
rm -rf "${d}"

echo
echo "== 切换失败时留在上一代"
if (( EUID == 0 )); then
    echo "  - 以 root 执行，权限拦不住 rename，本项跳过"
else
    d=$(setup)
    site "${d}/src" A
    publish "${d}" >/dev/null
    site "${d}/src" B
    chmod 500 "${d}/dest"
    out=$(publish "${d}")
    rc=$?
    chmod 700 "${d}/dest"
    ok "退出码非零" "$((rc != 0))" "1"
    ok "读到的仍是上一代" "$(marks "${d}")" "A"
    ok "两个名称仍然指向 .site" "$(linked "${d}")" "2"
    rm -rf "${d}"
fi

echo
if (( fail )); then
    echo ">>> ${fail} 项未通过，${pass} 项通过"
    exit 1
fi
echo ">>> ${pass} 项全部通过"
