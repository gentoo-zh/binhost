#!/bin/bash
# 新镜像机的一次性布建。在本机执行，通过 ssh 作用于目标。
#
#   TARGET=root@203.0.113.7 deploy/provision.sh
#
# 顺序是有意的：每一步都先验证新路可用，再断旧路。中途任何一步失败都不会把
# 自己关在门外。
#
# 上一台是边做边补，这里把当时踩过的坑一次做完：
#   - 网卡名与 /etc/conf.d/net 对不上，一重启就失联
#   - 只生成了 C/POSIX，SSH 带过来的 LC_* 让每条命令都报 setlocale 失败
#   - logrotate.d 有配置但 logrotate 没装，日志永不轮转
#   - 防火墙规则改错会锁死自己（这里一律挂自动回滚）

set -euo pipefail

TARGET="${TARGET:?用法: TARGET=root@主机 $0}"
ADMIN="${ADMIN:-zakk}"
SSH_PORT="${SSH_PORT:-60001}"
PUBKEY="${PUBKEY:-$HOME/.ssh/gentoozh_mirror.pub}"

[[ -r ${PUBKEY} ]] || { echo "找不到公钥 ${PUBKEY}" >&2; exit 1; }

say() { printf '\n=== %s ===\n' "$1"; }
on()  { ssh -o StrictHostKeyChecking=accept-new "${TARGET}" "$@"; }

say "现状"
# shellcheck disable=SC2016  # 单引号是有意的：这些命令要在远端展开，不是本地
on 'echo "  $(uname -sr)"; echo "  init: $(ps -p1 -o comm=)"; echo "  $(df -h / | awk "NR==2{print \$2\" 盘，已用 \"\$3}")"; echo "  $(free -h | awk "/^Mem/{print \$2\" 内存\"}")"'

say "管理员与密钥"
on "id ${ADMIN} >/dev/null 2>&1 || useradd -m -G wheel -s /bin/bash ${ADMIN}
    install -dm700 -o ${ADMIN} -g ${ADMIN} /home/${ADMIN}/.ssh"
# shellcheck disable=SC2029  # ADMIN 就是要在本地展开成具体路径
ssh "${TARGET}" "install -m600 -o ${ADMIN} -g ${ADMIN} /dev/stdin /home/${ADMIN}/.ssh/authorized_keys" < "${PUBKEY}"
on "command -v sudo >/dev/null || emerge -q app-admin/sudo
    echo '${ADMIN} ALL=(ALL:ALL) NOPASSWD: ALL' > /etc/sudoers.d/${ADMIN}
    chmod 440 /etc/sudoers.d/${ADMIN}
    visudo -c >/dev/null && echo '  sudoers 语法 ok'"

say "locale"
# SSH 会把客户端的 LANG/LC_* 带过来，服务器上没有对应 locale 时每条命令都报
# setlocale 失败。系统自身仍用 C.UTF-8。
on 'printf "en_US.UTF-8 UTF-8\nen_GB.UTF-8 UTF-8\nzh_CN.UTF-8 UTF-8\nzh_TW.UTF-8 UTF-8\n" > /etc/locale.gen
    locale-gen 2>&1 | tail -1 | sed "s/^/  /"'

say "网络：确认开机不会失联"
# shellcheck disable=SC2016  # 同上，远端展开
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
# shellcheck disable=SC2016  # heredoc 内容原样写到远端，不在本地展开
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
    # OpenRC 的模块自载入在这里，不是 systemd 的 modules-load.d
    [ -f /etc/conf.d/modules ] && ! grep -q tcp_bbr /etc/conf.d/modules \
        && echo "modules=\"tcp_bbr\"" >> /etc/conf.d/modules
    modprobe tcp_bbr 2>/dev/null || true
    sysctl -q -p /etc/sysctl.d/99-mirror.conf
    echo "  拥塞控制: $(sysctl -n net.ipv4.tcp_congestion_control)"'

say "日志轮转"
# /etc/logrotate.d 里常常已有配置，但 logrotate 本身没装，那些配置一条都不生效
on 'command -v logrotate >/dev/null || emerge -q app-admin/logrotate
    if command -v logrotate >/dev/null; then echo "  logrotate 已就位"; fi'

say "收紧 sshd"
# 放在最后，且只在密钥登录确认可用之后：顺序反了会把自己关在门外。
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
