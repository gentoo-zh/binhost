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
        old_state = audit.STATE
        audit.STATE = str(state)
        try:
            deleted = audit.reap(set(orphans), paths, grace=grace)
        finally:
            audit.STATE = old_state
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
