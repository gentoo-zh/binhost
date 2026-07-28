#!/usr/bin/env python3
"""Cases for audit-distfiles.py's reap.

This is the only code in the repository that deletes distfiles, and distfiles
cannot be fetched again once upstream drops a release. It had no test at all.
"""

import importlib.util
import json
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
            deleted = audit.reap(set(orphans), paths, grace=grace)
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


def run_main(packages, on_mirror):
    """跑完整的 main()，回传 (退出码, 镜像上剩下的文件, 回收目录里的文件)。"""
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        ov = build_overlay(d / "overlay", packages)
        dist = d / "dist" / "ab"
        dist.mkdir(parents=True)
        for name in on_mirror:
            (dist / name).write_text("x")
        old = (audit.STATE, audit.RECYCLE, audit.GRACE_SECONDS)
        audit.STATE = str(d / "state.json")
        audit.RECYCLE = str(d / "recycle")
        audit.GRACE_SECONDS = 0          # 立即到期，好在一轮里看到结果
        try:
            rc = audit.main(str(ov), str(d / "dist"))
        finally:
            audit.STATE, audit.RECYCLE, audit.GRACE_SECONDS = old
        left = sorted(p.name for p in dist.iterdir())
        binned = sorted(p.name for p in (d / "recycle").iterdir()) \
            if (d / "recycle").is_dir() else []
        return rc, left, binned


def sweep_case():
    """回收目录里放一新一旧，跑一次 sweep，回传清掉几个。"""
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp) / "recycle"
        d.mkdir()
        old_file, new_file = d / "old.tar.gz", d / "new.tar.gz"
        old_file.write_text("x")
        new_file.write_text("x")
        now = int(time.time())
        import os
        os.utime(old_file, (now - audit.RECYCLE_SECONDS - 1,) * 2)
        os.utime(new_file, (now, now))
        prev = audit.RECYCLE
        audit.RECYCLE = str(d)
        try:
            gone = audit.sweep_recycle(now=now)
        finally:
            audit.RECYCLE = prev
        return gone if new_file.exists() and not old_file.exists() else -1


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

# 回收目录里过了保留期的才清掉，没过的留着
case("回收目录按保留期清理", lambda: (
    lambda got: got == 1
)(sweep_case()))


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
