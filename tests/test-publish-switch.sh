#!/bin/bash

set -uo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
REAL_RSYNC=$(command -v rsync)
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

FILES=(Packages Packages.gz installed.txt official.txt source.txt generation.json)

# The switch runs on the mirror over ssh. Under test is what it does to the
# directory, not the transport, so the block is cut out of build/publish.sh and
# run against a local directory. Cutting it keeps the assertions bound to the
# file that is deployed.
extract() {
    sed -n "/<<'SWITCH'/,/^SWITCH\$/p" "${ROOT}/build/publish.sh" |
        sed -e 1d -e '$d'
}

# One published root, six regular files, the state every mirror is in today.
published() {
    local d mark
    d=$(mktemp -d)
    mark="$1"
    for name in "${FILES[@]}"; do
        printf '%s-%s\n' "${mark}" "${name}" > "${d}/${name}"
    done
    echo "${d}"
}

generation() {
    local d="$1" gen="$2" mark="$3" name
    mkdir -p "${d}/${gen}"
    for name in "${FILES[@]}"; do
        printf '%s-%s\n' "${mark}" "${name}" > "${d}/${gen}/${name}"
    done
}

switch() {
    local d="$1" gen="$2"
    ( cd "${d}" && sh "${d}/switch.sh" "${d}" "${gen}" "${FILES[@]}" ) 2>&1
}

setup() {
    local d="$1"
    extract > "${d}/switch.sh"
}

# What every one of the six reads, collapsed to one line. Any name lagging a
# generation behind shows up as a second mark in this string.
marks() {
    local d="$1" name out=""
    for name in "${FILES[@]}"; do
        out+="$(cut -d- -f1 < "${d}/${name}" 2>/dev/null || echo 无)"
    done
    tr ' ' '\n' <<< "${out}" | fold -w1 | sort -u | tr -d '\n'
}

linked() {
    local d="$1" name n=0
    for name in "${FILES[@]}"; do
        [[ $(readlink "${d}/${name}" 2>/dev/null) == ".gen/${name}" ]] &&
            n=$((n + 1))
    done
    echo "${n}"
}

leftovers() {
    find "$1" -maxdepth 1 \( -name '.switch-*' -o -name '.gen-seed-*' \) | wc -l
}

# Run the complete publisher against a local directory. These wrappers preserve
# stdin and execute the same remote shell blocks and rsync file lists, so the
# assertions below cover their filesystem effects instead of their source text.
transport() {
    local d="$1"
    mkdir -p "${d}/bin"
    cat > "${d}/bin/ssh" <<'EOF'
#!/bin/bash
shift
exec /bin/sh -c "$*"
EOF
    cat > "${d}/bin/rsync" <<'EOF'
#!/bin/bash
set -eu
args=()
for arg in "$@"; do
    case ${arg} in
        fixture:*) arg=${arg#fixture:} ;;
    esac
    args+=("${arg}")
done
exec "${REAL_RSYNC}" "${args[@]}"
EOF
    chmod +x "${d}/bin/ssh" "${d}/bin/rsync"
}

package_generation() {
    local generation_root="$1" payload_root="$2" mark="$3" path size i=0
    shift 3
    mkdir -p "${generation_root}" "${payload_root}"
    {
        printf 'ACCEPT_KEYWORDS: amd64\nARCH: amd64\n'
        printf 'PACKAGES: %s\nTIMESTAMP: 1700000000\nVERSION: 0\n\n' "$#"
        for path in "$@"; do
            i=$((i + 1))
            mkdir -p "${payload_root}/$(dirname "${path}")"
            printf '%s-%s\n' "${mark}" "${path}" > "${payload_root}/${path}"
            size=$(stat -c %s "${payload_root}/${path}")
            (( i == 1 )) || printf '\n'
            printf 'CPV: app-misc/pkg%s-1\nPATH: %s\nREPO: gentoo-zh\nSIZE: %s\nSLOT: 0\n' \
                "${i}" "${path}" "${size}"
        done
    } > "${generation_root}/Packages"
    gzip -n -c "${generation_root}/Packages" > "${generation_root}/Packages.gz"
    printf 'installed\n' > "${generation_root}/installed.txt"
    printf 'official\n' > "${generation_root}/official.txt"
    printf 'source\n' > "${generation_root}/source.txt"
    python3 "${ROOT}/build/generation.py" create "${generation_root}"
}

link_generation() {
    local public="$1" gen="$2" name
    ln -s "${gen}" "${public}/.gen"
    for name in "${FILES[@]}"; do
        ln -s ".gen/${name}" "${public}/${name}"
    done
}

run_publish() {
    local root="$1" stage="$2" public="$3" run_id="$4"
    PATH="${root}/bin:${PATH}" REAL_RSYNC="${REAL_RSYNC}" \
        CHANNEL=stable STAGE="${stage}" REMOTE=fixture REMOTE_ROOT="${public}" \
        LOCK_DIR="${public}/.publish.lock" RUN_ID="${run_id}" \
        bash "${ROOT}/build/publish.sh"
}

echo "== 首次切换：六个名称变成链接，内容不变"
# The identity generation carries exactly what is already published. If turning
# the six names into links changed anything, this is where it would show.
d=$(published a)
setup "${d}"
generation "${d}" .gen-run1 a
out=$(switch "${d}" .gen-run1)
ok "退出码为零" "$?" "0"
ok "内容没有改变" "$(marks "${d}")" "a"
ok "六个名称都指向 .gen" "$(linked "${d}")" "6"
ok ".gen 指向本次的代际目录" "$(readlink "${d}/.gen")" ".gen-run1"
ok "不留临时档" "$(leftovers "${d}")" "0"

echo
echo "== 再次切换：一次 rename 换掉全部六个"
generation "${d}" .gen-run2 b
switch "${d}" .gen-run2 >/dev/null
ok "六个都读到新一代" "$(marks "${d}")" "b"
ok "六个名称仍然指向 .gen" "$(linked "${d}")" "6"
ok "上一代目录已移除" \
   "$(test -d "${d}/.gen-run1" && echo 在 || echo 已移除)" "已移除"
ok "本次的代际目录保留" \
   "$(test -d "${d}/.gen-run2" && echo 在 || echo 不在)" "在"
ok "不留临时档" "$(leftovers "${d}")" "0"
rm -rf "${d}"

echo
echo "== 代际目录不完整时不切换"
d=$(published a)
setup "${d}"
generation "${d}" .gen-run1 a
switch "${d}" .gen-run1 >/dev/null
generation "${d}" .gen-run2 b
rm -f "${d}/.gen-run2/Packages.gz"
out=$(switch "${d}" .gen-run2)
rc=$?
ok "退出码非零" "$((rc != 0))" "1"
ok "说出缺的是哪一个" "$([[ ${out} == *Packages.gz* ]] && echo yes)" "yes"
ok "仍然读到上一代" "$(marks "${d}")" "a"
ok ".gen 没有改变" "$(readlink "${d}/.gen")" ".gen-run1"
printf 'x\n' > "${d}/.gen-run2/Packages.gz"
: > "${d}/.gen-run2/source.txt"
out=$(switch "${d}" .gen-run2)
ok "空档也算缺" "$([[ ${out} == *source.txt* ]] && echo yes)" "yes"
ok "空档时仍读上一代" "$(marks "${d}")" "a"
rm -rf "${d}"

echo
echo "== 首次切换时代际不完整：停在旧内容上"
# The abort has to leave the six reading what they read before this run. The
# seed is what they read through at that point, so this is also the only place
# the seed's content is observable from outside.
d=$(published a)
setup "${d}"
generation "${d}" .gen-run1 b
rm -f "${d}/.gen-run1/official.txt"
out=$(switch "${d}" .gen-run1)
rc=$?
ok "退出码非零" "$((rc != 0))" "1"
ok "六个仍然读到旧内容" "$(marks "${d}")" "a"
ok "没有失效的名称" \
   "$(for n in "${FILES[@]}"; do [[ -e ${d}/${n} ]] || echo x; done | wc -l)" "0"
ok "没有切到这一代" \
   "$([[ $(readlink "${d}/.gen") == .gen-run1 ]] && echo 切了 || echo 没切)" "没切"
ok "六个名称已经是链接" "$(linked "${d}")" "6"
ok "读的是种子那一代" \
   "$([[ $(readlink "${d}/.gen") == .gen-seed-* ]] && echo 是 || echo 否)" "是"
rm -rf "${d}"

echo
echo "== 半转换的根遇上不完整的代际：种子里是各名称当下解析到的内容"
d=$(published a)
setup "${d}"
generation "${d}" .gen-run1 a
switch "${d}" .gen-run1 >/dev/null
rm -f "${d}/Packages"
printf 'c-Packages\n' > "${d}/Packages"
generation "${d}" .gen-run2 b
rm -f "${d}/.gen-run2/official.txt"
switch "${d}" .gen-run2 >/dev/null
ok "读的是种子那一代" \
   "$([[ $(readlink "${d}/.gen") == .gen-seed-* ]] && echo 是 || echo 否)" "是"
ok "手动放的那份没有被换掉" "$(cat "${d}/Packages")" "c-Packages"
ok "其余五个还是上一代" \
   "$(cat "${d}/source.txt" "${d}/official.txt" | sort -u | cut -d- -f1 | sort -u | tr -d '\n')" "a"
rm -rf "${d}"

echo
echo "== .gen 不是链接时拒绝动手"
d=$(published a)
setup "${d}"
mkdir "${d}/.gen"
generation "${d}" .gen-run1 b
out=$(switch "${d}" .gen-run1)
rc=$?
ok "退出码非零" "$((rc != 0))" "1"
ok "说明 .gen 不是链接" "$([[ ${out} == *符号链接* ]] && echo yes)" "yes"
ok "六个名称没有被改成链接" "$(linked "${d}")" "0"
ok "内容没有被换掉" "$(marks "${d}")" "a"
rm -rf "${d}"

echo
echo "== 只有部分名称是链接时也不会读到空"
# Someone replaces one name by hand and the root is half converted. Seeding has
# to take what each name resolves to, or the five that are already links point
# into a seed that does not hold them.
d=$(published a)
setup "${d}"
generation "${d}" .gen-run1 a
switch "${d}" .gen-run1 >/dev/null
rm -f "${d}/Packages"
printf 'c-Packages\n' > "${d}/Packages"
generation "${d}" .gen-run2 b
out=$(switch "${d}" .gen-run2)
rc=$?
ok "退出码为零" "${rc}" "0"
ok "没有报不一致" "$([[ ${out} == *不一致* ]] && echo yes)" ""
ok "六个都读到新一代" "$(marks "${d}")" "b"
ok "六个名称都是链接" "$(linked "${d}")" "6"
ok "没有悬空的名称" \
   "$(for n in "${FILES[@]}"; do [[ -e ${d}/${n} ]] || echo x; done | wc -l)" "0"
rm -rf "${d}"

echo
echo "== rename 失败时留在上一代"
if (( EUID == 0 )); then
    echo "  - 以 root 执行，权限拦不住 rename，本项跳过"
else
    d=$(published a)
    setup "${d}"
    generation "${d}" .gen-run1 a
    switch "${d}" .gen-run1 >/dev/null
    generation "${d}" .gen-run2 b
    chmod 500 "${d}"
    out=$(switch "${d}" .gen-run2)
    rc=$?
    chmod 700 "${d}"
    ok "退出码非零" "$((rc != 0))" "1"
    ok "六个仍然是上一代" "$(marks "${d}")" "a"
    ok ".gen 仍指向上一代" "$(readlink "${d}/.gen")" ".gen-run1"
    ok "上一代目录还在" \
       "$(test -d "${d}/.gen-run1" && echo 在 || echo 不在)" "在"
    rm -rf "${d}"
fi

echo
echo "== 完整发布：隔离删除与修剪代际都改变临时公开根"
effects_root=$(mktemp -d)
trap 'rm -rf "${effects_root}"' EXIT
transport "${effects_root}"
public="${effects_root}/public-prune"
stage="${effects_root}/stage-prune"
mkdir -p "${public}/.gen-live" "${stage}"
denied=app-misc/denied-1.gpkg.tar
retained=app-misc/retained-1.gpkg.tar
package_generation "${public}/.gen-live" "${public}" old "${denied}" "${retained}"
link_generation "${public}" .gen-live
printf '%s\n' "${denied}" > "${stage}/quarantine.txt"
printf 'PATH: app-misc/next-1.gpkg.tar\n' > "${stage}/Packages"
printf 'test stop after quarantine\n' > "${stage}/publish-blocked.txt"
out=$(run_publish "${effects_root}" "${stage}" "${public}" prune-run 2>&1)
rc=$?
ok "发布按预设闸门停止" "$((rc != 0))" "1"
ok "隔离包体确实从公开路径移除" \
   "$(test -e "${public}/${denied}" && echo 在 || echo 已移除)" "已移除"
ok "未被隔离的包体仍在原路径" \
   "$(cat "${public}/${retained}" 2>/dev/null)" "old-${retained}"
ok "公开索引已经移除隔离路径" \
   "$(grep -cF "PATH: ${denied}" "${public}/Packages")" "0"
ok "公开索引仍保留原代际的其他内容" \
   "$(grep -cF "PATH: ${retained}" "${public}/Packages")" "1"
ok "修剪后代际通过独立清单验证" \
   "$(python3 "${ROOT}/build/generation.py" verify "${public}/.gen" >/dev/null 2>&1; echo $?)" "0"

echo
echo "== 完整发布：新 PATH 在指定公开根取得到"
public="${effects_root}/public-upload"
stage="${effects_root}/stage-upload"
uploaded=app-misc/uploaded-1.gpkg.tar
package_generation "${stage}" "${stage}" new "${uploaded}"
out=$(run_publish "${effects_root}" "${stage}" "${public}" upload-run 2>&1)
rc=$?
ok "完整发布成功" "${rc}" "0"
ok "新 PATH 位于指定公开根" \
   "$(cat "${public}/${uploaded}" 2>/dev/null)" "new-${uploaded}"
ok "公开索引列出的 PATH 可以取得" \
   "$(path=$(awk '/^PATH: /{print $2; exit}' "${public}/Packages"); \
      test -s "${public}/${path}" && echo yes)" "yes"
ok "发布锁已经释放" \
   "$(test -d "${public}/.publish.lock" && echo 在 || echo 已释放)" "已释放"
rm -rf "${effects_root}"
trap - EXIT

echo
echo "== publish.sh 按这个形状使用它"
# The patterns below name shell variables, so the dollar sign is injected
# rather than written inside single quotes.
d1='$'
ok "六个档案只列一次" \
   "$(grep -c '^GEN_FILES=(Packages Packages.gz installed.txt official.txt source.txt generation.json)$' \
      "${ROOT}/build/publish.sh")" "1"
ok "代际目录带上本次执行的编号" \
   "$(grep -c "^GEN=\"\.gen-${d1}{RUN_ID}\"${d1}" "${ROOT}/build/publish.sh")" "1"
at() { grep -nF -e "$1" "${ROOT}/build/publish.sh" | cut -d: -f1; }
call_line=$(at "switch_generation \"${d1}{GEN}\" \"${d1}{STAGE}\"")
packages_line=$(at '--info=stats2 --files-from=-')
ok "这两行各只找到一处" \
   "$(printf '%s %s' "${call_line}" "${packages_line}")" \
   "$(printf '%s %s' "${call_line}" "${packages_line}" |
      grep -o '^[1-9][0-9]* [1-9][0-9]*$')"
ok "包体先传上去，最后才切换" "$(( ${packages_line:-0} < ${call_line:-0} ))" "1"
ok "代际目录由切换函数自己建立" \
   "$(grep -c "install -dm755 '${d1}{REMOTE_ROOT}/${d1}{gen}'" \
      "${ROOT}/build/publish.sh")" "1"

echo
if (( fail )); then
    echo ">>> ${fail} 项未通过，${pass} 项通过"
    exit 1
fi
echo ">>> ${pass} 项全部通过"
