#!/usr/bin/env python3

import importlib.util
import pathlib
import re
import sys
import tempfile
import time

spec = importlib.util.spec_from_file_location(
    "stage_index", pathlib.Path(__file__).with_name("stage-index.py"))
stage_index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage_index)

HEADER = "ACCEPT_KEYWORDS: ~amd64\nPACKAGES: 999\nTIMESTAMP: 1\nVERSION: 0"
HEADER_WITH_REV = HEADER + '\nREPO_REVISIONS: {}'


def stanza(cpv, repo="gentoo-zh", build_id=None, restrict=None, PATH=None):
    cp = cpv.rsplit("-", 1)[0]
    path = f"{cp}/{cpv.split('/')[-1]}.gpkg.tar" if PATH is None else PATH
    lines = [f"CPV: {cpv}", f"PATH: {path}", f"REPO: {repo}"]
    if build_id is not None:
        lines.append(f"BUILD_ID: {build_id}")
    if restrict:
        lines.append(f"RESTRICT: {restrict}")
    return "\n".join(lines)


def run(stanzas, overlay_has=None, excluded=frozenset(), masked=()):
    _, entries = stage_index.parse(HEADER + "\n\n" + "\n\n".join(stanzas) + "\n")
    if overlay_has is None:
        return stage_index.select(entries, excluded=excluded)
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
        return stage_index.select(entries, ov, excluded=excluded)


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
            rc = stage_index.main(str(pkg), str(stage))
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
            rc = stage_index.main(str(pkg), str(stage))
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
              and [c for c, _ in r[3]] == ["app-misc/b-1"]
)(run([stanza("app-misc/a-1"),
       stanza("app-misc/b-1", restrict="bindist"),
       stanza("app-misc/c-1")])))

case("被跳过的那个连它的路径一起记下来，好从公开路径移除", lambda: (
    run([stanza("app-misc/a-1"),
         stanza("app-misc/b-1", restrict="bindist")])[3]
    == [("app-misc/b-1", "app-misc/b/b-1.gpkg.tar")]))

case("RESTRICT 里带 bindist 前缀的其他词不算", lambda: (
    not run([stanza("app-misc/b-1", restrict="bindistfoo")])[3]))

case("RESTRICT 是多个词时按整词认", lambda: (
    [c for c, _ in run([stanza("app-misc/b-1", restrict="mirror bindist strip")])[3]]
    == ["app-misc/b-1"]))

case("bindist 的那一个不会进索引", lambda: (
    "app-misc/b-1" not in cpvs(run([stanza("app-misc/a-1"),
                                    stanza("app-misc/b-1", restrict="bindist")])[0])))

bad = 0
for name, fn in CASES:
    try:
        ok = bool(fn())
    except Exception as e:                                  # noqa: BLE001
        ok, name = False, f"{name}（抛异常 {type(e).__name__}: {e}）"
    print(f"  {'✓' if ok else '✗'} {name}")
    bad += not ok

sys.exit(1 if bad else 0)
