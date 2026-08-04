#!/usr/bin/env python3

import importlib.util
import os
import pathlib
import sys
import tempfile

BUILD = pathlib.Path(__file__).resolve().parent.parent / "build"

HEADER = "ACCEPT_KEYWORDS: ~amd64\nPACKAGES: 9\nTIMESTAMP: 1\nVERSION: 0"


def stanza(cpv, repo, slot="0"):
    cp = cpv.rsplit("-", 1)[0]
    return (f"CPV: {cpv}\nPATH: {cp}/{cpv.split('/')[-1]}.gpkg.tar\n"
            f"REPO: {repo}\nSLOT: {slot}")


def fresh(d, index_text=None, index_path=None):
    """gen-packages reads its paths at import, so each case needs its own."""
    if index_text is not None:
        (d / "Packages").write_text(HEADER + "\n\n" + index_text + "\n")
    os.environ["INDEX"] = index_path or str(d / "Packages")
    os.environ["OUT"] = str(d / "packages.json")
    (d / "list.txt").write_text("")
    os.environ["LIST"] = str(d / "list.txt")
    os.environ["EXCLUDED"] = str(BUILD / "excluded.txt")
    os.environ["DIST_INDEX"] = str(d / "nope.json")
    spec = importlib.util.spec_from_file_location(
        "gen_packages", BUILD / "gen-packages.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load(index_text):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        old = dict(os.environ)
        try:
            return fresh(d, index_text).read_deps()
        finally:
            os.environ.clear()
            os.environ.update(old)


def run_main(index_text, overlay=None, index_path=None):
    """The whole generator, so the json and the two text files are covered."""
    import contextlib, io, json
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        ov = pathlib.Path(overlay or (d / "overlay"))
        if overlay is None:
            (ov / "profiles").mkdir(parents=True)
            (ov / "profiles" / "repo_name").write_text("gentoo-zh\n")
        old = dict(os.environ)
        try:
            m = fresh(d, index_text, index_path)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = m.main(str(ov))
        finally:
            os.environ.clear()
            os.environ.update(old)
        data = json.loads((d / "packages.json").read_text()) \
            if (d / "packages.json").exists() else None
        deps_txt = (d / "deps.txt").read_text() if (d / "deps.txt").exists() else None
        pkgs_txt = (d / "packages.txt").read_text() if (d / "packages.txt").exists() else None
        return rc, data, deps_txt, pkgs_txt, buf.getvalue()


CASES = []


def case(name, fn):
    CASES.append((name, fn))


case("只收 ::gentoo 的产物，本仓库的不算", lambda: (
    [(d["cp"], d["ver"]) for d in load("\n\n".join([
        stanza("app-misc/a-1", "gentoo-zh"), stanza("dev-libs/lib-1", "gentoo")]))]
    == [("dev-libs/lib", "1")]))

case("同一个包发布了两个版本时两个都列", lambda: (
    [d["ver"] for d in load("\n\n".join([stanza("dev-libs/lib-1", "gentoo"),
                                          stanza("dev-libs/lib-2", "gentoo")]))]
    == ["1", "2"]))

case("版本按 Portage 规则排序，不按字符串排序", lambda: (
    [d["ver"] for d in load("\n\n".join([stanza("dev-libs/lib-1.10", "gentoo"),
                                            stanza("dev-libs/lib-1.9", "gentoo")]))]
    == ["1.9", "1.10"]))

case("同一个包的两个 slot 都列，并标出 slot", lambda: (
    [(d["slot"], d["ver"]) for d in load("\n\n".join([
        stanza("dev-libs/lib-1", "gentoo", slot="1"),
        stanza("dev-libs/lib-2", "gentoo", slot="2")]))]
    == [("1", "1"), ("2", "2")]))

case("sub-slot 只取主 slot", lambda: (
    load(stanza("net-libs/webkit-gtk-2.52.5-r410", "gentoo", slot="4.1/0"))[0]["slot"]
    == "4.1"))

case("r0 不写进版本号", lambda: (
    load(stanza("dev-libs/lib-1.2-r0", "gentoo"))[0]["ver"] == "1.2"))

case("非 r0 的 revision 要写出来", lambda: (
    load(stanza("dev-libs/lib-1.2-r3", "gentoo"))[0]["ver"] == "1.2-r3"))

case("按包名排序", lambda: (
    [d["cp"] for d in load("\n\n".join([stanza("z-misc/z-1", "gentoo"),
                                        stanza("a-misc/a-1", "gentoo")]))]
    == ["a-misc/a", "z-misc/z"]))

case("索引中不含 ::gentoo 的产物时给出空清单", lambda: (
    load(stanza("app-misc/a-1", "gentoo-zh")) == []))

case("未知仓库的产物不静默归入 ::gentoo，整轮中止", lambda: (
    (lambda r: r[0] == 1 and r[1] is None and "未知仓库" in r[4])(
        run_main(stanza("app-misc/a-1", "some-other-overlay")))))

case("已设定的索引无法读取时中止，不覆写上一份输出", lambda: (
    (lambda r: r[0] == 1 and r[1] is None and "不存在" in r[4])(
        run_main("", index_path="/nonexistent/Packages"))))

case("写出 schema 版本，供页面判断数据是否够新", lambda: (
    run_main(stanza("dev-libs/lib-1", "gentoo"))[1]["schema"] == 2))

case("deps.txt 单独成档，不占用 packages.txt 的状态栏", lambda: (
    (lambda r: "dev-libs/lib" in r[2] and "dev-libs/lib" not in r[3])(
        run_main(stanza("dev-libs/lib-1", "gentoo")))))

case("deps.txt 的说明行都以 # 开头", lambda: (
    all(l.startswith("#") or not l.strip() or l.split()[0].count("/") == 1
        for l in run_main(stanza("dev-libs/lib-1", "gentoo"))[2].splitlines())))

print(f"  {'用例':<44} 结果")
bad = 0
for name, fn in CASES:
    try:
        ok = bool(fn())
    except Exception as e:                                  # noqa: BLE001
        ok, name = False, f"{name}（抛异常 {type(e).__name__}: {e}）"
    print(f"  {'✓' if ok else '✗'} {name}")
    bad += not ok

sys.exit(1 if bad else 0)
