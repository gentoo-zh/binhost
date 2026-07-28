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
    ("add+drop 后已跟上",                        [f"{PKG}-{NOW}"], [PKG], {PKG: NOW},    (),     "无问题"),
    ("add+drop 后没跟上",                        [f"{PKG}-0.0.1"], [PKG], {PKG: NOW},    (),     "落后"),
    ("索引比 overlay 还新（不该发生，也要报）",   [f"{PKG}-99.0"],  [PKG], {PKG: NOW},    (),     "落后"),
    ("只 add，索引还没有",                       [],               [PKG], {PKG: NOW},    (),     "缺"),
    ("只 drop，索引留着旧版",                    [f"{PKG}-0.9"],   [PKG], {PKG: NOW},    (),     "落后"),
    ("mask 之后清单没清",                        [],               [PKG], {PKG: NOW},    (PKG,), "已屏蔽"),
    ("move 之后清单没跟",                        [],               [PKG], {},            (),     "已移除"),
    # A deleted package looks the same from the list as a moved category: not
    # found in the overlay
    ("包被删除，清单还留着",                     [],               [PKG], {},            (),     "已移除"),
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
      f"{'报出 %d 个' % len(lines) if lines else '没报出来'}  (退出码 {rc}，应为 0)")
if not ok:
    bad += 1

sys.exit(1 if bad else 0)
