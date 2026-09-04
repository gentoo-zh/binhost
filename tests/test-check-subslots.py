#!/usr/bin/env python3

import importlib.util
import io
import contextlib
import pathlib
import sys
import tempfile

BUILD = pathlib.Path(__file__).resolve().parent.parent / "build"

spec = importlib.util.spec_from_file_location("check_subslots",
                                              BUILD / "check-subslots.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

HEADER = "ACCEPT_KEYWORDS: amd64 ~amd64\nPACKAGES: 1\nVERSION: 0"

CASES = []


def case(name, fn):
    CASES.append((name, fn))


class FakeTree:
    """Stands in for the portage lookup: what subslot a package has now."""

    def __init__(self, mapping):
        self.mapping = mapping

    def current_subslot(self, cp, slot):
        # Keyed by the atom the caller asked for, so a test can give one answer
        # for cat/pkg:0 and another for the package as a whole.
        return self.mapping.get(f"{cp}:{slot}", self.mapping.get(cp))


def stanza(cpv, rdepend="", depend="", bdepend=""):
    lines = [f"CPV: {cpv}", f"PATH: {cpv}.gpkg.tar", "SLOT: 0"]
    if rdepend:
        lines.append(f"RDEPEND: {rdepend}")
    if depend:
        lines.append(f"DEPEND: {depend}")
    if bdepend:
        lines.append(f"BDEPEND: {bdepend}")
    return "\n".join(lines)


def stale(rdepend, mapping, **kw):
    return check.stale_in(stanza("app-misc/x-1", rdepend=rdepend, **kw),
                          FakeTree(mapping))


case("子槽变化时报出", lambda: (
    stale("media-libs/libavif:0/16.3=", {"media-libs/libavif": "16.4"})
    == [("media-libs/libavif", "0/16.3", "16.4")]))

case("子槽没变就不报", lambda: (
    stale("media-libs/libavif:0/16.3=", {"media-libs/libavif": "16.3"}) == []))

case("树里查不到这个包时不报", lambda: (
    stale("media-libs/libavif:0/16.3=", {}) == []))

case("没有 = 的依赖不看子槽", lambda: (
    stale("dev-libs/glib:2", {"dev-libs/glib": "9"}) == []))

case("查询时带上被钉住的槽", lambda: (
    check.atom_for("net-libs/mbedtls", "0") == "net-libs/mbedtls:0"))

case("没有写槽时按整个包查询", lambda: (
    check.atom_for("net-libs/mbedtls", "") == "net-libs/mbedtls"))

case("同一个槽里子槽变了才报", lambda: (
    stale("net-libs/mbedtls:0/7.14.1=", {"net-libs/mbedtls:0": "8.0.0"})
    == [("net-libs/mbedtls", "0/7.14.1", "8.0.0")]))

# A := dependency pins the slot too, so a newer major version living in another
# slot has not moved for this consumer.
case("别的槽里有新版本不算过期", lambda: (
    stale("net-libs/mbedtls:0/7.14.1=",
          {"net-libs/mbedtls:0": "7.14.1", "net-libs/mbedtls": "16.21.7"}) == []))

case("同一个包在一条依赖里出现两次只报一次", lambda: (
    len(stale("dev-libs/icu:0/78= dev-libs/icu:0/78=",
              {"dev-libs/icu": "79"})) == 1))

case("带 use 条件的写法也能认出来", lambda: (
    stale("media-libs/harfbuzz:0/6.0.0=[icu(+)]", {"media-libs/harfbuzz": "7.0.0"})
    == [("media-libs/harfbuzz", "0/6.0.0", "7.0.0")]))

case("取反的依赖同样按子槽判断", lambda: (
    stale("!!dev-libs/icu:0/78=", {"dev-libs/icu": "79"})
    == [("dev-libs/icu", "0/78", "79")]))

# A build-time subslot change does not affect the built package, so reporting
# it would only add noise.
case("DEPEND 里的子槽不报", lambda: (
    stale("", {"dev-lang/go": "1.27.0"}, depend="dev-lang/go:0/1.26.7=") == []))

case("BDEPEND 里的子槽不报", lambda: (
    stale("", {"dev-lang/go": "1.27.0"}, bdepend="dev-lang/go:0/1.26.7=") == []))


case("从索引头部读出这一代的关键字", lambda: (
    check.accepted_keywords("ACCEPT_KEYWORDS: amd64\nPACKAGES: 1") == "amd64"))

case("头部没有关键字时返回空", lambda: (
    check.accepted_keywords("PACKAGES: 1") == ""))


def run_main(stanzas, mapping, header=HEADER):
    """Run main(), returning (exit code, stdout, alert text or None)."""
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        (d / "Packages").write_text(header + "\n\n" + "\n\n".join(stanzas) + "\n")
        alert = d / "alert.txt"
        alert.write_text("上一轮留下的内容")
        original = check.Tree
        seen = []

        def fake(keywords):
            seen.append(keywords)
            return FakeTree(mapping)

        check.Tree = fake
        argv = sys.argv
        sys.argv = ["check-subslots.py", "--index", str(d / "Packages"),
                    "--alert", str(alert)]
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                rc = check.main()
        finally:
            check.Tree = original
            sys.argv = argv
        text = alert.read_text() if alert.exists() else None
        return rc, out.getvalue(), text, seen[0] if seen else None


case("有过期的包时以非零退出", lambda: (
    run_main([stanza("net-libs/w-1", rdepend="media-libs/libavif:0/16.3=")],
             {"media-libs/libavif": "16.4"})[0] == 1))

case("并且写出告警，指名是哪个包哪条依赖", lambda: (
    all(part in run_main(
        [stanza("net-libs/w-1", rdepend="media-libs/libavif:0/16.3=")],
        {"media-libs/libavif": "16.4"})[2]
        for part in ("net-libs/w-1", "media-libs/libavif", "0/16.3", "16.4"))))

case("全部正常时以 0 退出", lambda: (
    run_main([stanza("net-libs/w-1", rdepend="media-libs/libavif:0/16.3=")],
             {"media-libs/libavif": "16.3"})[0] == 0))

# An alert left from the previous round would be sent again every night, long
# after the problem it names was fixed.
case("全部正常时移除上一轮的告警文件", lambda: (
    run_main([stanza("net-libs/w-1", rdepend="media-libs/libavif:0/16.3=")],
             {"media-libs/libavif": "16.3"})[2] is None))

case("输出里给出检查了多少个包", lambda: (
    "1 个包" in run_main(
        [stanza("net-libs/w-1", rdepend="media-libs/libavif:0/16.3=")],
        {"media-libs/libavif": "16.3"})[1]))

# Measuring a stable index with the running machine's keywords reads a version
# only ~arch can install as current, and reports packages that were never due
# for an update.
case("按索引头部的关键字判断可见性，不按运行的机器", lambda: (
    run_main([stanza("net-libs/w-1", rdepend="media-libs/libavif:0/16.3=")],
             {"media-libs/libavif": "16.3"},
             header="ACCEPT_KEYWORDS: amd64\nPACKAGES: 1\nVERSION: 0")[3]
    == "amd64"))

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
