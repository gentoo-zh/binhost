#!/bin/bash

set -euo pipefail

TARGET="${TARGET:?用法: TARGET=root@主机 $0}"
ADMIN="${ADMIN:-zakk}"
SSH_PORT="${SSH_PORT:-60001}"
PUBKEY="${PUBKEY:-$HOME/.ssh/gentoozh_mirror.pub}"

[[ -r ${PUBKEY} ]] || { echo "找不到公钥 ${PUBKEY}" >&2; exit 1; }

say() { printf '\n=== %s ===\n' "$1"; }
on()  { ssh -o StrictHostKeyChecking=accept-new "${TARGET}" "$@"; }

say "现状"
# shellcheck disable=SC2016  # single quotes are deliberate: these expand on the
on 'echo "  $(uname -sr)"; echo "  init: $(ps -p1 -o comm=)"; echo "  $(df -h / | awk "NR==2{print \$2\" 盘，已用 \"\$3}")"; echo "  $(free -h | awk "/^Mem/{print \$2\" 内存\"}")"'

say "管理员与密钥"
on "id ${ADMIN} >/dev/null 2>&1 || useradd -m -G wheel -s /bin/bash ${ADMIN}
    install -dm700 -o ${ADMIN} -g ${ADMIN} /home/${ADMIN}/.ssh"
# shellcheck disable=SC2029  # ADMIN is meant to expand locally
ssh "${TARGET}" "install -m600 -o ${ADMIN} -g ${ADMIN} /dev/stdin /home/${ADMIN}/.ssh/authorized_keys" < "${PUBKEY}"
on "command -v sudo >/dev/null || emerge -q app-admin/sudo
    echo '${ADMIN} ALL=(ALL:ALL) NOPASSWD: ALL' > /etc/sudoers.d/${ADMIN}
    chmod 440 /etc/sudoers.d/${ADMIN}
    visudo -c >/dev/null && echo '  sudoers 语法 ok'"

say "locale"
# shellcheck disable=SC2016
on 'printf "en_US.UTF-8 UTF-8\nen_GB.UTF-8 UTF-8\nzh_CN.UTF-8 UTF-8\nzh_TW.UTF-8 UTF-8\n" > /etc/locale.gen
    lg=$(mktemp)
    locale-gen > "$lg" 2>&1 || echo "  !! locale-gen 未完成"
    tail -1 "$lg" | sed "s/^/  /"; rm -f "$lg"'

say "网络：确认开机后不会失去连接"
# shellcheck disable=SC2016  # as above, expands on the remote
on 'iface=$(ip -o -4 route show default | awk "{print \$5}" | head -1)
    echo "  默认路由走 ${iface}"
    if [ -f /etc/conf.d/net ] && grep -q "^config_" /etc/conf.d/net; then
        grep -q "config_${iface}" /etc/conf.d/net \
            && echo "  /etc/conf.d/net 与网卡名一致" \
            || echo "  !! /etc/conf.d/net 配置的不是 ${iface}，重启后会失去连接"
    fi
    if [ -d /etc/init.d ]; then
        rc-update show default 2>/dev/null | grep -qE "dhcpcd|net\." \
            && echo "  网络服务在 default runlevel" \
            || echo "  !! 没有网络服务在 default runlevel"
    fi'

say "内核网络调优"
# shellcheck disable=SC2016  # the heredoc is written out verbatim, no local
on 'cat > /etc/sysctl.d/99-mirror.conf <<EOF
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.somaxconn = 8192
net.ipv4.tcp_max_syn_backlog = 8192
net.core.netdev_max_backlog = 16384
net.ipv4.tcp_fastopen = 3
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_syncookies = 1
vm.swappiness = 10
vm.vfs_cache_pressure = 50
EOF
    if [ -f /etc/conf.d/modules ] && ! grep -q tcp_bbr /etc/conf.d/modules; then
        if grep -qE "^modules=" /etc/conf.d/modules; then
            sed -i -E "s/^modules=(\"|'\''|)(.*)\1\s*$/modules=\"\2 tcp_bbr\"/" /etc/conf.d/modules
        else
            echo "modules=\"tcp_bbr\"" >> /etc/conf.d/modules
        fi
    fi
    modprobe tcp_bbr 2>/dev/null || true
    sysctl -q -p /etc/sysctl.d/99-mirror.conf
    echo "  拥塞控制: $(sysctl -n net.ipv4.tcp_congestion_control)"'

say "日志轮转"
on 'command -v logrotate >/dev/null || emerge -q app-admin/logrotate
    if command -v logrotate >/dev/null; then echo "  logrotate 已就位"; fi'

say "收紧 sshd"
on "ssh-keygen -l -f /home/${ADMIN}/.ssh/authorized_keys >/dev/null" ||
    { echo '!! 公钥没装好，不动 sshd' >&2; exit 1; }
on "sed -i -E \
      -e 's/^#?PermitRootLogin.*/PermitRootLogin no/' \
      -e 's/^#?PasswordAuthentication.*/PasswordAuthentication no/' \
      -e 's/^#?Port .*/Port ${SSH_PORT}/' /etc/ssh/sshd_config
    grep -qE '^Port ' /etc/ssh/sshd_config || echo 'Port ${SSH_PORT}' >> /etc/ssh/sshd_config
    sshd -t && echo '  sshd 配置通过'"

say "完成"
echo "接下来："
echo "  1. 另开一个终端确认 ssh -i ${PUBKEY%.pub} -p ${SSH_PORT} ${ADMIN}@${TARGET#*@} 能登录"
echo "  2. 确认之后再重启 sshd：ssh ${TARGET} 'rc-service sshd restart'"
echo "     当前这个连接不会中断，重启前请保持它作为退路"
echo "  3. 执行 deploy/install.sh 安装服务"
