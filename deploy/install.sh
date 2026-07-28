#!/bin/bash
# 把这个仓库装到镜像机上。在本机执行，通过 ssh 作用于目标。
#
#   ./deploy/install.sh            # 装到 ssh 别名 mirror
#   REMOTE=root@1.2.3.4 ./deploy/install.sh
#   MONITORS='a.b.c.d e.f.g.h' ./deploy/install.sh   # 允许抓 9100 的监控机 IP
#
# MONITORS 空格分隔，不入库。nftables.conf 带 flush ruleset，套用会清空
# monitor_hosts 集合，故每次装都要带上，由 install.sh 重填。漏传则 9100 全关。
#
# 在此之前先跑 deploy/provision.sh（建账号、locale、内核调优、日志轮转）。
#
# 装完之后还要手工做两件事，因为它们涉及不入库的凭据：
#   /etc/binhost/alert.conf   Telegram 的 token 与 chat id
#   certbot                   TLS 证书

set -euo pipefail

REMOTE="${REMOTE:-mirror}"
MONITORS="${MONITORS:-}"
cd "$(dirname "$0")/.."

say() { printf '\n=== %s ===\n' "$1"; }

say "上传"
tmp=$(ssh "${REMOTE}" 'mktemp -d')
# shellcheck disable=SC2029  # tmp 要在本地展开
rsync -a deploy/ build/gen-packages.py build/packages.txt build/excluded.txt build/status.sh build/alert.sh \
    nginx/ site/ "${REMOTE}:${tmp}/"

# shellcheck disable=SC2029  # 同上
ssh "${REMOTE}" "set -euo pipefail
cd '${tmp}'

echo '--- 脚本'
sudo install -dm755 /usr/local/lib/binhost /srv/mirrors /var/log/emirrordist
sudo install -m755 daily.sh            /usr/local/bin/binhost-daily
sudo install -m755 distfiles-sync.sh   /usr/local/bin/binhost-distfiles-sync
sudo install -m755 distfiles-index.sh  /usr/local/bin/binhost-distfiles-index
sudo install -m755 site-sync.sh        /usr/local/bin/binhost-site-sync
sudo install -m755 status.sh           /usr/local/bin/binhost-status
sudo install -m644 gen-packages.py     /usr/local/lib/binhost/gen-packages.py
sudo install -m644 packages.txt        /usr/local/lib/binhost/packages.txt
sudo install -m644 excluded.txt        /usr/local/lib/binhost/excluded.txt
sudo install -m755 audit-distfiles.py  /usr/local/lib/binhost/audit-distfiles.py

echo '--- rsync'
sudo install -m644 rsyncd.conf /etc/rsyncd.conf

echo '--- 防火墙'
# 先 -c 检查再套用：这份文件带 flush ruleset，语法错会把机器关在门外。
# nftables 服务从 /var/lib/nftables/rules-save 还原，套用之后要 save 一次，
# 否则重启回到旧规则。
sudo nft -c -f nftables.conf
sudo install -m644 nftables.conf /etc/nftables.conf
sudo nft -f /etc/nftables.conf
sudo rc-update add nftables default 2>/dev/null || true
sudo rc-service nftables save

echo '--- nginx'
sudo install -dm755 /etc/nginx/conf.d
sudo install -m644 nginx.conf         /etc/nginx/nginx.conf
sudo install -m644 distfiles.conf       /etc/nginx/conf.d/distfiles.conf
sudo install -m644 mirror-common.inc  /etc/nginx/conf.d/mirror-common.inc
sudo nginx -t

echo '--- 日志轮替'
sudo install -m644 logrotate-binhost /etc/logrotate.d/binhost
sudo logrotate -d /etc/logrotate.d/binhost >/dev/null

echo '--- 定时任务'
sudo install -m644 cron.d-binhost /etc/cron.d/binhost

echo '--- 监控'
# node_exporter 供两套 Prometheus 抓取。9100 只放行 monitor_hosts 集合。
command -v node_exporter >/dev/null || sudo emerge -q app-metrics/node_exporter
sudo rc-update add node_exporter default 2>/dev/null || true
# '防火墙' 那步 flush 清空了 monitor_hosts，据 MONITORS 重填并存盘。
if [ -n '${MONITORS}' ]; then
    sudo nft flush set inet filter monitor_hosts
    for ip in ${MONITORS}; do sudo nft add element inet filter monitor_hosts { \$ip }; done
    sudo rc-service nftables save >/dev/null
    echo '  monitor_hosts: ${MONITORS}'
fi

echo '--- overlay 副本'
# distfiles 按它的 Manifest 取，包列表按它的目录生成
[ -d /var/lib/binhost-overlay/.git ] ||
    sudo git clone --quiet --depth=1 https://github.com/gentoo-zh/overlay /var/lib/binhost-overlay

echo '--- 让 portage 认得这个 repo（emirrordist 要）'
sudo install -dm755 /etc/portage/repos.conf
printf '[gentoo-zh]\nlocation = /var/lib/binhost-overlay\nauto-sync = no\n' |
    sudo install -m644 /dev/stdin /etc/portage/repos.conf/gentoo-zh.conf

echo '--- 启动'
sudo rc-update add cronie default 2>/dev/null || true
sudo rc-update add rsyncd default 2>/dev/null || true
sudo rc-update add nginx  default 2>/dev/null || true
for s in cronie rsyncd nginx node_exporter; do sudo rc-service \$s restart >/dev/null 2>&1 || true; done
rm -rf '${tmp}'
"

say "完成"
echo "站点内容由 deploy/site-sync.sh 自己拉，五分钟内会出现。"
echo "还要手工配：/etc/binhost/alert.conf、TLS 证书。"
[ -n "${MONITORS}" ] || echo "未传 MONITORS，9100 对外全关。"
