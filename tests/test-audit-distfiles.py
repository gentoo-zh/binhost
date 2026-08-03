#!/usr/bin/env python3

import importlib.util
import json
import contextlib
import io
import os
import pathlib
import sys
import tempfile
import time

TARGET = pathlib.Path(__file__).resolve().parent.parent / "deploy" / "audit-distfiles.py"
if not TARGET.exists():
    print(f"  跳过：{TARGET} 不存在，本机没有完整仓库")
    sys.exit(0)

spec = importlib.util.spec_from_file_location("audit_distfiles", TARGET)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def reap(orphans, files, seen=None, grace=audit.GRACE_SECONDS):
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
        old_state, old_bin, old_led = audit.STATE, audit.RECYCLE, audit.LEDGER
        audit.STATE = str(state)
        audit.RECYCLE = str(d / "recycle")
        audit.LEDGER = str(d / "reaped.json")
        try:
            deleted, _failed = audit.reap(set(orphans), paths, grace=grace)
        finally:
            audit.STATE, audit.RECYCLE, audit.LEDGER = old_state, old_bin, old_led
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

case("超过回收期之后才会删除", lambda: (
    lambda r: r[0] == ["a.tar.gz"] and r[1] == []
)(reap(["a.tar.gz"], {"a.tar.gz": "x"}, seen={"a.tar.gz": OLD})))

case("不是孤儿的一个都不碰", lambda: (
    lambda r: r[0] == [] and r[1] == ["a.tar.gz", "b.tar.gz"]
)(reap([], {"a.tar.gz": "x", "b.tar.gz": "y"}, seen={"a.tar.gz": OLD})))

case("又被引用了就从状态里忘掉", lambda: (
    "a.tar.gz" not in reap([], {"a.tar.gz": "x"}, seen={"a.tar.gz": OLD})[2]))

case("删除之后状态里不再保留它", lambda: (
    "a.tar.gz" not in reap(["a.tar.gz"], {"a.tar.gz": "x"}, seen={"a.tar.gz": OLD})[2]))

case("文件名带方括号也能移除", lambda: (
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




def build_overlay(root, packages, src_style="url"):
    root = pathlib.Path(root)
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    (root / "profiles" / "repo_name").write_text("gentoo-zh\n")
    for cp, versions in packages.items():
        d = root / cp
        d.mkdir(parents=True, exist_ok=True)
        dists = set()
        for ver, spec in versions.items():
            files, restrict = spec if isinstance(spec, tuple) else (spec, "")
            body = 'EAPI=8\nSLOT="0"\n'
            if src_style == "bare":
                body += 'SRC_URI="' + " ".join(files) + '"\n'
            elif src_style != "none":
                body += 'SRC_URI="' + " ".join(f"https://example.invalid/{f}"
                                               for f in files) + '"\n'
            if restrict:
                body += f'RESTRICT="{restrict}"\n'
            (d / f"{d.name}-{ver}.ebuild").write_text(body)
            dists.update(files)
        (d / "Manifest").write_text(
            "".join(f"DIST {f} 1 BLAKE2B x SHA512 y\n" for f in sorted(dists)))
    return root


def text_aux(overlay):
    """Read SRC_URI and RESTRICT straight from the fixture ebuilds.

    The fixtures write literal values, so no expansion is needed; this keeps
    the tests on the same attribution path without registering a Portage repo.
    """
    import re as _re

    def aux(cp):
        d = pathlib.Path(overlay) / cp
        for eb in sorted(d.glob("*.ebuild")):
            text = eb.read_text()
            def field(name):
                m = _re.search(rf'^{name}="([^"]*)"', text, _re.M)
                return m.group(1) if m else ""
            yield f"{cp}-{eb.stem.split('-')[-1]}", field("SRC_URI"), field("RESTRICT")
    return aux


def run_main(packages, on_mirror, aged=None, preload=None, bin_readonly=False,
             grace=0, src_style="url"):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        ov = build_overlay(d / "overlay", packages, src_style)
        dist = d / "dist" / "ab"
        dist.mkdir(parents=True)
        for name in on_mirror:
            (dist / name).write_text("x")
        now = int(time.time())
        for name, age in (aged or {}).items():
            os.utime(dist / name, (now - age, now - age))
        old = (audit.STATE, audit.RECYCLE, audit.GRACE_SECONDS, audit.LEDGER)
        audit.STATE = str(d / "state.json")
        audit.RECYCLE = str(d / "recycle")
        audit.GRACE_SECONDS = grace
        audit.LEDGER = str(d / "reaped.json")
        if preload:
            (d / "recycle").mkdir(parents=True, exist_ok=True)
            for name, content in preload.items():
                (d / "recycle" / name).write_text(content)
        if bin_readonly:
            blocked = d / "blocked"
            blocked.write_text("不是目录")
            audit.RECYCLE = str(blocked / "recycle")
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = audit.main(str(ov), str(d / "dist"), aux=text_aux(ov))
        finally:
            audit.STATE, audit.RECYCLE, audit.GRACE_SECONDS, audit.LEDGER = old
        left = sorted(p.name for p in dist.iterdir())
        binned = sorted(p.name for p in (d / "recycle").iterdir()) \
            if (d / "recycle").is_dir() else []
        return rc, left, binned, buf.getvalue()


case("overlay 无法读取内容时拒绝清理", lambda: (
    lambda r: r[0] == 1 and len(r[1]) == 5 and r[2] == []
)(run_main({}, ["a.tar.gz", "b.tar.xz", "c.zip", "d.tar.bz2", "e.crate"])))

case("真实的大批 treeclean 不该被拒绝", lambda: (
    lambda r: r[0] == 0 and len(r[2]) == 138
)(run_main({f"app-misc/p{i}": {"1": [f"p{i}.tar.gz"]} for i in range(1086)},
           [f"p{i}.tar.gz" for i in range(1086)] + [f"old{i}.tar.gz" for i in range(138)])))

case("孤儿比例过高时拒绝清理", lambda: (
    lambda r: r[0] == 1 and len(r[1]) == 5 and r[2] == []
)(run_main({"app-misc/a": {"1": ["a.tar.gz"]}},
           ["a.tar.gz", "b.tar.xz", "c.zip", "d.tar.bz2", "e.crate"])))

case("正常比例下移入回收目录，而非就地删除", lambda: (
    lambda r: r[0] == 0 and "old.tar.gz" not in r[1] and r[2] == ["old.tar.gz"]
)(run_main({f"app-misc/p{i}": {"1": [f"p{i}.tar.gz"]} for i in range(20)},
           [f"p{i}.tar.gz" for i in range(20)] + ["old.tar.gz"])))

case("layout.conf 不算孤儿", lambda: (
    lambda r: "layout.conf" in r[1]
)(run_main({f"app-misc/p{i}": {"1": [f"p{i}.tar.gz"]} for i in range(20)},
           [f"p{i}.tar.gz" for i in range(20)] + ["layout.conf"])))




case("原文件很旧时回收仍然留得住", lambda: (
    lambda r: r[0] == 0 and r[2] == ["old.tar.gz"]
)(run_main({f"app-misc/p{i}": {"1": [f"p{i}.tar.gz"]} for i in range(20)},
           [f"p{i}.tar.gz" for i in range(20)] + ["old.tar.gz"],
           aged={"old.tar.gz": 90 * 86400})))

case("同名不覆盖回收桶里已有的", lambda: (
    lambda r: sorted(r[2]) == ["dup.tar.gz", "dup.tar.gz.1"]
)(run_main({f"app-misc/p{i}": {"1": [f"p{i}.tar.gz"]} for i in range(20)},
           [f"p{i}.tar.gz" for i in range(20)] + ["dup.tar.gz"],
           preload={"dup.tar.gz": "早先回收的那一份"})))

case("回收失败要反映在退出码上", lambda: (
    lambda r: r[0] == 1
)(run_main({f"app-misc/p{i}": {"1": [f"p{i}.tar.gz"]} for i in range(20)},
           [f"p{i}.tar.gz" for i in range(20)] + ["old.tar.gz"],
           bin_readonly=True)))

case("空 overlay 那一支单独成立", lambda: (
    lambda r: r[0] == 1
)(run_main({}, ["layout.conf"])))

case("README.txt 不算孤儿", lambda: (
    lambda r: "README.txt" in r[1]
)(run_main({f"app-misc/p{i}": {"1": [f"p{i}.tar.gz"]} for i in range(20)},
           [f"p{i}.tar.gz" for i in range(20)] + ["README.txt"])))

print(f"  {'用例':<44} 结果")
bad = 0

case("没有 RESTRICT 就不动它", lambda: (
    lambda r: r[0] == 0 and r[1] == ["foo-1.0.tar.gz"] and r[2] == []
)(run_main({"app-misc/foo": {"1.0": ["foo-1.0.tar.gz"]}}, ["foo-1.0.tar.gz"])))

case("禁止镜像的文件会被回收", lambda: (
    lambda r: r[1] == [] and r[2] == ["foo-1.0.tar.gz"]
)(run_main({"app-misc/foo": {"1.0": (["foo-1.0.tar.gz"], "mirror")}},
           ["foo-1.0.tar.gz"])))

case("已回收的文件不应导致本次稽核失败", lambda: (
    lambda r: r[0] == 0
)(run_main({"app-misc/foo": {"1.0": (["foo-1.0.tar.gz"], "mirror")}},
           ["foo-1.0.tar.gz"])))

case("移入回收目录，而非就地删除", lambda: (
    lambda r: r[2] == ["foo-1.0.tar.gz"]
)(run_main({"app-misc/foo": {"1.0": (["foo-1.0.tar.gz"], "bindist mirror strip")}},
           ["foo-1.0.tar.gz"])))

case("按版本归属，未受限的那个保留", lambda: (
    lambda r: r[1] == ["foo-2.0.tar.gz"] and r[2] == ["foo-1.0.tar.gz"]
)(run_main({"app-misc/foo": {"1.0": (["foo-1.0.tar.gz"], "mirror"),
                             "2.0": ["foo-2.0.tar.gz"]}},
           ["foo-1.0.tar.gz", "foo-2.0.tar.gz"])))

case("文件名没有版本号时从严", lambda: (
    lambda r: r[1] == [] and r[2] == ["shared.tar.gz"]
)(run_main({"app-misc/foo": {"1.0": (["shared.tar.gz"], "mirror"),
                             "2.0": ["shared.tar.gz"]}}, ["shared.tar.gz"])))

case("禁止镜像的不等宽限期，孤儿等", lambda: (
    lambda r: "orphan.tar.gz" in r[1] and r[2] == ["banned.tar.gz"]
)(run_main({"app-misc/foo": {"1.0": (["banned.tar.gz"], "mirror")},
            "app-misc/bar": {"1.0": [f"bar-{i}.tar.gz" for i in range(8)]}},
           ["banned.tar.gz", "orphan.tar.gz"] + [f"bar-{i}.tar.gz" for i in range(8)],
           grace=7 * 24 * 3600)))

case("禁止镜像的比例过高时不清", lambda: (
    lambda r: r[0] == 1 and r[2] == []
)(run_main({"app-misc/foo": {"1.0": ([f"x-{i}.tar.gz" for i in range(30)], "mirror")}},
           [f"x-{i}.tar.gz" for i in range(30)])))


def _budget_rounds():
    import tempfile as _t, pathlib as _p
    d = _p.Path(_t.mkdtemp())
    old = (audit.LEDGER, audit.STATE, audit.RECYCLE, audit.GRACE_SECONDS)
    audit.LEDGER = str(d / "reaped.json")
    audit.RECYCLE = str(d / "recycle")
    audit.GRACE_SECONDS = 0
    files = d / "f"
    files.mkdir()
    have, got = 300, []
    cap = int(have * audit.MAX_REAP_SHARE)
    try:
        for r in (1, 2, 3):
            budget = max(0, cap - audit.recent_deletions(0))
            orph = [f"x{r}-{i}.tar.gz" for i in range(90)]
            paths = {}
            for f in orph:
                (files / f).write_text("x")
                paths[f] = files / f
            audit.STATE = str(d / f"s{r}.json")
            deleted, _ = audit.reap(orph, paths, budget=budget)
            audit.recent_deletions(len(deleted))
            got.append(len(deleted))
    finally:
        audit.LEDGER, audit.STATE, audit.RECYCLE, audit.GRACE_SECONDS = old
    return got, cap


case("累计额度在删除之前就生效", lambda: (
    lambda r: sum(r[0]) <= r[1])(_budget_rounds()))

case("额度耗尽后不再删除", lambda: (
    lambda r: r[0][-1] == 0)(_budget_rounds()))

def _fetch_probe():
    import tempfile as _t, pathlib as _p
    with _t.TemporaryDirectory() as tmp:
        ov = _p.Path(tmp)
        (ov / "profiles").mkdir(parents=True)
        (ov / "profiles" / "repo_name").write_text("gentoo-zh\n")
        (ov / "profiles" / "package.mask").write_text("")
        d = ov / "app-misc" / "b"
        d.mkdir(parents=True)
        (d / "b-1.0.ebuild").write_text(
            'EAPI=8\nSLOT="0"\nSRC_URI="https://x/b-1.0.tar.gz"\n'
            'RESTRICT="fetch"\n')
        (d / "b-2.0.ebuild").write_text(
            'EAPI=8\nSLOT="0"\nSRC_URI="https://x/b-2.0.tar.gz"\n')
        (d / "Manifest").write_text(
            "DIST b-1.0.tar.gz 1 BLAKE2B x SHA512 y\n"
            "DIST b-2.0.tar.gz 1 BLAKE2B x SHA512 y\n")
        dist = _p.Path(tmp) / "dist" / "ab"
        dist.mkdir(parents=True)
        old = (audit.STATE, audit.RECYCLE, audit.LEDGER, audit.GRACE_SECONDS)
        audit.STATE = str(ov / "s.json"); audit.RECYCLE = str(ov / "rec")
        audit.LEDGER = str(ov / "l.json"); audit.GRACE_SECONDS = 0
        import io, contextlib
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                audit.main(str(ov), str(_p.Path(tmp) / "dist"), aux=text_aux(ov))
        finally:
            audit.STATE, audit.RECYCLE, audit.LEDGER, audit.GRACE_SECONDS = old
        return buf.getvalue()


case("fetch 限制不跨版本传染", lambda: (
    lambda r: "b-2.0.tar.gz" in r
)(_fetch_probe()))

case("带 fetch 的那个版本自己算无法获取", lambda: (
    lambda r: "b-1.0.tar.gz" not in r
)(_fetch_probe()))

def scan_with(pkgs):
    """pkgs: {cp: [(cpv, SRC_URI, RESTRICT)]}; the Manifest is derived from SRC_URI."""
    with tempfile.TemporaryDirectory() as tmp:
        ov = pathlib.Path(tmp)
        (ov / "profiles").mkdir(parents=True)
        (ov / "profiles" / "repo_name").write_text("gentoo-zh\n")
        for cp, rows in pkgs.items():
            d = ov / cp
            d.mkdir(parents=True, exist_ok=True)
            names = set()
            for _, src, _ in rows:
                if src:
                    names |= audit.distfiles_of(src) or set()
            (d / "Manifest").write_text(
                "".join(f"DIST {n} 1 BLAKE2B x SHA512 y\n" for n in sorted(names)))

        def aux(cp):
            yield from pkgs[cp]
        return audit.scan(ov, aux)


case("SRC_URI 的改名形式按改名后的文件归属", lambda: (
    (lambda r: set(r[0]) == {"pkg-1.tar.gz"} and not r[1])(
        scan_with({"app-misc/pkg": [
            ("app-misc/pkg-1", "https://x/v1.tar.gz -> pkg-1.tar.gz", "")]}))))

case("条件式里的文件也算被引用", lambda: (
    set(scan_with({"app-misc/pkg": [
        ("app-misc/pkg-1", "https://x/a.tar nls? ( https://x/b.tar )", "")]})[0])
    == {"a.tar", "b.tar"}))

case("无版本号的文件名同样归属正确", lambda: (
    set(scan_with({"app-misc/pkg": [
        ("app-misc/pkg-1", "https://x/noversion.zip", "")]})[0])
    == {"noversion.zip"}))


def scan_with_manifest(pkgs, manifests):
    with tempfile.TemporaryDirectory() as tmp:
        ov = pathlib.Path(tmp)
        (ov / "profiles").mkdir(parents=True)
        (ov / "profiles" / "repo_name").write_text("gentoo-zh\n")
        for cp, names in manifests.items():
            d = ov / cp
            d.mkdir(parents=True, exist_ok=True)
            (d / "Manifest").write_text(
                "".join(f"DIST {n} 1 BLAKE2B x SHA512 y\n" for n in names))

        def aux(cp):
            yield from pkgs[cp]
        return audit.scan(ov, aux)


case("裸文件名按 SRC_URI 归属，不落入不确定", lambda: (
    (lambda r: r[0]["manual.zip"] == [("app-misc/m", False)] and not r[1])(
        scan_with_manifest({"app-misc/m": [("app-misc/m-1", "manual.zip", "")]},
                           {"app-misc/m": ["manual.zip"]}))))

case("metadata 无法读取时归入不确定，且仍记为受限", lambda: (
    (lambda r: r[1] == {"z.tar"} and r[0]["z.tar"] == [("app-misc/z", True)])(
        scan_with_manifest({"app-misc/z": [("app-misc/z-1", None, None)]},
                           {"app-misc/z": ["z.tar"]}))))

case("SRC_URI 为空时同样归入不确定", lambda: (
    (lambda r: r[1] == {"y.tar"} and r[0]["y.tar"] == [("app-misc/y", True)])(
        scan_with_manifest({"app-misc/y": [("app-misc/y-1", "", "")]},
                           {"app-misc/y": ["y.tar"]}))))

case("裸文件名的 SRC_URI 也能归属，不会当成无人引用而回收", lambda: (
    lambda r: "manual.zip" in r[1] and r[2] == []
)(run_main({**{f"app-misc/f{i}": {"1.0": [f"f{i}.tar.gz"]} for i in range(9)}, "app-misc/m": {"1.0": ["manual.zip"]}},
           ["manual.zip"] + [f"f{i}.tar.gz" for i in range(9)],
           aged={"manual.zip": 10 ** 7}, src_style="bare")))

case("ebuild 没有 SRC_URI 时归入不确定，超过宽限期也不删", lambda: (
    lambda r: "mystery.tar.gz" in r[1] and r[2] == []
)(run_main({"app-misc/m": {"1.0": ["mystery.tar.gz"]}},
           ["mystery.tar.gz"] + [f"f{i}.tar.gz" for i in range(9)],
           aged={"mystery.tar.gz": 10 ** 7}, src_style="none")))

case("共用文件有一方禁止镜像时，已在镜像上的要下架", lambda: (
    lambda r: r[2] == ["s.tar"]
)(run_main({"app-misc/a": {"1.0": ["s.tar"]},
            "app-misc/b": {"1.0": (["s.tar"], "mirror")}}, ["s.tar"],
           aged={"s.tar": 10 ** 7})))

case("共用文件有一方禁止镜像时，也不该报成缺失", lambda: (
    lambda r: "缺 0" in r[3]
)(run_main({"app-misc/a": {"1.0": ["s.tar"]},
            "app-misc/b": {"1.0": (["s.tar"], "mirror")}}, [])))

for name, fn in CASES:
    try:
        ok = bool(fn())
    except Exception as e:                                  # noqa: BLE001
        ok, name = False, f"{name}（抛异常 {type(e).__name__}: {e}）"
    print(f"  {'✓' if ok else '✗'} {name}")
    bad += not ok

sys.exit(1 if bad else 0)
