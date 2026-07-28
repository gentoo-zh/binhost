#!/usr/bin/env python3
"""Cases for audit-distfiles.py's reap.

This is the only code in the repository that deletes distfiles, and distfiles
cannot be fetched again once upstream drops a release. It had no test at all.
"""

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import time

TARGET = pathlib.Path(__file__).resolve().parent.parent / "deploy" / "audit-distfiles.py"
if not TARGET.exists():
    # Only build/ is installed on the build machine; deploy/ is not there.
    # This is a repository-level test and runs in CI.
    print(f"  跳过：{TARGET} 不存在，本机没有完整仓库")
    sys.exit(0)

spec = importlib.util.spec_from_file_location("audit_distfiles", TARGET)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def reap(orphans, files, seen=None, grace=audit.GRACE_SECONDS):
    """Run reap over a scratch distdir. files is {name: content}.

    Returns (deleted names, names still on disk, state written).
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        dist = d / "dist" / "ab"
        dist.mkdir(parents=True)
        paths = {}
        for name, content in files.items():
            p = dist / name
            p.write_text(content)
            paths[name] = p
        state = d / "state.json"
        if seen is not None:
            state.write_text(json.dumps(seen))
        old_state, old_bin = audit.STATE, audit.RECYCLE
        audit.STATE = str(state)
        audit.RECYCLE = str(d / "recycle")
        try:
            deleted, _failed = audit.reap(set(orphans), paths, grace=grace)
        finally:
            audit.STATE, audit.RECYCLE = old_state, old_bin
        left = sorted(p.name for p in dist.iterdir())
        written = json.loads(state.read_text()) if state.exists() else {}
        return sorted(deleted), left, written


NOW = int(time.time())
OLD = NOW - audit.GRACE_SECONDS - 60

CASES = []


def case(name, fn):
    CASES.append((name, fn))


case("刚发现的孤儿不删，只记时间", lambda: (
    lambda r: r[0] == [] and r[1] == ["a.tar.gz"] and "a.tar.gz" in r[2]
)(reap(["a.tar.gz"], {"a.tar.gz": "x"})))

case("过了回收期才删", lambda: (
    lambda r: r[0] == ["a.tar.gz"] and r[1] == []
)(reap(["a.tar.gz"], {"a.tar.gz": "x"}, seen={"a.tar.gz": OLD})))

case("不是孤儿的一个都不碰", lambda: (
    lambda r: r[0] == [] and r[1] == ["a.tar.gz", "b.tar.gz"]
)(reap([], {"a.tar.gz": "x", "b.tar.gz": "y"}, seen={"a.tar.gz": OLD})))

case("又被引用了就从状态里忘掉", lambda: (
    "a.tar.gz" not in reap([], {"a.tar.gz": "x"}, seen={"a.tar.gz": OLD})[2]))

case("删完之后状态里不再留着它", lambda: (
    "a.tar.gz" not in reap(["a.tar.gz"], {"a.tar.gz": "x"}, seen={"a.tar.gz": OLD})[2]))

# [ ] and ? in a filename used to be read as a glob pattern: one form matched
# nothing at all, the other matched some other file and deleted it.
case("文件名带方括号也能删掉", lambda: (
    lambda r: r[0] == ["a-[1.0].tar.gz"] and r[1] == []
)(reap(["a-[1.0].tar.gz"], {"a-[1.0].tar.gz": "x"}, seen={"a-[1.0].tar.gz": OLD})))

case("文件名带问号时不误伤同名模式匹配到的文件", lambda: (
    lambda r: r[0] == ["pkg-?.tar.gz"] and r[1] == ["pkg-1.tar.gz"]
)(reap(["pkg-?.tar.gz"],
       {"pkg-?.tar.gz": "x", "pkg-1.tar.gz": "keep"},
       seen={"pkg-?.tar.gz": OLD})))

case("文件名带星号同理", lambda: (
    lambda r: r[0] == ["pkg-*.tar.gz"] and r[1] == ["pkg-9.tar.gz"]
)(reap(["pkg-*.tar.gz"],
       {"pkg-*.tar.gz": "x", "pkg-9.tar.gz": "keep"},
       seen={"pkg-*.tar.gz": OLD})))

case("孤儿在磁盘上已经不存在时不报错", lambda: (
    reap(["gone.tar.gz"], {"a.tar.gz": "x"}, seen={"gone.tar.gz": OLD})[0] == []))



# --- main(): 决定「什么算孤儿」的那一半 -------------------------------------
# 原来一条都没有。把 scan() 改成回传空 dict（等于整个镜像变孤儿）时，上面九条
# 照样全过，因为它们把孤儿清单直接喂给 reap。真正危险的是清单怎么算出来的。

def build_overlay(root, packages):
    """packages: {cp: {ebuild 版本: [DIST 文件名]}}，写出 Manifest 与 ebuild。"""
    root = pathlib.Path(root)
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    (root / "profiles" / "repo_name").write_text("gentoo-zh\n")
    for cp, versions in packages.items():
        d = root / cp
        d.mkdir(parents=True, exist_ok=True)
        dists = set()
        for ver, files in versions.items():
            (d / f"{d.name}-{ver}.ebuild").write_text('EAPI=8\nSLOT="0"\n')
            dists.update(files)
        (d / "Manifest").write_text(
            "".join(f"DIST {f} 1 BLAKE2B x SHA512 y\n" for f in sorted(dists)))
    return root


def run_main(packages, on_mirror, aged=None, preload=None, bin_readonly=False):
    """跑完整的 main()，回传 (退出码, 镜像上剩下的文件, 回收目录里的文件)。

    aged 把某个文件的 mtime 往前拨，模拟它很久以前就被抓下来了。
    preload 先在回收桶里放一份同名的。
    bin_readonly 让回收桶建不起来，模拟搬不动的情形。
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        ov = build_overlay(d / "overlay", packages)
        dist = d / "dist" / "ab"
        dist.mkdir(parents=True)
        for name in on_mirror:
            (dist / name).write_text("x")
        now = int(time.time())
        for name, age in (aged or {}).items():
            os.utime(dist / name, (now - age, now - age))
        old = (audit.STATE, audit.RECYCLE, audit.GRACE_SECONDS)
        audit.STATE = str(d / "state.json")
        audit.RECYCLE = str(d / "recycle")
        audit.GRACE_SECONDS = 0          # 立即到期，好在一轮里看到结果
        if preload:
            (d / "recycle").mkdir(parents=True, exist_ok=True)
            for name, content in preload.items():
                (d / "recycle" / name).write_text(content)
        if bin_readonly:
            # 回收桶的父目录不可写，mkdir 与 rename 都会失败
            blocked = d / "blocked"
            blocked.mkdir()
            blocked.chmod(0o500)
            audit.RECYCLE = str(blocked / "recycle")
        try:
            rc = audit.main(str(ov), str(d / "dist"))
        finally:
            audit.STATE, audit.RECYCLE, audit.GRACE_SECONDS = old
        left = sorted(p.name for p in dist.iterdir())
        binned = sorted(p.name for p in (d / "recycle").iterdir()) \
            if (d / "recycle").is_dir() else []
        return rc, left, binned


# overlay 读不出任何 Manifest：整个镜像都会算成孤儿，必须一个都不动并且报错
case("overlay 读不到内容时拒绝清理", lambda: (
    lambda r: r[0] == 1 and len(r[1]) == 5 and r[2] == []
)(run_main({}, ["a.tar.gz", "b.tar.xz", "c.zip", "d.tar.bz2", "e.crate"])))

# 线上 2026-07-28 的真实数字：overlay 一次 treeclean 掉 30 个包，镜像上 1224 个
# 文件里 138 个变成无人引用，11%。这是正当的一天，不能被拒绝。
case("真实的大批 treeclean 不该被拒绝", lambda: (
    lambda r: r[0] == 0 and len(r[2]) == 138
)(run_main({f"app-misc/p{i}": {"1": [f"p{i}.tar.gz"]} for i in range(1086)},
           [f"p{i}.tar.gz" for i in range(1086)] + [f"old{i}.tar.gz" for i in range(138)])))

# 半读的 overlay：引用了一个，镜像上五个，四个变孤儿远超上限
case("孤儿比例过高时拒绝清理", lambda: (
    lambda r: r[0] == 1 and len(r[1]) == 5 and r[2] == []
)(run_main({"app-misc/a": {"1": ["a.tar.gz"]}},
           ["a.tar.gz", "b.tar.xz", "c.zip", "d.tar.bz2", "e.crate"])))

# 正常的一轮：一次 bump 留下一个旧档，比例在上限内，回收而不是删掉
case("正常比例下回收而不是直接删", lambda: (
    lambda r: r[0] == 0 and "old.tar.gz" not in r[1] and r[2] == ["old.tar.gz"]
)(run_main({f"app-misc/p{i}": {"1": [f"p{i}.tar.gz"]} for i in range(20)},
           [f"p{i}.tar.gz" for i in range(20)] + ["old.tar.gz"])))

# layout.conf 是 portage 的目录布局标记，不是 distfile，任何时候都不能动
case("layout.conf 不算孤儿", lambda: (
    lambda r: "layout.conf" in r[1]
)(run_main({f"app-misc/p{i}": {"1": [f"p{i}.tar.gz"]} for i in range(20)},
           [f"p{i}.tar.gz" for i in range(20)] + ["layout.conf"])))




# 回收桶里的文件不能因为原文件很旧就当场消失。上一版用 mtime 判到期，而
# rename 保留原 mtime，distfile 的 mtime 是它被抓下来的时间——在镜像上待过两周
# 的文件，回收的同一轮就被扫掉了，等于没有回收窗口。
case("原文件很旧时回收仍然留得住", lambda: (
    lambda r: r[0] == 0 and r[2] == ["old.tar.gz"]
)(run_main({f"app-misc/p{i}": {"1": [f"p{i}.tar.gz"]} for i in range(20)},
           [f"p{i}.tar.gz" for i in range(20)] + ["old.tar.gz"],
           aged={"old.tar.gz": 90 * 86400})))

# 回收桶里已经有同名的一份时不能覆盖：桶里那份是更早回收的，也就是更可能
# 有人要回头找的
case("同名不覆盖回收桶里已有的", lambda: (
    lambda r: sorted(r[2]) == ["dup.tar.gz", "dup.tar.gz.1"]
)(run_main({f"app-misc/p{i}": {"1": [f"p{i}.tar.gz"]} for i in range(20)},
           [f"p{i}.tar.gz" for i in range(20)] + ["dup.tar.gz"],
           preload={"dup.tar.gz": "早先回收的那一份"})))

# 回收不成不能算清理成功，否则清理永远失效而退出码一直是 0
case("回收失败要反映在退出码上", lambda: (
    lambda r: r[0] == 1
)(run_main({f"app-misc/p{i}": {"1": [f"p{i}.tar.gz"]} for i in range(20)},
           [f"p{i}.tar.gz" for i in range(20)] + ["old.tar.gz"],
           bin_readonly=True)))

# overlay 一个 Manifest 都读不到那一支，要在比例闸门够不着的地方测：镜像上
# 只有 MARKERS 时孤儿数是 0，比例是 0%，闸门放行，只有这一支能拦住它。
# 否则把那一支整个删掉，用例照样全过——比例闸门顺手替它接住了。
case("空 overlay 那一支单独成立", lambda: (
    lambda r: r[0] == 1
)(run_main({}, ["layout.conf"])))

# README.txt 只有 MARKERS 一道防线，layout.conf 有两道
case("README.txt 不算孤儿", lambda: (
    lambda r: "README.txt" in r[1]
)(run_main({f"app-misc/p{i}": {"1": [f"p{i}.tar.gz"]} for i in range(20)},
           [f"p{i}.tar.gz" for i in range(20)] + ["README.txt"])))

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
