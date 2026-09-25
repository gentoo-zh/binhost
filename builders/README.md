# builders

每个频道一台常驻 systemd-nspawn 机器 `binhost-<频道>`，由 `binhost-update <频道>` 在宿主机以 root 执行。以下以 `stable` 为例，`unstable` 相同，仓库部署在 `/var/lib/binhost`，告警配置 `/etc/binhost/alert.conf` 须已存在，宿主机已同步 gentoo 与 gentoo-zh，root 能 ssh 到发布目标，签名私钥不设口令：

```sh
printf '[gentoo-zh]\nlocation = /var/db/repos/gentoo-zh\nsync-type = git\nsync-uri = https://github.com/gentoo-zh/overlay.git\n' > /etc/portage/repos.conf/gentoo-zh.conf
install -d -m 0700 -o root -g root /var/lib/binhost/gnupg && gpg --homedir /var/lib/binhost/gnupg --batch --import <签名私钥文件>
getuto && gpg --homedir /etc/portage/gnupg --batch --import <签名公钥文件> && echo '<签名公钥指纹>:6:' | gpg --homedir /etc/portage/gnupg --batch --import-ownertrust && gpg --homedir /etc/portage/gnupg --batch --check-trustdb
zfs create -p -o mountpoint=/var/lib/machines/binhost-stable binhost/machines/stable
tar xpf stage3-amd64-desktop-systemd-*.tar.xz --xattrs-include='*.*' --numeric-owner -C /var/lib/machines/binhost-stable
mkdir -p /var/cache/distfiles /var/cache/binhost/{stable,gentoo} /var/tmp/portage/stable
cd /var/lib/machines/binhost-stable/etc/portage
for f in /var/lib/binhost/builders/stable/portage/*; do rm -rf "${f##*/}"; ln -s "/etc/binhost/stable/portage/${f##*/}" .; done
ln -sf /etc/binhost/stable/world ../../var/lib/portage/world
mkdir -p repos.conf && printf '[gentoo-zh]\nlocation = /var/db/repos/gentoo-zh\n' > repos.conf/gentoo-zh.conf
N="systemd-nspawn -M binhost-stable --bind-ro /var/db/repos/gentoo --bind-ro /var/db/repos/gentoo-zh --bind-ro /var/lib/binhost/builders:/etc/binhost"
$N --bind-ro <签名公钥文件>:/tmp/binhost.asc sh -c 'getuto && gpg --homedir /etc/portage/gnupg --batch --import /tmp/binhost.asc && echo "<签名公钥指纹>:6:" | gpg --homedir /etc/portage/gnupg --batch --import-ownertrust && gpg --homedir /etc/portage/gnupg --batch --check-trustdb'
$N emerge -pvuDN @world > /tmp/world-stable.txt
```

宿主机的 `/etc/portage/gnupg` 用于 `gpkg-sign --skip-signed` 以 nobody 身份校验已签名的包。两台机器的 `emerge -pvuDN @world` 输出交给维护者，确认没有冲突后再安装单元并启用 timer：`cp /var/lib/binhost/deploy/systemd/binhost-{alert@.service,update@.service,update-*.timer} /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now binhost-update-{stable,unstable}.timer`。

`binhost-update` 每轮更新前给机器建快照，保留最近 7 个。更新损坏机器时回滚：`zfs rollback -r binhost/machines/stable@<时间>`，并从 PKGDIR 删除造成损坏的 binpkg。
