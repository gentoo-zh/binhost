#!/usr/bin/env python3
"""Check check-versions against the shapes real overlay commits take.

overlay 的提交主要是这几种：`add X, drop Y`、只 add、只 drop、package.mask、
以及改分类。每种对索引的影响不同，这里各构造一个索引状态，看检测器给出的
结论对不对。

    test-check-versions.py [overlay 路径] [packages.txt]

需要一份真实的 overlay：判定要读它的 ebuild 版本与 package.mask。
"""
import pathlib
import subprocess
import sys
import tempfile

CHECK = str(pathlib.Path(__file__).with_name("check-versions.py"))
def make_overlay(root, packages, masked=()):
    """Build a minimal overlay: {cp: version} plus a package.mask list.

    Fixtures, not the live overlay. Every case here used to read
    /var/db/repos/gentoo-zh, so a case only held as long as some real package
    stayed in the state it needed: net-misc/biliup-rs was the masked example
    until it was treecleaned, and the case then reported 已移除 instead.
    """
    root = pathlib.Path(root)
    for cp, ver in packages.items():
        d = root / cp
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{d.name}-{ver}.ebuild").write_text(
            'EAPI=8\ninherit cmake\nKEYWORDS="~amd64"\nSLOT="0"\n')
    prof = root / "profiles"
    prof.mkdir(parents=True, exist_ok=True)
    (prof / "repo_name").write_text("gentoo-zh\n")
    (prof / "package.mask").write_text(
        "".join(f"# masked for removal\n{cp}\n" for cp in masked))
    return root


def run(index_lines, list_lines, packages=None, masked=()):
    """Write the index, the list and a fixture overlay, run the checker once,
    return its output.

    A context manager rather than mkdtemp: this runs nine cases, and the
    directories mkdtemp leaves behind are never collected.
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        overlay = make_overlay(d / "overlay", packages or {}, masked)
        (d / "Packages").write_text(
            "ACCEPT_KEYWORDS: ~amd64\nPACKAGES: 0\n\n" + "\n\n".join(index_lines) + "\n")
        (d / "list.txt").write_text("\n".join(list_lines) + "\n")
        p = subprocess.run([sys.executable, CHECK, str(overlay),
                            str(d / "Packages"), str(d / "list.txt")],
                           capture_output=True, text=True)
        return p.returncode, p.stdout


def stanza(cpv):
    cp = cpv.rsplit("-", 1)[0]
    return f"CPV: {cpv}\nPATH: {cp}/{cpv.split('/')[-1]}.gpkg.tar\nREPO: gentoo-zh"


PKG = "app-misc/example"
NOW = "1.2.0"

CASES = [
    # shape                                      index          list     overlay        masked  expected
    ("add+drop 后索引已跟上",                        [f"{PKG}-{NOW}"], [PKG], {PKG: NOW},    (),     "无问题"),
    ("add+drop 后索引未跟上",                        [f"{PKG}-0.0.1"], [PKG], {PKG: NOW},    (),     "落后"),
    ("索引版本高于 overlay，同样报出",   [f"{PKG}-99.0"],  [PKG], {PKG: NOW},    (),     "落后"),
    ("仅 add，索引尚无该版本",                       [],               [PKG], {PKG: NOW},    (),     "缺"),
    ("仅 drop，索引仍为旧版本",                    [f"{PKG}-0.9"],   [PKG], {PKG: NOW},    (),     "落后"),
    ("mask 后清单未更新",                        [],               [PKG], {PKG: NOW},    (PKG,), "已屏蔽"),
    ("改分类后清单未更新",                        [],               [PKG], {},            (),     "已移除"),
    # A deleted package looks the same from the list as a moved category: not
    # found in the overlay
    ("包已删除，清单未更新",                     [],               [PKG], {},            (),     "已移除"),
    # 索引同时留着 1.9 与 1.10 时，按字串序 1.9 在后。取最后一笔会把建对了的
    # 这一轮报成落后。
    ("索引里同一个包两个版本，取最高的那个",
     [f"{PKG}-1.10", f"{PKG}-1.9"], [PKG], {PKG: "1.10"}, (), "无问题"),
    # 只有 -9999 的包永远不会进索引，原来这是唯一不被报出的缺席原因
    ("清单成员只有 9999",                        [],               [PKG], {PKG: "9999"}, (),     "仅"),
]


def newcomer_case():
    """A new package: has a build system, installable on amd64, not on the list.

    A fixture overlay holding only this package. Read from the live overlay the
    case would fail the moment the list is fully triaged, which is the state the
    system is meant to be in.
    """
    return run([], [], {"dev-util/binhost-test-newcomer": "1.0"})

print(f"  {'型态':<24} {'预期':<8} 实际")
bad = 0
for name, idx, lst, packages, masked, expect in CASES:
    rc, out = run([stanza(c) for c in idx], lst, packages, masked)
    # Look only at the line naming the package under test. Field names in the
    # summary line would match by accident, and the uncollected newcomers are
    # listed in bulk every time, which would bury this case's conclusion.
    target = lst[0]
    hit = [l.strip() for l in out.splitlines()
           if l.startswith("    ") and target in l]
    got = hit[0].split()[0] if hit else "无问题"
    # The exit code is asserted, not just printed: a crash leaves stdout empty,
    # and every case expecting 无问题 would pass on it.
    want_rc = 0 if expect == "无问题" else 1
    ok = got == expect and rc == want_rc
    print(f"  {'✓' if ok else '✗'} {name:<22} {expect:<8} {got}  (退出码 {rc}，应为 {want_rc})")
    if not ok:
        bad += 1
        for l in out.splitlines()[1:4]:
            print(f"      {l}")

rc, out = newcomer_case()
lines = [l.strip() for l in out.splitlines() if l.strip().startswith("新包")]
# A newcomer is reported but does not fail the round, so the exit code is 0.
ok = len(lines) == 1 and rc == 0
print(f"  {'✓' if ok else '✗'} {'新包上线未收录':<22} {'新包':<8} "
      f"{'报出 %d 个' % len(lines) if lines else '未报出'}  (退出码 {rc}，应为 0)")
if not ok:
    bad += 1

# --- --newcomers ---------------------------------------------------------------
# newcomers workflow 据它开 PR，改错了会无人值守地送出去。


def newcomers(packages, list_lines, masked=(), restrict=None, keywords=None):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        overlay = make_overlay(d / "overlay", packages, masked)
        for cp, extra in (restrict or {}).items():
            for eb in (overlay / cp).glob("*.ebuild"):
                eb.write_text(eb.read_text() + f'RESTRICT="{extra}"\n')
        for cp, kw in (keywords or {}).items():
            for eb in (overlay / cp).glob("*.ebuild"):
                eb.write_text(eb.read_text().replace('KEYWORDS="~amd64"',
                                                     f'KEYWORDS="{kw}"'))
        (d / "list.txt").write_text("\n".join(list_lines) + "\n")
        p = subprocess.run([sys.executable, CHECK, "--newcomers", str(overlay),
                            str(d / "list.txt")], capture_output=True, text=True)
        return p.returncode, [l for l in p.stdout.splitlines() if l.strip()]


NEW = [
    ("在清单里的不报", {PKG: NOW}, [PKG], {}, []),
    ("不在清单里的报出来", {PKG: NOW}, [], {}, [f"{PKG} {NOW}"]),
    ("被 mask 的不报", {PKG: NOW}, [], {"masked": (PKG,)}, []),
    ("acct-group 不报", {"acct-group/foo": "0"}, [], {}, []),
    ("virtual 不报", {"virtual/foo": "0"}, [], {}, []),
    ("-bin 结尾不报", {"app-misc/foo-bin": "1.0"}, [], {}, []),
    ("不接受 amd64 的不报", {PKG: NOW}, [], {"keywords": {PKG: "~arm64"}}, []),
    ("RESTRICT=bindist 不报", {PKG: NOW}, [], {"restrict": {PKG: "bindist"}}, []),
]

for name, pkgs, lst, kw, want in NEW:
    rc, got = newcomers(pkgs, lst, **kw)
    ok = got == want and rc == 0
    print(f"  {'✓' if ok else '✗'} {name:<24} {got if got else '（无）'}")
    if not ok:
        bad += 1

sys.exit(1 if bad else 0)
