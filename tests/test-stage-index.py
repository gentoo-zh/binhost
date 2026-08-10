#!/usr/bin/env python3

import importlib.util
import pathlib
import re
import sys
import tempfile
import time

BUILD = pathlib.Path(__file__).resolve().parent.parent / "build"

spec = importlib.util.spec_from_file_location(
    "stage_index", BUILD / "stage-index.py")
stage_index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage_index)

HEADER = "ACCEPT_KEYWORDS: ~amd64\nPACKAGES: 999\nTIMESTAMP: 1\nVERSION: 0"
HEADER_WITH_REV = HEADER + '\nREPO_REVISIONS: {}'
OVERLAY_REV = "a" * 40
GENTOO_REV = "b" * 40


def stage_main(*args, **kwargs):
    kwargs.setdefault("rev", OVERLAY_REV)
    kwargs.setdefault("gentoo_rev", GENTOO_REV)
    return stage_index.main(*args, **kwargs)


def digest_of(data):
    import hashlib
    return hashlib.sha1(data).hexdigest()


def md5_of(data):
    import hashlib
    return hashlib.md5(data).hexdigest()


def stanza(cpv, repo="gentoo-zh", build_id=None, restrict=None, PATH=None,
           rdepend=None, depend=None, idepend=None, pdepend=None,
           slot="0", use=None, iuse=None, eapi="8", sha1=None, license=None):
    cp = cpv.rsplit("-", 1)[0]
    path = f"{cp}/{cpv.split('/')[-1]}.gpkg.tar" if PATH is None else PATH
    lines = [f"CPV: {cpv}", f"PATH: {path}", f"REPO: {repo}"]
    if eapi is not None:
        lines.append(f"EAPI: {eapi}")
    if slot is not None:
        lines.append(f"SLOT: {slot}")
    if use:
        lines.append(f"USE: {use}")
    if iuse:
        lines.append(f"IUSE: {iuse}")
    if pdepend:
        lines.append(f"PDEPEND: {pdepend}")
    if build_id is not None:
        lines.append(f"BUILD_ID: {build_id}")
    if restrict:
        lines.append(f"RESTRICT: {restrict}")
    if license:
        lines.append(f"LICENSE: {license}")
    if sha1:
        lines.append(f"SHA1: {sha1}")
    if rdepend:
        lines.append(f"RDEPEND: {rdepend}")
    if depend:
        lines.append(f"DEPEND: {depend}")
    if idepend:
        lines.append(f"IDEPEND: {idepend}")
    return "\n".join(lines)


def fake_lookup(restricts=None):
    """(cpv, repo) -> RESTRICT. None stands for metadata not readable."""
    restricts = restricts or {}

    def get(cpv, repo):
        if (cpv, repo) in restricts:
            return restricts[(cpv, repo)]
        return restricts.get(cpv, "")
    return get


def run(stanzas, overlay_has=None, excluded=frozenset(), masked=(), with_deps=False,
        restricts=None, licenses=None, gentoo_tree=None, seed_packages=None,
        inherited=None):
    old_tree = stage_index.GENTOO_TREE
    stage_index.GENTOO_TREE = gentoo_tree or "/nonexistent/gentoo"
    try:
        _, entries = stage_index.parse(
            HEADER + "\n\n" + "\n\n".join(stanzas) + "\n")
        lookup = fake_lookup(restricts)
        licenses = licenses or {}

        def license_lookup(cpv, fields):
            key = (cpv, fields.get("REPO", ""))
            return licenses.get(key, licenses.get(cpv, "yes"))

        inherit_map = inherited or {}

        def inherit_lookup(cpv, repo):
            return inherit_map.get(cpv, "")

        if overlay_has is None:
            return stage_index.select(
                entries, excluded=excluded, with_deps=with_deps,
                lookup=lookup, license_lookup=license_lookup,
                seed_packages=seed_packages, inherit_lookup=inherit_lookup)
        with tempfile.TemporaryDirectory() as tmp:
            ov = pathlib.Path(tmp)
            for cpv in overlay_has:
                cp = re.match(r"^([a-z0-9-]+/.+?)-[0-9]", cpv).group(1)
                d = ov / cp
                d.mkdir(parents=True, exist_ok=True)
                (d / (cpv.split("/", 1)[1] + ".ebuild")).write_text("EAPI=8\n")
            prof = ov / "profiles"
            prof.mkdir(parents=True, exist_ok=True)
            (prof / "repo_name").write_text("gentoo-zh\n")
            (prof / "package.mask").write_text(
                "".join(f"# masked for removal\n{cp}\n" for cp in masked))
            return stage_index.select(
                entries, ov, excluded=excluded, lookup=lookup,
                license_lookup=license_lookup, with_deps=with_deps,
                seed_packages=seed_packages, inherit_lookup=inherit_lookup)
    finally:
        stage_index.GENTOO_TREE = old_tree


def cpvs(kept):
    return sorted(f["CPV"] for _, f, _ in kept)


CASES = []


def case(name, fn):
    CASES.append((name, fn))


case("本仓库的产物保留", lambda: (
    cpvs(run([stanza("app-misc/a-1")])[0]) == ["app-misc/a-1"]))

case("::gentoo 的产物被过滤", lambda: (
    run([stanza("dev-libs/b-1", repo="gentoo")])[0] == []))

case("混合输入时仅保留本仓库的产物", lambda: (
    cpvs(run([stanza("app-misc/a-1"), stanza("dev-libs/b-1", repo="gentoo")])[0])
    == ["app-misc/a-1"]))

case("RESTRICT=bindist 不进索引", lambda: (
    cpvs(run([stanza("app-misc/a-1", restrict="bindist mirror")])[0]) == []))

case("RESTRICT 为其他值时照常收录", lambda: (
    cpvs(run([stanza("app-misc/a-1", restrict="mirror strip")])[0]) == ["app-misc/a-1"]))


class FakeLicenseSettings:
    def _getMissingLicenses(self, _cpv, metadata):
        if metadata["LICENSE"] == "BROKEN":
            raise ValueError("invalid license expression")
        return [metadata["LICENSE"]] if metadata["LICENSE"] == "NO-REDIST" else []


case("当前许可证可再分发时通过", lambda: (
    stage_index.effective_license(
        "app-misc/a-1", {"LICENSE": "MIT", "SLOT": "0", "REPO": "gentoo-zh"},
        "GPL-2", "0", FakeLicenseSettings()) == "yes"))

case("缓存许可证不参与当前再分发判定", lambda: (
    stage_index.effective_license(
        "app-misc/a-1", {"LICENSE": "NO-REDIST", "SLOT": "0",
                         "REPO": "gentoo-zh"},
        "MIT", "0", FakeLicenseSettings()) == "yes"))

case("当前许可证不可再分发时拒绝旧缓存", lambda: (
    stage_index.effective_license(
        "app-misc/a-1", {"LICENSE": "MIT", "SLOT": "0", "REPO": "gentoo-zh"},
        "NO-REDIST", "0", FakeLicenseSettings()) == "no"))

case("空许可证按 Portage 的许可证集合判定", lambda: (
    stage_index.effective_license(
        "app-misc/a-1", {"SLOT": "0", "REPO": "gentoo-zh"},
        "", "0", FakeLicenseSettings()) == "yes"))

case("许可证表达式无法判定时不默认放行", lambda: (
    stage_index.effective_license(
        "app-misc/a-1", {"LICENSE": "MIT", "SLOT": "0", "REPO": "gentoo-zh"},
        "BROKEN", "0", FakeLicenseSettings()) == "unknown"))


def host_license_override(kind):
    from portage.package.ebuild.config import LocationsManager

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        tree = root / "gentoo"
        overlay = root / "gentoo-zh"
        for repo, name in ((tree, "gentoo"), (overlay, "gentoo-zh")):
            profiles = repo / "profiles"
            profiles.mkdir(parents=True)
            (profiles / "repo_name").write_text(name + "\n")
            (profiles / "categories").write_text("app-misc\n")
        metadata = overlay / "metadata"
        metadata.mkdir()
        (metadata / "layout.conf").write_text("masters = gentoo\n")

        profile = tree / "profiles/test"
        profile.mkdir()
        (profile / "eapi").write_text("8\n")
        (profile / "make.defaults").write_text('ARCH="amd64"\n')

        config = root / "host/etc/portage"
        config.mkdir(parents=True)
        (config / "make.profile").symlink_to(profile)
        if kind == "package.license":
            value = "app-misc/example all-rights-reserved\n"
        else:
            value = "BINARY-REDISTRIBUTABLE all-rights-reserved\n"
        (config / kind).write_text(value)

        real_init = LocationsManager.__init__

        def host_config(self, *args, **kwargs):
            if kwargs.get("config_root") is None:
                kwargs["config_root"] = str(root / "host")
            return real_init(self, *args, **kwargs)

        LocationsManager.__init__ = host_config
        try:
            db = stage_index.pinned_portdbapi(
                overlay, tree, accept_license=stage_index.BINARY_LICENSES)
            return stage_index.effective_license(
                "app-misc/example-1", {"USE": "", "REPO": "gentoo-zh"},
                "all-rights-reserved", "0", db.settings) == "no"
        finally:
            LocationsManager.__init__ = real_init


case("主机 package.license 不得放宽发布策略", lambda: (
    host_license_override("package.license")))

case("主机 license_groups 不得放宽发布策略", lambda: (
    host_license_override("license_groups")))

case("许可证策略拒绝的产物进入隔离清单", lambda: (
    run([stanza("app-misc/a-1", license="NO-REDIST")],
        licenses={"app-misc/a-1": "no"})[3]
    == [("app-misc/a-1", "app-misc/a/a-1.gpkg.tar", "license")]))

case("同一版本多实例仅保留 BUILD_ID 最大者", lambda: (
    len(run([stanza("app-misc/a-1", build_id=1),
             stanza("app-misc/a-1", build_id=3),
             stanza("app-misc/a-1", build_id=2)])[0]) == 1))

case("保留的实例 BUILD_ID 为最大值", lambda: (
    run([stanza("app-misc/a-1", build_id=1),
         stanza("app-misc/a-1", build_id=3)])[0][0][0] == 3))

case("BUILD_ID 输入顺序不影响结果", lambda: (
    run([stanza("app-misc/a-1", build_id=3),
         stanza("app-misc/a-1", build_id=1)])[0][0][0] == 3))

case("excluded.txt 里的包不发布", lambda: (
    run([stanza("app-text/wiki2man_on_rust-0.5.1-r1")],
        excluded={"app-text/wiki2man_on_rust"})[0] == []))

case("acct-group 只在使用者系统本地安装", lambda: (
    cpvs(run([stanza("acct-group/aptly-0")], excluded={"app-misc/other"})[0])
    == []))

case("acct-user 只在使用者系统本地安装", lambda: (
    cpvs(run([stanza("acct-user/aptly-0")])[0]) == []))

case("virtual 只在使用者系统本地安装", lambda: (
    cpvs(run([stanza("virtual/lib-0", repo="gentoo")])[0]) == []))

case("本地安装类别从候选索引排除", lambda: (
    run([stanza("virtual/lib-0", repo="gentoo")])[3]
    == [("virtual/lib-0", "virtual/lib/lib-0.gpkg.tar", "source")]))

KMOD = {"sys-fs/zfs-2.4.3": "toolchain-funcs linux-mod-r1 dist-kernel-utils"}

case("同一个包不带 linux-mod 时照常发布", lambda: (
    cpvs(run([stanza("sys-fs/zfs-2.4.3")])[0]) == ["sys-fs/zfs-2.4.3"]))

case("继承 linux-mod-r1 的包不发布", lambda: (
    cpvs(run([stanza("sys-fs/zfs-2.4.3")], inherited=KMOD)[0]) == []))

case("继承 linux-mod 的包不发布", lambda: (
    cpvs(run([stanza("app-emulation/vbox-mod-7.2")],
             inherited={"app-emulation/vbox-mod-7.2": "linux-mod"})[0]) == []))

case("内核模块包按 kernel-module 记入拒发", lambda: (
    run([stanza("sys-fs/zfs-2.4.3")], inherited=KMOD)[3]
    == [("sys-fs/zfs-2.4.3", "sys-fs/zfs/zfs-2.4.3.gpkg.tar", "kernel-module")]))

case("内核模块包立即从公开路径移除", lambda: (
    "kernel-module" in stage_index.IMMEDIATE_QUARANTINE_STATES))

case("eclass 名字相近但不建模块的包照常发布", lambda: (
    cpvs(run([stanza("app-misc/a-1")],
             inherited={"app-misc/a-1": "linux-info linux-mod-nonesuch"})[0])
    == ["app-misc/a-1"]))

case("INHERITED 查询失败时拒绝发布", lambda: (
    (lambda result: cpvs(result[0]) == [] and result[3] == [
        ("sys-fs/zfs-2.4.3", "sys-fs/zfs/zfs-2.4.3.gpkg.tar", "unknown")
    ])(run([stanza("sys-fs/zfs-2.4.3")],
           overlay_has=["sys-fs/zfs-2.4.3"],
           inherited={"sys-fs/zfs-2.4.3": None}))))


def inherited_lookup_preserves_failure():
    class BrokenDb:
        def aux_get(self, _cpv, _fields, myrepo=None):
            raise RuntimeError("metadata unavailable")

    original = stage_index.pinned_portdbapi
    stage_index.pinned_portdbapi = lambda *_args, **_kwargs: BrokenDb()
    try:
        _restrict, _license, inherited = stage_index.portage_policy("/overlay")
        return inherited("sys-fs/zfs-2.4.3", "gentoo-zh") is None
    finally:
        stage_index.pinned_portdbapi = original


case("INHERITED reader 区分查询失败与空值", inherited_lookup_preserves_failure)


def quarantine_for(value):
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        pkgdir = root / "pkgdir"
        pkgdir.mkdir()
        (pkgdir / "Packages").write_text(HEADER + "\n\n" + value + "\n")
        stage = root / "stage"
        stage.mkdir()
        stage_main(pkgdir, stage, lookup=lambda _cpv, _repo: "")
        return (stage / "quarantine.txt").read_text().splitlines()


case("本地安装类别等待新索引成功后再清理", lambda: (
    quarantine_for(stanza("virtual/lib-0", repo="gentoo")) == []))


def counts_for(entries):
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        pkgdir = root / "pkgdir"
        pkgdir.mkdir()
        content = b"x\n"
        digest = md5_of(content)
        for cpv, path in entries:
            blob = pkgdir / path
            blob.parent.mkdir(parents=True, exist_ok=True)
            blob.write_bytes(content)
        body = "\n\n".join(
            f"CPV: {cpv}\nPATH: {path}\nREPO: gentoo-zh\nEAPI: 8\nSLOT: 0\n"
            f"MD5: {digest}"
            for cpv, path in entries)
        (pkgdir / "Packages").write_text(HEADER + "\n\n" + body + "\n")
        stage = root / "stage"
        stage.mkdir()
        stage_main(pkgdir, stage, lookup=lambda _cpv, _repo: "")
        return (stage / "counts.txt").read_text().split()


case("同一个包的两份产物只算一个 overlay 包", lambda: (
    counts_for([("app-misc/a-1", "app-misc/a/a-1.gpkg.tar"),
                ("app-misc/a-2", "app-misc/a/a-2.gpkg.tar")]) == ["1", "0"]))

case("不同包分别计数", lambda: (
    counts_for([("app-misc/a-1", "app-misc/a/a-1.gpkg.tar"),
                ("app-misc/b-1", "app-misc/b/b-1.gpkg.tar")]) == ["2", "0"]))

case("bindist 产物仍立即进入隔离清单", lambda: (
    quarantine_for(stanza("app-misc/restricted-1", restrict="bindist"))
    == ["app-misc/restricted/restricted-1.gpkg.tar"]))

case("mask 不会盖过新增的 bindist 限制", lambda: (
    run([stanza("app-misc/a-1")], overlay_has=["app-misc/a-1"],
        masked=("app-misc/a",), restricts={"app-misc/a-1": "bindist"})[3]
    == [("app-misc/a-1", "app-misc/a/a-1.gpkg.tar", "yes")]))

case("excluded 不会盖过新增的许可证限制", lambda: (
    run([stanza("app-misc/a-1", license="NO-REDIST")],
        excluded={"app-misc/a"}, licenses={"app-misc/a-1": "no"})[3]
    == [("app-misc/a-1", "app-misc/a/a-1.gpkg.tar", "license")]))

def removed_source_only_version():
    with tempfile.TemporaryDirectory() as tmp:
        return run([stanza("virtual/lib-0", repo="gentoo")],
                   restricts={"virtual/lib-0": None}, gentoo_tree=tmp)[3] == [
            ("virtual/lib-0", "virtual/lib/lib-0.gpkg.tar", "source")]


case("本地安装类别的旧版本不会误判成 metadata 未知",
     removed_source_only_version)


def broken_source_only_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        tree = pathlib.Path(tmp)
        package = tree / "virtual/lib"
        package.mkdir(parents=True)
        (package / "lib-0.ebuild").write_text("EAPI=8\n")
        return run([stanza("virtual/lib-0", repo="gentoo")],
                   restricts={"virtual/lib-0": None}, gentoo_tree=tree)[3] == [
            ("virtual/lib-0", "virtual/lib/lib-0.gpkg.tar", "unknown")]


case("ebuild 仍存在但 metadata 无法读取时继续从严",
     broken_source_only_metadata)

case("本地安装类别仍服从当前版本新增的 bindist 限制", lambda: (
    run([stanza("virtual/lib-0", repo="gentoo")],
        restricts={"virtual/lib-0": "bindist"})[3]
    == [("virtual/lib-0", "virtual/lib/lib-0.gpkg.tar", "yes")]))

case("overlay 已移除的版本等待新索引成功后再清理", lambda: (
    run([stanza("app-misc/a-1")], overlay_has=[],
        restricts={"app-misc/a-1": None})[3]
    == [("app-misc/a-1", "app-misc/a/a-1.gpkg.tar", "removed")]))


def removed_gentoo_version():
    with tempfile.TemporaryDirectory() as tmp:
        return run([stanza("dev-libs/a-1", repo="gentoo")],
                   restricts={"dev-libs/a-1": None}, gentoo_tree=tmp)[3] == [
                ("dev-libs/a-1", "dev-libs/a/a-1.gpkg.tar", "removed")]


case("Gentoo 主树已移除的版本等待新索引成功后再清理",
     removed_gentoo_version)

case("带 revision 的版本号可匹配排除清单", lambda: (
    run([stanza("app-misc/a-1.2.3-r4")], excluded={"app-misc/a"})[0] == []))

case("overlay 中已不存在的包被过滤", lambda: (
    run([stanza("dev-libs/libratbag-0.18")], overlay_has=["app-misc/a-1"])[0] == []))

case("overlay 中仍存在的包保留", lambda: (
    cpvs(run([stanza("app-misc/a-1")], overlay_has=["app-misc/a-1"])[0]) == ["app-misc/a-1"]))

case("未提供 overlay 时不做该项过滤", lambda: (
    cpvs(run([stanza("dev-libs/gone-1")])[0]) == ["dev-libs/gone-1"]))

case("带 revision 的版本号可解析出 cp", lambda: (
    run([stanza("app-misc/a-1.2.3-r4")], overlay_has=["app-misc/a-1.2.3-r4"])[0] != []))

case("bump 之后旧版本退场", lambda: (
    cpvs(run([stanza("dev-util/gitea-cli-0.14.2"), stanza("dev-util/gitea-cli-0.15.0")],
             overlay_has=["dev-util/gitea-cli-0.15.0"])[0]) == ["dev-util/gitea-cli-0.15.0"]))

case("目录还在但这个版本已移除，仍应过滤", lambda: (
    run([stanza("app-misc/a-1")], overlay_has=["app-misc/a-2"])[0] == []))

case("同一个包的多个版本都在 overlay 里就都保留", lambda: (
    cpvs(run([stanza("app-misc/a-1"), stanza("app-misc/a-2")],
             overlay_has=["app-misc/a-1", "app-misc/a-2"])[0]) == ["app-misc/a-1", "app-misc/a-2"]))

case("ebuild 带 -r0 而 CPV 不带时仍然匹配", lambda: (
    run([stanza("app-misc/a-1")], overlay_has=["app-misc/a-1-r0"])[0] != []))

case("头部 PACKAGES 重写为实际数量", lambda: (
    lambda h: re.findall(r"^PACKAGES: .*$", h, re.M) == ["PACKAGES: 7"]
)(stage_index.rewrite_header(HEADER, 7, "")))

case("头部 TIMESTAMP 重写为本代时间", lambda: (
    lambda got: abs(got - int(time.time())) <= 5
)(int(re.search(r"^TIMESTAMP: (\d+)$",
                stage_index.rewrite_header(HEADER, 7, ""), re.M).group(1))))

case("头部缺少该行时插入", lambda: (
    '"gentoo-zh": "abc123"' in stage_index.rewrite_header(HEADER, 7, "abc123")))

case("头部同时记录 Gentoo 主树与 overlay", lambda: (
    'REPO_REVISIONS: {"gentoo": "gentoo123", "gentoo-zh": "overlay123"}'
    in stage_index.rewrite_header(
        HEADER, 7, "overlay123", "gentoo123")))

case("头部已有该行时覆盖", lambda: (
    '"gentoo-zh": "abc123"' in stage_index.rewrite_header(HEADER_WITH_REV, 7, "abc123")
    and "REPO_REVISIONS: {}" not in stage_index.rewrite_header(HEADER_WITH_REV, 7, "abc123")))

case("写入后头部仅有一行 REPO_REVISIONS", lambda: (
    stage_index.rewrite_header(HEADER, 7, "abc").count("REPO_REVISIONS") == 1))

case("未提供 rev 时不新增该行", lambda: (
    "REPO_REVISIONS" not in stage_index.rewrite_header(HEADER, 7, "")))

case("未提供 rev 时保留原有该行", lambda: (
    "REPO_REVISIONS: {}" in stage_index.rewrite_header(HEADER_WITH_REV, 7, "")))


def non_git_tree_has_no_revision():
    with tempfile.TemporaryDirectory() as tmp:
        return stage_index.repository_revision(tmp) == ""


case("主树不是 git 仓库时省略修订而不失败", non_git_tree_has_no_revision)


def staged_header(gentoo_rev):
    """main() has to hand the revision through, not just accept the argument."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        pkgdir = root / "pkgdir"
        pkgdir.mkdir()
        content = b"x\n"
        blob = pkgdir / "app-misc/a/a-1.gpkg.tar"
        blob.parent.mkdir(parents=True)
        blob.write_bytes(content)
        (pkgdir / "Packages").write_text(
            HEADER + "\n\nCPV: app-misc/a-1\nPATH: app-misc/a/a-1.gpkg.tar\n"
            f"REPO: gentoo-zh\nEAPI: 8\nSLOT: 0\nMD5: {md5_of(content)}\n")
        stage = root / "stage"
        stage.mkdir()
        stage_main(pkgdir, stage, gentoo_rev=gentoo_rev,
                   lookup=lambda _cpv, _repo: "")
        return (stage / "Packages").read_text()


case("main 把两棵树的修订都写进暂存索引", lambda: (
    f'REPO_REVISIONS: {{"gentoo": "{GENTOO_REV}", "gentoo-zh": "{OVERLAY_REV}"}}'
    in staged_header(GENTOO_REV)))

def missing_revision(rev, gentoo_rev):
    try:
        stage_index.main("/nonexistent", "/nonexistent", rev=rev,
                         gentoo_rev=gentoo_rev)
    except SystemExit as exc:
        return str(exc)
    return ""


case("无法取得主树修订时拒绝 stage", lambda: (
    "gentoo" in missing_revision(OVERLAY_REV, "")))
case("无法取得 overlay 修订时拒绝 stage", lambda: (
    "gentoo-zh" in missing_revision("", GENTOO_REV)))
case("仓库修订不是 40 位提交值时拒绝 stage", lambda: (
    "gentoo-zh" in missing_revision("abc123", GENTOO_REV)))

case("插入后头部保持字母序", lambda: (
    (lambda ls: ls == sorted(ls))(stage_index.rewrite_header(
        "ACCEPT_KEYWORDS: ~amd64\nPACKAGES: 1\nTIMESTAMP: 1\nVERSION: 0", 7, "abc").splitlines())))

print(f"  {'用例':<40} 结果")
case("overlay mask 掉之后不再 stage", lambda: (
    cpvs(run([stanza("app-misc/a-1")], overlay_has=["app-misc/a-1"],
             masked=("app-misc/a",))[0]) == []))

case("overlay mask 的包不会作为依赖重新进入索引", lambda: (
    (lambda r: cpvs(r[0]) == ["app-misc/a-1"]
     and ("app-misc/b-1", "app-misc/b/b-1.gpkg.tar", "masked") in r[3])(
        run([stanza("app-misc/a-1", rdepend="app-misc/b"),
             stanza("app-misc/b-1")],
            overlay_has=["app-misc/a-1", "app-misc/b-1"],
            masked=("app-misc/b",), with_deps=True))))

case("excluded.txt 的包不会作为依赖重新进入索引", lambda: (
    (lambda r: cpvs(r[0]) == ["app-misc/a-1"]
     and ("app-misc/b-1", "app-misc/b/b-1.gpkg.tar", "excluded") in r[3])(
        run([stanza("app-misc/a-1", rdepend="app-misc/b"),
             stanza("app-misc/b-1")],
            overlay_has=["app-misc/a-1", "app-misc/b-1"],
            excluded={"app-misc/b"}, with_deps=True))))

case("显式种子不会发布缓存里的无关 overlay 包", lambda: (
    cpvs(run([stanza("app-misc/a-1"), stanza("app-misc/b-1")],
             seed_packages={"app-misc/a"})[0]) == ["app-misc/a-1"]))

case("清单外的 overlay 运行期依赖仍会随种子发布", lambda: (
    cpvs(run([stanza("app-misc/a-1", rdepend="app-misc/b"),
              stanza("app-misc/b-1")], with_deps=True,
             seed_packages={"app-misc/a"})[0])
    == ["app-misc/a-1", "app-misc/b-1"]))

case("频道排除项不会经运行期依赖重新进入索引", lambda: (
    (lambda result: cpvs(result[0]) == ["app-misc/a-1"]
     and ("app-misc/b-1", "app-misc/b/b-1.gpkg.tar", "excluded")
     in result[3])(
        run([stanza("app-misc/a-1", rdepend="app-misc/b"),
             stanza("app-misc/b-1")], excluded={"app-misc/b"},
            with_deps=True, seed_packages={"app-misc/a"}))))


def main_channel_policy():
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        pkgdir = root / "pkgdir"
        stage = root / "stage"
        stage.mkdir()
        records = []
        for cpv in ("app-misc/a-1", "app-misc/b-1", "app-misc/c-1"):
            content = f"{cpv}\n".encode()
            relative = pathlib.Path("app-misc") / f"{cpv.split('/')[-1]}.gpkg.tar"
            package = pkgdir / relative
            package.parent.mkdir(parents=True, exist_ok=True)
            package.write_bytes(content)
            records.append(stanza(
                cpv, PATH=str(relative), sha1=digest_of(content),
                rdepend="app-misc/b" if cpv == "app-misc/a-1" else None))
        (pkgdir / "Packages").write_text(
            HEADER + "\n\n" + "\n\n".join(records) + "\n")
        seeds = root / "seeds.txt"
        seeds.write_text("app-misc/a\n")
        excluded = root / "excluded.txt"
        excluded.write_text("app-misc/b\tnot in this channel\n")
        rc = stage_main(
            pkgdir, stage, lookup=fake_lookup(), seed_file=seeds,
            excluded_files=(excluded,))
        _, entries = stage_index.parse((stage / "Packages").read_text())
        unresolved = (stage / "unresolved.txt").read_text()
        return rc, sorted(fields["CPV"] for fields, _ in entries), unresolved


case("main 读取频道种子与排除清单", lambda: (
    (lambda result: result[0] == 0 and result[1] == ["app-misc/a-1"]
     and "app-misc/b" in result[2])(main_channel_policy())))

case("没 mask 时照旧收录", lambda: (
    cpvs(run([stanza("app-misc/a-1")], overlay_has=["app-misc/a-1"])[0])
    == ["app-misc/a-1"]))

case("PATH 是绝对路径时全部拒绝", lambda: (
    run([stanza("app-misc/a-1", PATH="/etc/passwd")])[2] is not None))

case("PATH 里有 .. 时全部拒绝", lambda: (
    run([stanza("app-misc/a-1", PATH="../../etc/passwd")])[2] is not None))

case("PATH 中段有 .. 时全部拒绝", lambda: (
    run([stanza("app-misc/a-1", PATH="app-misc/../../x.gpkg.tar")])[2] is not None))

case("PATH 为空时全部拒绝", lambda: (
    run([stanza("app-misc/a-1", PATH="")])[2] is not None))

case("PATH 带前后空白时全部拒绝", lambda: (
    run([stanza("app-misc/a-1", PATH=" app-misc/a-1.gpkg.tar")])[2] is not None))

case("PATH 带当前目录前缀时全部拒绝", lambda: (
    run([stanza("app-misc/a-1", PATH="./app-misc/a-1.gpkg.tar")])[2] is not None))

case("PATH 带重复分隔符时全部拒绝", lambda: (
    run([stanza("app-misc/a-1", PATH="app-misc//a-1.gpkg.tar")])[2] is not None))

case("正常的相对路径照常通过", lambda: (
    run([stanza("app-misc/a-1", PATH="app-misc/a-1-1.gpkg.tar")])[2] is None))

case("拒绝时一个包都不 stage", lambda: (
    run([stanza("app-misc/a-1", PATH="app-misc/ok.gpkg.tar"),
         stanza("app-misc/b-1", PATH="/etc/passwd")])[0] == []))

def _escape(shape):
    import os
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        pkg = d / "pkgdir"
        (pkg / "app-misc").mkdir(parents=True)
        stage = d / "stage"
        stage.mkdir()
        (d / "OUTSIDE").write_text("outside\n")
        target = pkg / "app-misc" / "a-1.gpkg.tar"
        if shape == "final":
            os.symlink(d / "OUTSIDE", target)
        elif shape == "relative":
            os.symlink("../../OUTSIDE", target)
        elif shape == "intermediate":
            (pkg / "app-misc").rmdir()
            real = d / "elsewhere"
            real.mkdir()
            (real / "a-1.gpkg.tar").write_text("outside\n")
            os.symlink(real, pkg / "app-misc")
        elif shape == "fifo":
            os.mkfifo(target)
        else:
            target.write_text("inside\n")
        (pkg / "Packages").write_text(
            HEADER + "\n\n" + stanza("app-misc/a-1", PATH="app-misc/a-1.gpkg.tar",
                                      sha1=digest_of(b"inside\n")) + "\n")
        try:
            rc = stage_main(str(pkg), str(stage),
                                  lookup=lambda cpv, repo: "")
        except SystemExit as e:
            rc = e.code
        out = stage / "app-misc" / "a-1.gpkg.tar"
        leaked = out.exists() and "outside" in out.read_text(errors="replace")
        return rc, leaked


for _shape in ("final", "relative", "intermediate", "fifo"):
    case(f"来源是 {_shape} symlink 时拒绝且不泄漏",
         (lambda s=_shape: (lambda r: r[0] not in (0, None) and not r[1])(_escape(s))))

case("正常文件照常 stage", lambda: _escape("plain")[0] in (0, None))


def _digest_probe(sha1=None, md5=None, content=b"inside\n", return_content=False):
    """Stage one package and report whether main accepted it."""
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        pkg = d / "pkg"
        (pkg / "app-misc").mkdir(parents=True)
        (pkg / "app-misc" / "a-1.gpkg.tar").write_bytes(content)
        stage = d / "stage"
        stage.mkdir()
        lines = ["CPV: app-misc/a-1", "PATH: app-misc/a-1.gpkg.tar",
                 "REPO: gentoo-zh", "EAPI: 8", "SLOT: 0"]
        if sha1:
            lines.append(f"SHA1: {sha1}")
        if md5:
            lines.append(f"MD5: {md5}")
        (pkg / "Packages").write_text(HEADER + "\n\n" + "\n".join(lines) + "\n")
        try:
            rc = stage_main(str(pkg), str(stage), lookup=lambda cpv, repo: "")
        except SystemExit as e:
            rc = e.code
        if return_content:
            output = stage / "app-misc" / "a-1.gpkg.tar"
            return rc, output.read_bytes() if output.exists() else None
        return rc


case("SHA1 与索引相符时照常 stage", lambda: (
    _digest_probe(sha1=digest_of(b"inside\n")) in (0, None)))

case("正常 stage 逐字节保留来源内容", lambda: (
    (lambda content: _digest_probe(
        sha1=digest_of(content), content=content, return_content=True)
     == (0, content))(bytes(range(256)) + b"stage\n")))

case("SHA1 不符时拒绝，不按旧 stanza 发布", lambda: (
    (lambda rc: rc not in (0, None) and "SHA1" in str(rc))(
        _digest_probe(sha1=digest_of(b"something else")))))

case("只有 MD5 时按 MD5 核对", lambda: (
    _digest_probe(md5=md5_of(b"inside\n")) in (0, None)))

case("MD5 不符时同样拒绝", lambda: (
    _digest_probe(md5=md5_of(b"other")) not in (0, None)))

case("SHA1 相符但 MD5 不符时仍然拒绝", lambda: (
    (lambda rc: rc not in (0, None) and "MD5" in str(rc))(
        _digest_probe(sha1=digest_of(b"inside\n"), md5=md5_of(b"other")))))

case("索引没有给出摘要时拒绝，不默认放行", lambda: (
    (lambda rc: rc not in (0, None) and "无法确认" in str(rc))(_digest_probe())))


def _dest_escape(shape):
    import os
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        pkg = d / "pkgdir"
        (pkg / "app-misc").mkdir(parents=True)
        (pkg / "app-misc" / "a-1.gpkg.tar").write_text("payload\n")
        stage = d / "stage"
        stage.mkdir()
        payload_sha1 = digest_of(b"payload\n")
        outside = d / "OUTSIDE"
        outside.mkdir()
        if shape == "dir":
            os.symlink(outside, stage / "app-misc")
        elif shape == "file":
            (stage / "app-misc").mkdir()
            os.symlink(outside / "a-1.gpkg.tar", stage / "app-misc" / "a-1.gpkg.tar")
        (pkg / "Packages").write_text(
            HEADER + "\n\n" + stanza("app-misc/a-1", PATH="app-misc/a-1.gpkg.tar",
                                      sha1=payload_sha1) + "\n")
        try:
            rc = stage_main(str(pkg), str(stage),
                                  lookup=lambda cpv, repo: "")
        except SystemExit as e:
            rc = e.code
        leaked = any(p.is_file() and p.name == "a-1.gpkg.tar" for p in outside.rglob("*"))
        return rc, leaked


case("目的地的中间目录是 symlink 时拒绝且不写出去",
     lambda: (lambda r: r[0] not in (0, None) and not r[1])(_dest_escape("dir")))
case("目的地的目标档案是 symlink 时拒绝且不写出去",
     lambda: (lambda r: r[0] not in (0, None) and not r[1])(_dest_escape("file")))
case("目的地干净时照常写入",
     lambda: _dest_escape("clean")[0] in (0, None))

case("某个包被加了 bindist 时只跳过它", lambda: (
    lambda r: cpvs(r[0]) == ["app-misc/a-1", "app-misc/c-1"]
              and r[2] is None
              and [c for c, _, _ in r[3]] == ["app-misc/b-1"]
)(run([stanza("app-misc/a-1"),
       stanza("app-misc/b-1", restrict="bindist"),
       stanza("app-misc/c-1")])))

case("被跳过的那个连它的路径一起记下来，好从公开路径移除", lambda: (
    run([stanza("app-misc/a-1"),
         stanza("app-misc/b-1", restrict="bindist")])[3]
    == [("app-misc/b-1", "app-misc/b/b-1.gpkg.tar", "yes")]))

case("同一 CPV 的所有 BUILD_ID 路径都进入隔离清单", lambda: (
    sorted(path for cpv, path, _state in run([
        stanza("app-misc/b-1", build_id=1, restrict="bindist",
               PATH="app-misc/b/b-1-1.gpkg.tar"),
        stanza("app-misc/b-1", build_id=2, restrict="bindist",
               PATH="app-misc/b/b-1-2.gpkg.tar")])[3] if cpv == "app-misc/b-1")
    == ["app-misc/b/b-1-1.gpkg.tar", "app-misc/b/b-1-2.gpkg.tar"]))

case("无法读取 metadata 与 bindist 分别标注，操作提示才不会指错方向", lambda: (
    [s for _, _, s in with_meta([stanza("app-misc/a-1"), stanza("app-misc/b-1")],
                                {("app-misc/a-1", "gentoo-zh"): "bindist"},
                                default=None)[3]]
    == ["yes", "unknown"]))

case("RESTRICT 里带 bindist 前缀的其他词不算", lambda: (
    not run([stanza("app-misc/b-1", restrict="bindistfoo")])[3]))

case("RESTRICT 是多个词时按整词认", lambda: (
    [c for c, _, _ in run([stanza("app-misc/b-1", restrict="mirror bindist strip")])[3]]
    == ["app-misc/b-1"]))

case("bindist 的那一个不会进索引", lambda: (
    "app-misc/b-1" not in cpvs(run([stanza("app-misc/a-1"),
                                    stanza("app-misc/b-1", restrict="bindist")])[0])))

def with_meta(stanzas, restricts, default=""):
    """restricts maps (cpv, repo) to RESTRICT. default=None fakes a read failure."""
    _, entries = stage_index.parse(HEADER + "\n\n" + "\n\n".join(stanzas) + "\n")

    def lookup(cpv, repo):
        return restricts.get((cpv, repo), default)
    return stage_index.select(entries, None, excluded=set(), with_deps=False,
                              lookup=lookup)


def only_refused(result, cpv):
    return cpvs(result[0]) == [] and [c for c, _, _ in result[3]] == [cpv]


case("旧 stanza 无 RESTRICT，但当前 metadata 已加 bindist，仍要拒绝", lambda: (
    only_refused(with_meta([stanza("app-misc/example-1")],
                           {("app-misc/example-1", "gentoo-zh"): "bindist"}),
                 "app-misc/example-1")))

case("当前 metadata 没有 bindist 时正常发布", lambda: (
    cpvs(with_meta([stanza("app-misc/example-1")],
                   {("app-misc/example-1", "gentoo-zh"): "strip"})[0])
    == ["app-misc/example-1"]))

case("eclass 加进来的 bindist 同样识别", lambda: (
    only_refused(with_meta([stanza("app-misc/example-1")],
                           {("app-misc/example-1", "gentoo-zh"): "strip bindist"}),
                 "app-misc/example-1")))

case("无法读取 metadata 时拒绝发布，不回退到 stanza", lambda: (
    only_refused(with_meta([stanza("app-misc/example-1")], {}, default=None),
                 "app-misc/example-1")))

case("按 stanza 的 REPO 选来源", lambda: (
    only_refused(with_meta([stanza("app-misc/example-1", repo="gentoo-zh")],
                           {("app-misc/example-1", "gentoo-zh"): "bindist",
                            ("app-misc/example-1", "gentoo"): ""},
                           default=None),
                 "app-misc/example-1")))

case("同名 CPV 在另一个仓库受限时不影响本仓库的判定", lambda: (
    cpvs(with_meta([stanza("app-misc/example-1", repo="gentoo-zh")],
                   {("app-misc/example-1", "gentoo-zh"): "",
                    ("app-misc/example-1", "gentoo"): "bindist"},
                   default=None)[0])
    == ["app-misc/example-1"]))

def portage_lookup_error(overlay):
    try:
        stage_index.portage_policy(overlay)
    except stage_index.MetadataUnavailable as e:
        return str(e)
    return None


case("仓库路径解析不到指定位置时不返回可用的查询函数", lambda: (
    portage_lookup_error("/nonexistent/overlay") is not None))

case("路径不符时报出期望的位置", lambda: (
    "/nonexistent/overlay" in (portage_lookup_error("/nonexistent/overlay") or "")))

case("没有 overlay 就无法确认来源，本次不发布", lambda: (
    (lambda r: r[0] == [] and "no overlay to resolve gentoo-zh against" in (r[2] or ""))(
        stage_index.select(
            stage_index.parse(HEADER + "\n\n" + stanza("app-misc/example-1") + "\n")[1],
            None, excluded=set(), with_deps=False))))

case("stanza 建成时受限，即使当前 metadata 已解除也不发布", lambda: (
    only_refused(with_meta([stanza("app-misc/example-1", restrict="bindist")],
                           {("app-misc/example-1", "gentoo-zh"): ""}),
                 "app-misc/example-1")))

case("IDEPEND 里的包也要一起发", lambda: (
    deps([stanza("app-misc/a-1", idepend="dev-util/tool"),
          stanza("dev-util/tool-1", repo="gentoo")])
    == ["app-misc/a-1", "dev-util/tool-1"]))

case("blocker 不算依赖，不跟着发", lambda: (
    deps([stanza("app-misc/a-1", rdepend="!dev-libs/lib !!dev-libs/deep"),
          stanza("dev-libs/lib-1", repo="gentoo"),
          stanza("dev-libs/deep-1", repo="gentoo")])
    == ["app-misc/a-1"]))


def deps(stanzas):
    return sorted(cpvs(run(stanzas, with_deps=True)[0]))


def deps_excluded():
    r = run([stanza("app-misc/a-1", rdepend="dev-libs/lib"),
             stanza("dev-libs/lib-1", repo="gentoo")],
            excluded={"app-misc/a"}, with_deps=True)
    return cpvs(r[0]) == []


LIB = stanza("dev-libs/lib-1", repo="gentoo")
DEEP = stanza("dev-libs/deep-1", repo="gentoo")
TOOL = stanza("dev-util/tool-1", repo="gentoo")
OTHER = stanza("dev-libs/other-1", repo="gentoo")
UNUSED = stanza("app-misc/unused-1", repo="gentoo")

case("不开依赖时，::gentoo 的一律不发", lambda: (
    deps([stanza("app-misc/a-1")]) == ["app-misc/a-1"]))

case("我们的包用到的 ::gentoo 依赖会一起发", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib"), LIB])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("依赖的依赖也跟着发", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib"),
          stanza("dev-libs/lib-1", repo="gentoo", rdepend="dev-libs/deep"), DEEP])
    == ["app-misc/a-1", "dev-libs/deep-1", "dev-libs/lib-1"]))

case("没人用到的 ::gentoo 包不发", lambda: (
    deps([stanza("app-misc/a-1"), UNUSED]) == ["app-misc/a-1"]))

case("只在构建期用到的不发", lambda: (
    deps([stanza("app-misc/a-1", depend="dev-util/tool"), TOOL])
    == ["app-misc/a-1"]))

case("带版本、slot 与 USE 的原子逐项匹配", lambda: (
    deps([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-1:0/1=[foo]"),
          stanza("dev-libs/lib-1", repo="gentoo", slot="0/1", use="foo", iuse="foo")])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("stanza 省略 SLOT 时按 portage 的默认值 0 匹配", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib:0"),
          stanza("dev-libs/lib-1", repo="gentoo", slot=None)])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("slot 不符时不算满足", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib:2"),
          stanza("dev-libs/lib-1", repo="gentoo", slot="0")])
    == ["app-misc/a-1"]))

case("sub-slot 不符时不算满足", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib:0/9"),
          stanza("dev-libs/lib-1", repo="gentoo", slot="0/1")])
    == ["app-misc/a-1"]))

case("stanza 省略 IUSE 时不满足未开启的 USE 依赖", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib[foo]"),
          stanza("dev-libs/lib-1", repo="gentoo")])
    == ["app-misc/a-1"]))

case("stanza 省略 IUSE 但开启了该 flag 时算满足", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib[foo]"),
          stanza("dev-libs/lib-1", repo="gentoo", use="foo")])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("IUSE 与 EAPI 都省略时 USE 依赖匹配不到，两者要一起读", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib[foo]"),
          stanza("dev-libs/lib-1", repo="gentoo", use="foo", eapi=None)])
    == ["app-misc/a-1"]))

case("stanza 省略 EAPI 时仍能按版本匹配", lambda: (
    deps([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-1"),
          stanza("dev-libs/lib-1", repo="gentoo", eapi=None)])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("USE 依赖不满足时不算满足", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib[foo]"),
          stanza("dev-libs/lib-1", repo="gentoo", use="bar", iuse="foo bar")])
    == ["app-misc/a-1"]))

case("::repo 限定只匹配该仓库的产物", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib::gentoo-zh"),
          stanza("dev-libs/lib-1", repo="gentoo")])
    == ["app-misc/a-1"]))

case("::repo 限定命中时照常发布", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib::gentoo"),
          stanza("dev-libs/lib-1", repo="gentoo")])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("大于等于只取满足条件的版本，不带上旧版", lambda: (
    deps([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-2"),
          stanza("dev-libs/lib-1", repo="gentoo"),
          stanza("dev-libs/lib-2", repo="gentoo")])
    == ["app-misc/a-1", "dev-libs/lib-2"]))

case("波浪号匹配同一版本的 revision", lambda: (
    deps([stanza("app-misc/a-1", rdepend="~dev-libs/lib-1.2"),
          stanza("dev-libs/lib-1.2-r3", repo="gentoo")])
    == ["app-misc/a-1", "dev-libs/lib-1.2-r3"]))

case("万用版本匹配带 revision 的版本", lambda: (
    deps([stanza("app-misc/a-1", rdepend="=dev-libs/lib-1*"),
          stanza("dev-libs/lib-1-r1", repo="gentoo")])
    == ["app-misc/a-1", "dev-libs/lib-1-r1"]))

case("同一个 CPV 跨仓库时发布种子所属仓库的 stanza", lambda: (
    (lambda r: [(f["CPV"], f["REPO"]) for _b, f, _s in r[0]]
     == [("app-misc/a-1", "gentoo-zh")])(
        run([stanza("app-misc/a-1", repo="gentoo-zh", build_id=1),
             stanza("app-misc/a-1", repo="gentoo", build_id=2)], with_deps=True))))

case("BUILD_ID 只在同一个仓库内比较", lambda: (
    (lambda r: sorted((f["REPO"], b) for b, f, _s in r[0])
     == [("gentoo-zh", 15)])(
        run([stanza("app-misc/a-1", repo="gentoo-zh", build_id=9),
             stanza("app-misc/a-1", repo="gentoo-zh", build_id=15)], with_deps=True))))

case("依赖同时存在于两个仓库时选择 overlay stanza", lambda: (
    (lambda r: sorted((f["CPV"], f["REPO"]) for _b, f, _s in r[0])
     == [("app-misc/a-1", "gentoo-zh"), ("dev-libs/lib-1", "gentoo-zh")])(
        run([stanza("app-misc/a-1", rdepend="dev-libs/lib"),
             stanza("dev-libs/lib-1", repo="gentoo-zh", build_id=1),
             stanza("dev-libs/lib-1", repo="gentoo", build_id=2)],
            overlay_has=["app-misc/a-1", "dev-libs/lib-1"], with_deps=True))))

case("::gentoo 限定依赖选择主树 stanza", lambda: (
    (lambda r: sorted((f["CPV"], f["REPO"]) for _b, f, _s in r[0])
     == [("app-misc/a-1", "gentoo-zh"), ("dev-libs/lib-1", "gentoo")])(
        run([stanza("app-misc/a-1", rdepend="dev-libs/lib::gentoo"),
             stanza("dev-libs/lib-1", repo="gentoo-zh", build_id=1),
             stanza("dev-libs/lib-1", repo="gentoo", build_id=2)],
            overlay_has=["app-misc/a-1"], with_deps=True))))

case("闭包读取最终发布的 stanza", lambda: (
    deps([stanza("app-misc/a-1", build_id=15, rdepend="dev-libs/other"),
          stanza("app-misc/a-1", build_id=9, rdepend="dev-libs/lib"),
          LIB, OTHER])
    == ["app-misc/a-1", "dev-libs/other-1"]))

case("或组第一个分支不可散布时改选第二个", lambda: (
    sorted(f["CPV"] for _b, f, _s in run(
        [stanza("app-misc/a-1", rdepend="|| ( dev-libs/lib dev-libs/deep )"),
         LIB, DEEP], with_deps=True,
        restricts={("dev-libs/lib-1", "gentoo"): "bindist"})[0])
    == ["app-misc/a-1", "dev-libs/deep-1"]))

case("不可散布的候选不进闭包，也不因此少发别的", lambda: (
    (lambda r: [c for c, _p, _s in r[3]] == ["dev-libs/lib-1"])(
        run([stanza("app-misc/a-1", rdepend="|| ( dev-libs/lib dev-libs/deep )"),
             LIB, DEEP], with_deps=True,
            restricts={("dev-libs/lib-1", "gentoo"): "bindist"}))))

case("精确版本指到旧的那一个时也要发", lambda: (
    deps([stanza("app-misc/a-1", rdepend="=dev-libs/lib-1"),
          stanza("dev-libs/lib-1", repo="gentoo"),
          stanza("dev-libs/lib-2", repo="gentoo")])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("同一个包新旧两版各被不同的包指到时都发", lambda: (
    deps([stanza("app-misc/a-1", rdepend="=dev-libs/lib-1"),
          stanza("app-misc/b-1", rdepend="=dev-libs/lib-2"),
          stanza("dev-libs/lib-1", repo="gentoo"),
          stanza("dev-libs/lib-2", repo="gentoo")])
    == ["app-misc/a-1", "app-misc/b-1", "dev-libs/lib-1", "dev-libs/lib-2"]))

case("裸原子只取每个 slot 里最新的那个", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib"),
          stanza("dev-libs/lib-1", repo="gentoo"),
          stanza("dev-libs/lib-2", repo="gentoo")])
    == ["app-misc/a-1", "dev-libs/lib-2"]))

case("不同 slot 各取一个", lambda: (
    deps([stanza("app-misc/a-1", rdepend="dev-libs/lib"),
          stanza("dev-libs/lib-1", repo="gentoo", slot="1"),
          stanza("dev-libs/lib-2", repo="gentoo", slot="2")])
    == ["app-misc/a-1", "dev-libs/lib-1", "dev-libs/lib-2"]))

case("或组取第一个索引能满足的分支", lambda: (
    deps([stanza("app-misc/a-1", rdepend="|| ( dev-libs/gone dev-libs/lib )"), LIB])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("或组的合取分支缺少原子时改选完整分支", lambda: (
    deps([stanza(
        "app-misc/a-1",
        rdepend="|| ( ( dev-libs/lib dev-libs/missing ) dev-libs/deep )"),
          LIB, DEEP])
    == ["app-misc/a-1", "dev-libs/deep-1"]))

case("或组两个分支都在时只取前一个", lambda: (
    deps([stanza("app-misc/a-1", rdepend="|| ( dev-libs/lib dev-libs/deep )"),
          LIB, DEEP])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("或组一个分支都满足不了时什么都不发", lambda: (
    deps([stanza("app-misc/a-1", rdepend="|| ( dev-libs/gone dev-libs/missing )"), LIB])
    == ["app-misc/a-1"]))

case("或组满足不了要记进未解析清单", lambda: (
    (lambda u: any("||" in a for a in u))(
        run([stanza("app-misc/a-1", rdepend="|| ( dev-libs/gone dev-libs/missing )")],
            with_deps=True)[4])))

case("索引中不存在的原子记进未解析清单", lambda: (
    (lambda u: [a for a in u] == ["sys-libs/glibc"])(
        run([stanza("app-misc/a-1", rdepend="sys-libs/glibc")], with_deps=True)[4])))

case("未解析清单记下是谁引用的", lambda: (
    run([stanza("app-misc/a-1", rdepend="sys-libs/glibc")],
        with_deps=True)[4]["sys-libs/glibc"] == {"app-misc/a-1"}))

case("virtual 留给使用者的 Portage 从源码解析", lambda: (
    deps([stanza("app-misc/a-1", rdepend="virtual/lib"),
          stanza("virtual/lib-0", repo="gentoo", rdepend="|| ( dev-libs/lib dev-libs/deep )"),
          LIB, DEEP])
    == ["app-misc/a-1"]))

case("PDEPEND 里的包也一起发", lambda: (
    deps([stanza("app-misc/a-1", pdepend="dev-libs/lib"), LIB])
    == ["app-misc/a-1", "dev-libs/lib-1"]))

case("use 条件式里的依赖一并算上", lambda: (
    deps([stanza("app-misc/a-1", rdepend="foo? ( dev-libs/lib ) || ( dev-libs/deep )"),
          LIB, DEEP])
    == ["app-misc/a-1", "dev-libs/deep-1", "dev-libs/lib-1"]))

case("依赖里带 bindist 的仍然被拒", lambda: (
    (lambda r: cpvs(r[0]) == ["app-misc/a-1"]
               and [c for c, _, _ in r[3]] == ["dev-libs/lib-1"])(
        run([stanza("app-misc/a-1", rdepend="dev-libs/lib"),
             stanza("dev-libs/lib-1", repo="gentoo", restrict="bindist")],
            with_deps=True))))

case("被 excluded 的包不做种子，它的依赖也不发", deps_excluded)


bad = 0
for name, fn in CASES:
    try:
        ok = bool(fn())
    except Exception as e:                                  # noqa: BLE001
        ok, name = False, f"{name}（抛异常 {type(e).__name__}: {e}）"
    print(f"  {'✓' if ok else '✗'} {name}")
    bad += not ok

sys.exit(1 if bad else 0)
