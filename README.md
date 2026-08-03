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

在 stage3 容器里构建，`CFLAGS="-O2 -pipe -march=x86-64 -mtune=generic"`，`FEATURES=binpkg-signing`。仓库按 CPU 基线切分（`x86-64`），与官方 binhost 一致。

发布的主体是收录清单里的 overlay 包，另外附带这些包所需的部分 `::gentoo` 运行期
依赖，两者在同一份索引里，用 `REPO` 字段区分。许可证不允许再分发的、
`RESTRICT=bindist` 的都不发布。附带的依赖范围只到这些包的运行期依赖，
不替代 Gentoo 官方 binhost。

`@world` 对齐后的容器提交成基础镜像，超过 7 天才刷新，平时的构建从已经对齐好的根开始。

`PUBLISH=1` 会把基础镜像推到 `ghcr.io/gentoo-zh/binhost-base`。签名密钥是挂载进容器的，不在镜像里。

`run-full.sh` 在基础镜像过期时自动重建它；`status.sh` 依次核对密钥、证书、索引、
取包、distfiles、exporter 与心跳。

```bash
SIGNING_KEY=<指纹> build/run-full.sh
build/publish.sh
build/status.sh
```

两台机器分开装。build/ 下有几支两边都要（status.sh、gen-packages.py），由各自的安装脚本分别装过去：

前者装镜像机，后者装构建机：

```bash
MONITORS='<抓 9100 的监控机>' SIGNING_FPR=<签名指纹> \
  REMOTE=mirror ./deploy/install.sh
SIGNING_KEY=<指纹> REMOTE="ssh build" \
    ./deploy/install-builder.sh
```

构建机那边装的是构建脚本、overlay 副本与每日构建的 systemd timer，
入口是 `build/cycle.sh`：更新 overlay、构建、发布、报告失败。

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
