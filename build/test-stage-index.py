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


def stanza(cpv, repo="gentoo-zh", build_id=None, restrict=None):
    cp = cpv.rsplit("-", 1)[0]
    lines = [f"CPV: {cpv}", f"PATH: {cp}/{cpv.split('/')[-1]}.gpkg.tar", f"REPO: {repo}"]
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

case("RESTRICT=bindist 中止本轮", lambda: (
    run([stanza("app-misc/a-1", restrict="bindist mirror")])[2] is not None))

case("RESTRICT 为其他值时不中止", lambda: (
    run([stanza("app-misc/a-1", restrict="mirror strip")])[2] is None))

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

case("目录还在但这个版本没了，照样过滤", lambda: (
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

bad = 0
for name, fn in CASES:
    try:
        ok = bool(fn())
    except Exception as e:                                  # noqa: BLE001
        ok, name = False, f"{name}（抛异常 {type(e).__name__}: {e}）"
    print(f"  {'✓' if ok else '✗'} {name}")
    bad += not ok

sys.exit(1 if bad else 0)
