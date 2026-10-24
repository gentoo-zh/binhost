#!/bin/bash
# Test a project nginx config before it replaces the live one.
#
# The config names its includes and the listing stylesheet by absolute path
# under /etc/nginx/conf.d, so nginx -t on an unchanged copy reads the files
# already installed there: a first install fails on a file that is not there
# yet, and a leftover file hides one the new config no longer ships. This copies
# nginx.conf and every *.conf, *.inc and *.xsl beside it into <stage>, writes
# copies under <stage>/check whose conf.d paths point at <stage>/check, and
# tests those. Every *.conf other than nginx.conf is a conf.d vhost.
# The system module directory and mime types stay where the system keeps them.
# The files in <stage> itself are not rewritten; they are what gets installed.

set -euo pipefail

SRC="${1:?用法：$0 <配置来源目录> <暂存目录> <mime.types 路径>}"
STAGE="${2:?用法：$0 <配置来源目录> <暂存目录> <mime.types 路径>}"
MIME="${3:?用法：$0 <配置来源目录> <暂存目录> <mime.types 路径>}"
CONF_D=/etc/nginx/conf.d

[[ -e ${STAGE} ]] && { echo "!! ${STAGE} 已存在，暂存目录必须是新的" >&2; exit 1; }
for f in nginx.conf distfiles.conf; do
    [[ -r ${SRC}/${f} ]] || { echo "!! ${SRC} 未包含 ${f}" >&2; exit 1; }
done

shopt -s nullglob
parts=()
for f in "${SRC}"/*.conf "${SRC}"/*.inc "${SRC}"/*.xsl; do
    [[ ${f} == "${SRC}/nginx.conf" ]] || parts+=("${f}")
done
mkdir -p "${STAGE}/check/conf.d"
STAGE=$(cd "${STAGE}" && pwd)
CHECK="${STAGE}/check"
cp -- "${SRC}/nginx.conf" "${parts[@]}" "${STAGE}/"

# Point only the paths this script copied at the stage.
repoint=()
for f in "${parts[@]}"; do
    name=$(basename "${f}")
    repoint+=(-e "s|${CONF_D}/${name//./\\.};|${CHECK}/conf.d/${name};|g")
done
for f in "${parts[@]}"; do
    name=$(basename "${f}")
    sed "${repoint[@]}" "${STAGE}/${name}" > "${CHECK}/conf.d/${name}"
done
sed -e 's|include modules-enabled/\*\.conf;|include /etc/nginx/modules-enabled/*.conf;|' \
    -e "s|include mime\.types\.nginx;|include ${MIME};|" \
    -e "s|include ${CONF_D}/\*\.conf;|include ${CHECK}/conf.d/*.conf;|" \
    "${STAGE}/nginx.conf" > "${CHECK}/nginx.conf"

# A conf.d path left over names a file this config does not ship, and the test
# would pass on whatever an earlier install left there.
if left=$(grep -rn "${CONF_D}/" "${CHECK}"); then
    echo "!! 配置引用了未随仓库提供的文件：" >&2
    printf '   %s\n' "${left}" >&2
    exit 1
fi

run=()
(( EUID == 0 )) || run=(sudo)
"${run[@]}" nginx -t -c "${CHECK}/nginx.conf"
