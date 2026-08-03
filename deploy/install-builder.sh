#!/bin/bash

set -euo pipefail

REMOTE="${REMOTE:?用法: REMOTE=\"ssh ...\" $0}"
ROOT="${ROOT:-/var/lib/binhost}"
SIGNING_KEY="${SIGNING_KEY:?需要签名密钥指纹}"
BUILD_USER="${BUILD_USER:-adminc3b9c6}"

cd "$(dirname "$0")/.."

COMMIT="$(git rev-parse HEAD)"
git diff --quiet && git diff --cached --quiet || COMMIT="${COMMIT}-dirty"

say() { printf '\n=== %s ===\n' "$1"; }

say "确认没有构建正在进行"
if ${REMOTE} "[ -e '${ROOT}/stage/build.lock' ] && ! flock -n '${ROOT}/stage/build.lock' -c true"; then
    echo "有一轮构建正在进行（${ROOT}/stage/build.lock）。" >&2
    echo "等它结束再部署；确实要现在覆盖就传 FORCE=1。" >&2
    [ "${FORCE:-}" = 1 ] || exit 1
    echo "已设置 FORCE=1，继续部署。" >&2
else
    echo "  没有"
fi

say "上传构建脚本"
tmp=$(${REMOTE} 'mktemp -d')
rsync -a -e "${REMOTE% *}" build/ "${REMOTE##* }:${tmp}/"

# shellcheck disable=SC2029  # the path is meant to expand locally
${REMOTE} "set -euo pipefail
sudo install -dm755 '${ROOT}' '${ROOT}/logs' '${ROOT}/stage'
sudo rsync -a --delete '${tmp}/' '${ROOT}/build/'
rm -rf '${tmp}'
sudo install -m755 '${ROOT}/build/status.sh' /usr/local/bin/binhost-status
printf %s '${COMMIT}' | sudo install -m644 /dev/stdin '${ROOT}/build/VERSION'

echo '--- overlay 副本'
[ -d '${ROOT}/overlay/.git' ] ||
    sudo git clone --quiet https://github.com/gentoo-zh/overlay '${ROOT}/overlay'
sudo chown -R ${BUILD_USER}:${BUILD_USER} '${ROOT}'

echo '--- 告警凭据'
if sudo test -e /etc/binhost/alert.conf; then
    sudo chmod 755 /etc/binhost
    sudo chown ${BUILD_USER}:${BUILD_USER} /etc/binhost/alert.conf
    sudo chmod 600 /etc/binhost/alert.conf
    sudo -u ${BUILD_USER} test -r /etc/binhost/alert.conf &&
        echo '    ${BUILD_USER} 可读取' ||
        echo '    !! ${BUILD_USER} 仍然无法读取，告警将无法传送'
else
    echo '    /etc/binhost/alert.conf 尚未建立，告警不会发出'
fi
"

say "定时单元"
utmp=$(${REMOTE} 'mktemp -d')
rsync -a -e "${REMOTE% *}" deploy/systemd/ "${REMOTE##* }:${utmp}/"
${REMOTE} "sudo install -m644 ${utmp}/binhost-*.service ${utmp}/binhost-*.timer \
    /etc/systemd/system/
rm -rf '${utmp}'
sudo sed -i -e 's|^Environment=SIGNING_KEY=.*|Environment=SIGNING_KEY=${SIGNING_KEY}|' \
    /etc/systemd/system/binhost-build.service
grep -q \"^Environment=SIGNING_KEY=${SIGNING_KEY}\$\" \
    /etc/systemd/system/binhost-build.service ||
    { echo '    !! SIGNING_KEY 没有写进 unit'; exit 1; }
sudo sed -i -e 's|^User=.*|User=${BUILD_USER}|' -e 's|^Group=.*|Group=${BUILD_USER}|' \
    /etc/systemd/system/binhost-*.service
sudo systemctl daemon-reload
sudo systemctl enable --now binhost-build.timer binhost-status.timer
systemctl list-timers --all --no-pager | grep binhost || true"

say "完成"
echo "尚需手动设置：签名密钥（${ROOT}/gnupg）、到镜像机的免密 ssh、"
echo "告警凭据 /etc/binhost/alert.conf。"
