# gentoo-zh binhost

本仓库维护 [distfiles.gentoozh.org](https://distfiles.gentoozh.org/) 的静态站点、
nginx 配置，以及构建、签名和发布 [gentoo-zh overlay](https://github.com/gentoo-zh/overlay)
二进制包的脚本。

用户可直接查看[配置步骤](https://distfiles.gentoozh.org/)、
[软件包状态](https://distfiles.gentoozh.org/packages)和
[常见问题](https://distfiles.gentoozh.org/faq)。

## 仓库结构

| 路径 | 内容 |
| --- | --- |
| `builders/` | 两个频道的构建机配置、更新、签名与发布 |
| `build/` | 软件包清单、内核归档，以及只为回滚保留的旧流水线 |
| `deploy/` | 镜像机和构建机的安装、同步、定时任务与监控 |
| `ops/` | 两台共用的健康检查与告警 |
| `tools/` | 清单维护、仓库校验与提交检查，供本机与 CI 使用 |
| `nginx/` | HTTP、HTTP/3 和文件服务配置 |
| `site/` | 静态站点与公开签名密钥 |
| `site/tools/` | 站点数据生成与内容检查，供镜像机、本机与 CI 使用 |
| `docs/` | 密钥轮替、恢复与已评估未实施的改动 |

## 发布范围

直接构建目标来自 [`build/packages.txt`](build/packages.txt)，`tools/gen-worlds.py` 由它与
[`build/stable-excluded.txt`](build/stable-excluded.txt) 生成两个频道构建机的 world。构建机
发布整个 PKGDIR：这些 gentoo-zh overlay 软件包，以及构建时从源码编译的 `::gentoo`
依赖（运行期与构建期）。两类产物在同一份 `Packages` 中，以 `REPO` 字段区分。附带的
`::gentoo` 包由构建需要决定，不替代
[Gentoo 官方 binhost](https://wiki.gentoo.org/wiki/Gentoo_Binary_Host_Quickstart)。

构建机在签名前删除不满足以下任一条件的 binpkg：

- 当前 ebuild 的 `LICENSE` 表达式属于固定的 `@BINARY-REDISTRIBUTABLE`。
- 当前 ebuild 未被 mask，关键字符合本频道设置。
- 按该 binpkg 的 USE 求值，当前 ebuild 的 `RESTRICT` 不包含 `bindist`。
- 当前 ebuild 不继承 `linux-mod`。

列入 [`build/excluded.txt`](build/excluded.txt) 的软件包不进入 world，因此不会构建。
`RESTRICT` 中的 `bindist` 只限制 binpkg；distfiles 是否镜像由 `mirror`、`fetch` 与每项
`SRC_URI` 独立决定。

[软件包页](https://distfiles.gentoozh.org/packages)分别显示公开产物、直接构建清单、当前
发布政策和 distfiles 镜像状态。`✓` 表示公开索引已有 binpkg，不表示软件包仍在直接构建
清单。各标签的触发条件和常见原因见
[FAQ 状态说明](https://distfiles.gentoozh.org/faq#package-status)。

## 构建与发布

每个频道在构建机上有一台常驻 systemd-nspawn 机器 `binhost-<频道>`，使用
`desktop/systemd` profile，目标目录为 `x86-64`，编译参数为：

```text
CFLAGS="-O2 -pipe -march=x86-64 -mtune=generic"
```

stable 频道使用 Gentoo 主树稳定关键字，只对 `::gentoo-zh` 接受 `~amd64`；unstable 频道
全局接受 `~amd64`。`builders/binhost-update <频道>` 每轮依次执行：

1. 同步 Gentoo 与 gentoo-zh 仓库，并给机器建 ZFS 快照。
2. 在机器内执行 `emerge -uDN --changed-deps @world`，再清理不再需要的软件包和 binpkg。
3. `prune-unpublishable` 删除不满足发布条件的 binpkg。
4. 宿主机在无网络的 `systemd-run` 沙箱中以 `gpkg-sign` 签署尚未签名的包。
5. `emaint binhost --fix` 重建 `Packages`，再由 rsync 将整个 PKGDIR 同步到公开路径。

签名沙箱只能写入 PKGDIR 与签名密钥目录。第 2 步失败时，本轮仍发布已构建的包并发送
告警；第 3 至 5 步任一失败时，本轮不发布并发送告警。rsync 使用 `--delay-updates` 与
`--delete-after`，传输结束后才替换文件，并删除镜像上已不在 PKGDIR 中的文件。部署、
快照回滚等操作见 [`builders/README.md`](builders/README.md)。

| 频道 | 公开路径 | 每日构建时间（UTC+8） |
| --- | --- | --- |
| stable | `/binpkgs/x86-64` | 16:00 后随机 0–15 分钟 |
| unstable | `/unstable/binpkgs/x86-64` | 04:00 后随机 0–15 分钟 |

两个频道共用一个构建锁，因此不会同时运行；锁被占用时本轮跳过。

`build/kernel-archive.sh` 每日检查 `sys-kernel/gentoo-cjk-kernel` 的各条版本线，并将
对应 `-bin` ebuild 使用的归档发布到 `/gentoo-cjk-kernel/amd64/`。该任务在 10:00
（UTC+8）后随机 0–15 分钟执行，与两个频道的构建分开运行。

在确认没有自动构建运行后，可在构建机手动执行：

```bash
systemctl start binhost-update@stable.service
ops/status.sh
```

将 `stable` 改为 `unstable` 可手动运行测试频道。

`build/` 中基于 Docker 的旧流水线已停止定时运行，只为回滚保留，后续删除。

## 部署

镜像机与构建机分别安装。以下命令假设本机已有可用的 `mirror` 和 `build` SSH 目标：

```bash
MONITORS='<抓取 9100 的监控机地址>' SIGNING_FPR=<签名指纹> \
  REMOTE=mirror ./deploy/install.sh
SIGNING_KEY=<签名指纹> REMOTE="ssh build" \
  ./deploy/install-builder.sh
```

`deploy/install.sh` 在镜像机安装 nginx、rsync、distfiles 同步、站点同步、状态检查与相关
定时任务。每日任务分别生成 stable 与 unstable 的网页数据和纯文本清单；一个频道生成失败
不会覆写另一个频道上一份有效输出。任务分别检查两个频道的 `Packages` 能否解析、
`PACKAGES` 是否等于 `PATH` 条数，以及每个 `PATH` 是否存在；distfiles 同步失败时仍使用
上一份索引刷新包列表，并保持本次失败状态。TLS 证书和 `/etc/binhost/alert.conf` 需要
单独配置。

`deploy/install-builder.sh` 在构建机安装 `build/`、内核归档与状态检查的定时器，并停用旧
流水线的 `binhost-build*.timer`。脚本检测到构建锁时会中止；运行中的构建不应使用
`FORCE=1` 覆盖。两个频道的更新单元按 [`builders/README.md`](builders/README.md) 安装。

## 镜像

源站同时通过 HTTP 与只读 rsync 提供 binpkg 和 distfiles。rsync 无需申请：

```text
rsync://distfiles.gentoozh.org/gentoo-zh/binpkgs
rsync://distfiles.gentoozh.org/gentoo-zh/distfiles
```

`Packages` 中的 `PATH` 使用相对路径。镜像同时提供索引和对应相对路径下的文件后，即可
作为完整 binhost 使用。

[`deploy/mirror-sync.sh`](deploy/mirror-sync.sh) 供只有 HTTP 的下游同步 binpkg；它不处理
distfiles。完整镜像应使用 rsync module。

## 站点

镜像机的 `deploy/site-sync.sh` 每五分钟从 `master` 拉取并发布静态站点。站点同步使用
独立锁，不修改 binpkg 或 distfiles。页面与 assets 先写进本次发布的目录，再由一次
rename 整体切换，因此不会出现页面与其指纹化 assets 分属两代的中间状态。

需要立即发布站点，或同时更新 nginx 配置时执行：

```bash
./deploy-site.sh
```

该脚本先通过指纹清单验证公开密钥，再发布站点；nginx 配置通过 `nginx -t` 后才重新载入。

## 监控

`ops/status.sh` 检查签名密钥与证书有效期、索引一致性、实际取包、distfiles、exporter 与
心跳。配置 `/etc/binhost/alert.conf` 后，故障会发送到 Telegram。

镜像机每次检查都会更新时间戳。构建机检查该时间戳，避免镜像机宕机后无法自行报告。
索引超过两个构建周期没有更新时，构建机发出告警；systemd 的 `OnFailure` 提供后备通道。

| 退出码 | 含义 | 后备通道 |
| --- | --- | --- |
| 0 | 全部检查通过 | 不触发 |
| 10 | 检查失败，Telegram 已发送 | 不重复发送 |
| 11 | 检查失败，与上次相同且仍在冷却期 | 不重复发送 |
| 其他非零 | Telegram 发送失败或检查脚本出错 | 发送后备告警 |

只有 Telegram 发送成功后才记录通知时间，因此手动检查不会无条件延长冷却期。

## 维护

- 添加、移除或移动软件包见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。
- 排除的软件包及原因见 [`build/excluded.txt`](build/excluded.txt)。
- 签名密钥轮替与泄露处置见 [`docs/key-rotation.md`](docs/key-rotation.md)。

## 许可

MIT。
