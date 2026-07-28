#!/bin/bash
# Install the build side onto the build machine. Runs locally, acts over ssh.
#
#   REMOTE="ssh -i ~/.ssh/gentoobuild -p 49887 user@host" ./deploy/install-builder.sh
#
# The build machine and the mirror are installed separately: the first needs
# docker, the signing key and an overlay copy, the second only nginx and the
# sync scripts.
#
# Before installing, confirm docker works, the signing key is in
# SIGNING_GNUPGHOME, and passwordless ssh to the mirror is in place, since
# publish.sh pushes there.

set -euo pipefail

REMOTE="${REMOTE:?用法: REMOTE=\"ssh ...\" $0}"
ROOT="${ROOT:-/var/lib/binhost}"
SIGNING_KEY="${SIGNING_KEY:?需要签名密钥指纹}"
# Who the build runs as. The overlay copy, docker access and the ssh key to the
# mirror all have to belong to this user.
BUILD_USER="${BUILD_USER:-adminc3b9c6}"

cd "$(dirname "$0")/.."

say() { printf '\n=== %s ===\n' "$1"; }

# Deploying into a running build is not safe. bash reads a script by byte offset
# as it executes, and the round also copies build/ into its container at the
# start, so a mid-round replacement leaves the two disagreeing about which
# version is running. One round published a package that the new filter excludes
# because of exactly this.
#
# build-container.sh takes this lock for the length of a round. No lock file at
# all means the machine has never built, which is not a reason to refuse.
say "确认没有构建在跑"
if ${REMOTE} "[ -e '${ROOT}/stage/build.lock' ] && ! flock -n '${ROOT}/stage/build.lock' -c true"; then
    echo "有一轮构建正在进行（${ROOT}/stage/build.lock）。" >&2
    echo "等它结束再部署；确实要现在覆盖就传 FORCE=1。" >&2
    [ "${FORCE:-}" = 1 ] || exit 1
    echo "FORCE=1，照样部署。" >&2
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

echo '--- overlay 副本'
# Ownership has to match the user that runs it. The timer runs as ${BUILD_USER},
# and with a different owner git reports dubious ownership, so the overlay
# update fails every time with nothing to show for it.
[ -d '${ROOT}/overlay/.git' ] ||
    sudo git clone --quiet https://github.com/gentoo-zh/overlay '${ROOT}/overlay'
sudo chown -R ${BUILD_USER}:${BUILD_USER} '${ROOT}'

echo '--- 告警凭据'
# The build runs as ${BUILD_USER}. With the credentials owned by root at 0600
# the read fails, alert() skips without a word, and the whole machine goes
# silent.
if sudo test -e /etc/binhost/alert.conf; then
    # The directory has to be traversable too: with /etc/binhost itself
    # drwx------ root, chowning the file changes nothing and all alert() sees
    # is a file it cannot read.
    sudo chmod 755 /etc/binhost
    sudo chown ${BUILD_USER}:${BUILD_USER} /etc/binhost/alert.conf
    sudo chmod 600 /etc/binhost/alert.conf
    sudo -u ${BUILD_USER} test -r /etc/binhost/alert.conf &&
        echo '    ${BUILD_USER} 能读到' ||
        echo '    !! ${BUILD_USER} 仍然读不到，告警会是哑的'
else
    echo '    /etc/binhost/alert.conf 还没有，告警不会发出'
fi
"

say "定时单元"
rsync -a -e "${REMOTE% *}" deploy/systemd/ "${REMOTE##* }:/tmp/systemd/"
${REMOTE} "sudo install -m644 /tmp/systemd/binhost-*.service /tmp/systemd/binhost-*.timer \
    /etc/systemd/system/
rm -rf /tmp/systemd
sudo sed -i -e 's|^Environment=SIGNING_KEY=.*|Environment=SIGNING_KEY=${SIGNING_KEY}|' \
    /etc/systemd/system/binhost-build.service
# Every unit at once, not by name. Naming them missed binhost-alert@.service,
# which cannot start under a user that does not exist -- and that unit is the
# only layer left to speak on a timeout or an OOM.
sudo sed -i -e 's|^User=.*|User=${BUILD_USER}|' -e 's|^Group=.*|Group=${BUILD_USER}|' \
    /etc/systemd/system/binhost-*.service
sudo systemctl daemon-reload
sudo systemctl enable --now binhost-build.timer binhost-status.timer
systemctl list-timers --all --no-pager | grep binhost || true"

say "完成"
echo "还要手工配：签名密钥（${ROOT}/gnupg）、到镜像机的免密 ssh、"
echo "告警凭据 /etc/binhost/alert.conf。"
