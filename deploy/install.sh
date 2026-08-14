#!/bin/bash

set -euo pipefail

REMOTE="${REMOTE:-mirror}"
SITE_USER="${SITE_USER:-zakk}"
SIGNING_FPR="${SIGNING_FPR:-}"
MONITORS="${MONITORS:-}"
SSH_PORT="${SSH_PORT:-60001}"
ROLLBACK_S="${ROLLBACK_S:-300}"
CONFIRM=/run/binhost-firewall-confirmed
ROLLBACK_FILE=/run/binhost-firewall-rollback.rules
GEN_FILE=/run/binhost-firewall-generation
cd "$(dirname "$0")/.."

if ! [[ ${SSH_PORT} =~ ^[0-9]+$ ]] || (( SSH_PORT < 1 || SSH_PORT > 65535 )); then
    echo "SSH_PORT 不是 1-65535 的整数：${SSH_PORT}" >&2
    exit 1
fi
if ! [[ ${ROLLBACK_S} =~ ^[0-9]+$ ]] || (( ROLLBACK_S < 30 )); then
    echo "ROLLBACK_S 至少 30 秒：${ROLLBACK_S}" >&2
    exit 1
fi

GEN="$(date +%s)-$$"

COMMIT="$(git rev-parse HEAD)"
git diff --quiet && git diff --cached --quiet || COMMIT="${COMMIT}-dirty"

say() { printf '\n=== %s ===\n' "$1"; }

say "上传"
tmp=$(ssh "${REMOTE}" 'mktemp -d')
# shellcheck disable=SC2029  # tmp is meant to expand locally
rsync -a deploy/ build/gen-packages.py build/ebuilds.py build/verify-deps.py \
    build/generation.py \
    build/dep-exceptions.txt build/packages.txt build/excluded.txt build/stable-excluded.txt \
    ops/status.sh ops/alert.sh \
    nginx/ site/ "${REMOTE}:${tmp}/"

# shellcheck disable=SC2029  # as above
ssh "${REMOTE}" "set -euo pipefail
cd '${tmp}'

echo '--- 依赖'
for cmd in git rsync logrotate certbot; do
    command -v \${cmd} >/dev/null && continue
    case \${cmd} in
        git)       sudo emerge -q dev-vcs/git ;;
        rsync)     sudo emerge -q net-misc/rsync ;;
        logrotate) sudo emerge -q app-admin/logrotate ;;
        certbot)   sudo emerge -q app-crypt/certbot ;;
    esac
done
missing=''
for cmd in git rsync logrotate certbot; do command -v \${cmd} >/dev/null || missing=\"\${missing} \${cmd}\"; done
[ -z \"\${missing}\" ] || { echo \"!! 缺少命令：\${missing}\" >&2; exit 1; }

echo '--- 防火墙'
listening=\$(sudo sshd -T 2>/dev/null | awk '/^port /{print \$2}')
if [ '${SKIP_SSH_PORT_CHECK:-0}' = 1 ]; then
    echo '   !! SKIP_SSH_PORT_CHECK=1：跳过端口一致性检查' >&2
    echo \"   即将 flush ruleset 并只放行 ${SSH_PORT}；若与实际不符，当前连线会中断，且没有已确认的备用管理通道\" >&2
elif [ -z \"\${listening}\" ]; then
    echo '!! 无法从 sshd -T 取得实际监听端口，不能确认防火墙会放行它' >&2
    echo '   套用后可能切断当前连线，已中止' >&2
    exit 1
elif ! echo \"\${listening}\" | grep -qx '${SSH_PORT}'; then
    echo \"!! sshd 实际监听 \${listening}，而防火墙只会放行 ${SSH_PORT}\" >&2
    echo '   套用后当前连线会中断，且没有已确认的备用管理通道，已中止' >&2
    exit 1
fi
sed 's/__SSH_PORT__/${SSH_PORT}/g' nftables.conf > nftables.conf.real
sudo nft -c -f nftables.conf.real
sudo install -m644 nftables.conf.real /etc/nftables.conf
sudo rm -f '${CONFIRM}'
sudo sh -c 'nft list ruleset > ${ROLLBACK_FILE}'
printf %s '${GEN}' | sudo install -m644 /dev/stdin '${GEN_FILE}'
sudo setsid sh -c 'sleep ${ROLLBACK_S}
    [ \"\$(cat ${GEN_FILE} 2>/dev/null)\" = \"${GEN}\" ] || exit 0
    [ \"\$(cat ${CONFIRM} 2>/dev/null)\" = \"${GEN}\" ] && exit 0
    if nft -c -f ${ROLLBACK_FILE} && nft flush ruleset && nft -f ${ROLLBACK_FILE}; then
        logger -t binhost \"防火墙在 ${ROLLBACK_S} 秒内未确认，已回滚到套用前的规则\"
    else
        logger -t binhost \"防火墙回滚失败，当前规则可能不可用，需要带外介入\"
    fi' \\
    </dev/null >/dev/null 2>&1 &
echo '    已备份现有规则，${ROLLBACK_S} 秒内未确认就自动回滚（世代 ${GEN}）'
sudo nft -f /etc/nftables.conf
sudo rc-update add nftables default 2>/dev/null || true
"

say "验证新的 SSH 连线仍可建立"
if ssh -o ConnectTimeout=15 -o BatchMode=yes "${REMOTE}" \
       "sudo rc-service nftables save >/dev/null 2>&1 &&
        printf %s '${GEN}' | sudo install -m644 /dev/stdin '${CONFIRM}'"; then
    echo "  第二条 SSH 连线已建立，规则已保存"
else
    echo "!! 无法建立第二条 SSH 连线，或规则未能保存" >&2
    echo "   ${ROLLBACK_S} 秒内会自动回滚到套用前的规则，回滚完成后重新执行" >&2
    exit 1
fi


# shellcheck disable=SC2029  # tmp is meant to expand locally
ssh "${REMOTE}" "set -euo pipefail
cd '${tmp}'

echo '--- nginx'
sudo install -dm755 /etc/portage/package.use
printf '%s\n' 'www-servers/nginx NGINX_MODULES_HTTP: v3' |
    sudo install -m644 /dev/stdin /etc/portage/package.use/nginx
if ! nginx -V 2>&1 | grep -q http_v3; then
    echo '    nginx 没有 http_v3，重新编译'
    sudo emerge --oneshot --quiet-build=y www-servers/nginx
fi
mkdir -p nginx-test/conf.d
cp mirror-common.inc headers-site.inc headers-files.inc nginx-test/conf.d/
CERT=/etc/letsencrypt/live/distfiles.gentoozh.org
if sudo test -r \"\${CERT}/fullchain.pem\" && sudo test -r \"\${CERT}/privkey.pem\"; then
    cp distfiles.conf nginx-test/conf.d/distfiles.conf
else
    if sudo grep -qs 'listen 443' /etc/nginx/conf.d/distfiles.conf; then
        echo '    !! 无法读取证书，但现有配置在监听 443；保留现有配置' >&2
        echo '       证书确实已失效时，先处理证书，再重新执行本脚本' >&2
        sudo cat /etc/nginx/conf.d/distfiles.conf > nginx-test/conf.d/distfiles.conf
    else
        echo '    证书尚未签发，先只配置 HTTP；签发之后重新执行本脚本'
        awk '/^server \{/{n++} n<2' distfiles.conf |
            tee nginx-test/conf.d/distfiles.conf >/dev/null
    fi
fi
sed -e 's|include modules-enabled/\*.conf;|include /etc/nginx/modules-enabled/*.conf;|' \
    -e 's|include mime.types.nginx;|include /etc/nginx/mime.types.nginx;|' \
    -e 's|include /etc/nginx/conf.d/\*.conf;|include ${tmp}/nginx-test/conf.d/*.conf;|' \
    nginx.conf > nginx-test/nginx.conf
sudo nginx -t -c '${tmp}/nginx-test/nginx.conf'
sudo install -m644 logrotate-binhost nginx-test/logrotate-binhost
sudo logrotate -d nginx-test/logrotate-binhost >/dev/null

echo '--- 站台锁'
[ -e /var/lib/binhost-site.lock ] ||
    sudo install -m644 -o '${SITE_USER}' -g '${SITE_USER}' /dev/null /var/lib/binhost-site.lock
exec 9>/var/lib/binhost-site.lock
flock -n 9 || { echo '另一次站台同步正在进行，未部署' >&2; exit 1; }

echo '--- 脚本'
sudo install -dm755 /usr/local/lib/binhost /var/log/emirrordist
sudo install -dm755 -o '${SITE_USER}' -g '${SITE_USER}' /srv/mirrors /var/lib/binhost-site
sudo install -m755 daily.sh            /usr/local/bin/binhost-daily
sudo install -m755 distfiles-sync.sh   /usr/local/bin/binhost-distfiles-sync
sudo install -m755 distfiles-index.sh  /usr/local/bin/binhost-distfiles-index
sudo install -m755 livecd-sync.sh      /usr/local/bin/binhost-livecd-sync
sudo install -m755 server-status.sh    /usr/local/bin/binhost-server-status
sudo install -m755 site-sync.sh        /usr/local/bin/binhost-site-sync
sudo install -m755 publish-site.sh     /usr/local/lib/binhost/publish-site.sh
sudo install -m755 status.sh           /usr/local/bin/binhost-status
sudo install -m644 alert.sh            /usr/local/lib/binhost/alert.sh
sudo install -m644 gen-packages.py     /usr/local/lib/binhost/gen-packages.py
sudo install -m644 ebuilds.py          /usr/local/lib/binhost/ebuilds.py
sudo install -m755 verify-deps.py      /usr/local/lib/binhost/verify-deps.py
sudo install -m755 generation.py       /usr/local/lib/binhost/generation.py
sudo install -m644 dep-exceptions.txt  /usr/local/lib/binhost/dep-exceptions.txt
sudo install -m644 packages.txt        /usr/local/lib/binhost/packages.txt
sudo install -m644 excluded.txt        /usr/local/lib/binhost/excluded.txt
sudo install -m644 stable-excluded.txt /usr/local/lib/binhost/stable-excluded.txt
sudo install -m755 audit-distfiles.py  /usr/local/lib/binhost/audit-distfiles.py

echo '--- rsync'
sudo install -m644 rsyncd.conf /etc/rsyncd.conf

sudo install -dm755 /srv/pub
sudo install -dm755 -o '${SITE_USER}' -g '${SITE_USER}' /srv/pub/binpkgs /srv/pub/distfiles /srv/pub/gigos /srv/pub/gentoo-cjk-kernel /srv/pub/gentoo-cjk-livecd
# mirror-common.inc serves the ACME challenge from here, and certbot renews
# through that path.
sudo install -dm755 /var/www/acme/.well-known/acme-challenge
sudo install -dm755 /etc/nginx/conf.d
sudo install -m644 nginx.conf                          /etc/nginx/nginx.conf
sudo install -m644 nginx-test/conf.d/mirror-common.inc /etc/nginx/conf.d/mirror-common.inc
sudo install -m644 nginx-test/conf.d/headers-site.inc  /etc/nginx/conf.d/headers-site.inc
sudo install -m644 nginx-test/conf.d/headers-files.inc /etc/nginx/conf.d/headers-files.inc
sudo install -m644 nginx-test/conf.d/distfiles.conf    /etc/nginx/conf.d/distfiles.conf

echo '--- 日志轮替'
sudo install -m644 logrotate-binhost /etc/logrotate.d/binhost

echo '--- 定时任务'
if [ -n '${SIGNING_FPR}' ]; then
  sudo install -dm755 /etc/binhost
  printf '%s\n' '${SIGNING_FPR}' | sudo tee /etc/binhost/signing-key.fpr >/dev/null
  echo '    signing-key.fpr 已写入'
elif [ ! -r /etc/binhost/signing-key.fpr ]; then
  echo '    /etc/binhost/signing-key.fpr 尚未建立，公钥不会同步（传 SIGNING_FPR= 设定它）'
else
  echo '    沿用已有的 signing-key.fpr:'
  sed 's/^/      /' /etc/binhost/signing-key.fpr
fi

sudo install -m644 cron.d-binhost /etc/cron.d/binhost
sudo sed -i 's|^\(\*/5 \* \* \* \* \)[^ ]*|\1${SITE_USER}|' /etc/cron.d/binhost

echo '--- 监控'
command -v node_exporter >/dev/null ||
    sudo emerge -q app-metrics/node_exporter ||
    echo '    !! node_exporter 未安装，监控这一项暂缺'
sudo rc-update add node_exporter default 2>/dev/null || true
mon='${MONITORS}'
[ -n \"\${mon}\" ] || mon=\$(cat /usr/local/lib/binhost/MONITORS 2>/dev/null || true)
if [ -n \"\${mon}\" ]; then
    sudo nft flush set inet filter monitor_hosts
    for ip in \${mon}; do sudo nft add element inet filter monitor_hosts { \$ip }; done
    sudo rc-service nftables save >/dev/null
    echo \"  monitor_hosts: \${mon}\"
fi
printf %s \"\${mon}\" | sudo install -m644 /dev/stdin /usr/local/lib/binhost/MONITORS

echo '--- overlay 副本'
[ -d /var/lib/binhost-overlay/.git ] ||
    sudo git clone --quiet --depth=1 https://github.com/gentoo-zh/overlay /var/lib/binhost-overlay

echo '--- 注册 repo 供 emirrordist 使用'
sudo install -dm755 /etc/portage/repos.conf
printf '[gentoo-zh]\nlocation = /var/lib/binhost-overlay\nauto-sync = no\n' |
    sudo install -m644 /dev/stdin /etc/portage/repos.conf/gentoo-zh.conf

echo '--- 启动'
sudo rc-update add cronie default 2>/dev/null || true
sudo rc-update add rsyncd default 2>/dev/null || true
sudo rc-update add nginx  default 2>/dev/null || true
svc_bad=0
for s in cronie rsyncd; do
    if sudo rc-service \$s status >/dev/null 2>&1; then
        echo "    \$s 已在运行，配置在每次请求时读取，无需重启"
    else
        sudo rc-service \$s start >/dev/null 2>&1 || { echo "    !! \$s 未能启动"; svc_bad=1; }
    fi
done
if sudo rc-service nginx status >/dev/null 2>&1; then
    if sudo rc-service nginx reload >/dev/null 2>&1; then
        echo "    nginx 已重新载入配置，进行中的下载不受影响"
    else
        echo "    !! nginx 未能重新载入配置"
        svc_bad=1
    fi
else
    sudo rc-service nginx start >/dev/null 2>&1 || { echo "    !! nginx 未能启动"; svc_bad=1; }
fi
sudo rc-service node_exporter restart >/dev/null 2>&1 ||
    echo "    !! node_exporter 未能启动（可选）"
[ \${svc_bad} -eq 0 ] || { echo "!! 关键服务未能启动" >&2; exit 1; }
printf %s '${COMMIT}' | sudo install -m644 /dev/stdin /usr/local/lib/binhost/VERSION
cd /
rm -rf '${tmp}'
"

say "完成"
echo "站点内容由 site-sync.sh 同步，五分钟内会出现。"
echo "尚需手动设置：/etc/binhost/alert.conf、TLS 证书。"
if [ -n "${MONITORS}" ]; then
    echo "monitor_hosts: ${MONITORS}"
else
    echo "未传 MONITORS，沿用上次安装记录的抓取源；两者都为空时 9100 不对外开放。"
fi
