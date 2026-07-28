# 签名密钥

指纹 `6A0726AF1476A2F382C6AC6638A0234EC16AD42E`，2028-07-25 到期。
私钥在构建机 `/var/lib/binhost/gnupg`，另有一份离线副本。
公钥发布在站点 `/gentoo-zh-binhost.asc`，也在本仓库 `site/` 下。

`build/status.sh` 在到期前 180 天开始告警。这个提前量是给下面的重叠期留的。

## 为什么要重叠

用户的 `/etc/portage/gnupg` 里只有他导入那一次的公钥，没有任何机制会自动更新。
换了密钥立刻用新的签，凡是没重新导入的人，`binpkg-request-signature` 会让
portage 拒收所有包——表现是「突然装不上了」，而错误信息只说验签失败，
看不出是我们换了钥匙。

所以轮替不是一次切换，是一段两把钥匙都有效的时间。

## 步骤

**一、生成新密钥，同时生成撤销证书**

```bash
gpg --homedir /var/lib/binhost/gnupg --quick-generate-key \
    "gentoo-zh binhost <binhost@gentoozh.org>" ed25519 sign 3y
gpg --homedir /var/lib/binhost/gnupg --output revoke-<新指纹>.asc \
    --gen-revoke <新指纹>
```

撤销证书离线保存，和私钥备份分开放。私钥泄露时它是唯一能公开作废这把钥匙的
手段，而那种时候往往来不及现生成。

**二、把新公钥并进已发布的那份**

`.asc` 里可以有多把公钥。两把都放进去，用户导入一次就同时信任新旧。

```bash
gpg --homedir /var/lib/binhost/gnupg --armor \
    --export <旧指纹> <新指纹> > site/gentoo-zh-binhost.asc
```

提交、合并，等镜像机拉过去（五分钟内）。**这一步之后不要立刻换签名密钥**：
先给用户留出重新导入的时间。

**三、重叠期，至少一个月**

继续用旧密钥签。同时在站点首页和社区渠道说明要重新导入。

判断可以往下走的依据是时间，不是感觉——我们看不到有多少人已经导入了。

**四、换成新密钥签**

```bash
# build-container.sh 的 SIGNING_KEY 换成新指纹
SIGNING_KEY=<新指纹> build/run-full.sh
build/publish.sh
```

存量的包仍然是旧密钥签的，此时两把钥匙都在用户的钥匙串里，都能验过。
下一轮全量构建会把它们逐步换成新签名。

**五、旧密钥到期后**

从 `.asc` 里去掉旧公钥，重新发布。到这一步旧密钥签的包应该已经全部被替换过。

## 私钥泄露时

不走上面的流程，顺序反过来：

1. 立刻发布撤销证书（导入进 `.asc` 一并发布），并在社区渠道公告
2. 生成新密钥
3. 用新密钥重签所有存量包：重跑一次全量构建
4. 站点上说明泄露时间窗，让在那之前装过包的人自行判断

`.asc` 里带撤销证书时，用户导入后 gpg 会把旧钥匙标成 revoked，
用它签的包立刻验不过——这是有意的。

## 指纹写在哪几处

轮替时这些都要跟着换，漏一处就是签名与用户核对的对不上。
`build/test-fingerprint-consistent.py` 在 CI 里比对它们是否一致，
所以漏改会红，但它只保证一致，不保证是新的那一把。

| 位置 | 作用 |
|---|---|
| `deploy/systemd/binhost-build.service` 的 `Environment=SIGNING_KEY=` | 构建时用哪把钥匙签 |
| `site/index.html` 的指纹与复制按钮 | 用户导入后核对的依据 |
| `docs/key-rotation.md` 开头 | 本文自己记的当前指纹 |
| 镜像机的 `/etc/binhost/signing-key.fpr` | `site-sync.sh` 据它决定要不要同步仓库里的公钥 |

最后一处不在版本库里，是每台机器自己的记录：让检查从被检查的对象里读取
预期值，这个检查就没有意义。它由 `install.sh` 的 `SIGNING_FPR` 写入。
轮替时先改它，再推站点，否则公钥同步会因指纹对不上而停住——那是预期行为。

## 当前欠缺的

- 私钥在构建期间对容器可读。容器跑的是 180 个第三方 ebuild 的 root 阶段，
  任何一个都能读到它。要封住得把编译和签名拆成两段，第二段不跑上游代码。
- 离线副本只有一份。
