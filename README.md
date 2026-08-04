# gentoo-zh binhost

[distfiles.gentoozh.org](https://distfiles.gentoozh.org/) 的站点、nginx 配置，以及构建和发布 [gentoo-zh overlay](https://github.com/gentoo-zh/overlay) 二进制包的脚本。

```
build/    构建、发布与各项检查。多数在构建机上运行，
          gen-packages.py、status.sh 等几支由 install.sh 装到镜像机
deploy/   两台机器的安装、同步与定时任务
nginx/    服务器配置
site/     站点
docs/     运维手册
```

## 分发

索引与包体都在 distfiles.gentoozh.org，直接由 nginx 提供。

## 构建

在 stage3 容器里构建，`CFLAGS="-O2 -pipe -march=x86-64 -mtune=generic"`。
仓库按 CPU 基线切分（`x86-64`），与 Gentoo 官方 binhost 一致。

发布的主体是收录清单里的 overlay 包，另外附带这些包所需的部分 `::gentoo` 运行期
依赖，两者在同一份索引里，用 `REPO` 字段区分。许可证不允许再分发的、
`RESTRICT=bindist` 的都不发布。附带内容仅包含这些包的运行期依赖，
不替代 Gentoo 官方 binhost。

`@world` 对齐后的容器提交成基础镜像，超过 7 天才刷新，平时的构建从已经对齐好的根开始。

基础镜像更新与每日构建容器都会执行 ebuild。两者不使用 `--privileged`，采用 Docker
默认的设备隔离，并启用 `no-new-privileges`；容器不挂载私钥、Docker socket 或主机根
文件系统。

容器在 emerge 之前记录基础系统的 CPV、SLOT、USE、IUSE、EAPI 与 repository，依赖检查
按完整 Portage Atom 匹配该快照。构建完成后，脚本还会记录当轮实际使用的 Gentoo
binhost 索引。若依赖只能从源码取得，则另从当前 Gentoo 仓库记录可匹配的版本；带 USE
约束的源码依赖不会按未知配置推定为可用。

签名阶段使用固定 digest 的官方 stage3，不复用执行过 ebuild 的基础镜像。该容器没有网络、
Linux capability 与 ebuild 仓库，根文件系统只读；宿主机只挂载暂存目录、必要脚本，以及
在 tmpfs 中导出的指定私钥与公钥。容器只重新签署未由当前密钥有效签名的软件包。签名完成后，
宿主机使用指定公钥独立验证每个索引条目，再将变更写回持久的 PKGDIR；未变化的软件包在
下一轮保持原有字节。

暂存索引必须覆盖 `packages.txt` 中每个包的当前可用版本，并通过运行期依赖检查。
`Packages`、`Packages.gz`、构建前基础系统快照、Gentoo binhost 可用包快照与
Gentoo 源码可用包快照的 SHA-256 写入 `generation.json`，六个文件按同一代发布。
检查失败时保留公开索引与一般清理计划，
但仍立即移除 `quarantine.txt` 中不可继续散布的产物。

`PUBLISH=1` 会把基础镜像推到 `ghcr.io/gentoo-zh/binhost-base`。

`run-full.sh` 在基础镜像过期时自动重建它；`status.sh` 依次核对密钥、证书、索引、
取包、distfiles、exporter 与心跳。

```bash
SIGNING_KEY=<指纹> build/run-full.sh
build/publish.sh
build/status.sh
```

两台机器分别安装。`deploy/install.sh` 在镜像机安装同步、索引、站点、状态检查脚本，以及
`gen-packages.py`、`verify-deps.py`、`generation.py` 等运行依赖。
`deploy/install-builder.sh` 在构建机安装整个 `build/` 目录与 systemd 单元：

```bash
MONITORS='<抓 9100 的监控机>' SIGNING_FPR=<签名指纹> \
  REMOTE=mirror ./deploy/install.sh
SIGNING_KEY=<指纹> REMOTE="ssh build" \
    ./deploy/install-builder.sh
```

构建机还会建立 overlay 副本与每日构建的 systemd timer。入口 `build/cycle.sh` 依次更新
overlay、构建、发布并报告失败。

构建机的本机锁只允许一个 `cycle.sh` 运行。镜像机没有远端发布锁，因此不得并行
执行自动发布与人工 `build/publish.sh`。

## 镜像

873 端口开放只读 rsync，无需申请：

```
rsync://distfiles.gentoozh.org/gentoo-zh/{binpkgs,distfiles}
```

两样都能走 HTTP 或 rsync。`deploy/mirror-sync.sh` 是给只有 HTTP 的下游用的，它只同步二进制包；distfiles 目前没有对应的 HTTP 同步脚本，用 rsync。索引中的 `PATH` 是相对路径，把 `Packages` 和同样相对路径下的文件一并提供即构成一个完整的 binhost。

## 站点

推到 master 后由镜像机主动拉取，五分钟内生效（`deploy/site-sync.sh` + cron）。

需要立即生效或变更 nginx 配置时：

```bash
./deploy-site.sh
```

## 监控

`build/status.sh` 检查签名密钥与证书有效期、索引新鲜度，并实际取回一个包。失败推送到 Telegram。

镜像机每次运行写一个时间戳，构建机上的那份核对它多久没有更新，因为宕机的机器无法自己报告宕机。构建机依据索引的新旧判断：超过两轮没有更新就报出，另有 systemd 的 `OnFailure` 作为后备通道。

后备通道靠退出码区分三种结果，`build/alert-failed.sh` 只对前两种保持沉默：

| 退出码 | 含义 | 后备通道 |
|---|---|---|
| 0 | 全部通过 | 不触发 |
| 10 | 有故障，已直接推送 Telegram | 不再发第二条 |
| 11 | 有故障，与上次相同且在冷却期内 | 不再发第二条 |
| 其他非零 | 有故障但推送失败，或脚本本身出错 | 发出后备告警 |

只有推送成功才记录通知时间，所以手动执行不会让定时任务误以为已经通知过。

## 加入包

见 [CONTRIBUTING.md](CONTRIBUTING.md)。构建不出来或不能分发的包连同原因记在
[`build/excluded.txt`](build/excluded.txt)。

## 签名密钥

轮替与泄露处置见 [docs/key-rotation.md](docs/key-rotation.md)。

## 许可

MIT。
