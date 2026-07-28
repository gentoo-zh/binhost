#!/bin/bash
# Install this repository onto the mirror. Runs locally, acts over ssh.
#
#   ./deploy/install.sh            # to the ssh alias `mirror`
#   REMOTE=root@1.2.3.4 ./deploy/install.sh
#   MONITORS='a.b.c.d e.f.g.h' ./deploy/install.sh   # hosts allowed to scrape 9100
#
# MONITORS is space separated and stays out of the repository. nftables.conf
# carries flush ruleset, so applying it empties the monitor_hosts set; pass it
# on every install and install.sh refills it. Leave it out and 9100 is closed to
# everyone.
#
# Run deploy/provision.sh first: accounts, locale, kernel tuning, log rotation.
#
# Two things remain manual afterwards because they involve credentials that
# stay out of the repository:
#   /etc/binhost/alert.conf   Telegram token and chat id
#   certbot                   TLS certificate
#
# SIGNING_FPR sets /etc/binhost/signing-key.fpr, which decides whether the
# signing public key gets synced at all. Pass it on the first install.

set -euo pipefail

REMOTE="${REMOTE:-mirror}"
# The site sync runs as an ordinary user (see cron.d-binhost) and has to write
# /srv/mirrors as well as clone the repository into /var/lib/binhost-site. Both
# are created and owned here; otherwise the sync fails every five minutes on a
# fresh machine, and cron's mail has nowhere to go.
SITE_USER="${SITE_USER:-zakk}"
# The signing key fingerprint the mirror will accept. site-sync.sh installs the
# public key only when the file in the repository matches this, so without it the
# key is never synced and the site serves whatever was there before. It is
# recorded on the machine rather than in the repository on purpose: a check that
# reads its expected value from the thing it checks is not a check.
SIGNING_FPR="${SIGNING_FPR:-}"
MONITORS="${MONITORS:-}"
# 与 provision.sh 同一个默认值。防火墙里那个端口原本写死，改过端口的机器
# 装完就连不进去。
SSH_PORT="${SSH_PORT:-60001}"
cd "$(dirname "$0")/.."

say() { printf '\n=== %s ===\n' "$1"; }

say "上传"
tmp=$(ssh "${REMOTE}" 'mktemp -d')
# shellcheck disable=SC2029  # tmp is meant to expand locally
rsync -a deploy/ build/gen-packages.py build/ebuilds.py build/packages.txt build/excluded.txt build/status.sh build/alert.sh \
    nginx/ site/ "${REMOTE}:${tmp}/"

# shellcheck disable=SC2029  # as above
ssh "${REMOTE}" "set -euo pipefail
cd '${tmp}'

echo '--- 脚本'
sudo install -dm755 /usr/local/lib/binhost /var/log/emirrordist
sudo install -dm755 -o '${SITE_USER}' -g '${SITE_USER}' /srv/mirrors /var/lib/binhost-site
sudo install -m755 daily.sh            /usr/local/bin/binhost-daily
sudo install -m755 distfiles-sync.sh   /usr/local/bin/binhost-distfiles-sync
sudo install -m755 distfiles-index.sh  /usr/local/bin/binhost-distfiles-index
sudo install -m755 site-sync.sh        /usr/local/bin/binhost-site-sync
sudo install -m755 status.sh           /usr/local/bin/binhost-status
sudo install -m644 alert.sh            /usr/local/lib/binhost/alert.sh
sudo install -m644 gen-packages.py     /usr/local/lib/binhost/gen-packages.py
# gen-packages.py imports ebuilds from the same directory
sudo install -m644 ebuilds.py          /usr/local/lib/binhost/ebuilds.py
sudo install -m644 packages.txt        /usr/local/lib/binhost/packages.txt
sudo install -m644 excluded.txt        /usr/local/lib/binhost/excluded.txt
sudo install -m755 audit-distfiles.py  /usr/local/lib/binhost/audit-distfiles.py

echo '--- rsync'
sudo install -m644 rsyncd.conf /etc/rsyncd.conf

echo '--- 防火墙'
# Check with -c before applying: this file carries flush ruleset, and a syntax
# error would lock the machine out. The nftables service restores from
# /var/lib/nftables/rules-save, so save once after applying or a reboot returns
# to the old rules.
sed 's/__SSH_PORT__/${SSH_PORT}/g' nftables.conf > nftables.conf.real
sudo nft -c -f nftables.conf.real
sudo install -m644 nftables.conf.real /etc/nftables.conf
sudo nft -f /etc/nftables.conf
sudo rc-update add nftables default 2>/dev/null || true
sudo rc-service nftables save

echo '--- nginx'
# 套件与 distfiles 的根。rsyncd 的模块指着它且 use chroot=yes，nginx 的三个
# location 也以它为 root，两者都在下面被启动，而目录到第一次同步才会出现。
# binpkgs 与 distfiles 归发布用户：publish.sh 用普通用户 ssh 过来，直接
# install -d 建架构子目录、rsync 写包，都不经过 sudo。属主是 root 时
# 新机器第一次发布即 Permission denied。/srv/pub 自身留给 root。
sudo install -dm755 /srv/pub
sudo install -dm755 -o '${SITE_USER}' -g '${SITE_USER}' /srv/pub/binpkgs /srv/pub/distfiles
sudo install -dm755 /etc/nginx/conf.d
sudo install -m644 nginx.conf         /etc/nginx/nginx.conf
sudo install -m644 mirror-common.inc  /etc/nginx/conf.d/mirror-common.inc
# 证书还没签发时 nginx -t 会以 cannot load certificate 失败，而 set -e 会让
# 这一句中止整个安装：日志轮替、cron、node_exporter、overlay 副本、服务启动
# 全都不会跑，而 /etc/nginx 已经被换成一份载不起来的配置。
#
# 这是个先有鸡还是先有蛋：certbot 的 HTTP-01 需要 nginx 先跑起来提供 acme 的
# location。所以证书不在就跳过 HTTPS 那份配置，先把 HTTP 立起来，签发之后再
# 跑一次这个脚本。
CERT=/etc/letsencrypt/live/distfiles.gentoozh.org
# 两个文件都要在。只测 fullchain 时，续期中断留下的半套证书会让这里判定
# 证书齐全，于是配上 HTTPS 那一份，nginx -t 再以 cannot load certificate 失败。
if sudo test -r \"\${CERT}/fullchain.pem\" && sudo test -r \"\${CERT}/privkey.pem\"; then
    sudo install -m644 distfiles.conf /etc/nginx/conf.d/distfiles.conf
else
    # 机器上已经在跑 HTTPS 时不要降级。证书临时读不到（续期把目录换掉的一瞬、
    # sudo 规则变了）就把 443 从配置里删掉，等于用一次例行安装把站点打回明文，
    # 而且 HSTS 已经发出去的浏览器会直接连不上。
    if sudo grep -qs 'listen 443' /etc/nginx/conf.d/distfiles.conf; then
        echo '    !! 读不到证书，但现有配置在监听 443；保持原样不动' >&2
        echo '       证书确实没了就先修证书，再重跑本脚本' >&2
    else
        echo '    证书还没有，先只配 HTTP；签发之后重跑本脚本'
        # 整个第二个 server 块一起去掉。从 listen 443 那一行删起会把它的
        # server { 留在原地，大括号不配对，nginx -t 一样失败。
        awk '/^server \{/{n++} n<2' distfiles.conf |
            sudo install -m644 /dev/stdin /etc/nginx/conf.d/distfiles.conf
    fi
fi
sudo nginx -t

echo '--- 日志轮替'
sudo install -m644 logrotate-binhost /etc/logrotate.d/binhost
sudo logrotate -d /etc/logrotate.d/binhost >/dev/null

echo '--- 定时任务'
if [ -n '${SIGNING_FPR}' ]; then
  sudo install -dm755 /etc/binhost
  printf '%s\n' '${SIGNING_FPR}' | sudo tee /etc/binhost/signing-key.fpr >/dev/null
  echo '    signing-key.fpr 已写入'
elif [ ! -r /etc/binhost/signing-key.fpr ]; then
  echo '    /etc/binhost/signing-key.fpr 还没有，公钥不会同步（传 SIGNING_FPR= 设定它）'
else
  # Say which fingerprint is being kept. Rotating the key without passing
  # SIGNING_FPR leaves the old one here, and the public key then stops syncing
  # because it no longer matches -- correct behaviour, but silent.
  echo '    沿用已有的 signing-key.fpr:'
  sed 's/^/      /' /etc/binhost/signing-key.fpr
fi

sudo install -m644 cron.d-binhost /etc/cron.d/binhost
# The site sync line's user must match the one the directories were created
# for, or it cannot write /srv/mirrors.
sudo sed -i 's|^\(\*/5 \* \* \* \* \)[^ ]*|\1${SITE_USER}|' /etc/cron.d/binhost

echo '--- 监控'
# node_exporter is scraped by two Prometheus instances. Port 9100 admits only
# the monitor_hosts set.
# emerge 失败不该挡住后面的 overlay 副本、repos.conf 与服务启动——那些是这台
# 机器能不能工作的部分，监控只是能不能被看见。
command -v node_exporter >/dev/null ||
    sudo emerge -q app-metrics/node_exporter ||
    echo '    !! node_exporter 未安装，监控这一项先缺着'
sudo rc-update add node_exporter default 2>/dev/null || true
# The firewall step's flush emptied monitor_hosts; refill it from MONITORS and
# save.
if [ -n '${MONITORS}' ]; then
    sudo nft flush set inet filter monitor_hosts
    for ip in ${MONITORS}; do sudo nft add element inet filter monitor_hosts { \$ip }; done
    sudo rc-service nftables save >/dev/null
    echo '  monitor_hosts: ${MONITORS}'
fi

echo '--- overlay 副本'
# distfiles are fetched by its Manifests, the package list generated from its
# directories
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
# 起不来要说出来。原来整句 || true，四个服务全挂也照样打印「完成」。
for s in cronie rsyncd nginx node_exporter; do
    sudo rc-service \$s restart >/dev/null 2>&1 ||
        echo "    !! \$s 没起来"
done
rm -rf '${tmp}'
"

say "完成"
echo "站点内容由 deploy/site-sync.sh 自己拉，五分钟内会出现。"
echo "还要手工配：/etc/binhost/alert.conf、TLS 证书。"
[ -n "${MONITORS}" ] || echo "未传 MONITORS，9100 对外全关。"
