#!/usr/bin/env python3
"""用 overlay 真实提交的型态验证 check-versions 的判定。

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
OVERLAY = sys.argv[1] if len(sys.argv) > 1 else "/var/db/repos/gentoo-zh"


def run(index_lines, list_lines, overlay=OVERLAY):
    """把索引与清单写进临时文件，跑一次检测器，返回输出。

    用上下文管理器而不是 mkdtemp：这个测试一跑就是九个用例，mkdtemp 留下的
    目录没人收，跑几轮机器的 /tmp 里就是几十个空壳。
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        (d / "Packages").write_text(
            "ACCEPT_KEYWORDS: ~amd64\nPACKAGES: 0\n\n" + "\n\n".join(index_lines) + "\n")
        (d / "list.txt").write_text("\n".join(list_lines) + "\n")
        p = subprocess.run([sys.executable, CHECK, overlay, str(d / "Packages"), str(d / "list.txt")],
                           capture_output=True, text=True)
        return p.returncode, p.stdout


def stanza(cpv):
    cp = cpv.rsplit("-", 1)[0]
    return f"CPV: {cpv}\nPATH: {cp}/{cpv.split('/')[-1]}.gpkg.tar\nREPO: gentoo-zh"


def cur_version(cp):
    """overlay 里这个包当前的版本。测试数据不能写死——overlay 一 bump 就失效。"""
    d = pathlib.Path(OVERLAY) / cp
    ebs = [e for e in d.glob("*.ebuild") if "9999" not in e.name]
    if not ebs:
        return None
    return sorted(e.name[len(d.name) + 1:-7] for e in ebs)[-1]


NAUT = "gnome-extra/nautilus-open-any-terminal"
NOW = cur_version(NAUT) or "0.0"

CASES = [
    # 型态                    索引里的版本                            清单            预期
    ("add+drop 后已跟上", [f"{NAUT}-{NOW}"], [NAUT], "无问题"),
    ("add+drop 后没跟上", [f"{NAUT}-0.0.1"], [NAUT], "落后"),
    ("索引比 overlay 还新（不该发生，也要报）", [f"{NAUT}-99.0"], [NAUT], "落后"),
    ("只 add，索引还没有",
     [],
     ["app-misc/openclaude"], "缺"),
    ("只 drop，索引留着旧版",
     ["www-servers/dufs-0.45.0"],
     ["www-servers/dufs"], "落后"),
    ("mask 之后清单没清",
     [],
     ["net-misc/biliup-rs"], "已屏蔽"),
    ("move 之后清单没跟",
     [],
     ["www-apps/dufs"], "已移除"),
    # 包被整个删掉，和改分类在清单这边表现一样：overlay 里找不到了
    ("包被删除，清单还留着",
     [],
     ["net-misc/no-such-package"], "已移除"),
]

def newcomer_case():
    """新包上线：overlay 里有构建系统、能装在 amd64 上、又不在清单里。

    造一棵只有这一个包的 overlay，不看真实 overlay。看真实的话，清单一旦
    整理干净就再没有这类包，这一项会在系统状态最正确的时候失败。
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp) / "dev-util" / "binhost-test-newcomer"
        d.mkdir(parents=True)
        (d / "binhost-test-newcomer-1.0.ebuild").write_text(
            'EAPI=8\ninherit cmake\nKEYWORDS="~amd64"\nSLOT="0"\n')
        return run([], [], overlay=str(pathlib.Path(tmp)))

print(f"  {'型态':<24} {'预期':<8} 实际")
bad = 0
for name, idx, lst, expect in CASES:
    rc, out = run([stanza(c) for c in idx], lst)
    # 只看提到被测包的那一行。摘要行里的字段名会误配，而未收录的新包
    # 每次都会列一大批，不筛就会盖住本例的结论。
    target = lst[0]
    hit = [l.strip() for l in out.splitlines()
           if l.startswith("    ") and target in l]
    got = hit[0].split()[0] if hit else "无问题"
    ok = "✓" if got == expect else "✗"
    print(f"  {ok} {name:<22} {expect:<8} {got}  (退出码 {rc})")
    if got != expect:
        bad += 1
        for l in out.splitlines()[1:4]:
            print(f"      {l}")

rc, out = newcomer_case()
lines = [l.strip() for l in out.splitlines() if l.strip().startswith("新包")]
ok = "✓" if len(lines) == 1 else "✗"
print(f"  {ok} {'新包上线未收录':<22} {'新包':<8} "
      f"{'报出 %d 个' % len(lines) if lines else '没报出来'}  (退出码 {rc})")
if len(lines) != 1:
    bad += 1

sys.exit(1 if bad else 0)
