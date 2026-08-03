#!/usr/bin/env python3

import importlib.util
import pathlib
import sys

BUILD = pathlib.Path(__file__).resolve().parent.parent / "build"

spec = importlib.util.spec_from_file_location("verify_deps", BUILD / "verify-deps.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)

HEADER = "ACCEPT_KEYWORDS: ~amd64\nPACKAGES: 9\nTIMESTAMP: 1\nVERSION: 0"


def stanza(cpv, repo="gentoo-zh", rdepend=None, slot="0", use=None, iuse=None,
           eapi="8"):
    cp = cpv.rsplit("-", 1)[0]
    lines = [f"CPV: {cpv}", f"PATH: {cp}/{cpv.split('/')[-1]}.gpkg.tar",
             f"REPO: {repo}", f"EAPI: {eapi}"]
    if slot is not None:
        lines.append(f"SLOT: {slot}")
    if use:
        lines.append(f"USE: {use}")
    if iuse:
        lines.append(f"IUSE: {iuse}")
    if rdepend:
        lines.append(f"RDEPEND: {rdepend}")
    return "\n".join(lines)


def run(stanzas):
    fields = verify.parse(HEADER + "\n\n" + "\n\n".join(stanzas) + "\n")
    return verify.check(fields)


def run_main(stanzas, exceptions=None):
    import contextlib, io, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        (d / "Packages").write_text(HEADER + "\n\n" + "\n\n".join(stanzas) + "\n")
        exc = d / "exc.txt"
        exc.write_text(exceptions or "")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = verify.main(str(d / "Packages"), exceptions=str(exc))
        return rc, out.getvalue(), err.getvalue()


CASES = []


def case(name, fn):
    CASES.append((name, fn))


case("依赖有可匹配的已发布版本时通过", lambda: (
    (lambda r: not r[0] and not r[1])(
        run([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-1"),
             stanza("dev-libs/lib-2", repo="gentoo")]))))

case("索引不收录的包算基础系统，不算缺陷", lambda: (
    (lambda r: not r[0] and set(r[1]) == {"sys-libs/glibc"})(
        run([stanza("app-misc/a-1", rdepend="sys-libs/glibc")]))))

case("包在索引里但版本不满足时算缺陷", lambda: (
    (lambda r: set(r[0]) == {">=dev-libs/lib-2"} and not r[1])(
        run([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-2"),
             stanza("dev-libs/lib-1", repo="gentoo")]))))

case("slot 不满足时算缺陷", lambda: (
    (lambda r: set(r[0]) == {"dev-libs/lib:2"})(
        run([stanza("app-misc/a-1", rdepend="dev-libs/lib:2"),
             stanza("dev-libs/lib-1", repo="gentoo", slot="0")]))))

case("USE 依赖不满足时算缺陷", lambda: (
    (lambda r: set(r[0]) == {"dev-libs/lib[foo]"})(
        run([stanza("app-misc/a-1", rdepend="dev-libs/lib[foo]"),
             stanza("dev-libs/lib-1", repo="gentoo", use="bar", iuse="foo bar")]))))

case("或组只要有一个分支满足就算通过", lambda: (
    (lambda r: not r[0])(
        run([stanza("app-misc/a-1", rdepend="|| ( dev-libs/lib sys-libs/glibc )"),
             stanza("dev-libs/lib-1", repo="gentoo")]))))

case("或组全部分支都不满足时，缺陷与基础系统分开记", lambda: (
    (lambda r: set(r[0]) == {">=dev-libs/lib-9"} and set(r[1]) == {"sys-libs/glibc"})(
        run([stanza("app-misc/a-1", rdepend="|| ( >=dev-libs/lib-9 sys-libs/glibc )"),
             stanza("dev-libs/lib-1", repo="gentoo")]))))

case("blocker 不算依赖", lambda: (
    (lambda r: not r[0] and not r[1])(
        run([stanza("app-misc/a-1", rdepend="!dev-libs/lib")]))))

case("省略 SLOT 的 stanza 按默认值 0 满足 :0 依赖", lambda: (
    (lambda r: not r[0])(
        run([stanza("app-misc/a-1", rdepend="dev-libs/lib:0"),
             stanza("dev-libs/lib-1", repo="gentoo", slot=None)]))))

case("记下是哪些包引用了不满足的原子", lambda: (
    run([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-2"),
         stanza("app-misc/b-1", rdepend=">=dev-libs/lib-2"),
         stanza("dev-libs/lib-1", repo="gentoo")])[0][">=dev-libs/lib-2"]
    == {"app-misc/a-1", "app-misc/b-1"}))

case("精确版本指到旧的那一个时算满足", lambda: (
    (lambda r: not r[0])(
        run([stanza("app-misc/a-1", rdepend="=dev-libs/lib-1"),
             stanza("dev-libs/lib-1", repo="gentoo"),
             stanza("dev-libs/lib-2", repo="gentoo")]))))

case("不满足时退出码非零", lambda: (
    run_main([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-2"),
              stanza("dev-libs/lib-1", repo="gentoo")])[0] == 1))

case("列进例外之后不再失败", lambda: (
    run_main([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-2"),
              stanza("dev-libs/lib-1", repo="gentoo")],
             exceptions=">=dev-libs/lib-2\t知道，暂时如此\n")[0] == 0))

case("例外本轮已能满足时报出应删除", lambda: (
    "应从 dep-exceptions.txt 删除" in run_main(
        [stanza("app-misc/a-1", rdepend=">=dev-libs/lib-1"),
         stanza("dev-libs/lib-2", repo="gentoo")],
        exceptions=">=dev-libs/lib-1\t早先的例外\n")[2]))

case("例外指的原子索引里没提到时不报应删除", lambda: (
    "应从 dep-exceptions.txt 删除" not in run_main(
        [stanza("app-misc/a-1")],
        exceptions=">=dev-libs/lib-1\t与本索引无关\n")[2]))

case("注释与空行不算例外", lambda: (
    run_main([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-2"),
              stanza("dev-libs/lib-1", repo="gentoo")],
             exceptions="# >=dev-libs/lib-2\t被注释掉了\n\n")[0] == 1))

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
