# 签名密钥轮替

当前指纹 `6A0726AF1476A2F382C6AC6638A0234EC16AD42E`，2028-07-25 到期。
私钥位于建置机 `/var/lib/binhost/gnupg`，另有一份离线副本。
公钥发布在站点 `/gentoo-zh-binhost.asc`，仓库中的副本在 `site/` 下。

`build/status.sh` 在到期前 180 天开始告警，这个提前量用于下面的重叠期。

## 目的

用户的 `/etc/portage/gnupg` 只包含导入时的那一份公钥，没有任何机制会自动更新。
因为换用新密钥签名后，未重新导入的用户会被 `binpkg-request-signature` 拒收全部
软件包，而错误信息只说验签未通过，所以轮替必须是一段两把密钥同时有效的时间，
不能一次切换。

## 前置条件

- 建置机上可访问 `/var/lib/binhost/gnupg`
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

撤销证书离线保存，与私钥备份分开存放。私钥泄露时它是唯一能公开作废该密钥的
手段，而那种情况下通常没有时间重新生成。

### 二、把新指纹写入镜像机的记录

`site-sync.sh` 要求 `.asc` 中的每一把主公钥都在 `/etc/binhost/signing-key.fpr`
内，只要有一把不在就整轮不发布。因为该文件由 `install.sh` 的 `SIGNING_FPR`
写入、不在版本库中，所以必须先更新它，再推带两把公钥的 `.asc`。顺序反了会让
公钥同步停住，而失败只写 stderr，这台机器的 cron 没有邮件出口。

该文件可以列多个指纹，一行一个。此时保留旧指纹，追加新指纹。

### 三、把新公钥并入已发布的那一份

`.asc` 可以包含多把公钥，两把都放进去，用户导入一次即同时信任新旧。

```bash
gpg --homedir /var/lib/binhost/gnupg --armor \
    --export <旧指纹> <新指纹> > site/gentoo-zh-binhost.asc
```

提交并合并，等镜像机拉取，五分钟内完成。CI 会通过，只是打印 `.asc` 中现有
两把公钥，提醒第六步回来收尾。

这一步之后不要立即更换签名密钥，先给用户留出重新导入的时间。

### 四、重叠期，至少一个月

继续用旧密钥签名，同时在站点首页与社区渠道说明需要重新导入。

判断可以继续的依据是时间，不是观察，因为无法得知有多少用户已经导入。

### 五、改用新密钥签名

先把 `deploy/systemd/binhost-build.service` 的 `Environment=SIGNING_KEY=`
改成新指纹，再执行：

```bash
SIGNING_KEY=<新指纹> build/run-full.sh
build/publish.sh
```

签名阶段先用新公钥检查暂存索引中的每个软件包。旧密钥签名无法通过该检查，因此脚本会
调用 Portage 的 `gpkg.update_signature` 重新签署全部存量软件包。发布前的独立验签只
导入新公钥，并要求通过验签的软件包数量与 `Packages` 完全一致。

### 六、旧密钥到期后收尾

移除旧公钥之前，先在建置机导出只含新密钥的公钥文件并复核暂存代：

```bash
gpg --homedir /var/lib/binhost/gnupg --armor --export <新指纹> \
    > /tmp/binhost-new.asc
python3 build/verify-signatures.py /var/lib/binhost/stage/x86-64 \
    /tmp/binhost-new.asc <新指纹>
```

命令必须成功，且输出数量必须与 `Packages` 的 `PACKAGES` 字段相同。随后从 `.asc`
中移除旧公钥并重新发布，再把旧指纹从 `/etc/binhost/signing-key.fpr` 中删除。

## 验证

`tests/test-fingerprint-consistent.py` 在 CI 中按 `.asc` 核对以下几处：

- `.asc` 可以包含多把公钥，重叠期即为此状态，它会打印数量提醒收尾
- 仓库中出现的每个指纹都必须是 `.asc` 已发布的公钥
- `binhost-build.service` 只能指定一把，且未撤销、具备签名能力
- 正在签名的那一把必须同时出现在 `site/index.html` 与本文中
- `.asc` 中不得保留已过期的公钥

它不判断哪一把应当是新的，只保证这几处互相一致，且都在已发布的公钥之内。

指纹出现在下列位置，轮替时需要同步更新：

| 位置 | 作用 |
|---|---|
| `deploy/systemd/binhost-build.service` 的 `Environment=SIGNING_KEY=` | 构建时使用的密钥 |
| `site/index.html` 的指纹与复制按钮 | 用户导入后核对的依据 |
| `docs/key-rotation.md` 开头 | 本文记录的当前指纹 |
| 镜像机的 `/etc/binhost/signing-key.fpr` | `site-sync.sh` 据此决定是否同步公钥 |

最后一处不在版本库中，是每台机器自身的记录。因为让检查从被检查的对象中读取
预期值会使检查失去意义，所以它必须独立于仓库。

站点第 1 步的 `--lsign-key` 使用指纹而非邮箱 UID，所以即使收到一份混入了其他
公钥的 `.asc`，用户也只会签我们这一把。

## 私钥泄露时的处置

顺序与常规轮替相反：

1. 立即发布撤销证书，并入 `.asc` 一同发布，同时在社区渠道公告
2. 生成新密钥
3. 用受信任的签名阶段重新签署全部存量软件包，并用只含新公钥的 keyring 验证
4. 在站点上说明泄露的时间窗，供在此之前安装过软件包的用户自行判断

`.asc` 中带撤销证书时，用户导入后 gpg 会把旧密钥标记为已撤销，用它签名的
软件包立即验签失败。这是预期行为。

## 回滚

第三步之前的任何一步都可以直接放弃，新密钥尚未进入 `.asc`，用户不受影响。

第三步之后，回滚方式是从 `.asc` 中移除新公钥并重新发布，同时把新指纹从
`/etc/binhost/signing-key.fpr` 中删除。因为签名密钥在第五步之前未更换，所以
存量软件包的验签不受影响。

第五步之后不能回退到旧密钥，只能继续向前。已用新密钥签名的软件包需要再次执行
完整签名阶段才能换回，期间旧密钥必须保留在 `.asc` 中。

## 当前欠缺

- 离线副本只有一份。
