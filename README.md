# gentoo-zh binhost

[distfiles.gentoozh.org](https://distfiles.gentoozh.org/) 的站点、nginx 配置，以及构建和发布 [gentoo-zh overlay](https://github.com/gentoo-zh/overlay) 二进制包的脚本。

```
site/     站点
nginx/    服务器配置
build/    构建与发布，在构建机上执行
```

## 分发

索引与包体都在 distfiles.gentoozh.org，直接由 nginx 提供。

## 构建

在 stage3 容器里构建，`CFLAGS="-O2 -pipe -march=x86-64 -mtune=generic"`，`FEATURES=binpkg-signing`。仓库按 CPU 基线切分（`x86-64`），与官方 binhost 一致。

只发 overlay 自己的包，且许可证允许再分发；`RESTRICT=bindist` 的不发。

`@world` 对齐后的容器提交成基础镜像，超过 7 天才刷新，平时的构建从已经对齐好的根开始。

`PUBLISH=1` 会把基础镜像推到 `ghcr.io/gentoo-zh/binhost-base`。签名密钥是挂载进容器的，不在镜像里。

```bash
SIGNING_KEY=<指纹> build/run-full.sh          # 基础镜像过期会自动重建
build/publish.sh
build/status.sh                              # 密钥/证书/索引/取包
```

两台机器分开装，没有共用的部分：

```bash
REMOTE=mirror ./deploy/install.sh                       # 镜像机
SIGNING_KEY=<指纹> REMOTE="ssh build" \
    ./deploy/install-builder.sh                          # 构建机
```

构建机那边装的是构建脚本、overlay 副本与每日构建的 systemd timer，
入口是 `build/cycle.sh`：更新 overlay、构建、发布、报告失败。

## 镜像

873 端口开放只读 rsync，无需申请：

```
rsync://distfiles.gentoozh.org/gentoo-zh/{binpkgs,distfiles}
```

二进制包也可以只走 HTTP，用 `deploy/mirror-sync.sh`；distfiles 只提供 rsync。索引中的 `PATH` 是相对路径，把 `Packages` 和同样相对路径下的文件一并提供即构成一个完整的 binhost。

## 站点

推到 master 后由镜像机主动拉取，五分钟内生效（`deploy/site-sync.sh` + cron）。

需要立即生效或变更 nginx 配置时：

```bash
./deploy-site.sh
```

## 监控

`build/status.sh` 检查签名密钥与证书有效期、索引新鲜度，并实际取回一个包。失败推送到 Telegram。

镜像机每次运行写一个时间戳，构建机上的那份检查它多久没更新——宕机的机器报不了自己宕机。构建机本身没有对应的监控。

## 加入包

见 [CONTRIBUTING.md](CONTRIBUTING.md)。构建不出来或不能分发的包连同原因记在
[`build/excluded.txt`](build/excluded.txt)。

## 签名密钥

轮替与泄露处置见 [docs/key-rotation.md](docs/key-rotation.md)。

## 许可

MIT。
