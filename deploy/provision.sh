#!/bin/bash
# One-time provisioning for a new mirror. Runs locally, acts over ssh.
#
#   TARGET=root@203.0.113.7 deploy/provision.sh
#
# The order is deliberate: each step proves the new path works before the old
# one is cut, so a failure anywhere cannot lock us out.
#
# The previous machine was fixed up as problems appeared; this does all of it
# at once:
#   - the interface name did not match /etc/conf.d/net, so a reboot lost the host
#   - only C/POSIX was generated, so the LC_* ssh carries over made every command
#     report a setlocale failure
#   - logrotate.d held configuration while logrotate itself was not installed, so
#     nothing ever rotated
#   - a wrong firewall rule locks the machine out, so every change here carries
#     an automatic rollback

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
                              # remote, not here
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
# ssh carries the client LANG/LC_* across, and without the matching locale on
# the server every command reports a setlocale failure. The system itself stays
# on C.UTF-8.
on 'printf "en_US.UTF-8 UTF-8\nen_GB.UTF-8 UTF-8\nzh_CN.UTF-8 UTF-8\nzh_TW.UTF-8 UTF-8\n" > /etc/locale.gen
    locale-gen > /tmp/lg.log 2>&1 || echo "  !! locale-gen 没跑完"
    tail -1 /tmp/lg.log | sed "s/^/  /"; rm -f /tmp/lg.log'

say "网络：确认开机不会失联"
# shellcheck disable=SC2016  # as above, expands on the remote
on 'iface=$(ip -o -4 route show default | awk "{print \$5}" | head -1)
    echo "  默认路由走 ${iface}"
    if [ -f /etc/conf.d/net ] && grep -q "^config_" /etc/conf.d/net; then
        grep -q "config_${iface}" /etc/conf.d/net \
            && echo "  /etc/conf.d/net 与网卡名一致" \
            || echo "  !! /etc/conf.d/net 配的不是 ${iface}，重启会失联"
    fi
    if [ -d /etc/init.d ]; then
        rc-update show default 2>/dev/null | grep -qE "dhcpcd|net\." \
            && echo "  网络服务在 default runlevel" \
            || echo "  !! 没有网络服务在 default runlevel"
    fi'

say "内核网络调优"
# shellcheck disable=SC2016  # the heredoc is written out verbatim, no local
                              # expansion
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
    # OpenRC loads modules from here, not from the systemd modules-load.d
    # 追加到既有的值里，不是再写一行。OpenRC 是 source 这个文件，后面的赋值
    # 盖前面的：原来那一行会让机器上本来有的 modules= 下次开机全部不再加载。
    if [ -f /etc/conf.d/modules ] && ! grep -q tcp_bbr /etc/conf.d/modules; then
        if grep -q "^modules=" /etc/conf.d/modules; then
            sed -i "s/^modules=\"\(.*\)\"/modules=\"\1 tcp_bbr\"/" /etc/conf.d/modules
        else
            echo "modules=\"tcp_bbr\"" >> /etc/conf.d/modules
        fi
    fi
    modprobe tcp_bbr 2>/dev/null || true
    sysctl -q -p /etc/sysctl.d/99-mirror.conf
    echo "  拥塞控制: $(sysctl -n net.ipv4.tcp_congestion_control)"'

say "日志轮转"
# /etc/logrotate.d often already holds configuration while logrotate itself is
# not installed, and then none of it does anything.
on 'command -v logrotate >/dev/null || emerge -q app-admin/logrotate
    if command -v logrotate >/dev/null; then echo "  logrotate 已就位"; fi'

say "收紧 sshd"
# Last, and only once key login is confirmed working: the other order locks the
# machine out.
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
echo "     当前这个连接不会断，重启前留着它当退路"
echo "  3. 跑 deploy/install.sh 装服务"
