#!/usr/bin/env python3
import os
import pathlib
import subprocess
import sys
import tempfile

CHECK = str(pathlib.Path(__file__).with_name("check-versions.py"))
def make_overlay(root, packages, masked=(), body=None):
    root = pathlib.Path(root)
    for cp, vers in packages.items():
        d = root / cp
        d.mkdir(parents=True, exist_ok=True)
        for ver in ([vers] if isinstance(vers, str) else vers):
            (d / f"{d.name}-{ver}.ebuild").write_text(
                (body or {}).get(cp,
                    'EAPI=8\ninherit cmake\nKEYWORDS="~amd64"\nSLOT="0"\n'))
    prof = root / "profiles"
    prof.mkdir(parents=True, exist_ok=True)
    (prof / "repo_name").write_text("gentoo-zh\n")
    (prof / "package.mask").write_text(
        "".join(f"# masked for removal\n{cp}\n" for cp in masked))
    return root


def make_tree(root, packages, empty=()):
    root = pathlib.Path(root)
    for cp in packages:
        d = root / cp
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{d.name}-1.0.ebuild").write_text('EAPI=8\nSLOT="0"\n')
    for cp in empty:
        (root / cp).mkdir(parents=True, exist_ok=True)
    return root


def run(index_lines, list_lines, packages=None, masked=(), tree=(), body=None,
        tree_empty=()):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        overlay = make_overlay(d / "overlay", packages or {}, masked, body)
        gentoo = make_tree(d / "gentoo", tree, tree_empty)
        (d / "Packages").write_text(
            "ACCEPT_KEYWORDS: ~amd64\nPACKAGES: 0\n\n" + "\n\n".join(index_lines) + "\n")
        (d / "list.txt").write_text("\n".join(list_lines) + "\n")
        p = subprocess.run([sys.executable, CHECK, str(overlay),
                            str(d / "Packages"), str(d / "list.txt")],
                           capture_output=True, text=True,
                           env={**os.environ, "GENTOO_TREE": str(gentoo)})
        return p.returncode, p.stdout


def retire(list_lines, packages=None, masked=(), body=None):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        overlay = make_overlay(d / "overlay", packages or {}, masked, body)
        (d / "list.txt").write_text("\n".join(list_lines) + "\n")
        p = subprocess.run([sys.executable, CHECK, "--retire", str(overlay),
                            str(d / "list.txt")], capture_output=True, text=True)
        return p.returncode, [l for l in p.stdout.splitlines() if l.strip()]


def stanza(cpv):
    cp = cpv.rsplit("-", 1)[0]
    return f"CPV: {cpv}\nPATH: {cp}/{cpv.split('/')[-1]}.gpkg.tar\nREPO: gentoo-zh"


PKG = "app-misc/example"
NOW = "1.2.0"

CASES = [
    ("add+drop 后索引已跟上",                        [f"{PKG}-{NOW}"], [PKG], {PKG: NOW},    (),     "无问题"),
    ("add+drop 后索引未跟上",                        [f"{PKG}-0.0.1"], [PKG], {PKG: NOW},    (),     "落后"),
    ("索引版本高于 overlay，同样报出",   [f"{PKG}-99.0"],  [PKG], {PKG: NOW},    (),     "落后"),
    ("仅 add，索引尚无该版本",                       [],               [PKG], {PKG: NOW},    (),     "缺"),
    ("仅 drop，索引仍为旧版本",                    [f"{PKG}-0.9"],   [PKG], {PKG: NOW},    (),     "落后"),
    ("mask 后清单未更新",                        [],               [PKG], {PKG: NOW},    (PKG,), "已屏蔽"),
    ("改分类后清单未更新",                        [],               [PKG], {},            (),     "已移除"),
    ("包已删除，清单未更新",                     [],               [PKG], {},            (),     "已移除"),
    ("索引里同一个包两个版本，取最高的那个",
     [f"{PKG}-1.10", f"{PKG}-1.9"], [PKG], {PKG: "1.10"}, (), "无问题"),
    ("清单成员只有 9999",                        [],               [PKG], {PKG: "9999"}, (),     "仅"),
]


def newcomer_case():
    return run([], [], {"dev-util/binhost-test-newcomer": "1.0"})

print(f"  {'型态':<24} {'预期':<8} 实际")
bad = 0
for name, idx, lst, packages, masked, expect in CASES:
    rc, out = run([stanza(c) for c in idx], lst, packages, masked)
    target = lst[0]
    hit = [l.strip() for l in out.splitlines()
           if l.startswith("    ") and target in l]
    got = hit[0].split()[0] if hit else "无问题"
    want_rc = 0 if expect == "无问题" else 1
    ok = got == expect and rc == want_rc
    print(f"  {'✓' if ok else '✗'} {name:<22} {expect:<8} {got}  (退出码 {rc}，应为 {want_rc})")
    if not ok:
        bad += 1
        for l in out.splitlines()[1:4]:
            print(f"      {l}")

rc, out = newcomer_case()
lines = [l.strip() for l in out.splitlines() if l.strip().startswith("新包")]
ok = len(lines) == 1 and rc == 0
print(f"  {'✓' if ok else '✗'} {'新包上线未收录':<22} {'新包':<8} "
      f"{'报出 %d 个' % len(lines) if lines else '未报出'}  (退出码 {rc}，应为 0)")
if not ok:
    bad += 1



MOVED_OLD = "app-misc/example"
MOVED_NEW = "net-misc/example"
BINDIST = 'EAPI=8\ninherit cmake\nKEYWORDS="~amd64"\nSLOT="0"\nRESTRICT="bindist"\n'
OKKW = 'EAPI=8\ninherit cmake\nKEYWORDS="~amd64"\nSLOT="0"\n'
NOKW = 'EAPI=8\ninherit cmake\nKEYWORDS="~arm64"\nSLOT="0"\n'
VAGUE = 'EAPI=8\ninherit cmake\nKEYWORDS="~amd64"\nSLOT="0"\nR="x"\nRESTRICT="${R}"\n'


def retire_mixed(list_lines, cp, versions):
    """One package, a different ebuild body per version."""
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        overlay = make_overlay(d / "overlay", {})
        pkg = overlay / cp
        pkg.mkdir(parents=True, exist_ok=True)
        for ver, body in versions.items():
            (pkg / f"{pkg.name}-{ver}.ebuild").write_text(body)
        (d / "list.txt").write_text("\n".join(list_lines) + "\n")
        p = subprocess.run([sys.executable, CHECK, "--retire", str(overlay),
                            str(d / "list.txt")], capture_output=True, text=True)
        return p.returncode, [l for l in p.stdout.splitlines() if l.strip()]

MIGRATE = [
    ("改分类，两边同名，配成一对",
     [], [MOVED_OLD], {MOVED_NEW: NOW}, (), f"疑似改分类 {MOVED_OLD} -> {MOVED_NEW}"),
    ("包真的删了，没有同名新包，仍报已移除",
     [], [MOVED_OLD], {"net-misc/unrelated": NOW}, (), f"已移除 {MOVED_OLD}"),
    ("同名新包已经在清单里，不算改分类",
     [], [MOVED_OLD, MOVED_NEW], {MOVED_NEW: NOW}, (), f"已移除 {MOVED_OLD}"),
]
for name, idx, lst, packages, tree, want in MIGRATE:
    rc, out = run(idx, lst, packages, tree=tree)
    ok = any(l.strip().startswith(want) for l in out.splitlines()) and rc == 1
    print(f"  {'✓' if ok else '✗'} {name:<24} {want}")
    if not ok:
        bad += 1
        for l in out.splitlines()[1:6]:
            print(f"      {l}")

UPSTREAM = [
    ("::gentoo 也有这个包就报出", (PKG,), (), True),
    ("::gentoo 没有就不报", ("app-misc/other",), (), False),
    ("::gentoo 有目录但没有 ebuild 不算", (), (PKG,), False),
]
for name, tree, tree_empty, want in UPSTREAM:
    rc, out = run([stanza(f"{PKG}-{NOW}")], [PKG], {PKG: NOW},
                  tree=tree, tree_empty=tree_empty)
    got = any("已进主树" in l for l in out.splitlines())
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {name:<24} {'报出' if got else '未报出'}")
    if not ok:
        bad += 1

RETIRE = [
    ("overlay 中不存在的列为可移出", [PKG], {},
     {}, [f"{PKG}\toverlay 中已不存在该软件包"]),
    ("整包被 mask 的列为可移出", [PKG], {PKG: NOW},
     {"masked": (PKG,)}, [f"{PKG}\toverlay 的 package.mask 屏蔽了全部版本"]),
    ("只有 9999 的列为可移出", [PKG], {PKG: "9999"},
     {}, [f"{PKG}\t只有 live ebuild，无法构建可发布的版本"]),
    ("RESTRICT=bindist 的列为可移出", [PKG], {PKG: NOW},
     {"body": {PKG: BINDIST}},
     [f"{PKG}\t全部可用版本都是 RESTRICT=bindist，不可再散布"]),
    ("正常的包不列出", [PKG], {PKG: NOW}, {}, []),
    ("只 mask 新版、旧版仍可用的不列出", [PKG], {PKG: ["1.0", "2.0"]},
     {"masked": (f">={PKG}-2",)}, []),
    ("mask 覆盖了全部版本的才列出", [PKG], {PKG: ["1.0", "2.0"]},
     {"masked": (f">={PKG}-1",)},
     [f"{PKG}\toverlay 的 package.mask 屏蔽了全部版本"]),
    ("新版无 amd64、旧版有的不列出", [PKG], {PKG: ["1.0", "2.0"]},
     {"body": {PKG: None}}, []),
    ("全部版本都无 amd64 的才列出", [PKG], {PKG: ["1.0", "2.0"]},
     {"body": {PKG: NOKW}}, [f"{PKG}\t没有接受 amd64 的版本"]),
    ("RESTRICT 无法判定的不列出", [PKG], {PKG: NOW},
     {"body": {PKG: VAGUE}}, []),
]
for name, lst, packages, kw, want in RETIRE:
    if kw.get("body") == {PKG: None}:
        kw = {}
        rc, got = retire_mixed(lst, PKG, {"1.0": OKKW, "2.0": NOKW})
        ok = got == want and rc == 0
        print(f"  {'✓' if ok else '✗'} {name:<24} {got if got else '（无）'}")
        if not ok:
            bad += 1
        continue
    rc, got = retire(lst, packages, **kw)
    ok = got == want and rc == 0
    print(f"  {'✓' if ok else '✗'} {name:<24} {got if got else '（无）'}")
    if not ok:
        bad += 1

rc, got = retire([PKG], {PKG: NOW}, masked=(PKG,))
ok = len(got) == 1 and got[0].count("\t") == 1
print(f"  {'✓' if ok else '✗'} {'每行一个制表符分隔包名和原因':<24} {got}")
if not ok:
    bad += 1


def newcomers(packages, list_lines, masked=(), restrict=None, keywords=None, body=None):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        overlay = make_overlay(d / "overlay", packages, masked, body)
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
    ("不在清单里的会被报出", {PKG: NOW}, [], {}, [f"{PKG} {NOW}"]),
    ("被 mask 的不报", {PKG: NOW}, [], {"masked": (PKG,)}, []),
    ("acct-group 不报", {"acct-group/foo": "0"}, [], {}, []),
    ("virtual 不报", {"virtual/foo": "0"}, [], {}, []),
    ("-bin 结尾不报", {"app-misc/foo-bin": "1.0"}, [], {}, []),
    ("不接受 amd64 的不报", {PKG: NOW}, [], {"keywords": {PKG: "~arm64"}}, []),
    ("RESTRICT=bindist 不报", {PKG: NOW}, [], {"restrict": {PKG: "bindist"}}, []),
    ("自己写 src_configure 的会被报出", {PKG: NOW}, [],
     {"body": {PKG: 'EAPI=8\nKEYWORDS="~amd64"\nSLOT="0"\nsrc_configure() {\n\t./configure\n}\n'}}, [f"{PKG} {NOW}"]),
    ("自己写 src_compile 的会被报出", {PKG: NOW}, [],
     {"body": {PKG: 'EAPI=8\nKEYWORDS="~amd64"\nSLOT="0"\nsrc_compile() {\n\temake\n}\n'}}, [f"{PKG} {NOW}"]),
    ("既没有构建 eclass 也没有编译阶段的不报", {PKG: NOW}, [],
     {"body": {PKG: 'EAPI=8\nKEYWORDS="~amd64"\nSLOT="0"\n'}}, []),
    ("unpacker 即使写了 src_compile 也不报", {PKG: NOW}, [],
     {"body": {PKG: 'EAPI=8\ninherit unpacker\nKEYWORDS="~amd64"\nSLOT="0"\nsrc_compile() {\n\t:\n}\n'}}, []),
]

for name, pkgs, lst, kw, want in NEW:
    rc, got = newcomers(pkgs, lst, **kw)
    ok = got == want and rc == 0
    print(f"  {'✓' if ok else '✗'} {name:<24} {got if got else '（无）'}")
    if not ok:
        bad += 1

sys.exit(1 if bad else 0)
