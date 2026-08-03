#!/usr/bin/env python3

import importlib.util
import pathlib
import re
import sys
import tempfile
import time

BUILD = pathlib.Path(__file__).resolve().parent.parent / "build"

spec = importlib.util.spec_from_file_location(
    "stage_index", BUILD / "stage-index.py")
stage_index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage_index)

HEADER = "ACCEPT_KEYWORDS: ~amd64\nPACKAGES: 999\nTIMESTAMP: 1\nVERSION: 0"
HEADER_WITH_REV = HEADER + '\nREPO_REVISIONS: {}'


def stanza(cpv, repo="gentoo-zh", build_id=None, restrict=None, PATH=None,
           rdepend=None, depend=None, idepend=None, pdepend=None,
           slot="0", use=None, iuse=None, eapi="8"):
    cp = cpv.rsplit("-", 1)[0]
    path = f"{cp}/{cpv.split('/')[-1]}.gpkg.tar" if PATH is None else PATH
    lines = [f"CPV: {cpv}", f"PATH: {path}", f"REPO: {repo}"]
    if eapi is not None:
        lines.append(f"EAPI: {eapi}")
    if slot is not None:
        lines.append(f"SLOT: {slot}")
    if use:
        lines.append(f"USE: {use}")
    if iuse:
        lines.append(f"IUSE: {iuse}")
    if pdepend:
        lines.append(f"PDEPEND: {pdepend}")
    if build_id is not None:
        lines.append(f"BUILD_ID: {build_id}")
    if restrict:
        lines.append(f"RESTRICT: {restrict}")
    if rdepend:
        lines.append(f"RDEPEND: {rdepend}")
    if depend:
        lines.append(f"DEPEND: {depend}")
    if idepend:
        lines.append(f"IDEPEND: {idepend}")
    return "\n".join(lines)


def fake_lookup(restricts=None):
    """(cpv, repo) -> RESTRICT. None stands for metadata not readable."""
    restricts = restricts or {}

    def get(cpv, repo):
        if (cpv, repo) in restricts:
            return restricts[(cpv, repo)]
        return restricts.get(cpv, "")
    return get


def run(stanzas, overlay_has=None, excluded=frozenset(), masked=(), with_deps=False,
        restricts=None):
    _, entries = stage_index.parse(HEADER + "\n\n" + "\n\n".join(stanzas) + "\n")
    lookup = fake_lookup(restricts)
    if overlay_has is None:
        return stage_index.select(entries, excluded=excluded, with_deps=with_deps,
                                  lookup=lookup)
    with tempfile.TemporaryDirectory() as tmp:
        ov = pathlib.Path(tmp)
        for cpv in overlay_has:
            cp = re.match(r"^([a-z0-9-]+/.+?)-[0-9]", cpv).group(1)
            d = ov / cp
            d.mkdir(parents=True, exist_ok=True)
            (d / (cpv.split("/", 1)[1] + ".ebuild")).write_text("EAPI=8\n")
        prof = ov / "profiles"
        prof.mkdir(parents=True, exist_ok=True)
        (prof / "repo_name").write_text("gentoo-zh\n")
        (prof / "package.mask").write_text(
            "".join(f"# masked for removal\n{cp}\n" for cp in masked))
        return stage_index.select(entries, ov, excluded=excluded, lookup=lookup)


def cpvs(kept):
    return sorted(f["CPV"] for _, f, _ in kept)


CASES = []


def case(name, fn):
    CASES.append((name, fn))


case("本仓库的产物保留", lambda: (
    cpvs(run([stanza("app-misc/a-1")])[0]) == ["app-misc/a-1"]))

case("::gentoo 的产物被过滤", lambda: (
    run([stanza("dev-libs/b-1", repo="gentoo")])[0] == []))

case("混合输入时仅保留本仓库的产物", lambda: (
    cpvs(run([stanza("app-misc/a-1"), stanza("dev-libs/b-1", repo="gentoo")])[0])
    == ["app-misc/a-1"]))

case("RESTRICT=bindist 不进索引", lambda: (
    cpvs(run([stanza("app-misc/a-1", restrict="bindist mirror")])[0]) == []))

case("RESTRICT 为其他值时照常收录", lambda: (
    cpvs(run([stanza("app-misc/a-1", restrict="mirror strip")])[0]) == ["app-misc/a-1"]))

case("同一版本多实例仅保留 BUILD_ID 最大者", lambda: (
    len(run([stanza("app-misc/a-1", build_id=1),
             stanza("app-misc/a-1", build_id=3),
             stanza("app-misc/a-1", build_id=2)])[0]) == 1))

case("保留的实例 BUILD_ID 为最大值", lambda: (
    run([stanza("app-misc/a-1", build_id=1),
         stanza("app-misc/a-1", build_id=3)])[0][0][0] == 3))

case("BUILD_ID 输入顺序不影响结果", lambda: (
    run([stanza("app-misc/a-1", build_id=3),
         stanza("app-misc/a-1", build_id=1)])[0][0][0] == 3))

case("excluded.txt 里的包不发布", lambda: (
    run([stanza("app-text/wiki2man_on_rust-0.5.1-r1")],
        excluded={"app-text/wiki2man_on_rust"})[0] == []))

case("不在收录清单不等于排除，依赖引入的产物照常发布", lambda: (
    cpvs(run([stanza("acct-group/aptly-0")], excluded={"app-misc/other"})[0])
    == ["acct-group/aptly-0"]))

case("带 revision 的版本号可匹配排除清单", lambda: (
    run([stanza("app-misc/a-1.2.3-r4")], excluded={"app-misc/a"})[0] == []))

case("overlay 中已不存在的包被过滤", lambda: (
    run([stanza("dev-libs/libratbag-0.18")], overlay_has=["app-misc/a-1"])[0] == []))

case("overlay 中仍存在的包保留", lambda: (
    cpvs(run([stanza("app-misc/a-1")], overlay_has=["app-misc/a-1"])[0]) == ["app-misc/a-1"]))

case("未提供 overlay 时不做该项过滤", lambda: (
    cpvs(run([stanza("dev-libs/gone-1")])[0]) == ["dev-libs/gone-1"]))

case("带 revision 的版本号可解析出 cp", lambda: (
    run([stanza("app-misc/a-1.2.3-r4")], overlay_has=["app-misc/a-1.2.3-r4"])[0] != []))

case("bump 之后旧版本退场", lambda: (
    cpvs(run([stanza("dev-util/gitea-cli-0.14.2"), stanza("dev-util/gitea-cli-0.15.0")],
             overlay_has=["dev-util/gitea-cli-0.15.0"])[0]) == ["dev-util/gitea-cli-0.15.0"]))

case("目录还在但这个版本已移除，仍应过滤", lambda: (
    run([stanza("app-misc/a-1")], overlay_has=["app-misc/a-2"])[0] == []))

case("同一个包的多个版本都在 overlay 里就都保留", lambda: (
    cpvs(run([stanza("app-misc/a-1"), stanza("app-misc/a-2")],
             overlay_has=["app-misc/a-1", "app-misc/a-2"])[0]) == ["app-misc/a-1", "app-misc/a-2"]))

case("ebuild 带 -r0 而 CPV 不带时仍然匹配", lambda: (
    run([stanza("app-misc/a-1")], overlay_has=["app-misc/a-1-r0"])[0] != []))

case("头部 PACKAGES 重写为实际数量", lambda: (
    lambda h: re.findall(r"^PACKAGES: .*$", h, re.M) == ["PACKAGES: 7"]
)(stage_index.rewrite_header(HEADER, 7, "")))

case("头部 TIMESTAMP 重写为本代时间", lambda: (
    lambda got: abs(got - int(time.time())) <= 5
)(int(re.search(r"^TIMESTAMP: (\d+)$",
                stage_index.rewrite_header(HEADER, 7, ""), re.M).group(1))))

case("头部缺少该行时插入", lambda: (
    '"gentoo-zh": "abc123"' in stage_index.rewrite_header(HEADER, 7, "abc123")))

case("头部已有该行时覆盖", lambda: (
    '"gentoo-zh": "abc123"' in stage_index.rewrite_header(HEADER_WITH_REV, 7, "abc123")
    and "REPO_REVISIONS: {}" not in stage_index.rewrite_header(HEADER_WITH_REV, 7, "abc123")))

case("写入后头部仅有一行 REPO_REVISIONS", lambda: (
    stage_index.rewrite_header(HEADER, 7, "abc").count("REPO_REVISIONS") == 1))

case("未提供 rev 时不新增该行", lambda: (
    "REPO_REVISIONS" not in stage_index.rewrite_header(HEADER, 7, "")))

case("未提供 rev 时保留原有该行", lambda: (
    "REPO_REVISIONS: {}" in stage_index.rewrite_header(HEADER_WITH_REV, 7, "")))

case("插入后头部保持字母序", lambda: (
    (lambda ls: ls == sorted(ls))(stage_index.rewrite_header(
        "ACCEPT_KEYWORDS: ~amd64\nPACKAGES: 1\nTIMESTAMP: 1\nVERSION: 0", 7, "abc").splitlines())))

print(f"  {'用例':<40} 结果")
case("overlay mask 掉之后不再 stage", lambda: (
    cpvs(run([stanza("app-misc/a-1")], overlay_has=["app-misc/a-1"],
             masked=("app-misc/a",))[0]) == []))

case("没 mask 时照旧收录", lambda: (
    cpvs(run([stanza("app-misc/a-1")], overlay_has=["app-misc/a-1"])[0])
    == ["app-misc/a-1"]))

case("PATH 是绝对路径时整轮拒绝", lambda: (
    run([stanza("app-misc/a-1", PATH="/etc/passwd")])[2] is not None))

case("PATH 里有 .. 时整轮拒绝", lambda: (
    run([stanza("app-misc/a-1", PATH="../../etc/passwd")])[2] is not None))

case("PATH 中段有 .. 时整轮拒绝", lambda: (
    run([stanza("app-misc/a-1", PATH="app-misc/../../x.gpkg.tar")])[2] is not None))

case("PATH 为空时整轮拒绝", lambda: (
    run([stanza("app-misc/a-1", PATH="")])[2] is not None))

case("PATH 带前后空白时整轮拒绝", lambda: (
    run([stanza("app-misc/a-1", PATH=" app-misc/a-1.gpkg.tar")])[2] is not None))

case("正常的相对路径照常通过", lambda: (
    run([stanza("app-misc/a-1", PATH="app-misc/a-1-1.gpkg.tar")])[2] is None))

case("拒绝时一个包都不 stage", lambda: (
    run([stanza("app-misc/a-1", PATH="app-misc/ok.gpkg.tar"),
         stanza("app-misc/b-1", PATH="/etc/passwd")])[0] == []))

def _escape(shape):
    import os
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        pkg = d / "pkgdir"
        (pkg / "app-misc").mkdir(parents=True)
        stage = d / "stage"
        stage.mkdir()
        (d / "OUTSIDE").write_text("outside\n")
        target = pkg / "app-misc" / "a-1.gpkg.tar"
        if shape == "final":
            os.symlink(d / "OUTSIDE", target)
        elif shape == "relative":
            os.symlink("../../OUTSIDE", target)
        elif shape == "intermediate":
            (pkg / "app-misc").rmdir()
            real = d / "elsewhere"
            real.mkdir()
            (real / "a-1.gpkg.tar").write_text("outside\n")
            os.symlink(real, pkg / "app-misc")
        elif shape == "fifo":
            os.mkfifo(target)
        else:
            target.write_text("inside\n")
        (pkg / "Packages").write_text(
            HEADER + "\n\n" + stanza("app-misc/a-1", PATH="app-misc/a-1.gpkg.tar") + "\n")
        try:
            rc = stage_index.main(str(pkg), str(stage),
                                  lookup=lambda cpv, repo: "")
        except SystemExit as e:
            rc = e.code
        out = stage / "app-misc" / "a-1.gpkg.tar"
        leaked = out.exists() and "outside" in out.read_text(errors="replace")
        return rc, leaked


for _shape in ("final", "relative", "intermediate", "fifo"):
    case(f"来源是 {_shape} symlink 时拒绝且不泄漏",
         (lambda s=_shape: (lambda r: r[0] not in (0, None) and not r[1])(_escape(s))))

case("正常文件照常 stage", lambda: _escape("plain")[0] in (0, None))


def _dest_escape(shape):
    import os
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        pkg = d / "pkgdir"
        (pkg / "app-misc").mkdir(parents=True)
        (pkg / "app-misc" / "a-1.gpkg.tar").write_text("payload\n")
        stage = d / "stage"
        stage.mkdir()
        outside = d / "OUTSIDE"
        outside.mkdir()
        if shape == "dir":
            os.symlink(outside, stage / "app-misc")
        elif shape == "file":
            (stage / "app-misc").mkdir()
            os.symlink(outside / "a-1.gpkg.tar", stage / "app-misc" / "a-1.gpkg.tar")
        (pkg / "Packages").write_text(
            HEADER + "\n\n" + stanza("app-misc/a-1", PATH="app-misc/a-1.gpkg.tar") + "\n")
        try:
            rc = stage_index.main(str(pkg), str(stage),
                                  lookup=lambda cpv, repo: "")
        except SystemExit as e:
            rc = e.code
        leaked = any(p.is_file() and p.name == "a-1.gpkg.tar" for p in outside.rglob("*"))
        return rc, leaked


case("目的地的中间目录是 symlink 时拒绝且不写出去",
     lambda: (lambda r: r[0] not in (0, None) and not r[1])(_dest_escape("dir")))
case("目的地的目标档案是 symlink 时拒绝且不写出去",
     lambda: (lambda r: r[0] not in (0, None) and not r[1])(_dest_escape("file")))
case("目的地干净时照常写入",
     lambda: _dest_escape("clean")[0] in (0, None))

case("某个包被加了 bindist 时只跳过它", lambda: (
    lambda r: cpvs(r[0]) == ["app-misc/a-1", "app-misc/c-1"]
              and r[2] is None
              and [c for c, _, _ in r[3]] == ["app-misc/b-1"]
)(run([stanza("app-misc/a-1"),
       stanza("app-misc/b-1", restrict="bindist"),
       stanza("app-misc/c-1")])))

case("被跳过的那个连它的路径一起记下来，好从公开路径移除", lambda: (
    run([stanza("app-misc/a-1"),
         stanza("app-misc/b-1", restrict="bindist")])[3]
    == [("app-misc/b-1", "app-misc/b/b-1.gpkg.tar", "yes")]))

case("无法读取 metadata 与 bindist 分别标注，操作提示才不会指错方向", lambda: (
    [s for _, _, s in with_meta([stanza("app-misc/a-1"), stanza("app-misc/b-1")],
                                {("app-misc/a-1", "gentoo-zh"): "bindist"},
                                default=None)[3]]
    == ["yes", "unknown"]))

case("RESTRICT 里带 bindist 前缀的其他词不算", lambda: (
    not run([stanza("app-misc/b-1", restrict="bindistfoo")])[3]))

case("RESTRICT 是多个词时按整词认", lambda: (
    [c for c, _, _ in run([stanza("app-misc/b-1", restrict="mirror bindist strip")])[3]]
    == ["app-misc/b-1"]))

case("bindist 的那一个不会进索引", lambda: (
    "app-misc/b-1" not in cpvs(run([stanza("app-misc/a-1"),
                                    stanza("app-misc/b-1", restrict="bindist")])[0])))

def with_meta(stanzas, restricts, default=""):
    """restricts maps (cpv, repo) to RESTRICT. default=None fakes a read failure."""
    _, entries = stage_index.parse(HEADER + "\n\n" + "\n\n".join(stanzas) + "\n")

    def lookup(cpv, repo):
        return restricts.get((cpv, repo), default)
    return stage_index.select(entries, None, excluded=set(), with_deps=False,
                              lookup=lookup)


def only_refused(result, cpv):
    return cpvs(result[0]) == [] and [c for c, _, _ in result[3]] == [cpv]


case("旧 stanza 无 RESTRICT，但当前 metadata 已加 bindist，仍要拒绝", lambda: (
    only_refused(with_meta([stanza("app-misc/example-1")],
                           {("app-misc/example-1", "gentoo-zh"): "bindist"}),
                 "app-misc/example-1")))

case("当前 metadata 没有 bindist 时正常发布", lambda: (
    cpvs(with_meta([stanza("app-misc/example-1")],
                   {("app-misc/example-1", "gentoo-zh"): "strip"})[0])
    == ["app-misc/example-1"]))

case("eclass 加进来的 bindist 同样识别", lambda: (
    only_refused(with_meta([stanza("app-misc/example-1")],
                           {("app-misc/example-1", "gentoo-zh"): "strip bindist"}),
                 "app-misc/example-1")))

case("无法读取 metadata 时拒绝发布，不回退到 stanza", lambda: (
    only_refused(with_meta([stanza("app-misc/example-1")], {}, default=None),
                 "app-misc/example-1")))

case("按 stanza 的 REPO 选来源", lambda: (
    only_refused(with_meta([stanza("app-misc/example-1", repo="gentoo-zh")],
                           {("app-misc/example-1", "gentoo-zh"): "bindist",
                            ("app-misc/example-1", "gentoo"): ""},
                           default=None),
                 "app-misc/example-1")))

case("同名 CPV 在另一个仓库受限时不影响本仓库的判定", lambda: (
    cpvs(with_meta([stanza("app-misc/example-1", repo="gentoo-zh")],
                   {("app-misc/example-1", "gentoo-zh"): "",
                    ("app-misc/example-1", "gentoo"): "bindist"},
                   default=None)[0])
    == ["app-misc/example-1"]))

def portage_lookup_error(overlay):
    try:
        stage_index.portage_restrict(overlay)
    except stage_index.MetadataUnavailable as e:
        return str(e)
    return None


case("仓库路径解析不到指定位置时不返回可用的查询函数", lambda: (
    portage_lookup_error("/nonexistent/overlay") is not None))

case("路径不符时报出期望的位置", lambda: (
    "/nonexistent/overlay" in (portage_lookup_error("/nonexistent/overlay") or "")))

case("没有 overlay 就无法确认来源，整轮不发布", lambda: (
    (lambda r: r[0] == [] and "no overlay to resolve gentoo-zh against" in (r[2] or ""))(
        stage_index.select(
            stage_index.parse(HEADER + "\n\n" + stanza("app-misc/example-1") + "\n")[1],
            None, excluded=set(), with_deps=False))))

case("stanza 建成时受限，即使当前 metadata 已解除也不发布", lambda: (
    only_refused(with_meta([stanza("app-misc/example-1", restrict="bindist")],
                           {("app-misc/example-1", "gentoo-zh"): ""}),
                 "app-misc/example-1")))

case("IDEPEND 里的包也要一起发", lambda: (
    deps([stanza("app-misc/a-1", idepend="dev-util/tool"),
          stanza("dev-util/tool-1", repo="gentoo")])
    == ["app-misc/a-1", "dev-util/tool-1"]))

case("blocker 不算依赖，不跟着发", lambda: (
    deps([stanza("app-misc/a-1", rdepend="!dev-libs/lib !!dev-libs/deep"),
          stanza("dev-libs/lib-1", repo="gentoo"),
          stanza("dev-libs/deep-1", repo="gentoo")])
    == ["app-misc/a-1"]))


def deps(stanzas):
    return sorted(cpvs(run(stanzas, with_deps=True)[0]))


def deps_excluded():
    r = run([stanza("app-misc/a-1", rdepend="dev-libs/lib"),
             stanza("dev-libs/lib-1", repo="gentoo")],
            excluded={"app-misc/a"}, with_deps=True)
    return cpvs(r[0]) == []


LIB = stanza("dev-libs/lib-1", repo="gentoo")
DEEP = stanza("dev-libs/deep-1", repo="gentoo")
TOOL = stanza("dev-util/tool-1", repo="gentoo")
OTHER = stanza("dev-libs/other-1", repo="gentoo")
UNUSED = stanza("app-misc/unused-1", repo="gentoo")

case("不开依赖时，::gentoo 的一律不发", lambda: (
    deps([stanza("app-misc/a-1")]) == ["app-misc/a-1"]))

case("我们的包用到的 ::gentoo 依赖会一起发", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib"), LIB])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("依赖的依赖也跟着发", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib"),
          stanza("dev-libs/lib-1", repo="gentoo", rdepend="dev-libs/deep"), DEEP])
    == ["app-misc/a-1", "dev-libs/deep-1", "dev-libs/lib-1"]))

case("没人用到的 ::gentoo 包不发", lambda: (
    deps([stanza("app-misc/a-1"), UNUSED]) == ["app-misc/a-1"]))

case("只在构建期用到的不发", lambda: (
    deps([stanza("app-misc/a-1", depend="dev-util/tool"), TOOL])
    == ["app-misc/a-1"]))

case("带版本、slot 与 USE 的原子逐项匹配", lambda: (
    deps([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-1:0/1=[foo]"),
          stanza("dev-libs/lib-1", repo="gentoo", slot="0/1", use="foo", iuse="foo")])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("stanza 省略 SLOT 时按 portage 的默认值 0 匹配", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib:0"),
          stanza("dev-libs/lib-1", repo="gentoo", slot=None)])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("slot 不符时不算满足", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib:2"),
          stanza("dev-libs/lib-1", repo="gentoo", slot="0")])
    == ["app-misc/a-1"]))

case("sub-slot 不符时不算满足", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib:0/9"),
          stanza("dev-libs/lib-1", repo="gentoo", slot="0/1")])
    == ["app-misc/a-1"]))

case("stanza 省略 IUSE 时不满足未开启的 USE 依赖", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib[foo]"),
          stanza("dev-libs/lib-1", repo="gentoo")])
    == ["app-misc/a-1"]))

case("stanza 省略 IUSE 但开启了该 flag 时算满足", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib[foo]"),
          stanza("dev-libs/lib-1", repo="gentoo", use="foo")])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("IUSE 与 EAPI 都省略时 USE 依赖匹配不到，两者要一起读", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib[foo]"),
          stanza("dev-libs/lib-1", repo="gentoo", use="foo", eapi=None)])
    == ["app-misc/a-1"]))

case("stanza 省略 EAPI 时仍能按版本匹配", lambda: (
    deps([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-1"),
          stanza("dev-libs/lib-1", repo="gentoo", eapi=None)])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("USE 依赖不满足时不算满足", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib[foo]"),
          stanza("dev-libs/lib-1", repo="gentoo", use="bar", iuse="foo bar")])
    == ["app-misc/a-1"]))

case("::repo 限定只匹配该仓库的产物", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib::gentoo-zh"),
          stanza("dev-libs/lib-1", repo="gentoo")])
    == ["app-misc/a-1"]))

case("::repo 限定命中时照常发布", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib::gentoo"),
          stanza("dev-libs/lib-1", repo="gentoo")])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("大于等于只取满足条件的版本，不带上旧版", lambda: (
    deps([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-2"),
          stanza("dev-libs/lib-1", repo="gentoo"),
          stanza("dev-libs/lib-2", repo="gentoo")])
    == ["app-misc/a-1", "dev-libs/lib-2"]))

case("波浪号匹配同一版本的 revision", lambda: (
    deps([stanza("app-misc/a-1", rdepend="~dev-libs/lib-1.2"),
          stanza("dev-libs/lib-1.2-r3", repo="gentoo")])
    == ["app-misc/a-1", "dev-libs/lib-1.2-r3"]))

case("万用版本匹配带 revision 的版本", lambda: (
    deps([stanza("app-misc/a-1", rdepend="=dev-libs/lib-1*"),
          stanza("dev-libs/lib-1-r1", repo="gentoo")])
    == ["app-misc/a-1", "dev-libs/lib-1-r1"]))

case("同一个 CPV 跨仓库时，发布的是种子所在仓库的那一份", lambda: (
    (lambda r: [(f["CPV"], f["REPO"]) for _b, f, _s in r[0]]
     == [("app-misc/a-1", "gentoo-zh")])(
        run([stanza("app-misc/a-1", repo="gentoo-zh", build_id=1),
             stanza("app-misc/a-1", repo="gentoo", build_id=2)], with_deps=True))))

case("BUILD_ID 只在同一个仓库内比较", lambda: (
    (lambda r: sorted((f["REPO"], b) for b, f, _s in r[0])
     == [("gentoo-zh", 15)])(
        run([stanza("app-misc/a-1", repo="gentoo-zh", build_id=9),
             stanza("app-misc/a-1", repo="gentoo-zh", build_id=15)], with_deps=True))))

case("依赖同时存在于两个仓库时，取 overlay 的那一份", lambda: (
    (lambda r: sorted((f["CPV"], f["REPO"]) for _b, f, _s in r[0])
     == [("app-misc/a-1", "gentoo-zh"), ("dev-libs/lib-1", "gentoo-zh")])(
        run([stanza("app-misc/a-1", rdepend="dev-libs/lib"),
             stanza("dev-libs/lib-1", repo="gentoo-zh", build_id=1),
             stanza("dev-libs/lib-1", repo="gentoo", build_id=2)],
            overlay_has=["app-misc/a-1"]))))

case("::gentoo 限定的依赖取主树那一份", lambda: (
    (lambda r: sorted((f["CPV"], f["REPO"]) for _b, f, _s in r[0])
     == [("app-misc/a-1", "gentoo-zh"), ("dev-libs/lib-1", "gentoo")])(
        run([stanza("app-misc/a-1", rdepend="dev-libs/lib::gentoo"),
             stanza("dev-libs/lib-1", repo="gentoo-zh", build_id=1),
             stanza("dev-libs/lib-1", repo="gentoo", build_id=2)],
            overlay_has=["app-misc/a-1"]))))

case("闭包读的是最终要发布的那一份 stanza", lambda: (
    deps([stanza("app-misc/a-1", build_id=15, rdepend="dev-libs/other"),
          stanza("app-misc/a-1", build_id=9, rdepend="dev-libs/lib"),
          LIB, OTHER])
    == ["app-misc/a-1", "dev-libs/other-1"]))

case("或组第一个分支不可散布时改选第二个", lambda: (
    sorted(f["CPV"] for _b, f, _s in run(
        [stanza("app-misc/a-1", rdepend="|| ( dev-libs/lib dev-libs/deep )"),
         LIB, DEEP], with_deps=True,
        restricts={("dev-libs/lib-1", "gentoo"): "bindist"})[0])
    == ["app-misc/a-1", "dev-libs/deep-1"]))

case("不可散布的候选不进闭包，也不因此少发别的", lambda: (
    (lambda r: [c for c, _p, _s in r[3]] == ["dev-libs/lib-1"])(
        run([stanza("app-misc/a-1", rdepend="|| ( dev-libs/lib dev-libs/deep )"),
             LIB, DEEP], with_deps=True,
            restricts={("dev-libs/lib-1", "gentoo"): "bindist"}))))

case("精确版本指到旧的那一个时也要发", lambda: (
    deps([stanza("app-misc/a-1", rdepend="=dev-libs/lib-1"),
          stanza("dev-libs/lib-1", repo="gentoo"),
          stanza("dev-libs/lib-2", repo="gentoo")])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("同一个包新旧两版各被不同的包指到时都发", lambda: (
    deps([stanza("app-misc/a-1", rdepend="=dev-libs/lib-1"),
          stanza("app-misc/b-1", rdepend="=dev-libs/lib-2"),
          stanza("dev-libs/lib-1", repo="gentoo"),
          stanza("dev-libs/lib-2", repo="gentoo")])
    == ["app-misc/a-1", "app-misc/b-1", "dev-libs/lib-1", "dev-libs/lib-2"]))

case("裸原子只取每个 slot 里最新的那个", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib"),
          stanza("dev-libs/lib-1", repo="gentoo"),
          stanza("dev-libs/lib-2", repo="gentoo")])
    == ["app-misc/a-1", "dev-libs/lib-2"]))

case("不同 slot 各取一个", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib"),
          stanza("dev-libs/lib-1", repo="gentoo", slot="1"),
          stanza("dev-libs/lib-2", repo="gentoo", slot="2")])
    == ["app-misc/a-1", "dev-libs/lib-1", "dev-libs/lib-2"]))

case("或组取第一个索引能满足的分支", lambda: (
    deps([stanza("app-misc/a-1", rdepend="|| ( dev-libs/gone dev-libs/lib )"), LIB])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("或组两个分支都在时只取前一个", lambda: (
    deps([stanza("app-misc/a-1", rdepend="|| ( dev-libs/lib dev-libs/deep )"),
          LIB, DEEP])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("或组一个分支都满足不了时什么都不发", lambda: (
    deps([stanza("app-misc/a-1", rdepend="|| ( dev-libs/gone dev-libs/missing )"), LIB])
    == ["app-misc/a-1"]))

case("或组满足不了要记进未解析清单", lambda: (
    (lambda u: any("||" in a for a in u))(
        run([stanza("app-misc/a-1", rdepend="|| ( dev-libs/gone dev-libs/missing )")],
            with_deps=True)[4])))

case("索引中不存在的原子记进未解析清单", lambda: (
    (lambda u: [a for a in u] == ["sys-libs/glibc"])(
        run([stanza("app-misc/a-1", rdepend="sys-libs/glibc")], with_deps=True)[4])))

case("未解析清单记下是谁引用的", lambda: (
    run([stanza("app-misc/a-1", rdepend="sys-libs/glibc")],
        with_deps=True)[4]["sys-libs/glibc"] == {"app-misc/a-1"}))

case("virtual 的提供者沿它自己的依赖展开", lambda: (
    deps([stanza("app-misc/a-1", rdepend="virtual/lib"),
          stanza("virtual/lib-0", repo="gentoo", rdepend="|| ( dev-libs/lib dev-libs/deep )"),
          LIB, DEEP])
    == ["app-misc/a-1", "dev-libs/lib-1", "virtual/lib-0"]))

case("PDEPEND 里的包也一起发", lambda: (
    deps([stanza("app-misc/a-1", pdepend="dev-libs/lib"), LIB])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("use 条件式里的依赖一并算上", lambda: (
    deps([stanza("app-misc/a-1", rdepend="foo? ( dev-libs/lib ) || ( dev-libs/deep )"),
          LIB, DEEP])
    == ["app-misc/a-1", "dev-libs/deep-1", "dev-libs/lib-1"]))

case("依赖里带 bindist 的仍然被拒", lambda: (
    (lambda r: cpvs(r[0]) == ["app-misc/a-1"]
               and [c for c, _, _ in r[3]] == ["dev-libs/lib-1"])(
        run([stanza("app-misc/a-1", rdepend="dev-libs/lib"),
             stanza("dev-libs/lib-1", repo="gentoo", restrict="bindist")],
            with_deps=True))))

case("被 excluded 的包不做种子，它的依赖也不发", deps_excluded)


bad = 0
for name, fn in CASES:
    try:
        ok = bool(fn())
    except Exception as e:                                  # noqa: BLE001
        ok, name = False, f"{name}（抛异常 {type(e).__name__}: {e}）"
    print(f"  {'✓' if ok else '✗'} {name}")
    bad += not ok

sys.exit(1 if bad else 0)
