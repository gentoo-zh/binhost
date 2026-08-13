# 镜像机 /srv/pub 的恢复

回答一个问题：源站的公开目录全毁，多久能恢复到可服务，以及哪些内容恢复不了。

本文的数字来自在镜像机平行根 `/srv/recovery-rehearsal-<时间戳>` 上的实测演练，
全程不碰 `/srv/pub`：binpkg 与内核归档是 2026-08-10 那轮，distfiles 是 2026-08-13
那轮。**没有演练过的恢复程序不算数**，换一轮之后重新执行本文的命令即可再量一次。

## 结论摘要

| 内容 | 大小 | 恢复来源 | 实测耗时 |
| --- | ---: | --- | ---: |
| stable binpkg | 1.5 GB / 257 个 | 建置机 PKGDIR | 164 秒 |
| unstable binpkg | 2.2 GB / 433 个 | 建置机 PKGDIR | 225 秒 |
| 内核归档 | 274 MB / 2 个 | 建置机已发布副本（补齐后） | **未重新量测** |
| distfiles | 27 GB / 1403 个 | 各上游 SRC_URI | 575 秒，13 个取不回来 |
| GIG OS ISO | 7.8 GB / 2 个 | `Gig-OS/*` 仓库，建置机有副本 | 未量测 |

两个频道的 binpkg 加起来 **6 分半**可以恢复到可服务并通过同代校验。这一段没有意外。
distfiles 再 **9 分半**取回可镜像档案的 98.8%，剩下 13 个上游已经消失，只存在于
我们的镜像上，名单见下。

## 两个演练才发现的问题

### 内核归档必须从已发布副本恢复

`sys-kernel/gentoo-cjk-kernel-bin` 的 Manifest 按 URL 钉死每个档案的
BLAKE2B 与 SHA512。gpkg 不是位元可重现的，外层 tar 带建置时间，**同一个版本重建
一次摘要就变**。实测三个摘要：

```
overlay Manifest        49503e6ab6e5dac7401792496b3d1172…
正式发布的那份           49503e6ab6e5dac7401792496b3d1172…   一致
建置机 PKGDIR 恢复的      f74824e7eaa41c3a64a08ba579f5d2a2…   不一致
```

因此不能从 PKGDIR 恢复内核归档。`kernel-archive.sh` 现在把成功发布的档案原样保留在
`PUBLISHED_DIR`，默认路径是 `/var/lib/binhost/kernel-published/<系列>/<发布名>`。
副本只在 rsync 成功后写入；同一个发布名会被新副本覆盖。远端档案与本地副本使用同一份
overlay 清单和 `MAX_RETIRE` 上限，overlay 移除版本后，两处档案在同一轮清理。

部署这项改动时，既有两条内核线尚无本地副本。执行一次正常归档任务即可补齐：脚本从
镜像机取回已发布档案，核对大小与 overlay Manifest 的摘要，再把临时档案改成发布名。
核对失败时，脚本不写入副本并以非零状态结束。

```sh
BUILD_ROOT=${BUILD_ROOT:-/var/lib/binhost/build}
PUBLISHED_DIR=${PUBLISHED_DIR:-/var/lib/binhost/kernel-published}
PUBLISHED_DIR="$PUBLISHED_DIR" bash "$BUILD_ROOT/kernel-archive.sh"
```

这次执行不会重建摘要相符的既有版本；远端档案通过 Manifest 核验后，脚本直接补齐并跳过
建置。补齐完成之前，内核归档仍没有可用的恢复来源。

### Gentoo 镜像不带我们的 distfiles

抽样 8 个已发布的 distfile，按 Gentoo 镜像的 `filename-hash BLAKE2B 8` 布局取回，
**8 个全部 404**。这些是 gentoo-zh overlay 自己的 distfile，Gentoo 的镜像网络没有。

所以 distfiles 的恢复来源是**各个上游 SRC_URI**，不是 Gentoo 镜像。这带来两个后果：

- 恢复时间取决于几十个第三方站点，不是一条链路。抽样量到 GitHub release
  约 2 MiB/s。
- **上游已经消失的档案恢复不回来。** overlay 里确实有这类包，见 dead-upstream
  的既有记录。

正确的恢复路径是 `emirrordist --mirror --repo gentoo-zh`，它按 SRC_URI 逐个取。
同步日志、孤儿状态、回收目录与清理账本现在都能指向平行根，不会改写正式同步状态。
2026-08-13 在平行根上实测过，数字见下一节。

## distfiles 实测

2026-08-13 08:57 UTC 在镜像机的平行根
`/srv/recovery-rehearsal-20260813-085718` 上执行，握着 `binhost-daily` 的锁，
所以每小时那轮同步让开，不与它争上游带宽。当时公开目录是 27 GB、1403 个档案。

| 项目 | 结果 |
| --- | ---: |
| 首次同步 | 575 秒（9 分半），退出码 0 |
| 取回 | 1088 个档案，19 GB |
| 平均速率 | 34 MB/s |
| 取不回来 | 13 个 |
| 第二次同步（增量） | 4 秒，退出码 0 |

孤儿检查在隔离状态下正常执行：overlay 引用 1279 个，其中可镜像 1101、
不可镜像 178；平行根上 1088，缺 13。也就是**可镜像的档案恢复了 98.8%**。

### 这 13 个恢复不回来

不是网络问题，其余 1088 个同一轮都取到了。它们只存在于我们的镜像上：

```
zhwiki-20251220-all-titles-in-ns0.gz                   app-dicts/fcitx-pinyin-zhwiki
glibc-systemd-20210729.tar.gz                          app-emulation/liblol-glibc
autopxd2-3.2.3.tar.gz.provenance                       dev-python/autopxd2
conda-26.7.0.tar.gz                                    dev-python/conda
janus-2.0.0.tar.gz.provenance                          dev-python/janus
mw2fcitx-0.25.1.tar.gz.provenance                      dev-python/mw2fcitx
Sarasa-TTC-1.0.39.zip                                  media-fonts/sarasa-gothic
circuitjs1-bin-4.1.3.tar.gz                            sci-electronics/circuitjs1-bin
gentoo-kernel-config-g19.tar.bz2                       sys-kernel/gentoo-cjk-kernel
genpatches-6.12-37.base.tar.xz                         sys-kernel/xanmod-rt
genpatches-6.12-37.experimental.tar.xz                 sys-kernel/xanmod-rt
genpatches-6.12-37.extras.tar.xz                       sys-kernel/xanmod-rt
kernel-x86_64-fedora.config.6.12.12-200.fc41           sys-kernel/xanmod-rt
```

`gentoo-kernel-config-g19.tar.bz2` 要特别记一笔：`gentoo-cjk-kernel` 建置时需要
它，没有这个档案连内核都建不出来，而内核归档的恢复又依赖建置机能重新建置。

镜像本身就是这些档案唯一的存放处，所以 `/srv/pub/distfiles` 全毁时它们不在
「九分半恢复 98.8%」的范围内。要不要另外备份、备到哪里，是尚未决定的事。

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

前置条件：建置机可登入且 PKGDIR 与内核已发布副本完好、镜像机可登入、`/srv` 有足够
空间（binpkg 与 distfiles 合计约 28 GB）。

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
ssh mirror 'sudo sh -s' <<'EOF'
ROOT=/srv/recovery-rehearsal-$(date +%Y%m%d-%H%M%S)
install -dm755 "$ROOT"

DEST="$ROOT/distfiles" \
STATE="$ROOT/emirrordist" \
TEMP_DIR="$ROOT/.emirrordist-tmp" \
FAILURE_LOG="$ROOT/log/emirrordist/failures.log" \
SUCCESS_LOG="$ROOT/log/emirrordist/successes.log" \
    /usr/local/bin/binhost-distfiles-sync

ORPHAN_ORPHAN_STATE="$ROOT/emirrordist/orphans.json" \
RECYCLE="$ROOT/emirrordist/recycle" \
LEDGER="$ROOT/emirrordist/reaped.json" \
    python3 /usr/local/lib/binhost/audit-distfiles.py \
    /var/lib/binhost-overlay "$ROOT/distfiles"
EOF
```

这两条命令的目标、数据库、日志与清理状态都在同一个平行根下。同步会按 SRC_URI
逐个取回，失败的档案会记在平行根的失败日志里。上游已消失的档案取不回来。
本段的实测耗时与结果仍待补，不要填入估算值。

### 4 内核归档与 GIG OS

内核归档只能从已发布副本恢复。先逐个核对 Manifest；全部通过后，才把原有目录结构同步
到镜像机：

```sh
set -euo pipefail
BUILD_ROOT=${BUILD_ROOT:-/var/lib/binhost/build}
OVERLAY=${OVERLAY:-/var/lib/binhost/overlay}
PUBLISHED_DIR=${PUBLISHED_DIR:-/var/lib/binhost/kernel-published}
MANIFEST=${MANIFEST:-$OVERLAY/sys-kernel/gentoo-cjk-kernel-bin/Manifest}
REMOTE=${REMOTE:-mirror}
REMOTE_ROOT=${REMOTE_ROOT:-/srv/pub/gentoo-cjk-kernel/amd64}

mapfile -d '' files < <(find "$PUBLISHED_DIR" -mindepth 2 -maxdepth 2 \
    -type f -name '*.gpkg.tar' -print0)
((${#files[@]})) || { echo "没有可恢复的内核归档副本" >&2; exit 1; }
for f in "${files[@]}"; do
    python3 "$BUILD_ROOT/kernel-manifest.py" verify \
        "$MANIFEST" "$(basename "$f")" "$f"
done
ssh "$REMOTE" "install -dm755 '$REMOTE_ROOT'"
rsync -a "$PUBLISHED_DIR/" "$REMOTE:$REMOTE_ROOT/"
```

不要用 PKGDIR 代替 `PUBLISHED_DIR`，即使版本和发布名相同，重建的 gpkg 摘要也可能不同。

GIG OS 不由本仓库产生，恢复来源是 `Gig-OS/Live-ISO`（构建）与
`Gig-OS/gentoozh-liveiso-infra`（`build-and-deploy.sh`、`reupload-iso.sh`）。
当前两份 ISO 在建置机上有副本，恢复是复制而不是重建。**ISO 构建与 binhost 的两轮
构建共用同一台机器**，恢复或重建时要与 08:00 和 20:00 两个时段错开。

## 真的丢了就没有的

- **签章私钥。** 在 `~/.config/gentoozh/` 有离机副本；那份也没了，整条信任链要重来：
  换钥、改站点与 README 的指纹、通知已经导入旧钥的用户。
- **镜像机归档与建置机已发布副本同时丢失的内核归档位元组。** PKGDIR 不能替代已发布
  副本，因为同版本重建的 gpkg 摘要可能不同。
- **已经清理掉的历史代际。** 保留策略只留当前一代。
- **上游已经消失的 distfile。**

下游镜像缓存的档案不属于源站状态，不能当作必然可用的恢复来源；只有取得镜像维护者
同意并完成摘要核对之后，才能作为补充来源。
