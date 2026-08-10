#!/usr/bin/env python3

import importlib.util
import json
import os
import pathlib
import sys
import tempfile

BUILD = pathlib.Path(__file__).resolve().parent.parent / "build"

HEADER = "ACCEPT_KEYWORDS: ~amd64\nPACKAGES: 9\nTIMESTAMP: 1\nVERSION: 0"


def stanza(cpv, repo, slot="0"):
    cp = cpv.rsplit("-", 1)[0]
    return (f"CPV: {cpv}\nPATH: {cp}/{cpv.split('/')[-1]}.gpkg.tar\n"
            f"REPO: {repo}\nSLOT: {slot}")


def fresh(d, index_text=None, index_path=None, list_lines=(), distfiles=None):
    """gen-packages reads its paths at import, so each case needs its own."""
    if index_text is not None:
        (d / "Packages").write_text(HEADER + "\n\n" + index_text + "\n")
    os.environ["INDEX"] = index_path or str(d / "Packages")
    os.environ["OUT"] = str(d / "packages.json")
    (d / "list.txt").write_text("\n".join(list_lines) + ("\n" if list_lines else ""))
    os.environ["LIST"] = str(d / "list.txt")
    os.environ["EXCLUDED"] = str(BUILD / "excluded.txt")
    dist_index = d / "distfiles-index.json"
    if distfiles is not None:
        dist_index.write_text(json.dumps({"generated": 1, "files": distfiles}))
    os.environ["DIST_INDEX"] = str(dist_index)
    spec = importlib.util.spec_from_file_location(
        "gen_packages", BUILD / "gen-packages.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load(index_text):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        old = dict(os.environ)
        try:
            return fresh(d, index_text).read_deps()
        finally:
            os.environ.clear()
            os.environ.update(old)


def classify(cp, body=None):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        old = dict(os.environ)
        try:
            module = fresh(d, "")
            masked = type("Visible", (), {"masks": lambda *_args: False})()
            text = body or 'EAPI=8\ninherit cmake\nKEYWORDS="~amd64"\n'
            return module.why_not_listed(cp, "1", text, masked)
        finally:
            os.environ.clear()
            os.environ.update(old)


def run_main(index_text, overlay=None, index_path=None, list_lines=(), distfiles=None,
             policies=None, channel_excluded=()):
    """The whole generator, so the json and the two text files are covered."""
    import contextlib, io
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        ov = pathlib.Path(overlay or (d / "overlay"))
        if overlay is None:
            (ov / "profiles").mkdir(parents=True)
            (ov / "profiles" / "repo_name").write_text("gentoo-zh\n")
        old = dict(os.environ)
        try:
            if channel_excluded:
                channel_file = d / "channel-excluded.txt"
                channel_file.write_text("\n".join(
                    f"{cp}\ttest boundary" for cp in channel_excluded) + "\n")
                os.environ["CHANNEL_EXCLUDED"] = str(channel_file)
            else:
                os.environ.pop("CHANNEL_EXCLUDED", None)
            m = fresh(d, index_text, index_path, list_lines, distfiles)
            policies = policies or {}

            def policy_lookup(cpv):
                parts = m.catpkgsplit(cpv)
                cp = f"{parts[0]}/{parts[1]}" if parts else cpv
                return policies.get(cp, "")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = m.main(str(ov), policy_lookup=policy_lookup)
        finally:
            os.environ.clear()
            os.environ.update(old)
        data = json.loads((d / "packages.json").read_text()) \
            if (d / "packages.json").exists() else None
        deps_txt = (d / "deps.txt").read_text() if (d / "deps.txt").exists() else None
        pkgs_txt = (d / "packages.txt").read_text() if (d / "packages.txt").exists() else None
        return rc, data, deps_txt, pkgs_txt, buf.getvalue()


def make_overlay(root, packages):
    root = pathlib.Path(root)
    (root / "profiles").mkdir(parents=True)
    (root / "profiles" / "repo_name").write_text("gentoo-zh\n")
    for cp, spec in packages.items():
        pkgdir = root / cp
        pkgdir.mkdir(parents=True)
        ver = spec.get("ver", "1")
        body = spec.get(
            "body", 'EAPI=8\ninherit cmake\nKEYWORDS="~amd64"\nSLOT="0"\n')
        (pkgdir / f"{pkgdir.name}-{ver}.ebuild").write_text(body)
        files = spec.get("dist", [])
        (pkgdir / "Manifest").write_text(
            "".join(f"DIST {name} 1 BLAKE2B x SHA512 y\n" for name in files))
    return root


def availability_matrix():
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        overlay = make_overlay(d / "overlay", {
            "app-misc/both": {"dist": ["both.tar"]},
            "app-misc/bin-only": {},
            "app-misc/src-only": {"dist": ["src.tar"]},
            "app-misc/live-only": {
                "ver": "9999",
                "body": 'EAPI=8\ninherit git-r3 cmake\nKEYWORDS="~amd64"\nSLOT="0"\n',
            },
            "virtual/neither": {},
            "app-misc/repo-collision": {},
        })
        index = "\n\n".join([
            stanza("app-misc/both-1", "gentoo-zh"),
            stanza("app-misc/bin-only-1", "gentoo-zh"),
            stanza("app-misc/repo-collision-9", "gentoo"),
            stanza("app-misc/removed-1", "gentoo-zh"),
        ])
        result = run_main(
            index, overlay=overlay,
            list_lines=("app-misc/both", "app-misc/bin-only"),
            distfiles=("both.tar", "src.tar"))
        rows = {row["cp"]: row for row in result[1]["packages"]}
        statuses = {
            line.split()[0]: line.split()[1]
            for line in result[3].splitlines()
            if line and not line.startswith("#")
        }
        return result, rows, statuses


def policy_matrix():
    with tempfile.TemporaryDirectory() as tmp:
        overlay = make_overlay(pathlib.Path(tmp) / "overlay", {
            "app-misc/example": {
                "body": 'EAPI=8\ninherit unpacker\nKEYWORDS="~amd64"\n'
            }
        })
        result = run_main(
            "", overlay=overlay, policies={"app-misc/example": "license"})
        return next(row for row in result[1]["packages"]
                    if row["cp"] == "app-misc/example")


def channel_exclusion_matrix():
    with tempfile.TemporaryDirectory() as tmp:
        overlay = make_overlay(pathlib.Path(tmp) / "overlay", {
            "app-misc/example": {},
        })
        stable = run_main(
            "", overlay=overlay, list_lines=("app-misc/example",))
        unstable = run_main(
            "", overlay=overlay, list_lines=("app-misc/example",),
            channel_excluded=("app-misc/example",))
        return stable[1]["packages"][0], unstable[1]["packages"][0]


def missing_policy_tree():
    import contextlib, io
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        overlay = make_overlay(d / "overlay", {"app-misc/example": {}})
        old = dict(os.environ)
        try:
            os.environ["GENTOO_TREE"] = str(d / "missing-gentoo")
            module = fresh(d, "")
            previous = '{"sentinel":"previous"}\n'
            (d / "packages.json").write_text(previous)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                rc = module.main(str(overlay))
            return (rc == 1 and (d / "packages.json").exists()
                    and (d / "packages.json").read_text() == previous
                    and "gentoo repository does not exist" in buf.getvalue())
        finally:
            os.environ.clear()
            os.environ.update(old)


CASES = []


def case(name, fn):
    CASES.append((name, fn))


case("只收 ::gentoo 的产物，本仓库的不算", lambda: (
    [(d["cp"], d["ver"]) for d in load("\n\n".join([
        stanza("app-misc/a-1", "gentoo-zh"), stanza("dev-libs/lib-1", "gentoo")]))]
    == [("dev-libs/lib", "1")]))

case("同一个包发布了两个版本时两个都列", lambda: (
    [d["ver"] for d in load("\n\n".join([stanza("dev-libs/lib-1", "gentoo"),
                                          stanza("dev-libs/lib-2", "gentoo")]))]
    == ["1", "2"]))

case("版本按 Portage 规则排序，不按字符串排序", lambda: (
    [d["ver"] for d in load("\n\n".join([stanza("dev-libs/lib-1.10", "gentoo"),
                                            stanza("dev-libs/lib-1.9", "gentoo")]))]
    == ["1.9", "1.10"]))

case("同一个包的两个 slot 都列，并标出 slot", lambda: (
    [(d["slot"], d["ver"]) for d in load("\n\n".join([
        stanza("dev-libs/lib-1", "gentoo", slot="1"),
        stanza("dev-libs/lib-2", "gentoo", slot="2")]))]
    == [("1", "1"), ("2", "2")]))

case("sub-slot 只取主 slot", lambda: (
    load(stanza("net-libs/webkit-gtk-2.52.5-r410", "gentoo", slot="4.1/0"))[0]["slot"]
    == "4.1"))

case("r0 不写进版本号", lambda: (
    load(stanza("dev-libs/lib-1.2-r0", "gentoo"))[0]["ver"] == "1.2"))

case("非 r0 的 revision 要写出来", lambda: (
    load(stanza("dev-libs/lib-1.2-r3", "gentoo"))[0]["ver"] == "1.2-r3"))

case("按包名排序", lambda: (
    [d["cp"] for d in load("\n\n".join([stanza("z-misc/z-1", "gentoo"),
                                        stanza("a-misc/a-1", "gentoo")]))]
    == ["a-misc/a", "z-misc/z"]))

case("索引中不含 ::gentoo 的产物时给出空清单", lambda: (
    load(stanza("app-misc/a-1", "gentoo-zh")) == []))

case("未知仓库的产物不静默归入 ::gentoo，全部中止", lambda: (
    (lambda r: r[0] == 1 and r[1] is None and "未知仓库" in r[4])(
        run_main(stanza("app-misc/a-1", "some-other-overlay")))))

case("已设定的索引无法读取时中止，不覆写上一份输出", lambda: (
    (lambda r: r[0] == 1 and r[1] is None and "不存在" in r[4])(
        run_main("", index_path="/nonexistent/Packages"))))

case("写出 schema 版本，供页面判断数据是否够新", lambda: (
    run_main(stanza("dev-libs/lib-1", "gentoo"))[1]["schema"] == 4))

case("acct 与 virtual 归为本地安装", lambda: (
    classify("acct-group/example") == "meta"
    and classify("acct-user/example") == "meta"
    and classify("virtual/example") == "meta"))

case("virtual 不因 keyword 或 bindist 改变本地安装分类", lambda: (
    classify("virtual/example",
             'EAPI=8\nKEYWORDS="~arm64"\nRESTRICT="bindist"\n') == "meta"))

case("发布政策与构建清单分类分别写入", lambda: (
    (lambda r: r["binhost"] is False and r["policy"] == "license"
     and r["why"] == "prebuilt")(policy_matrix())))

case("频道排除只影响指定频道的构建状态", lambda: (
    (lambda stable, unstable:
     stable["binhost"] is True and "channelExcluded" not in stable
     and unstable["binhost"] is False
     and unstable["channelExcluded"] is True
     and "why" not in unstable)(*channel_exclusion_matrix())))


def resolved_policy(restrict="", missing=(), iuse="", cpv="app-misc/example-1"):
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        old = dict(os.environ)
        try:
            module = fresh(d, "")

            class Settings:
                def _getMissingLicenses(self, _cpv, metadata):
                    self.metadata = metadata
                    return list(missing)

            settings = Settings()

            class Database:
                def __init__(self):
                    self.settings = settings

                def aux_get(self, _cpv, names, myrepo=None):
                    values = {"LICENSE": "TEST", "SLOT": "0", "IUSE": iuse,
                              "RESTRICT": restrict}
                    return [values[name] for name in names]

            module.pinned_portdbapi = lambda *_args, **_kwargs: Database()
            state = module.publication_policy("/overlay", "/tree")(
                cpv)
            return state, getattr(settings, "metadata", None)
        finally:
            os.environ.clear()
            os.environ.update(old)


case("Portage 发布政策分别识别 bindist 与许可证拒绝", lambda: (
    resolved_policy(restrict="mirror bindist")[0] == "bindist"
    and resolved_policy(missing=("TEST",))[0] == "license"
    and resolved_policy()[0] == ""))

case("本地安装类别写入明确的发布政策", lambda: (
    resolved_policy(cpv="acct-group/example-1")[0] == "meta"
    and resolved_policy(cpv="acct-user/example-1")[0] == "meta"
    and resolved_policy(cpv="virtual/example-1")[0] == "meta"
    and resolved_policy(cpv="app-alternatives/example-1")[0] == ""))

case("本地安装类别仍优先显示 bindist 与许可证限制", lambda: (
    resolved_policy(restrict="bindist", cpv="virtual/example-1")[0] == "bindist"
    and resolved_policy(missing=("TEST",), cpv="virtual/example-1")[0] == "license"))

case("许可证政策按 ebuild 默认 USE 判定", lambda: (
    resolved_policy(iuse="+ssl minimal")[1]["USE"] == "ssl"))

case("Gentoo 主树缺失时中止且不写出降级结果", missing_policy_tree)

case("app-alternatives 不冒充本地安装类别", lambda: (
    classify("app-alternatives/example") == "candidate"))

case("deps.txt 单独成档，不占用 packages.txt 的状态栏", lambda: (
    (lambda r: "dev-libs/lib" in r[2] and "dev-libs/lib" not in r[3])(
        run_main(stanza("dev-libs/lib-1", "gentoo")))))

case("deps.txt 的说明行都以 # 开头", lambda: (
    all(l.startswith("#") or not l.strip() or l.split()[0].count("/") == 1
        for l in run_main(stanza("dev-libs/lib-1", "gentoo"))[2].splitlines())))

case("binpkg 与 distfiles 四种组合分别写出", lambda: (
    availability_matrix()[2] == {
        "app-misc/bin-only": "bin",
        "app-misc/both": "bin+src",
        "app-misc/live-only": "--",
        "app-misc/repo-collision": "--",
        "app-misc/removed": "bin",
        "app-misc/src-only": "src",
        "virtual/neither": "--",
    }))

case("同名 ::gentoo 依赖不算 overlay binpkg", lambda: (
    "app-misc/repo-collision" not in availability_matrix()[0][4]
    and availability_matrix()[2]["app-misc/repo-collision"] == "--"))

case("overlay 所有包都列出，包括两者都没有的包", lambda: (
    set(availability_matrix()[1]) == {
        "app-misc/bin-only", "app-misc/both", "app-misc/live-only",
        "app-misc/removed",
        "app-misc/repo-collision", "app-misc/src-only", "virtual/neither",
    }))

case("只有 9999 的包仍列出并标明原因", lambda: (
    availability_matrix()[1]["app-misc/live-only"].get("why") == "live"))

case("已删除但尚未退役的公开产物保留过渡状态", lambda: (
    availability_matrix()[1]["app-misc/removed"] == {
        "cp": "app-misc/removed", "binhost": False, "dist": [],
        "present": False, "why": "removed",
    }))

case("包数据与纯文本清单不再写入说明", lambda: (
    all("desc" not in row for row in availability_matrix()[1].values())
    and "DESCRIPTION" not in availability_matrix()[0][3]))

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
