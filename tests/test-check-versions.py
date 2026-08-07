#!/usr/bin/env python3
import os
import pathlib
import subprocess
import sys
import tempfile

BUILD = pathlib.Path(__file__).resolve().parent.parent / "build"

CHECK = str(BUILD / "check-versions.py")
def make_overlay(root, packages, masked=(), body=None, moves=()):
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
    if moves:
        updates = prof / "updates"
        updates.mkdir()
        (updates / "1Q-2026").write_text(
            "".join(f"move {source} {target}\n" for source, target in moves))
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
        tree_empty=(), moves=(), excluded=None, channel_excluded=None):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        overlay = make_overlay(d / "overlay", packages or {}, masked, body, moves)
        gentoo = make_tree(d / "gentoo", tree, tree_empty)
        (d / "Packages").write_text(
            "ACCEPT_KEYWORDS: ~amd64\nPACKAGES: 0\n\n" + "\n\n".join(index_lines) + "\n")
        (d / "list.txt").write_text("\n".join(list_lines) + "\n")
        env = {**os.environ, "GENTOO_TREE": str(gentoo)}
        if excluded is not None:
            (d / "excluded.txt").write_text(
                "".join(f"{cp}\treason\n" for cp in excluded))
            env["EXCLUDED"] = str(d / "excluded.txt")
        if channel_excluded is not None:
            (d / "channel-excluded.txt").write_text(
                "".join(f"{cp}\treason\n" for cp in channel_excluded))
            env["CHANNEL_EXCLUDED"] = str(d / "channel-excluded.txt")
        p = subprocess.run([sys.executable, CHECK, str(overlay),
                            str(d / "Packages"), str(d / "list.txt")],
                           capture_output=True, text=True, env=env)
        return p.returncode, p.stdout


def retire(list_lines, packages=None, masked=(), body=None, moves=()):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        overlay = make_overlay(d / "overlay", packages or {}, masked, body, moves)
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


def simultaneous_lifecycle_case():
    versioned = "app-misc/versioned"
    deleted = "app-misc/deleted"
    masked = "app-misc/masked"
    newcomer = "app-misc/newcomer"
    moved_old = "app-misc/moved"
    moved_new = "net-misc/moved"
    packages = {
        versioned: "2.0",
        masked: "1.0",
        moved_new: "1.0",
        newcomer: "1.0",
    }
    listed = [versioned, deleted, masked, moved_old]
    index = [stanza(f"{versioned}-1.0"), stanza(f"{deleted}-1.0"),
             stanza(f"{masked}-1.0"), stanza(f"{moved_old}-1.0")]
    rc, out = run(index, listed, packages, masked=(masked,),
                  moves=((moved_old, moved_new),))
    expected = (
        f"落后   {versioned}",
        f"已移除 {deleted}",
        f"已屏蔽 {masked}",
        f"改分类 {moved_old} -> {moved_new}",
        f"新包   {newcomer}",
    )
    return rc == 1 and all(value in out for value in expected)


ok = simultaneous_lifecycle_case()
print(f"  {'✓' if ok else '✗'} {'同一次 add/drop、删除、mask、move 与新增':<24}")
if not ok:
    bad += 1


def excluded_env_case():
    listed = "app-misc/listed"
    dropped = "app-misc/dropped"
    packages = {listed: "1.0", dropped: "1.0"}
    index = [stanza(f"{listed}-1.0")]
    without = run(index, [listed], packages)[1]
    with_file = run(index, [listed], packages, excluded=[dropped])[1]
    return f"新包   {dropped}" in without and f"新包   {dropped}" not in with_file


ok = excluded_env_case()
print(f"  {'✓' if ok else '✗'} {'EXCLUDED 指定的清单会被采用':<24}")
if not ok:
    bad += 1


def channel_excluded_case():
    """A channel builds from a filtered list; its own skips are not newcomers."""
    listed = "app-misc/listed"
    skipped = "app-misc/skipped"
    packages = {listed: "1.0", skipped: "1.0"}
    index = [stanza(f"{listed}-1.0")]
    without = run(index, [listed], packages)[1]
    with_file = run(index, [listed], packages, channel_excluded=[skipped])[1]
    return f"新包   {skipped}" in without and f"新包   {skipped}" not in with_file


ok = channel_excluded_case()
print(f"  {'✓' if ok else '✗'} {'频道排除的包不算未收录的新包':<24}")
if not ok:
    bad += 1



MOVED_OLD = "app-misc/example"
MOVED_NEW = "net-misc/example"
BINDIST = 'EAPI=8\ninherit cmake\nKEYWORDS="~amd64"\nSLOT="0"\nRESTRICT="bindist"\n'
OKKW = 'EAPI=8\ninherit cmake\nKEYWORDS="~amd64"\nSLOT="0"\n'
NOKW = 'EAPI=8\ninherit cmake\nKEYWORDS="~arm64"\nSLOT="0"\n'
VAGUE = 'EAPI=8\ninherit cmake\nKEYWORDS="~amd64"\nSLOT="0"\nR="x"\nRESTRICT="${R}"\n'

rc, out = run([], [PKG], {PKG: NOW}, body={PKG: VAGUE})
ok = rc == 1 and "待核对" in out and "binhost 维护者" in out
print(f"  {'✓' if ok else '✗'} {'RESTRICT 无法判定时阻止发布':<24}")
if not ok:
    bad += 1


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
    ("profiles/updates 的 move 配成一对",
     [], [MOVED_OLD], {MOVED_NEW: NOW}, (), ((MOVED_OLD, MOVED_NEW),),
     f"改分类 {MOVED_OLD} -> {MOVED_NEW}"),
    ("包真的删了，没有同名新包，仍报已移除",
     [], [MOVED_OLD], {"net-misc/unrelated": NOW}, (), (), f"已移除 {MOVED_OLD}"),
    ("同名新包没有 move 记录时不猜测改分类",
     [], [MOVED_OLD], {MOVED_NEW: NOW}, (), (), f"已移除 {MOVED_OLD}"),
]
for name, idx, lst, packages, tree, moves, want in MIGRATE:
    rc, out = run(idx, lst, packages, tree=tree, moves=moves)
    ok = any(l.strip().startswith(want) for l in out.splitlines()) and rc == 1
    print(f"  {'✓' if ok else '✗'} {name:<24} {want}")
    if not ok:
        bad += 1
        for l in out.splitlines()[1:6]:
            print(f"      {l}")

UPSTREAM = [
    ("该 CP 同时存在于 ::gentoo 时报出", (PKG,), (), True),
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
     [f"{PKG}\t全部可用版本都是 RESTRICT=bindist，不发布 binpkg"]),
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

rc, got = retire([MOVED_OLD], {MOVED_NEW: NOW},
                 moves=((MOVED_OLD, MOVED_NEW),))
ok = got == [] and rc == 0
print(f"  {'✓' if ok else '✗'} {'move 来源不由 retire 单独提出':<24} {got if got else '（无）'}")
if not ok:
    bad += 1

for name, packages in (
    ("move 来源与目标都消失时由 retire 提出", {}),
    ("move 目标没有 ebuild 时由 retire 提出", {MOVED_NEW: []}),
):
    rc, got = retire([MOVED_OLD], packages,
                     moves=((MOVED_OLD, MOVED_NEW),))
    want = [f"{MOVED_OLD}\toverlay 中已不存在该软件包"]
    ok = got == want and rc == 0
    print(f"  {'✓' if ok else '✗'} {name:<24} {got}")
    if not ok:
        bad += 1


def newcomers(packages, list_lines, masked=(), restrict=None, keywords=None, body=None,
              moves=()):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        overlay = make_overlay(d / "overlay", packages, masked, body, moves)
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
    ("仅自定义 src_install 仍不视为源码构建", {PKG: NOW}, [],
     {"body": {PKG: 'EAPI=8\nKEYWORDS="~amd64"\nSLOT="0"\nsrc_install() {\n\tdobin tool\n}\n'}}, []),
    ("unpacker 即使写了 src_compile 也不报", {PKG: NOW}, [],
     {"body": {PKG: 'EAPI=8\ninherit unpacker\nKEYWORDS="~amd64"\nSLOT="0"\nsrc_compile() {\n\t:\n}\n'}}, []),
    ("move 目标不由 newcomers 单独提出", {MOVED_NEW: NOW}, [MOVED_OLD],
     {"moves": ((MOVED_OLD, MOVED_NEW),)}, []),
    ("历史 move 来源未收录时目标仍可提出", {MOVED_NEW: NOW}, [],
     {"moves": ((MOVED_OLD, MOVED_NEW),)}, [f"{MOVED_NEW} {NOW}"]),
]

for name, pkgs, lst, kw, want in NEW:
    rc, got = newcomers(pkgs, lst, **kw)
    ok = got == want and rc == 0
    print(f"  {'✓' if ok else '✗'} {name:<24} {got if got else '（无）'}")
    if not ok:
        bad += 1

rc, out = run([stanza(f"{PKG}-{NOW}").replace("REPO: gentoo-zh", "REPO: gentoo")],
              [PKG], {PKG: NOW})
ok = rc == 1 and "缺" in out
print(f"  {'✓' if ok else '✗'} {'::gentoo stanza 不算 overlay 已发布版本':<24}")
if not ok:
    bad += 1


def classification_probe():
    packages = {
        "virtual/meta": "0", "app-misc/live": "9999",
        "app-misc/no-amd64": "1", "app-misc/bindist": "1",
        "app-misc/unknown": "1", "app-misc/tool-bin": "1",
        "app-misc/prebuilt": "1", "app-misc/no-build": "1",
        "app-misc/candidate": "1",
    }
    body = {
        "app-misc/no-amd64": NOKW,
        "app-misc/bindist": BINDIST,
        "app-misc/unknown": VAGUE,
        "app-misc/prebuilt": 'EAPI=8\ninherit unpacker\nKEYWORDS="~amd64"\nSLOT="0"\n',
        "app-misc/no-build": 'EAPI=8\nKEYWORDS="~amd64"\nSLOT="0"\n',
    }
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        overlay = make_overlay(d / "overlay", packages, body=body)
        management = (
            ".claude/worktrees", ".git/hooks", ".git/info", ".git/logs",
            ".git/objects", ".git/refs", ".git/worktrees", ".github/workflows",
            "metadata/md5-cache", "metadata/news", "profiles/updates",
        )
        for relative in management:
            (overlay / relative).mkdir(parents=True, exist_ok=True)
        (d / "list.txt").write_text("")
        result = subprocess.run(
            [sys.executable, CHECK, "--newcomers", str(overlay), str(d / "list.txt")],
            capture_output=True, text=True)
        atoms = [cp for cp in packages if cp != "app-misc/live"]
        atoms.append("app-misc/live")
        once = all(result.stderr.count(cp) == 1 for cp in atoms)
        categories = ("元包", "仅有 9999 ebuild", "无可用 amd64 版本或已屏蔽",
                      "RESTRICT=bindist", "RESTRICT 无法判定", "-bin 软件包",
                      "预构建 eclass", "无已知构建阶段", "候选")
        return result.returncode == 0 and once and all(
            f">>> {category}: 1:" in result.stderr for category in categories) \
            and not any(relative in result.stderr for relative in management) \
            and result.stdout.splitlines() == ["app-misc/candidate 1"]


ok = classification_probe()
print(f"  {'✓' if ok else '✗'} {'每个 newcomer 恰好归入一个可审计分类':<24}")
if not ok:
    bad += 1


def move_rows(packages=None):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        overlay = make_overlay(d / "overlay",
                               {MOVED_NEW: NOW} if packages is None else packages,
                               moves=((MOVED_OLD, MOVED_NEW),))
        (d / "list.txt").write_text(MOVED_OLD + "\n")
        p = subprocess.run([sys.executable, CHECK, "--moves", str(overlay),
                            str(d / "list.txt")], capture_output=True, text=True)
        return p.returncode, p.stdout.splitlines()


rc, rows = move_rows()
ok = rc == 0 and rows == [f"{MOVED_OLD}\t{MOVED_NEW}"]
print(f"  {'✓' if ok else '✗'} {'move 清单只输出权威配对':<24} {rows}")
if not ok:
    bad += 1

rc, rows = move_rows({MOVED_NEW: []})
ok = rc == 0 and rows == []
print(f"  {'✓' if ok else '✗'} {'move 目标没有 ebuild 时不输出配对':<24} {rows}")
if not ok:
    bad += 1

sys.exit(1 if bad else 0)
