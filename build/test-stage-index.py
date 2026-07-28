#!/usr/bin/env python3
"""Cases for stage-index.py.

This is the last filter between the build cache and what users install, so each
rule it applies gets a case: whose package it is, which instance of a rebuilt
version, what must stop the round, and what the index header ends up saying.
"""

import importlib.util
import pathlib
import sys
import tempfile

spec = importlib.util.spec_from_file_location(
    "stage_index", pathlib.Path(__file__).with_name("stage-index.py"))
stage_index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage_index)

# The header portage actually writes has no REPO_REVISIONS line -- it puts that
# per package. The fixture used to include one, which is why a substitution that
# silently does nothing when the line is absent passed the tests while the
# published index carried no revision at all.
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


def run(stanzas, overlay_has=None, excluded=frozenset()):
    """Parse and select.

    overlay_has is the list of cp that exist in the overlay; excluded is passed
    explicitly so the cases do not depend on what build/excluded.txt happens to
    hold today.
    """
    _, entries = stage_index.parse(HEADER + "\n\n" + "\n\n".join(stanzas) + "\n")
    if overlay_has is None:
        return stage_index.select(entries, excluded=excluded)
    with tempfile.TemporaryDirectory() as tmp:
        ov = pathlib.Path(tmp)
        for cp in overlay_has:
            (ov / cp).mkdir(parents=True)
        return stage_index.select(entries, ov, excluded=excluded)


def cpvs(kept):
    return sorted(f["CPV"] for _, f, _ in kept)


CASES = []


def case(name, fn):
    CASES.append((name, fn))


case("我们的包留下", lambda: (
    cpvs(run([stanza("app-misc/a-1")])[0]) == ["app-misc/a-1"]))

case("::gentoo 的产物滤掉", lambda: (
    run([stanza("dev-libs/b-1", repo="gentoo")])[0] == []))

case("两边混在一起时只留我们的", lambda: (
    cpvs(run([stanza("app-misc/a-1"), stanza("dev-libs/b-1", repo="gentoo")])[0])
    == ["app-misc/a-1"]))

case("RESTRICT=bindist 中止整轮", lambda: (
    run([stanza("app-misc/a-1", restrict="bindist mirror")])[2] is not None))

case("RESTRICT 有别的值不中止", lambda: (
    run([stanza("app-misc/a-1", restrict="mirror strip")])[2] is None))

case("同一版本多个实例只留 BUILD_ID 最大的", lambda: (
    len(run([stanza("app-misc/a-1", build_id=1),
             stanza("app-misc/a-1", build_id=3),
             stanza("app-misc/a-1", build_id=2)])[0]) == 1))

case("留下的确实是最大那个", lambda: (
    run([stanza("app-misc/a-1", build_id=1),
         stanza("app-misc/a-1", build_id=3)])[0][0][0] == 3))

case("BUILD_ID 顺序颠倒也一样", lambda: (
    run([stanza("app-misc/a-1", build_id=3),
         stanza("app-misc/a-1", build_id=1)])[0][0][0] == 3))

case("excluded.txt 里的包不发布", lambda: (
    run([stanza("app-text/wiki2man_on_rust-0.5.1-r1")],
        excluded={"app-text/wiki2man_on_rust"})[0] == []))

case("只是不在收录清单不算排除（依赖带出来的照发）", lambda: (
    cpvs(run([stanza("acct-group/aptly-0")], excluded={"app-misc/other"})[0])
    == ["acct-group/aptly-0"]))

case("带 revision 的版本号也能对上排除清单", lambda: (
    run([stanza("app-misc/a-1.2.3-r4")], excluded={"app-misc/a"})[0] == []))

case("overlay 里已经没有的包滤掉", lambda: (
    run([stanza("dev-libs/libratbag-0.18")], overlay_has=["app-misc/a"])[0] == []))

case("overlay 里还在的包留下", lambda: (
    cpvs(run([stanza("app-misc/a-1")], overlay_has=["app-misc/a"])[0]) == ["app-misc/a-1"]))

case("不传 overlay 时不按 overlay 过滤", lambda: (
    cpvs(run([stanza("dev-libs/gone-1")])[0]) == ["dev-libs/gone-1"]))

case("带 revision 的版本号也能取出 cp", lambda: (
    run([stanza("app-misc/a-1.2.3-r4")], overlay_has=["app-misc/a"])[0] != []))

case("头部的 PACKAGES 改成实际数量", lambda: (
    "PACKAGES: 7" in stage_index.rewrite_header(HEADER, 7, "")))

case("头部的 TIMESTAMP 不再是缓存里那个", lambda: (
    "TIMESTAMP: 1\n" not in stage_index.rewrite_header(HEADER, 7, "") + "\n"))

case("头部本来没有这一行时也要写进去", lambda: (
    '"gentoo-zh": "abc123"' in stage_index.rewrite_header(HEADER, 7, "abc123")))

case("头部本来有这一行时覆盖它", lambda: (
    '"gentoo-zh": "abc123"' in stage_index.rewrite_header(HEADER_WITH_REV, 7, "abc123")
    and "REPO_REVISIONS: {}" not in stage_index.rewrite_header(HEADER_WITH_REV, 7, "abc123")))

case("写进去之后头部仍然只有一行 REPO_REVISIONS", lambda: (
    stage_index.rewrite_header(HEADER, 7, "abc").count("REPO_REVISIONS") == 1))

case("没给 rev 就不凭空加一行", lambda: (
    "REPO_REVISIONS" not in stage_index.rewrite_header(HEADER, 7, "")))

case("没给 rev 时原有的那一行也不动", lambda: (
    "REPO_REVISIONS: {}" in stage_index.rewrite_header(HEADER_WITH_REV, 7, "")))

case("插入之后头部仍然按字母序", lambda: (
    (lambda ls: ls == sorted(ls))(stage_index.rewrite_header(
        "ACCEPT_KEYWORDS: ~amd64\nPACKAGES: 1\nTIMESTAMP: 1\nVERSION: 0", 7, "abc").splitlines())))

print(f"  {'用例':<40} 结果")
bad = 0
for name, fn in CASES:
    try:
        ok = bool(fn())
    except Exception as e:                                  # noqa: BLE001
        ok, name = False, f"{name}（抛异常 {type(e).__name__}: {e}）"
    print(f"  {'✓' if ok else '✗'} {name}")
    bad += not ok

sys.exit(1 if bad else 0)
