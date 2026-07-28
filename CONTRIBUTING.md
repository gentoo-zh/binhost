# 加入一个包

在 [`build/packages.txt`](build/packages.txt) 中添加一行 `category/package`，按字母序排列。

```diff
 app-i18n/cskk
+app-i18n/fcitx-rime-extra
 app-i18n/fcitx-bamboo
```

提交前本地跑一次校验，CI 跑的是同一个脚本：

```bash
python3 build/validate.py /var/db/repos/gentoo-zh
```

只需提交 `build/packages.txt`。站点的包列表由镜像机每天按 overlay 重新生成，
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

目录浏览与包状态需连接真实服务器方有数据。
