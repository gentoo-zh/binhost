#!/bin/bash

set -euo pipefail

SRC="${1:?用法： $0 <site 目录> [目标目录]}"
DEST="${2:-${DEST:-/srv/mirrors}}"
FPR_FILE="${FPR_FILE:-/etc/binhost/signing-key.fpr}"

[[ -d ${SRC} ]] || { echo "!! ${SRC} 不存在" >&2; exit 1; }
[[ -r ${SRC}/gentoo-zh-binhost.asc ]] ||
    { echo "!! ${SRC} 未包含 gentoo-zh-binhost.asc" >&2; exit 1; }
# A wrong source directory would otherwise publish a generation without pages
# and take the site down in one rename.
[[ -r ${SRC}/index.html ]] ||
    { echo "!! ${SRC} 未包含 index.html" >&2; exit 1; }

if [[ ! -r ${FPR_FILE} ]]; then
    echo "!! ${FPR_FILE} 不存在，不发布任何内容" >&2
    exit 1
fi

mapfile -t want < <(tr -d ' \r' < "${FPR_FILE}" | grep -oE '[0-9A-Fa-f]{40}' | tr 'a-f' 'A-F')
mapfile -t got < <(gpg --with-colons --show-keys "${SRC}/gentoo-zh-binhost.asc" 2>/dev/null |
                   awk -F: '$1=="pub"{p=1;next} $1=="sub"{p=0} $1=="fpr"&&p{print $10;p=0}')
unexpected=()
for g in "${got[@]}"; do
    [[ " ${want[*]} " == *" ${g} "* ]] || unexpected+=("${g}")
done
if (( ${#want[@]} == 0 || ${#got[@]} == 0 || ${#unexpected[@]} )); then
    echo "!! 公钥未通过校验，不发布任何内容" >&2
    echo "   本机记录的指纹：${want[*]:-无}" >&2
    echo "   来源中的指纹：${got[*]:-无}" >&2
    echo "   记录之外的指纹：${unexpected[*]:-无}" >&2
    exit 1
fi

RUN_ID="${RUN_ID:-$$-$(date +%s)}"
GEN=".site-${RUN_ID}"

# The pages carry fingerprinted asset URLs, so a page from one publication and
# an asset from another is a broken site. Everything the site owns is therefore
# a link into .site/, and .site is a link to the directory this run built:
# replacing all of it is the one rename at the end.
#
# DEST is not itself a generation directory because the daily jobs write
# packages.json, deps.txt and the status files straight into it. One list
# decides both what is copied and what may be deleted, and none of those job
# outputs can match it.
OWNED=('/assets/***' '/gentoo-zh-binhost.asc' '/*.html' '/robots.txt')

owns() {
    local name="$1" pattern
    for pattern in "${OWNED[@]}"; do
        pattern=${pattern#/}
        pattern=${pattern%/\*\*\*}
        # shellcheck disable=SC2053  # pattern is a glob, matching is the point
        if [[ ${name} == ${pattern} ]]; then
            return 0
        fi
    done
    return 1
}

owned_names() {
    local dir="$1" name
    for name in "${dir}"/*; do
        name=$(basename "${name}")
        [[ -e ${dir}/${name} ]] || continue
        owns "${name}" && printf '%s\n' "${name}"
    done
}

[[ -d ${DEST} ]] || { echo "!! ${DEST} 不存在" >&2; exit 1; }
cd "${DEST}" || { echo "!! 无法进入 ${DEST}" >&2; exit 1; }

if [[ -e .site && ! -L .site ]]; then
    echo "!! ${DEST}/.site 不是符号链接，无法切换代际" >&2
    exit 1
fi

# Conversion runs before the transfer, so a transfer that dies leaves a tree
# that is already linked and still serving exactly what it served before.
mapfile -t names < <(owned_names "${SRC}")
relink=0
for name in "${names[@]}"; do
    [[ -L ${name} ]] || relink=1
done
if (( relink )); then
    seed=".site-seed-${RUN_ID}"
    rm -rf "${seed}" && mkdir "${seed}" || exit 1
    for name in "${names[@]}"; do
        [[ -e ${name} ]] || continue
        cp -aL "${name}" "${seed}/${name}" || exit 1
    done
    ln -sfn "${seed}" ".switch-${RUN_ID}" && mv -Tf ".switch-${RUN_ID}" .site || exit 1
    for name in "${names[@]}"; do
        # rename(2) refuses to put a symlink where a directory is, so assets has
        # to move aside first. Those two renames are the only moment this design
        # is not atomic, they happen once, and the seed already serves the same
        # bytes on either side of them.
        if [[ -d ${name} && ! -L ${name} ]]; then
            mv -T "${name}" ".replaced-${RUN_ID}-${name}" || exit 1
        fi
        ln -sfn ".site/${name}" ".switch-${RUN_ID}" &&
            mv -Tf ".switch-${RUN_ID}" "${name}" || exit 1
    done
    rm -rf ".replaced-${RUN_ID}-"*
fi

rsync -a --checksum --safe-links \
    "${OWNED[@]/#/--include=}" --exclude='*' \
    "${SRC}/" "${DEST}/${GEN}/"

ln -sfn "${GEN}" ".switch-${RUN_ID}" || exit 1
mv -Tf ".switch-${RUN_ID}" .site || { rm -f ".switch-${RUN_ID}"; exit 1; }

# A page the repository dropped goes with it, the same as the old --delete did.
for name in *; do
    owns "${name}" || continue
    [[ -e ${GEN}/${name} ]] || rm -rf "${name}"
done

for old in .site-*; do
    [[ -d ${old} ]] || continue
    [[ ${old} == "${GEN}" ]] || rm -rf "${old}"
done
