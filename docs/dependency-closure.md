# 依赖闭包检查边界

本文说明 binhost 如何生成运行期依赖闭包、发布前能够证明哪些条件，以及哪些条件仍由
用户的 Portage 解析器决定。这里的检查证明每个运行期依赖表达式在规定的四个来源中
至少有一个匹配，不证明整份索引能够作为一个 world 同时安装。

## 检查链路

[`runtime_atoms()`](../build/ebuilds.py) 使用 Portage 的 `Atom` 与
`use_reduce()` 读取
binpkg 已求值的 `RDEPEND`、`PDEPEND` 与 `IDEPEND`。版本、revision、slot、sub-slot、
repository 与 USE 约束由 Portage 的 `fakedbapi.match()` 匹配，不在脚本中另行拆解。

[`runtime_closure()`](../build/stage-index.py) 从直接构建目标开始遍历运行期
依赖。它只接收
许可证、`RESTRICT` 与排除政策均允许发布的候选项，因此闭包不会把不可再分发的候选项
带进公开索引。没有从候选索引取得匹配的表达式写入 `unresolved.txt`，供后续检查处理。

[`verify-deps.py`](../build/verify-deps.py) 再检查最终暂存索引。每个运行期
依赖表达式必须
由以下四个来源之一满足：

| 来源 | 能够证明 | 不能证明 |
| --- | --- | --- |
| 本次暂存索引 | 同一代公开 binpkg 有完整 Atom 匹配 | 这些匹配能够组成一份无冲突的安装计划 |
| emerge 前的 VDB 快照 | 构建基础系统已经安装匹配版本 | 用户系统也已安装相同版本与 USE 组合 |
| Gentoo binhost 快照 | 本轮选定的官方索引提供完整 Atom 匹配 | 用户配置一定选择该版本 |
| Gentoo 与 gentoo-zh 源码快照 | 当前频道存在可见的匹配 ebuild | 该 ebuild 的递归依赖与构建阶段一定成功 |

`build/dep-exceptions.txt` 不属于匹配来源。它只在四个来源均不满足之后豁免已知原子；
已能满足的例外会被报告为过期。当前清单为空。

因此，这套检查在逐原子范围内使用 Portage 本身的匹配语义，并保证每个运行期依赖表达式
有发布产物、已安装软件包、官方 binpkg 或可见源码作为来源。它不执行完整依赖图的冲突与
顺序解析。

本文行号对应本次提交；代码变动后以函数名为准。

## `||` 组

暂存阶段依照声明顺序检查 `||` 组，选择第一个能完全由可发布候选项满足的分支。某个
分支含不可发布或不存在的候选项时，继续检查后续分支；没有分支可用时，整个表达式写入
`unresolved.txt`。

验证阶段允许四个来源共同满足任一完整分支。它不会要求验证阶段选择暂存阶段检查过的
同一个分支。Gentoo Devmanual 也说明，`||` 内的顺序只是解析提示，不保证 Portage 选择
哪个分支：

- [Any of many dependencies](https://devmanual.gentoo.org/general-concepts/dependencies/#any-of-many-dependencies)
- [Understanding any-of dependencies](https://devmanual.gentoo.org/general-concepts/dependencies/#understanding-any-of-dependencies)

完整解析器可能因为已安装软件包、slot 冲突、blocker 或其他依赖的共同约束而跳过前面的
分支。当前检查只证明至少有一个分支能按四个来源逐项匹配。

## 不执行完整解析的边界

逐原子匹配无法判定以下条件：

1. **跨软件包 USE 组合与 `REQUIRED_USE`**：单个 Atom 能检查目标软件包的 USE 状态，但
   不能为整份依赖图选择一组同时满足所有软件包 `REQUIRED_USE` 的配置。
2. **slot 实例能否同时满足**：每个 Atom 可以分别匹配 slot 与 sub-slot，但检查不会
   建立一份安装计划，无法证明所有 Atom 能由同一组 slot 实例同时满足。
3. **blocker**：暂存与验证阶段均把 blocker 视为已满足，没有检查被阻止的软件包是否也
   出现在暂存索引、基础系统或安装计划中。
4. **`||` 全局回溯**：检查按局部顺序选择可匹配分支，不会因依赖图其他位置的冲突返回
   并改选后续分支。
5. **mask、keyword 与许可证**：源码快照使用频道关键字和隔离的 Portage 配置，只证明
   构建侧可见性，不代表每个用户的 profile、mask、关键字与许可证配置。
6. **源码回退的递归构建依赖**：源码快照不递归解析 `BDEPEND` 与 `DEPEND`，也不执行
   ebuild，因此不能证明回退源码后的完整构建计划成功。
7. **SONAME `REQUIRES` 与 `PROVIDES`**：当前检查读取依赖字段，不解析 gpkg 的 SONAME
   元数据；ABI 是否可由消费端现有库满足仍由 Portage 决定。
8. **合并顺序与循环**：可用集合不含合并顺序。`PDEPEND` 可解除部分循环，其他循环
   需要 USE 调整、bootstrap 路径或解析器回溯。

完整解析器不直接接入发布检查，因为整份索引刻意允许不同版本并存。把索引当成一个
world 解析会制造用户实际安装请求中不存在的 slot 冲突。若按每个直接构建目标分别
解析，还需要定义 profile、USE、已安装集合、是否允许源码回退及成功标准，工程范围明显
大于当前的静态证明。

`emerge(1)` 说明 `--binpkg-respect-use` 在未启用 `--usepkgonly` 或
`--getbinpkgonly` 时自动启用。USE 不匹配的 binpkg 会被忽略；当前源码树存在可用 ebuild
时，普通安装会改用源码。这个行为限制了 USE 差异的影响，但不覆盖上述其他边界，也不适用
于只允许 binpkg 的安装请求。

## 2026-08-09 快照实证

以下数字来自构建机的两份已发布暂存结果，不是长期不变量：

| 频道 | 快照时间（UTC） | 暂存 stanza | `unresolved.txt` |
| --- | --- | ---: | ---: |
| stable | 2026-08-09 09:34 | 257 | 465 |
| unstable | 2026-08-08 21:38 | 433 | 565 |

每行 `unresolved.txt` 按 VDB、Gentoo binhost、源码与 `||` 组依次分类。VDB 与官方索引
同时匹配时归入 VDB；stable 有 5 条这类交集，unstable 有 7 条。

| 分类 | stable | unstable | 实例 |
| --- | ---: | ---: | --- |
| VDB 已安装 | 244 | 352 | `>=app-arch/xz-utils-5.2.5-r1:0/0=[abi_x86_64(-)]` |
| Gentoo binhost | 201 | 192 | `<dev-libs/protobuf-34` |
| 源码快照 | 17 | 18 | `acct-group/aptly`、`virtual/wine` |
| `||` 组 | 3 | 3 | `app-containers/docker-cli` 或 `app-containers/podman` |
| 无法分类 | 0 | 0 | 无 |

容器内共执行 18 次 `emerge -p`，覆盖 17 个不同的原子；`qca` 在两个频道各验证一次。
抽样包括：

- VDB：`xz-utils`、`freetype`、`typing-extensions`、`gpgme`、`zstd` 与 `expat`；
- Gentoo binhost：`protobuf`、`abseil-cpp`、`lz4`、`qca` 与 `highway`；
- 源码：`acct-group/aptly`、`acct-user/dufs`、`openh264` 与 `virtual/wine`；
- `||` 组：`pack-cli` 的 `docker-cli`/`podman`，以及 Plasma 小部件的
  `breeze-icons`/`oxygen-icons`。

VDB 样本均能在已安装快照中匹配；Gentoo binhost 样本由 `[binary]` 满足；源码样本有
可选的 `[ebuild]`；两个 `||` 样本选择了当前规则预期的分支。该抽样只确认分类方法与
代表性原子，不代表逐条执行了全部 1030 个表达式，也不要求计划不重装已安装软件包。

同一快照中，stable 有 16 个 blocker，unstable 有 41 个。移除 blocker 标记后，没有一个
与四个来源中的软件包匹配，因此当前没有已观测到的 blocker 冲突。stable 运行期依赖图没有
循环强连通分量；unstable 有 6 组，共 17 个节点，并且该轮构建成功。这说明当前循环可由
既有安装状态、`PDEPEND` 或 Portage 顺序处理，不证明未来新增的循环也可解析。

## 重新验证

在构建机取得同一轮的暂存文件后，先检查记录数量并重新执行发布前验证：

```bash
cd /var/lib/binhost
for channel in stable/x86-64 x86-64; do
    stage="/var/lib/binhost/stage/${channel}"
    wc -l "${stage}/unresolved.txt"
    python3 build/verify-deps.py "${stage}/Packages" \
        --installed "${stage}/installed.txt" \
        --available "${stage}/official.txt" \
        --source "${stage}/source.txt"
done
```

`verify-deps.py` 必须退出 0。输出会分别列出 VDB、Gentoo binhost 与源码匹配的原子数；
数量随仓库、基础镜像与频道变化，不应要求等于本文快照。

复核代表性原子时，使用与对应频道相同的基础镜像，并只读挂载本轮仓库快照。`emerge -p`
用于观察完整计划；VDB 归类仍以同代 `installed.txt` 的 Atom 匹配为准：

```bash
sudo docker run --rm -i --security-opt=no-new-privileges \
    -v /var/db/repos/gentoo:/var/db/repos/gentoo:ro \
    -v /var/lib/binhost/overlay:/var/db/repos/gentoo-zh:ro \
    gentoo-zh/binhost-base:stable-x86-64 \
    emerge -p '>=app-arch/xz-utils-5.2.5-r1:0/0=[abi_x86_64(-)]'
```

unstable 频道把镜像名改为 `gentoo-zh/binhost-base:x86-64`。每类至少选择一个本轮
实际出现的原子；`||` 组应对消费者执行 `emerge -p`，再检查计划选中的分支。重新验证时
还应重新统计 blocker 的实际匹配和依赖图循环，不能沿用 2026-08-09 的数量。
