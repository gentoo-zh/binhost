#!/bin/bash

set -euo pipefail

OUT="${OUT:-/srv/mirrors/server-status.json}"

uptime_seconds=$(cut -d. -f1 /proc/uptime)

# The counters reset at boot, so uptime is published alongside them.
iface="${IFACE:-$(ip route show default 2>/dev/null | awk '{print $5; exit}')}"
[[ -n ${iface} ]] || iface=$(awk -F: 'NR>2 && $1 !~ /lo/ {gsub(/ /,"",$1); print $1; exit}' /proc/net/dev)
[[ -n ${iface} ]] || { echo "!! 找不到网卡，未写出 ${OUT}" >&2; exit 1; }

read -r rx tx < <(awk -F: -v want="${iface}" '
    NR>2 {gsub(/ /,"",$1); if ($1==want) {split($2,f," "); print f[1], f[9]}}' /proc/net/dev)
[[ ${rx:-} =~ ^[0-9]+$ && ${tx:-} =~ ^[0-9]+$ ]] ||
    { echo "!! 无法读取 ${iface} 的计数器，未写出 ${OUT}" >&2; exit 1; }

printf '{"uptime":%s,"rx":%s,"tx":%s,"generated":%s}\n' \
    "${uptime_seconds}" "${rx}" "${tx}" "$(date +%s)" > "${OUT}.new"
mv -f "${OUT}.new" "${OUT}"

echo "运行 ${uptime_seconds} 秒，${iface} 出站 ${tx} 字节 -> ${OUT}"
