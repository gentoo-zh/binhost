# 签名密钥轮替

当前指纹 `6A0726AF1476A2F382C6AC6638A0234EC16AD42E`，2028-07-25 到期。
私钥位于构建机 `/var/lib/binhost/gnupg`，另有一份离线备份。
公钥发布在站点 `/gentoo-zh-binhost.asc`，仓库中的副本在 `site/` 下。

`ops/status.sh` 在到期前 180 天开始告警，为下述重叠期预留时间。

## 目的

用户的 `/etc/portage/gnupg` 只包含导入时的公钥，不会自动更新。改用新密钥签名后，
尚未重新导入公钥的用户会因 `binpkg-request-signature` 拒绝所有软件包，错误信息仅表示
验签失败。因此轮替必须设置新旧密钥同时有效的重叠期。

## 前置条件

- 构建机上可访问 `/var/lib/binhost/gnupg`
- 镜像机的 `/etc/binhost/signing-key.fpr` 可写
- 已确定撤销证书的离线保存位置，且与私钥备份分开

## 操作

### 一、生成新密钥与撤销证书

```bash
gpg --homedir /var/lib/binhost/gnupg --quick-generate-key \
    "gentoo-zh binhost <binhost@gentoozh.org>" ed25519 sign 3y
gpg --homedir /var/lib/binhost/gnupg --output revoke-<新指纹>.asc \
    --gen-revoke <新指纹>
```

撤销证书应与私钥备份分开离线保存。私钥泄露后，维护者可用该证书公开撤销密钥，
无需再次访问私钥。

### 二、把新指纹写入镜像机的记录

`site-sync.sh` 要求 `.asc` 中的每个主公钥指纹都列在 `/etc/binhost/signing-key.fpr`
中，否则本次不发布。该文件由 `install.sh` 的 `SIGNING_FPR` 写入，不在版本库中。
因此必须先更新指纹清单，再提交包含新旧公钥的 `.asc`。顺序颠倒会阻止公钥同步；
错误只写入 `stderr`，镜像机的 `cron` 没有邮件出口。

该文件可以列多个指纹，一行一个。此时保留旧指纹，追加新指纹。

### 三、把新公钥并入已发布的公钥文件

`.asc` 可以包含多个公钥。同时包含新旧公钥后，用户重新导入一次即可信任两者。

```bash
gpg --homedir /var/lib/binhost/gnupg --armor \
    --export <旧指纹> <新指纹> > site/gentoo-zh-binhost.asc
```

提交并合并后，镜像机在下一次五分钟同步周期拉取。CI 检测到 `.asc` 包含多个公钥时
会输出公钥数量，提示第六步仍需收尾。

这一步之后至少等待一个月，供用户重新导入公钥，再更换签名密钥。

### 四、重叠期，至少一个月

继续用旧密钥签名，同时在站点首页与社区渠道说明需要重新导入。

由于无法统计已重新导入公钥的用户数量，重叠期以时间为准。

### 五、改用新密钥签名

先把 `deploy/systemd/binhost-build.service` 与
`deploy/systemd/binhost-build-unstable.service` 的 `Environment=SIGNING_KEY=` 都改成
新指纹。提交合并后，先部署构建机，再核对两个服务实际载入的值：

```bash
SIGNING_KEY=<新指纹> REMOTE="ssh build" ./deploy/install-builder.sh
ssh build 'for unit in binhost-build.service binhost-build-unstable.service; do
    printf "%s  " "$unit"
    systemctl show "$unit" -p Environment --value |
        tr " " "\n" | grep -Fx "SIGNING_KEY=<新指纹>"
done'
```

两个服务都输出新指纹后，才依次重建并发布两个频道。以下命令在构建机的
`/var/lib/binhost` 执行：

```bash
CHANNEL=stable SIGNING_KEY=<新指纹> build/run-full.sh
CHANNEL=stable build/publish.sh
CHANNEL=unstable SIGNING_KEY=<新指纹> build/run-full.sh
CHANNEL=unstable build/publish.sh
```

签名阶段先用新公钥检查暂存索引中的每个软件包。旧密钥签名无法通过该检查，因此脚本会
调用 Portage 的 `gpkg.update_signature` 重新签署全部存量软件包。发布前的独立验签只
导入新公钥，并要求通过验签的软件包数量与 `Packages` 完全一致。

### 六、旧密钥到期后收尾

移除旧公钥之前，先在构建机导出只含新密钥的公钥文件，并分别复核两个频道的暂存代：

```bash
gpg --homedir /var/lib/binhost/gnupg --armor --export <新指纹> \
    > /tmp/binhost-new.asc
python3 build/verify-signatures.py /var/lib/binhost/stage/stable/x86-64 \
    /tmp/binhost-new.asc <新指纹>
python3 build/verify-signatures.py /var/lib/binhost/stage/x86-64 \
    /tmp/binhost-new.asc <新指纹>
```

两条命令都必须成功，且输出数量必须与各自 `Packages` 的 `PACKAGES` 字段相同。
随后从两个公开频道各下载一个软件包，以只含新公钥的文件验证实际下载内容：

```bash
verify_download() (
    set -e
    base=$1
    work=$(mktemp -d)
    trap 'rm -rf "$work"' EXIT
    curl -fsS "$base/Packages" -o "$work/Packages"
    path=$(awk '/^PATH: /{print $2; exit}' "$work/Packages")
    test -n "$path"
    mkdir -p "$work/${path%/*}"
    curl -fsS "$base/$path" -o "$work/$path"
    python3 build/verify-signatures.py \
        "$work" /tmp/binhost-new.asc <新指纹>
)
verify_download https://distfiles.gentoozh.org/binpkgs/x86-64
verify_download https://distfiles.gentoozh.org/unstable/binpkgs/x86-64
```

两个频道的暂存代与公开下载都完成验证之前，不得移除旧公钥。全部通过后，从 `.asc`
中移除旧公钥并重新发布，再把旧指纹从 `/etc/binhost/signing-key.fpr` 中删除。

## 验证

`tests/test-fingerprint-consistent.py` 在 CI 中按 `.asc` 核对以下几处：

- `.asc` 可以包含多把公钥，重叠期即为此状态，它会打印数量提醒收尾
- 仓库中出现的每个指纹都必须是 `.asc` 已发布的公钥
- 两个构建服务必须指定同一把密钥，且该密钥未撤销、具备签名能力
- 当前签名密钥必须同时出现在 `site/index.html` 与本文中
- `.asc` 中不得保留已过期的公钥

它不判断哪个密钥是新密钥，只验证这些位置互相一致，且均包含在已发布的公钥中。

指纹出现在下列位置，轮替时需要同步更新：

| 位置 | 作用 |
|---|---|
| `deploy/systemd/binhost-build.service` 的 `Environment=SIGNING_KEY=` | stable 构建使用的密钥 |
| `deploy/systemd/binhost-build-unstable.service` 的 `Environment=SIGNING_KEY=` | unstable 构建使用的密钥 |
| `site/index.html` 的指纹与复制按钮 | 用户导入后核对的依据 |
| `docs/key-rotation.md` 开头 | 本文记录的当前指纹 |
| 镜像机的 `/etc/binhost/signing-key.fpr` | `site-sync.sh` 据此决定是否同步公钥 |

最后一处不在版本库中，是每台机器自身的记录。因为让检查从被检查的对象中读取
预期值会使检查失去意义，所以它必须独立于仓库。

站点第 1 步的 `--lsign-key` 使用指纹而非邮箱 UID。即使 `.asc` 中包含其他公钥，
该命令也只签署指定指纹对应的公钥。

## 私钥泄露时的处置

顺序与常规轮替相反：

1. 立即发布撤销证书，并入 `.asc` 一同发布，同时在社区渠道公告
2. 生成新密钥
3. 按第五步分别重建并发布 stable 与 unstable，再按第六步验证两个暂存代与公开下载
4. 在站点上说明泄露的时间窗，供在此之前安装过软件包的用户自行判断

`.asc` 中带撤销证书时，用户导入后 `gpg` 会把旧密钥标记为已撤销，用它签名的
软件包立即验签失败。这是预期行为。

## 回滚

第三步之前的任何一步都可以直接放弃，新密钥尚未进入 `.asc`，用户不受影响。

第三步之后，回滚方式是从 `.asc` 中移除新公钥并重新发布，同时把新指纹从
`/etc/binhost/signing-key.fpr` 中删除。因为签名密钥在第五步之前未更换，所以
存量软件包的验签不受影响。

第五步之后不得直接恢复旧密钥。已用新密钥签名的软件包必须再次执行完整签名阶段，
才能改用旧密钥；在此期间，`.asc` 必须保留旧公钥。

## 当前欠缺

- 离线副本只有一份。
