# 加入一个包

在 [`build/packages.txt`](build/packages.txt) 中添加一行 `category/package`，按字母序排列。

```diff
 app-i18n/fcitx-libthai
+app-i18n/fcitx-mcbopomofo
 app-i18n/fcitx-openbangla
```

提交前本地执行一次校验，CI 执行的是同一个脚本：

```bash
python3 build/validate.py /var/db/repos/gentoo-zh
```

只需提交 `build/packages.txt`。站点的包列表由镜像机每小时按 overlay 重新生成，
不入版本库。

## 适合收录的包

收录的价值在于编译成本与收益不成比例：

- 体积大、编译耗时长的包（Electron 应用、浏览器、办公套件）
- 依赖链长的包（Rust、Go 项目通常附带大量 crate 或 module）
- 使用面广的常用包

以下情形收益有限：

- 已是预编译二进制的 `-bin` 包，安装过程仅为解压
- 使用者较少的包
- USE 组合差异大的包。二进制包仅在 USE 完全匹配时才会被采用，命中率过低则构建成本无法回收

## 无法收录的包

- **`RESTRICT=bindist`**：上游不允许再分发构建产物，CI 会直接拒绝。
- **许可证不允许再分发**：构建时 `ACCEPT_LICENSE="-* @BINARY-REDISTRIBUTABLE"` 会拦截，但应在 PR 阶段即予说明。
- **不属于本 overlay 的包**：此处仅分发 gentoo-zh overlay 自身的包，::gentoo 的包请使用[官方 binhost](https://wiki.gentoo.org/wiki/Gentoo_Binary_Host_Quickstart)。

## 合并之后

合并不等于立即可用。包在下一轮构建时产出，构建每晚 02:00 由 binhost-build.timer 触发，产物签名后发布。

清单决定构建什么。构建一个包会把它的依赖一并编出来，其中属于本 overlay 的
那些也会随之发布，因此实际发布数多于清单条数。

## 站点与脚本

`site/` 为静态页面，`nginx/` 为服务器配置，`build/` 为构建与发布脚本，改动同样通过 PR 提交。

页面里的资源用的是绝对路径，`file://` 打开会缺样式，预览用：

```bash
python3 -m http.server -d site 8000
```

目录浏览与包状态需连接真实服务器方有数据。页面之间的链接不带扩展名（`/faq`），
去掉扩展名是 nginx 那边做的，本地预览要用 `/faq.html` 这样的地址。

## 提交信息

主题写英文，正文写中文。这和 PR 的约定一致：标题英文，正文用提出者的语言。
`git log --oneline` 与 GitHub 的列表只显示主题，英文对外读得通；理由写在正文，
中文表达更准。

主题写成 `scope: subject`：

```
stage-index: decide by version, not by package directory
site-sync: delete pages removed from the repository
test: skip repository-level tests on build-only machines
```

`scope` 要指得到这个提交改动的部分：脚本名去掉扩展名（`stage-index`、`site-sync`），
一个脚本装不下就用目录名（`build`、`deploy`、`site`、`nginx`），改 CI 用 `ci`。
一族文件共用横线前的那一段，所以动了几个 `test-*.py` 写 `test:` 即可。

一个主题只讲一件事。「删对文件、发得出告警、看得见 distfiles」是三个提交。

主题不超过 69 个字符（GLEP 66，与 overlay 同一个限制），结尾不加句号。正文与主题之间空一行，正文每行不超过 78 列，
缩进的引文和断不开的地址不计。

正文写**为什么**，不写做了什么——做了什么 diff 里有，改动的由来、原先错在哪、
怎么验证的，diff 里没有。测试怎么跑、跑出什么，同样写在正文。

中文不用全角引号 `「」`『』，代码和字面量用反引号。工具署名一律不写。这两条
check-commits.py 都会查。

### 一个逻辑改动一个提交

开 PR 之前先 squash。评审过程中的修改用 `git commit --amend` 或 `git rebase -i`，
不要在后面叠一个「改一处笔误」。

同一个 PR 可以有多个提交，前提是每个都独立成立，单独拿出来也说得通。

### 检查

CI 只检查 PR 自己带来的提交，不检查历史——这套规矩是后来才有的，为了让旧提交
合规而改写一个已经公开的分支，代价大于收益。

本地先执行一遍：

```bash
python3 build/check-commits.py origin/master..HEAD
```
