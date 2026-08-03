#!/usr/bin/env python3

import importlib.util
import os
import pathlib
import sys
import tempfile

BUILD = pathlib.Path(__file__).resolve().parent.parent / "build"

HEADER = "ACCEPT_KEYWORDS: ~amd64\nPACKAGES: 9\nTIMESTAMP: 1\nVERSION: 0"


def stanza(cpv, repo):
    cp = cpv.rsplit("-", 1)[0]
    return (f"CPV: {cpv}\nPATH: {cp}/{cpv.split('/')[-1]}.gpkg.tar\n"
            f"REPO: {repo}\nSLOT: 0")


def load(index_text):
    """gen-packages reads its paths at import, so each case needs its own."""
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        (d / "Packages").write_text(HEADER + "\n\n" + index_text + "\n")
        old = dict(os.environ)
        os.environ["INDEX"] = str(d / "Packages")
        os.environ["OUT"] = str(d / "packages.json")
        os.environ["LIST"] = str(BUILD / "packages.txt")
        os.environ["EXCLUDED"] = str(BUILD / "excluded.txt")
        try:
            spec = importlib.util.spec_from_file_location(
                "gen_packages", BUILD / "gen-packages.py")
            m = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(m)
            return m.read_deps()
        finally:
            os.environ.clear()
            os.environ.update(old)


CASES = []


def case(name, fn):
    CASES.append((name, fn))


case("只收 ::gentoo 的产物，本仓库的不算", lambda: (
    load("\n\n".join([stanza("app-misc/a-1", "gentoo-zh"),
                      stanza("dev-libs/lib-1", "gentoo")]))
    == [{"cp": "dev-libs/lib", "ver": "1"}]))

case("同一个包多个版本时取最新的", lambda: (
    load("\n\n".join([stanza("dev-libs/lib-1", "gentoo"),
                      stanza("dev-libs/lib-2", "gentoo")]))
    == [{"cp": "dev-libs/lib", "ver": "2"}]))

case("版本高但 revision 低的仍然算新", lambda: (
    load("\n\n".join([stanza("net-libs/webkit-gtk-2.52.3-r411", "gentoo"),
                      stanza("net-libs/webkit-gtk-2.52.5-r410", "gentoo")]))
    == [{"cp": "net-libs/webkit-gtk", "ver": "2.52.5-r410"}]))

case("r0 不写进版本号", lambda: (
    load(stanza("dev-libs/lib-1.2-r0", "gentoo"))
    == [{"cp": "dev-libs/lib", "ver": "1.2"}]))

case("非 r0 的 revision 要写出来", lambda: (
    load(stanza("dev-libs/lib-1.2-r3", "gentoo"))
    == [{"cp": "dev-libs/lib", "ver": "1.2-r3"}]))

case("按包名排序", lambda: (
    [d["cp"] for d in load("\n\n".join([stanza("z-misc/z-1", "gentoo"),
                                        stanza("a-misc/a-1", "gentoo")]))]
    == ["a-misc/a", "z-misc/z"]))

case("索引中不含 ::gentoo 的产物时给出空清单", lambda: (
    load(stanza("app-misc/a-1", "gentoo-zh")) == []))

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
