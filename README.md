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
| `build/` | 构建、暂存、签名、发布与一致性检查 |
| `deploy/` | 镜像机和构建机的安装、同步、定时任务与监控 |
| `ops/` | 两台共用的健康检查与告警 |
| `tools/` | 清单维护、仓库校验与提交检查，供本机与 CI 使用 |
| `nginx/` | HTTP、HTTP/3 和文件服务配置 |
| `site/` | 静态站点与公开签名密钥 |
| `site/tools/` | 站点数据生成与内容检查，供镜像机、本机与 CI 使用 |
| `docs/` | 依赖闭包边界与密钥轮替手册 |

## 发布范围

直接构建目标来自 [`build/packages.txt`](build/packages.txt)。公开 binpkg 索引主要包含
这些 gentoo-zh overlay 软件包，并附带它们需要的部分 `::gentoo` 运行期依赖。两类产物在
同一份 `Packages` 中，以 `REPO` 字段区分。附带内容只覆盖这些运行期依赖，不替代
[Gentoo 官方 binhost](https://wiki.gentoo.org/wiki/Gentoo_Binary_Host_Quickstart)。

每个公开 binpkg 必须同时满足以下条件：

- 当前 ebuild 的 `LICENSE` 表达式属于固定的 `@BINARY-REDISTRIBUTABLE`。
- 当前 ebuild 与缓存 binpkg 的 `RESTRICT` 均不包含 `bindist`。
- 软件包没有列入 [`build/excluded.txt`](build/excluded.txt)。
- 暂存索引中的运行期依赖可由本次发布、基础系统、Gentoo binhost 或源码快照满足。

`acct-group/*`、`acct-user/*` 与 `virtual/*` 由用户系统的 Portage 本地安装，本站不发布
这些类别的 binpkg。`RESTRICT` 中的 `bindist` 只限制 binpkg；distfiles 是否镜像由
`mirror`、`fetch` 与每项 `SRC_URI` 独立决定。

[软件包页](https://distfiles.gentoozh.org/packages)分别显示公开产物、直接构建清单、当前
发布政策和 distfiles 镜像状态。`✓` 表示公开索引已有 binpkg，不表示软件包仍在直接构建
清单。各标签的触发条件和常见原因见
[FAQ 状态说明](https://distfiles.gentoozh.org/faq#package-status)。

## 构建与发布

### 构建环境

构建使用 Docker 中的 Gentoo stage3，目标目录为 `x86-64`，编译参数为：

```text
CFLAGS="-O2 -pipe -march=x86-64 -mtune=generic"
```

`build/run-full.sh` 在基础镜像不存在或已满 7 天时重新生成基础镜像。基础镜像先将
`@world` 与当前 Gentoo 树对齐；对齐失败时保留原有基础镜像，不开始新的完整构建。
日常构建从已对齐的基础镜像启动。

基础镜像更新和日常构建都会执行 ebuild。两个容器均不使用 `--privileged`，不挂载
Docker socket、签名私钥或主机根文件系统，也不从主机挂载 `/dev`。部署验收确认运行中的
构建容器为 `Privileged=false`，且看不到主机根设备 `/dev/sda3`。

基础镜像更新和每次完整构建都会执行 `@preserved-rebuild`，再确认 Portage 没有留下保留库。
重建失败、检查失败或仍有保留库时，本次不会提交新基础镜像，也不会进入暂存、签名或发布
阶段。

### 依赖与暂存

构建容器在 emerge 前记录基础系统的 CPV、SLOT、USE、IUSE、EAPI 与 repository，并在
构建后记录本次实际使用的 Gentoo binhost 索引。暂存阶段按完整 Portage Atom 匹配这些
快照，再从当前 Gentoo 与 gentoo-zh 源码仓库补充无 USE 约束的可见版本。

一般源码依赖带 USE 约束时，不会因用户配置未知而推定为可用。对于本地安装的
`acct-group/*`、`acct-user/*` 与 `virtual/*`，源码快照使用当前 ebuild 的 `IUSE` 默认启用项。
这套检查不等同于执行完整的 Portage 依赖解析，边界记录在
[`docs/dependency-closure.md`](docs/dependency-closure.md)。

暂存索引必须覆盖直接构建清单中每个软件包的当前可用版本，并通过运行期依赖检查。
无法取得必要快照、依赖无法满足或索引不完整时，本次不会发布新索引。

### 签名

签名阶段使用固定 digest 的官方 stage3，不复用执行过 ebuild 的基础镜像。签名容器没有
网络与 Linux capability，根文件系统只读，也不包含 ebuild 仓库。宿主机只挂载暂存目录、
签名脚本，以及从 tmpfs 提供的指定私钥与公钥。

签名容器只重新签署没有当前密钥有效签名的软件包。签名完成后，宿主机使用指定公钥独立
验证每个索引条目，再将已验签的变更写回持久 PKGDIR；没有变化的软件包保持原有字节。

### 安装冒烟测试

依赖与版本检查通过后，构建机在无网络的一次性容器中抽样安装已验签的 gpkg。每个频道
最多检查 32 个包：优先选择最多 24 个本次新签或重新签名的包，再按仓库与包体大小轮替
抽验最多 8 个未变更的包。测试容器只读挂载暂存包、Gentoo binhost 本地缓存与两棵源码
树，不使用特权模式或设备直通。

stable 与 unstable 的结构化报告分别写入
`/var/lib/binhost/logs/stable/x86-64/smoke-install.json` 和
`/var/lib/binhost/logs/x86-64/smoke-install.json`。报告包含以下字段：

- `schema`、`channel`、`revisions` 与 `report_path` 标识报告格式、频道和输入版本。
- `selected` 记录抽样包及其仓库、大小、路径和签名变化状态。
- `strict_eligible`、`source_fallback`、`resolver_failed`、`installed`、
  `gpkg_install_failed` 与 `harness_failed` 记录各阶段结果。
- `duration_seconds` 记录本次检查耗时。

摘要同时写入本轮构建日志。`source_fallback` 是 Portage 在 binpkg 不适用时改用源码构建的
正常行为，因此第一版检查只报告数字，不阻止发布。`gpkg_install_failed` 与
`harness_failed` 会发送告警；测试超过十分钟时归入 `harness_failed`。

### 发布与退役

`Packages`、`Packages.gz`、基础系统快照、Gentoo binhost 快照、源码快照与
`generation.json` 按同一代发布。`generation.json` 记录其余五份文件的 SHA-256；任一
检查失败时，不切换到新的公开索引。镜像上这六个名称是指向 `.gen/` 的符号链接，`.gen`
再指向本次发布的目录，因此整代替换只是一次 rename，不会出现混合代。

源码本地安装、mask、排除或版本移除产生的常规退役，只在新一代索引发布成功后清理。
缓存产物后来设置 `RESTRICT=bindist`、许可证不再允许发布，或再分发资格无法确认时，
产物写入 `quarantine.txt`，并在索引切换前立即隔离。移除之后当场改写当前公开的那一代，
使其不再列出这些文件，因此下架与索引一致，不会留下指向已删除文件的条目。

`build/cycle.sh` 依次更新 overlay、执行完整构建并发布结果。stable 频道使用 Gentoo 主树
稳定关键字，只对 `::gentoo-zh` 接受 `~amd64`；unstable 频道全局接受 `~amd64`。两个频道
使用独立的基础镜像、PKGDIR、暂存区与日志，共用一个构建锁，因此不会同时运行。

| 频道 | 公开路径 | 每日构建时间（UTC+8） |
| --- | --- | --- |
| stable | `/binpkgs/x86-64` | 16:00 后随机 0–15 分钟 |
| unstable | `/unstable/binpkgs/x86-64` | 04:00 后随机 0–15 分钟 |

`build/publish.sh` 会在镜像机上取得发布锁，两个发布者不会同时写入。

`build/kernel-archive.sh` 每日检查 `sys-kernel/gentoo-cjk-kernel` 的各条版本线，并将
对应 `-bin` ebuild 使用的归档发布到 `/gentoo-cjk-kernel/amd64/`。该任务在 10:00
（UTC+8）后随机 0–15 分钟执行，与两个频道的完整构建分开运行。

在确认没有自动构建运行后，可在构建机手动执行：

```bash
CHANNEL=stable SIGNING_KEY=<指纹> build/run-full.sh
CHANNEL=stable build/publish.sh
ops/status.sh
```

将 `CHANNEL` 改为 `unstable` 可手动运行测试频道。不要省略人工操作中的频道名。

设置 `PUBLISH=1` 时，基础镜像会推送到 `ghcr.io/gentoo-zh/binhost-base`。

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
不会覆写另一个频道上一份有效输出。任务分别核验两个频道的同代清单与依赖闭包；distfiles
同步失败时仍使用上一份索引刷新包列表，并保持本次失败状态。TLS 证书和
`/etc/binhost/alert.conf` 需要单独配置。

`deploy/install-builder.sh` 在构建机安装 `build/`、两个频道的 systemd 服务与定时器，并
建立 overlay 副本。脚本检测到构建锁时会中止；运行中的构建不应使用 `FORCE=1` 覆盖。

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

`ops/status.sh` 检查签名密钥与证书有效期、同代索引、实际取包、distfiles、exporter 与
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
- 依赖闭包边界见 [`docs/dependency-closure.md`](docs/dependency-closure.md)。
- 签名密钥轮替与泄露处置见 [`docs/key-rotation.md`](docs/key-rotation.md)。

## 许可

MIT。
