# 在这个仓库工作

给自动化助手看的。人类贡献者看 [`CONTRIBUTING.md`](CONTRIBUTING.md) 与
[`README.md`](README.md)。

这套系统每天为 gentoo-zh overlay 建置二进制包，签名后发布到镜像机，用户通过
`binrepos.conf` 取用。它每天执行，改坏了用户当天就无法安装软件包。

## 先跑检查器，它们是规则的权威

八个检查器就是这个仓库的规范，文字说明只是它们的注解。改动之后至少跑与改动
相关的那几个：

    python3 tools/validate.py <overlay>        两份清单互斥、包在 overlay 里
    python3 tools/check-commits.py <range>     提交信息格式
    python3 site/tools/check-copy.py site      站点文案与口语词
    node site/tools/check-i18n.js site         三语键一致
    python3 site/tools/check-panes.py site     站点结构
    bash tests/test-shell-behaviour.sh         shell 行为

容器 shellcheck（本地版本可能与 CI 不同）：

    tar -cf - build ops deploy tests deploy-site.sh | ssh build 'bash -lc "
      rm -rf ~/sc && mkdir -p ~/sc && tar -xf - -C ~/sc &&
      sudo docker run --rm -v \$HOME/sc:/mnt -w /mnt --entrypoint sh \
        koalaman/shellcheck-alpine:stable -c \"shellcheck build/*.sh ops/*.sh deploy/*.sh tests/*.sh deploy-site.sh\"
      echo rc=\$?; rm -rf ~/sc"'

## 脚本里的中文是契约，不是文案

`build/`、`ops/`、`deploy/` 打印的中文字符串被 `tests/` 断言，也被运维的
grep 依赖。**改文案必须同时改断言**，否则测试红的是格式而不是行为。

改之前先确认有没有人在匹配它：

    grep -rl "<那段文字的前八个字>" tests ops deploy

## 中文用语

简体用大陆用语，站点的 `zh-tw` 段用台湾用语，两边都不能混。

| 用 | 不用 |
|---|---|
| 构建、构建机 | 建置、建置机 |
| 软件包 | 套件 |
| 用户 | 使用者 |

例外：`build/` 里的「使用者」指 preserved-libs 的 consumer——连结某个库的那一方，
是术语不是 user，不要替换。

站点 `zh-tw` 段里的「建置」「套件」「設定」是正确的台湾用语，扫描时不要报。

## 测试

**不要写这三类断言**，它们把重构路径变成契约，改对了也会红：

- 比较行号，或要求某段文字在另一段之前
- `grep -c` 某个字面字符串的出现次数
- 要求多个脚本含有完全相同的一行

要断言行为：给桩、跑入口、看退出码与输出。写完之后**把被测代码改坏，确认测试
真的会红**——这个仓库里出现过多次「测试全过但替换根本没生效」。

## 判断一个问题值不值得修

这是运行中的生产系统，判据是后果，不是整洁度：

- 会不会让发布停摆、产物错误、或者故障无人知晓
- 官方 Gentoo binhost 在同一问题上怎么做（`proj/binhost.git` 的
  `builders/*/binhost-update`，整个仓库 3837 行、零测试、无签名无世代）
- 偏离官方不等于错。我们发 overlay 的包、自己签名、自己对用户负责，
  所以有政策筛选与签名，那是产品边界不是冗余

评估过但决定不做的改动记在
[`docs/evaluated-not-done.md`](docs/evaluated-not-done.md)，先读那份，
避免重新走一遍。

## 扫描时的已知噪音

- `NonsolvableDepsInStable`：`~amd64` 包在 stable profile 下的固有噪音，
  每个版本一条。
- `DeadUrl` 指向 `www.kernel.org`：本地网络到该域名慢于 pkgcheck 的 5 秒超时，
  `cdn.kernel.org` 正常。
- `binhost-alert@` 与 `SystemdUnitFailed` 接的都是「执行后失败」，接不住
  「根本没有执行」。后者由 `Packages` 的 `Last-Modified` 超时覆盖。

## 不要做的

- 不 commit、不 push、不部署、不触发建置，除非维护者明确要求
- 不在 PR 或 issue 上发评论
- 不加 AI 署名
- 部署前确认三个服务都处于 inactive：
  `systemctl is-active binhost-build binhost-build-unstable binhost-kernel`
- 手动补跑 `build/` 下的脚本时不要加 `sudo`——`mirror` 是 `adminc3b9c6` 的
  SSH config 别名，root 没有那份配置，脚本内部需要提权时会自己 sudo
