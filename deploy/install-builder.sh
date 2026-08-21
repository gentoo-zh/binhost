#!/bin/bash

set -euo pipefail

REMOTE="${REMOTE:?用法： REMOTE=\"ssh ...\" $0}"
ROOT="${ROOT:-/var/lib/binhost}"
SIGNING_KEY="${SIGNING_KEY:?需要签名密钥指纹}"
[[ ${SIGNING_KEY} =~ ^[0-9A-Fa-f]{40}$ ]] || {
    # A path or a short key id reaches gpg as a lookup string it cannot resolve,
    # and the failure surfaces hours later when the finished build is signed.
    echo "SIGNING_KEY 要 40 位指纹，收到：${SIGNING_KEY}" >&2
    exit 1
}
BUILD_USER="${BUILD_USER:-adminc3b9c6}"

cd "$(dirname "$0")/.."

COMMIT="$(git rev-parse HEAD)"
git diff --quiet && git diff --cached --quiet || COMMIT="${COMMIT}-dirty"

say() { printf '\n=== %s ===\n' "$1"; }

say "上传"
tmp=$(${REMOTE} 'mktemp -d')
rsync -a -e "${REMOTE% *}" build ops deploy/systemd "${REMOTE##* }:${tmp}/"

# shellcheck disable=SC2029  # the path is meant to expand locally
${REMOTE} "set -euo pipefail
sudo install -dm755 '${ROOT}' '${ROOT}/logs' '${ROOT}/stage'
sudo chown ${BUILD_USER}:${BUILD_USER} '${ROOT}/stage'
exec 9>'${ROOT}/stage/build.lock'
if ! flock -n 9; then
    echo '有构建正在执行（${ROOT}/stage/build.lock）。' >&2
    echo '请等待当前构建结束；如需立即覆盖，请设置 FORCE=1。' >&2
    if [ '${FORCE:-0}' != 1 ]; then
        rm -rf '${tmp}'
        exit 1
    fi
    echo '已设置 FORCE=1，继续部署。' >&2
fi
trap \"rm -rf '${tmp}'\" EXIT

echo '--- 构建脚本'
sudo rsync -a --delete '${tmp}/build/' '${ROOT}/build/'
sudo rsync -a --delete '${tmp}/ops/' '${ROOT}/ops/'
sudo install -m755 '${ROOT}/ops/status.sh' /usr/local/bin/binhost-status

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

echo '--- 签名密钥'
sudo GNUPGHOME='${ROOT}/gnupg' gpg --batch --list-secret-keys '${SIGNING_KEY}' \
    >/dev/null 2>&1 || {
    echo \"    !! ${ROOT}/gnupg 里没有 ${SIGNING_KEY} 的私钥\" >&2
    exit 1
}
echo '    ${SIGNING_KEY} 可用'

echo '--- 定时单元'
sudo install -m644 '${tmp}'/systemd/binhost-*.service '${tmp}'/systemd/binhost-*.timer \
    /etc/systemd/system/
for unit in binhost-build.service binhost-build-unstable.service; do
    sudo sed -i -e 's|^Environment=SIGNING_KEY=.*|Environment=SIGNING_KEY=${SIGNING_KEY}|' \
        \"/etc/systemd/system/\${unit}\"
    grep -q \"^Environment=SIGNING_KEY=${SIGNING_KEY}\$\" \
        \"/etc/systemd/system/\${unit}\" ||
        { echo \"    !! SIGNING_KEY 没有写进 \${unit}\"; exit 1; }
done
sudo sed -i -e 's|^User=.*|User=${BUILD_USER}|' -e 's|^Group=.*|Group=${BUILD_USER}|' \
    /etc/systemd/system/binhost-*.service
sudo systemctl daemon-reload
sudo systemctl enable --now \
    binhost-build.timer binhost-build-unstable.timer binhost-status.timer \
    binhost-kernel.timer
printf %s '${COMMIT}' | sudo install -m644 /dev/stdin '${ROOT}/build/VERSION'
systemctl list-timers --all --no-pager | grep binhost || true
"

say "完成"
echo "尚需手动设置：签名密钥（${ROOT}/gnupg）、到镜像机的免密 ssh、"
echo "告警凭据 /etc/binhost/alert.conf。"
