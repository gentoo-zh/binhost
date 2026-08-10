# 镜像机 /srv/pub 的恢复

回答一个问题：源站的公开目录全毁，多久能恢复到可服务，以及哪些内容恢复不了。

本文的数字来自 2026-08-10 在镜像机平行根 `/srv/recovery-rehearsal-<时间戳>` 上的
一次实测演练，全程不碰 `/srv/pub`。**没有演练过的恢复程序不算数**，换一轮之后重新执行
本文的命令即可再量一次。

## 结论摘要

| 内容 | 大小 | 恢复来源 | 实测耗时 |
| --- | ---: | --- | ---: |
| stable binpkg | 1.5 GB / 257 个 | 建置机 PKGDIR | 164 秒 |
| unstable binpkg | 2.2 GB / 433 个 | 建置机 PKGDIR | 225 秒 |
| 内核归档 | 274 MB / 2 个 | **无可用来源，见下** | 36 秒（摘要不符） |
| distfiles | 24 GB / 1330 个 | 各上游 SRC_URI | **未量测，见下** |
| GIG OS ISO | 7.8 GB / 2 个 | `Gig-OS/*` 仓库，建置机有副本 | 未量测 |

两个频道的 binpkg 加起来 **6 分半**可以恢复到可服务并通过同代校验。这一段没有意外。

## 两个演练才发现的问题

### 内核归档从 PKGDIR 恢复出来的档案，摘要与 ebuild 的 Manifest 不一致

`sys-kernel/gentoo-cjk-kernel-bin` 的 Manifest 按 URL 钉死每个档案的
BLAKE2B 与 SHA512。gpkg 不是位元可重现的，外层 tar 带建置时间，**同一个版本重建
一次摘要就变**。实测三个摘要：

```
overlay Manifest        49503e6ab6e5dac7401792496b3d1172…
正式发布的那份           49503e6ab6e5dac7401792496b3d1172…   一致
建置机 PKGDIR 恢复的      f74824e7eaa41c3a64a08ba579f5d2a2…   不一致
```

建置机上找不到摘要相符的副本。因此 `/srv/pub/gentoo-cjk-kernel/` 一旦丢失，
**现有 ebuild 引用的那些版本就取不回来了**：照 PKGDIR 恢复会让每个用户的
digest 检查失败。

可行的做法只有两条，都要人工决定：

1. 恢复后按新档案更新 overlay 的 Manifest 并送 PR，等于换掉那些版本的内容；
2. 事先在别处留一份**已发布位元组**的副本。归档只有 274 MB，成本很低。

第 2 条是防患，第 1 条是事后补救。目前两条都没有做。

### Gentoo 镜像不带我们的 distfiles

抽样 8 个已发布的 distfile，按 Gentoo 镜像的 `filename-hash BLAKE2B 8` 布局取回，
**8 个全部 404**。这些是 gentoo-zh overlay 自己的 distfile，Gentoo 的镜像网络没有。

所以 distfiles 的恢复来源是**各个上游 SRC_URI**，不是 Gentoo 镜像。这带来两个后果：

- 恢复时间取决于几十个第三方站点，不是一条链路。抽样量到 GitHub release
  约 2 MiB/s。
- **上游已经消失的档案恢复不回来。** overlay 里确实有这类包，见 dead-upstream
  的既有记录。

正确的恢复路径是 `emirrordist --mirror --repo gentoo-zh`，它按 SRC_URI 逐个取。
**这一段目前无法在隔离环境下演练**：`deploy/distfiles-sync.sh` 的两个日志路径与
`deploy/audit-distfiles.py` 的孤儿状态、回收目录、清理账本都写死在正式路径，
不先补环境变量覆盖就会改写正式同步状态。补完之后才能量出真实数字。

## 链路速率

建置机到镜像机，`dd | ssh` 排除磁盘之后实测：

| 并行连线 | 合计速率 |
| ---: | ---: |
| 1 | 10 MiB/s |
| 4 | 36 MiB/s |
| 8 | 24 MiB/s |
| 16 | 11 MiB/s，并出现连线逾时 |

两端网卡分别是 10 Gbps 与 2.5 Gbps，所以**限制在单一连线上，不是路径总量**。
四条并行是甜蜜点，再多会退化并开始丢连线。`build/publish.sh` 用单一 rsync，
所以上表的 164 秒与 225 秒是单流的结果；两个频道分开跑就已经是两条流。

## 恢复步骤

前置条件：建置机可登入且 PKGDIR 完好、镜像机可登入、`/srv` 有足够空间
（binpkg 与 distfiles 合计约 28 GB）。

### 0 建立目标目录

`/srv` 属 root，恢复目录要用 root 建立再交给服务账号：

```sh
ssh mirror 'sudo install -dm755 -o zakk -g zakk /srv/pub'
```

### 1 binpkg，每个频道各做一次

从 stage 取代际六档，产物一律从 **PKGDIR** 取，然后用正式 `publish.sh` 发布：

```sh
CH=stable   # stable or unstable
case "$CH" in
  stable)   STAGE=/var/lib/binhost/stage/stable/x86-64
            PKGDIR=/var/cache/binhost/stable/x86-64
            SUB=binpkgs/x86-64 ;;
  unstable) STAGE=/var/lib/binhost/stage/x86-64
            PKGDIR=/var/cache/binhost/x86-64
            SUB=unstable/binpkgs/x86-64 ;;
esac
REC=/var/lib/binhost/stage/.recovery-$CH
rm -rf "$REC"; mkdir -p "$REC"
for f in Packages Packages.gz installed.txt official.txt source.txt generation.json; do
    cp -p "$STAGE/$f" "$REC/$f"
done
awk '/^PATH: /{print $2}' "$REC/Packages" | while read -r rel; do
    mkdir -p "$REC/$(dirname "$rel")"
    cp -p "$PKGDIR/$rel" "$REC/$rel"
done
python3 /var/lib/binhost/build/generation.py verify "$REC"
CHANNEL=$CH STAGE="$REC" REMOTE=mirror REMOTE_ROOT="/srv/pub/$SUB" \
    /var/lib/binhost/build/publish.sh
rm -rf "$REC"
```

整段在建置机上执行，并且要拿到建置锁，避免复制期间 PKGDIR 被下一轮换掉：

```sh
flock -w 60 /var/lib/binhost/stage/build.lock bash <上面那段>
```

### 2 验收

```sh
ssh mirror 'python3 /usr/local/lib/binhost/generation.py verify /srv/pub/binpkgs/x86-64'
curl -sS https://distfiles.gentoozh.org/binpkgs/x86-64/Packages | head -5
p=$(curl -sS https://distfiles.gentoozh.org/binpkgs/x86-64/Packages | awk '/^PATH: /{print $2; exit}')
curl -sS -o /dev/null -w '%{http_code}\n' "https://distfiles.gentoozh.org/binpkgs/x86-64/$p"
ssh build 'cd /var/lib/binhost && ./ops/status.sh'
```

索引条数、`PACKAGES` 头部、六个公开名称是否仍指向 `.gen/`，以及有没有
`.switch-*` 残留，都要看过。

### 3 distfiles

```sh
ssh mirror 'sudo -u root /usr/local/bin/binhost-daily'
```

按 SRC_URI 逐个取回，耗时未量测，失败的档案会留在失败日志里。上游已消失的取不回来。

### 4 内核归档与 GIG OS

内核归档见上面那一节，从 PKGDIR 恢复会让摘要不一致，需要人工决定走哪条路。

GIG OS 不由本仓库产生，恢复来源是 `Gig-OS/Live-ISO`（构建）与
`Gig-OS/gentoozh-liveiso-infra`（`build-and-deploy.sh`、`reupload-iso.sh`）。
当前两份 ISO 在建置机上有副本，恢复是复制而不是重建。**ISO 构建与 binhost 的两轮
构建共用同一台机器**，恢复或重建时要与 08:00 和 20:00 两个时段错开。

## 真的丢了就没有的

- **签章私钥。** 在 `~/.config/gentoozh/` 有离机副本；那份也没了，整条信任链要重来：
  换钥、改站点与 README 的指纹、通知已经导入旧钥的用户。
- **已发布的内核归档位元组。** 见上，现在没有第二份。
- **已经清理掉的历史代际。** 保留策略只留当前一代。
- **上游已经消失的 distfile。**

下游镜像缓存的档案不属于源站状态，不能当作必然可用的恢复来源；只有取得镜像维护者
同意并完成摘要核对之后，才能作为补充来源。
