# 加入一个包

## 规则来源

- [发布范围与构建频道](README.md#发布范围)
- [依赖闭包边界](docs/dependency-closure.md)
- [站点设计与文案规范](site/design.html)
- [提交信息](#提交信息)

在 [`build/packages.txt`](build/packages.txt) 中添加一行 `category/package`，按字母序排列。

```diff
 app-i18n/fcitx-libthai
+app-i18n/fcitx-mcbopomofo
 app-i18n/fcitx-openbangla
```

提交前本地执行一次校验，CI 执行的是同一个脚本：

```bash
python3 tools/validate.py /var/db/repos/gentoo-zh
```

只需提交 `build/packages.txt`。镜像机每日按 overlay 为 stable 与 unstable 分别生成
站点包列表，生成结果不入版本库。

## 适合收录的包

收录的价值在于编译成本与收益不成比例：

- 体积大、编译耗时长的包（Electron 应用、浏览器、办公套件）
- 依赖链长的包（Rust、Go 项目通常附带大量 crate 或 module）
- 使用面广的常用包

以下情形收益有限：

- 已是预编译二进制的 `-bin` 包，安装过程仅为解压
- 用户较少的包
- USE 组合差异大的包。二进制包仅在 USE 完全匹配时才会被采用，命中率过低则构建成本无法回收

## 无法收录的包

- **`RESTRICT=bindist`**：上游不允许再分发 binpkg，CI 会直接拒绝。
- **许可证不允许再分发**：构建时 `ACCEPT_LICENSE="-* @BINARY-REDISTRIBUTABLE"` 会拦截；提交 PR 时应说明该限制。
- **不属于本 overlay 的包**：收录清单只接受 gentoo-zh overlay 自身的包。已收录包所需的 `::gentoo` 运行期依赖会随之一并发布，其他 `::gentoo` 包请使用[官方 binhost](https://wiki.gentoo.org/wiki/Gentoo_Binary_Host_Quickstart)。

## 合并之后

合并不等于立即可用。stable 由 `binhost-build.timer` 在每日 16:00
（Asia/Shanghai）触发，unstable 由 `binhost-build-unstable.timer` 在每日 04:00
触发；两者各有最多 15 分钟的随机延迟。包会在符合对应频道边界的下一次构建中产出，
签名后分别发布。

清单决定直接构建目标。构建软件包时会同时构建其依赖；其中属于本 overlay 的依赖和
`::gentoo` 运行期依赖会随之一并发布，因此实际发布数多于清单条数。仅用于构建的依赖
不会发布。

## 站点与脚本

`site/` 为静态页面，`nginx/` 为服务器配置，`build/` 为构建与发布脚本，改动同样通过 PR 提交。

页面里的资源用的是绝对路径，`file://` 打开会缺样式，预览用：

```bash
python3 -m http.server -d site 8000
```

目录浏览与包状态需连接真实服务器方有数据。页面之间的链接不带扩展名（`/faq`），
无扩展名的页面路径由 nginx 映射，本地预览要用 `/faq.html` 这样的地址。

## 提交信息

主题使用英文，正文使用中文。PR 标题同样使用英文，正文使用提出者的语言。
`git log --oneline` 与 GitHub 列表只显示主题，因此主题必须能独立说明改动范围。
正文用于记录改动原因和剩余风险。

主题写成 `scope: subject`：

```
stage-index: decide by version, not by package directory
site-sync: delete pages removed from the repository
test: skip repository-level tests on build-only machines
```

`scope` 应明确对应改动范围：单个脚本使用去掉扩展名的脚本名（`stage-index`、
`site-sync`），多个脚本使用目录名（`build`、`deploy`、`site`、`nginx`），CI 改动使用
`ci`。同一组文件使用连字符前的共同部分；修改多个 `test-*.py` 时使用 `test:`。

一个主题只讲一件事。`删对文件`、`发得出告警`、`看得见 distfiles` 是三个提交。

主题不超过 69 个字符（GLEP 66，与 overlay 同一个限制），结尾不加句号。正文与主题
之间空一行，正文每行不超过 78 列；缩进的引文和无法换行的地址不计。

正文说明改动原因、原有缺陷和剩余风险；具体修改已经由 diff 展示。测试结果仅在影响
设计决定或证明关键反例时写入正文，不记录例行命令和通过项数。

中文不使用全角引号，代码和字面量使用反引号。工具署名一律不写。这两条
check-commits.py 都会查。

### 一个逻辑改动一个提交

开 PR 之前先 squash。评审过程中的修改用 `git commit --amend` 或 `git rebase -i`，
不要在后面追加一个 `改一处笔误` 之类的提交。

同一个 PR 可以有多个提交，前提是每个都独立成立，单独拿出来也说得通。

### 检查

CI 只检查 PR 自己带来的提交，不检查历史——这套规矩是后来才有的，为了让旧提交
合规而改写一个已经公开的分支，代价大于收益。

本地先执行一遍：

```bash
python3 tools/check-commits.py origin/master..HEAD
```
