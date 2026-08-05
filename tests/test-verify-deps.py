#!/usr/bin/env python3

import importlib.util
import pathlib
import sys

BUILD = pathlib.Path(__file__).resolve().parent.parent / "build"

spec = importlib.util.spec_from_file_location("verify_deps", BUILD / "verify-deps.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)

HEADER = "ACCEPT_KEYWORDS: ~amd64\nPACKAGES: 9\nTIMESTAMP: 1\nVERSION: 0"


def stanza(cpv, repo="gentoo-zh", rdepend=None, slot="0", use=None, iuse=None,
           eapi="8"):
    cp = cpv.rsplit("-", 1)[0]
    lines = [f"CPV: {cpv}", f"PATH: {cp}/{cpv.split('/')[-1]}.gpkg.tar",
             f"REPO: {repo}", f"EAPI: {eapi}"]
    if slot is not None:
        lines.append(f"SLOT: {slot}")
    if use:
        lines.append(f"USE: {use}")
    if iuse:
        lines.append(f"IUSE: {iuse}")
    if rdepend:
        lines.append(f"RDEPEND: {rdepend}")
    return "\n".join(lines)


def installed_db(packages):
    fields = []
    for value in packages:
        cpv = value if value.rsplit("/", 1)[-1].rsplit("-", 1)[-1][:1].isdigit() \
            else f"{value}-1"
        fields.append({"CPV": cpv, "SLOT": "0", "EAPI": "8", "REPO": "gentoo"})
    return verify.index_db(fields)


def run(stanzas, installed=None, available=None):
    fields = verify.parse(HEADER + "\n\n" + "\n\n".join(stanzas) + "\n")
    if isinstance(installed, set):
        installed = installed_db(installed)
    if isinstance(available, set):
        available = installed_db(available)
    return verify.check(fields, installed, available)


def run_main(stanzas, exceptions=None, installed=None, no_installed_file=False,
             available=None):
    import contextlib, io, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        (d / "Packages").write_text(HEADER + "\n\n" + "\n\n".join(stanzas) + "\n")
        exc = d / "exc.txt"
        exc.write_text(exceptions or "")
        inst = str(d / "installed.txt")
        if no_installed_file:
            inst = str(d / "missing.txt")
        else:
            (d / "installed.txt").write_text(
                installed if installed is not None else "PACKAGES: 0\nVERSION: 1\n\n")
        available_path = None
        if available is not None:
            available_path = str(d / "official.txt")
            (d / "official.txt").write_text(available)
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = verify.main(str(d / "Packages"), exceptions=str(exc),
                                 installed=inst, available=available_path)
        except SystemExit as e:
            return 2, out.getvalue(), f"{err.getvalue()}{e}"
        return rc, out.getvalue(), err.getvalue()


CASES = []


def case(name, fn):
    CASES.append((name, fn))


case("依赖有可匹配的已发布版本时通过", lambda: (
    (lambda r: not r[0] and not r[1])(
        run([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-1"),
             stanza("dev-libs/lib-2", repo="gentoo")], installed=set()))))

case("基础系统清单里有的包不算缺陷", lambda: (
    (lambda r: not r[0] and set(r[1]) == {"sys-libs/glibc"})(
        run([stanza("app-misc/a-1", rdepend="sys-libs/glibc")],
            installed={"sys-libs/glibc"}))))

case("Gentoo binhost 清单里有的包不算缺陷", lambda: (
    (lambda r: not r[0] and set(r[2]) == {">=dev-libs/lib-2"})(
        run([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-2")],
            installed=set(), available={"dev-libs/lib-2"}))))

case("索引与基础系统都没有的包算缺陷，不再默认成基础系统", lambda: (
    (lambda r: set(r[0]) == {"sys-libs/glibc"} and not r[1])(
        run([stanza("app-misc/a-1", rdepend="sys-libs/glibc")], installed=set()))))

case("没有基础系统清单时一律计为未满足", lambda: (
    (lambda r: set(r[0]) == {"sys-libs/glibc"} and not r[1])(
        run([stanza("app-misc/a-1", rdepend="sys-libs/glibc")]))))

case("包在索引里但版本不满足时算缺陷", lambda: (
    (lambda r: set(r[0]) == {">=dev-libs/lib-2"} and not r[1])(
        run([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-2"),
             stanza("dev-libs/lib-1", repo="gentoo")]))))

case("slot 不满足时算缺陷", lambda: (
    (lambda r: set(r[0]) == {"dev-libs/lib:2"})(
        run([stanza("app-misc/a-1", rdepend="dev-libs/lib:2"),
             stanza("dev-libs/lib-1", repo="gentoo", slot="0")]))))

case("USE 依赖不满足时算缺陷", lambda: (
    (lambda r: set(r[0]) == {"dev-libs/lib[foo]"})(
        run([stanza("app-misc/a-1", rdepend="dev-libs/lib[foo]"),
             stanza("dev-libs/lib-1", repo="gentoo", use="bar", iuse="foo bar")]))))

case("或组后面的分支满足时，前面失败的分支不算发现", lambda: (
    (lambda r: not r[0] and not r[1])(
        run([stanza("app-misc/a-1", rdepend="|| ( >=dev-libs/lib-9 dev-libs/other )"),
             stanza("dev-libs/lib-1", repo="gentoo"),
             stanza("dev-libs/other-1", repo="gentoo")]))))

case("万用版本按 Atom 的 cp 归类，不是当成没这个包", lambda: (
    (lambda r: set(r[0]) == {"=dev-libs/a-2*"} and not r[1])(
        run([stanza("app-misc/a-1", rdepend="=dev-libs/a-2*"),
             stanza("dev-libs/a-1", repo="gentoo")]))))

case("带 slot 与 use 的原子同样按 cp 归类", lambda: (
    (lambda r: set(r[0]) == {"dev-libs/a:9"})(
        run([stanza("app-misc/a-1", rdepend="dev-libs/a:9"),
             stanza("dev-libs/a-1", repo="gentoo")]))))

case("或组只要有一个分支满足就算通过", lambda: (
    (lambda r: not r[0])(
        run([stanza("app-misc/a-1", rdepend="|| ( dev-libs/lib sys-libs/glibc )"),
             stanza("dev-libs/lib-1", repo="gentoo")]))))

case("或组的分支由基础系统提供时，整组算满足", lambda: (
    (lambda r: not r[0] and set(r[1]) == {"sys-libs/glibc"})(
        run([stanza("app-misc/a-1", rdepend="|| ( >=dev-libs/lib-9 sys-libs/glibc )"),
             stanza("dev-libs/lib-1", repo="gentoo")],
            installed={"sys-libs/glibc"}))))

case("或组的分支索引与基础系统都没有时才算缺陷", lambda: (
    (lambda r: set(r[0]) == {">=dev-libs/lib-9", "sys-libs/glibc"} and not r[1])(
        run([stanza("app-misc/a-1", rdepend="|| ( >=dev-libs/lib-9 sys-libs/glibc )"),
             stanza("dev-libs/lib-1", repo="gentoo")],
            installed=set()))))

case("USE 依赖写在或组的基础系统分支上时也算满足", lambda: (
    (lambda r: not r[0])(
        run([stanza("app-misc/a-1",
                    rdepend="|| ( net-misc/iputils[arping(+)] net-analyzer/arping )")],
            installed={"net-misc/iputils"}))))

case("blocker 不算依赖", lambda: (
    (lambda r: not r[0] and not r[1])(
        run([stanza("app-misc/a-1", rdepend="!dev-libs/lib")]))))

case("省略 SLOT 的 stanza 按默认值 0 满足 :0 依赖", lambda: (
    (lambda r: not r[0])(
        run([stanza("app-misc/a-1", rdepend="dev-libs/lib:0"),
             stanza("dev-libs/lib-1", repo="gentoo", slot=None)]))))

case("记下是哪些包引用了不满足的原子", lambda: (
    run([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-2"),
         stanza("app-misc/b-1", rdepend=">=dev-libs/lib-2"),
         stanza("dev-libs/lib-1", repo="gentoo")])[0][">=dev-libs/lib-2"]
    == {"app-misc/a-1", "app-misc/b-1"}))

case("精确版本指到旧的那一个时算满足", lambda: (
    (lambda r: not r[0])(
        run([stanza("app-misc/a-1", rdepend="=dev-libs/lib-1"),
             stanza("dev-libs/lib-1", repo="gentoo"),
             stanza("dev-libs/lib-2", repo="gentoo")]))))

case("基础系统清单不存在时直接判不通过", lambda: (
    (lambda r: r[0] == 2 and "无法读取基础系统清单" in r[2])(
        run_main([stanza("app-misc/a-1", rdepend="sys-libs/glibc")],
                 no_installed_file=True))))

case("结构化快照按完整原子匹配", lambda: (
    run_main([stanza("app-misc/a-1", rdepend="sys-libs/glibc")],
             installed="PACKAGES: 1\nVERSION: 1\n\nCPV: sys-libs/glibc-2.43-r2\n"
                       "SLOT: 0\nUSE:\nIUSE:\nEAPI: 8\nREPO: gentoo\n")[0] == 0))

case("缺少匹配字段的结构化快照直接判不通过", lambda: (
    (lambda r: r[0] == 2 and "不是完整的基础系统快照" in r[2])(
        run_main([stanza("app-misc/a-1", rdepend="sys-libs/glibc")],
                 installed="PACKAGES: 1\nVERSION: 1\n\n"
                           "CPV: sys-libs/glibc-2.43-r2\nSLOT: 0\n"))))

case("基础快照版本不满足时算缺陷", lambda: (
    (lambda r: set(r[0]) == {">=dev-libs/lib-2"})(
        verify.check(
            verify.parse(HEADER + "\n\n" +
                         stanza("app-misc/a-1", rdepend=">=dev-libs/lib-2") + "\n"),
            verify.index_db([{"CPV": "dev-libs/lib-1", "SLOT": "0",
                              "EAPI": "8", "REPO": "gentoo"}])))))

case("基础快照 slot 不满足时算缺陷", lambda: (
    (lambda r: set(r[0]) == {"dev-libs/lib:2"})(
        verify.check(
            verify.parse(HEADER + "\n\n" +
                         stanza("app-misc/a-1", rdepend="dev-libs/lib:2") + "\n"),
            verify.index_db([{"CPV": "dev-libs/lib-1", "SLOT": "0",
                              "EAPI": "8", "REPO": "gentoo"}])))))

case("基础快照 USE 不满足时算缺陷", lambda: (
    (lambda r: set(r[0]) == {"dev-libs/lib[foo]"})(
        verify.check(
            verify.parse(HEADER + "\n\n" +
                         stanza("app-misc/a-1", rdepend="dev-libs/lib[foo]") + "\n"),
            verify.index_db([{"CPV": "dev-libs/lib-1", "SLOT": "0",
                              "USE": "bar", "IUSE": "foo bar", "EAPI": "8",
                              "REPO": "gentoo"}])))))

case("基础快照仓库不满足时算缺陷", lambda: (
    (lambda r: set(r[0]) == {"dev-libs/lib::gentoo-zh"})(
        verify.check(
            verify.parse(HEADER + "\n\n" + stanza(
                "app-misc/a-1", rdepend="dev-libs/lib::gentoo-zh") + "\n"),
            verify.index_db([{"CPV": "dev-libs/lib-1", "SLOT": "0",
                              "EAPI": "8", "REPO": "gentoo"}])))))

case("旧式 CPV 清单直接判不通过", lambda: (
    (lambda r: r[0] == 2 and "不是完整的基础系统快照" in r[2])(
        run_main([stanza("app-misc/a-1", rdepend="sys-libs/glibc")],
                 installed="sys-libs/glibc-2.43-r2\n"))))

case("不完整的 Gentoo binhost 快照直接判不通过", lambda: (
    (lambda r: r[0] == 2 and "不是完整的Gentoo binhost 可用包快照" in r[2])(
        run_main([stanza("app-misc/a-1", rdepend="dev-libs/lib")],
                 available="PACKAGES: 1\nVERSION: 1\n\n"
                           "CPV: dev-libs/lib-2\nSLOT: 0\n"))))

case("不满足时退出码非零", lambda: (
    run_main([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-2"),
              stanza("dev-libs/lib-1", repo="gentoo")])[0] == 1))

case("列进例外之后不再失败", lambda: (
    run_main([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-2"),
              stanza("dev-libs/lib-1", repo="gentoo")],
             exceptions=">=dev-libs/lib-2\t知道，暂时如此\n")[0] == 0))

case("例外本轮已能满足时报出应删除", lambda: (
    "应从 dep-exceptions.txt 删除" in run_main(
        [stanza("app-misc/a-1", rdepend=">=dev-libs/lib-1"),
         stanza("dev-libs/lib-2", repo="gentoo")],
        exceptions=">=dev-libs/lib-1\t早先的例外\n")[2]))

case("例外指的原子索引里没提到时不报应删除", lambda: (
    "应从 dep-exceptions.txt 删除" not in run_main(
        [stanza("app-misc/a-1")],
        exceptions=">=dev-libs/lib-1\t与本索引无关\n")[2]))

case("注释与空行不算例外", lambda: (
    run_main([stanza("app-misc/a-1", rdepend=">=dev-libs/lib-2"),
              stanza("dev-libs/lib-1", repo="gentoo")],
             exceptions="# >=dev-libs/lib-2\t被注释掉了\n\n")[0] == 1))


def generated_available_snapshot():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        package = root / "Packages"
        package.write_text(
            HEADER + "\n\n" +
            stanza("app-misc/a-1", rdepend="dev-libs/lib[foo]") + "\n")
        installed = root / "installed.txt"
        installed.write_text("PACKAGES: 0\nVERSION: 1\n\n")
        source = root / "source-Packages"
        source.write_text(
            "PACKAGES: 2\nTIMESTAMP: 123\nVERSION: 0\n\n" +
            stanza("dev-libs/lib-2", repo="gentoo", use="foo", iuse="foo") +
            "\n\n" + stanza("dev-libs/unused-1", repo="gentoo") + "\n")
        output = root / "official.txt"
        if verify.main(package, installed=installed, available=source,
                       write_available_path=output) != 0:
            return False
        text = output.read_text()
        if ("CPV: dev-libs/lib-2" not in text or
                "CPV: dev-libs/unused-1" in text or
                "SOURCE_TIMESTAMP: 123" not in text):
            return False
        if verify.main(package, installed=installed, available=output) != 0:
            return False
        output.write_text(text.replace("USE: foo", "USE: bar"))
        return verify.main(package, installed=installed, available=output) == 1


case("可用包快照只保留用到的 CP，且损坏匹配字段后会失败",
     generated_available_snapshot)


def generated_source_snapshot():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        package = root / "Packages"
        package.write_text(
            HEADER + "\n\n" + stanza(
                "app-misc/a-1", rdepend=">=media-libs/openh264-2.4:0/8=") + "\n")
        installed = root / "installed.txt"
        installed.write_text("PACKAGES: 0\nVERSION: 1\n\n")
        official = root / "official.txt"
        official.write_text("PACKAGES: 0\nVERSION: 1\n\n")
        source = root / "source.txt"

        def resolve(atom):
            assert str(atom) == ">=media-libs/openh264-2.4:0/8="
            return [{"CPV": "media-libs/openh264-2.6.0", "SLOT": "0/8",
                     "USE": "", "IUSE": "", "EAPI": "8", "REPO": "gentoo"}]

        if verify.main(package, installed=installed, available=official,
                       source_tree=root, write_source_path=source,
                       resolve_source=resolve) != 0:
            return False
        text = source.read_text()
        if verify.main(package, installed=installed, available=official,
                       source=source) != 0:
            return False
        source.write_text(text.replace("SLOT: 0/8", "SLOT: 0/7"))
        return verify.main(package, installed=installed, available=official,
                           source=source) == 1


case("源码快照按完整原子筛选，且不把 slot 不符的版本算作可用",
     generated_source_snapshot)


def generated_overlay_source_snapshot():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        package = root / "Packages"
        package.write_text(
            HEADER + "\n\n" + stanza(
                "app-misc/a-1", rdepend="virtual/local::gentoo-zh") + "\n")
        installed = root / "installed.txt"
        installed.write_text("PACKAGES: 0\nVERSION: 1\n\n")
        official = root / "official.txt"
        official.write_text("PACKAGES: 0\nVERSION: 1\n\n")
        source = root / "source.txt"
        overlay = root / "overlay"
        overlay.mkdir()

        def resolve(atom):
            assert str(atom) == "virtual/local::gentoo-zh"
            return [{"CPV": "virtual/local-0", "SLOT": "0", "USE": "",
                     "IUSE": "", "EAPI": "8", "REPO": "gentoo-zh"}]

        if verify.main(package, installed=installed, available=official,
                       source_tree=root, source_overlay=overlay,
                       write_source_path=source, resolve_source=resolve) != 0:
            return False
        text = source.read_text()
        if "SOURCE_OVERLAY_REPOSITORY: gentoo-zh" not in text:
            return False
        if verify.main(package, installed=installed, available=official,
                       source=source) != 0:
            return False
        source.write_text(text.replace("REPO: gentoo-zh", "REPO: gentoo"))
        return verify.main(package, installed=installed, available=official,
                           source=source) == 1


case("gentoo-zh 的本地安装依赖写入源码快照并保留仓库约束",
     generated_overlay_source_snapshot)

case("源码快照只启用 IUSE 中带加号的默认项", lambda: (
    verify.default_use("+ssl -minimal python +zstd") == "ssl zstd"))


def generated_source_only_use_snapshot():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        package = root / "Packages"
        package.write_text(
            HEADER + "\n\n" + stanza(
                "dev-vcs/git-2.55.0",
                rdepend=">=virtual/perl-libnet-3.110.0-r4[ssl,-minimal]") + "\n")
        installed = root / "installed.txt"
        installed.write_text("PACKAGES: 0\nVERSION: 1\n\n")
        official = root / "official.txt"
        official.write_text("PACKAGES: 0\nVERSION: 1\n\n")
        source = root / "source.txt"

        def resolve(atom):
            assert str(atom) == ">=virtual/perl-libnet-3.110.0-r4[ssl,-minimal]"
            return [{"CPV": "virtual/perl-libnet-3.150.0-r3", "SLOT": "0",
                     "USE": "ssl", "IUSE": "+ssl -minimal", "EAPI": "8",
                     "REPO": "gentoo"}]

        if verify.main(package, installed=installed, available=official,
                       source_tree=root, write_source_path=source,
                       resolve_source=resolve) != 0:
            return False
        text = source.read_text()
        if "USE: ssl" not in text or "IUSE: +ssl -minimal" not in text:
            return False
        source.write_text(text.replace("USE: ssl", "USE:"))
        return verify.main(package, installed=installed, available=official,
                           source=source) == 1


case("本地安装类别按 ebuild 默认 USE 满足带 USE 约束的原子",
     generated_source_only_use_snapshot)

case("带 USE 约束的原子不会由未知配置的源码包兜底", lambda: (
    not verify.select_source(
        {"dev-libs/lib[foo]"},
        lambda atom: [{"CPV": "dev-libs/lib-1", "SLOT": "0", "USE": "foo",
                       "IUSE": "foo", "EAPI": "8", "REPO": "gentoo"}])))


def real_source_visibility(host_file=None, host_value="", keywords="~amd64",
                           license_name="MIT", profile_mask=False,
                           repository="gentoo-zh", source_keywords="~amd64",
                           overlay_keywords=None):
    import tempfile
    from portage.dep import Atom
    from portage.package.ebuild.config import LocationsManager

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        root.chmod(0o755)
        tree = root / "gentoo"
        overlay = root / "gentoo-zh"
        for repo, name in ((tree, "gentoo"), (overlay, "gentoo-zh")):
            profiles = repo / "profiles"
            profiles.mkdir(parents=True)
            (profiles / "repo_name").write_text(name + "\n")
            (profiles / "categories").write_text("app-misc\n")
        (tree / "profiles/license_groups").write_text("FREE MIT\n")
        tree_metadata = tree / "metadata"
        tree_metadata.mkdir()
        (tree_metadata / "layout.conf").write_text("thin-manifests = true\n")
        profile = tree / "profiles/test"
        profile.mkdir()
        (profile / "eapi").write_text("8\n")
        (profile / "make.defaults").write_text(
            'ARCH="amd64"\nACCEPT_LICENSE="@FREE"\n')
        if profile_mask:
            (profile / "package.mask").write_text("app-misc/example\n")

        metadata = overlay / "metadata"
        metadata.mkdir()
        (metadata / "layout.conf").write_text(
            "masters = gentoo\nthin-manifests = true\n")
        repo_path = overlay if repository == "gentoo-zh" else tree
        package = repo_path / "app-misc/example"
        package.mkdir(parents=True)
        (package / "example-1.ebuild").write_text(
            f'EAPI=8\nSLOT="0"\nKEYWORDS="{keywords}"\n'
            f'LICENSE="{license_name}"\n')
        (package / "Manifest").write_text("")

        config = root / "host/etc/portage"
        config.mkdir(parents=True)
        (config / "make.profile").symlink_to(profile)
        if host_file is not None:
            (config / host_file).write_text(host_value + "\n")

        real_init = LocationsManager.__init__

        def host_config(self, *args, **kwargs):
            if kwargs.get("config_root") is None:
                kwargs["config_root"] = str(root / "host")
            return real_init(self, *args, **kwargs)

        LocationsManager.__init__ = host_config
        try:
            resolve = verify.source_resolver(
                tree, overlay, source_keywords, overlay_keywords)
            return resolve(Atom(f"app-misc/example::{repository}"))
        finally:
            LocationsManager.__init__ = real_init


case("源码快照不读取主机 package.mask", lambda: (
    [field["CPV"] for field in real_source_visibility(
        "package.mask", "app-misc/example")] == ["app-misc/example-1"]))

case("源码快照不读取主机 package.accept_keywords", lambda: (
    not real_source_visibility(
        "package.accept_keywords", "app-misc/example **", keywords="")))

case("源码快照不读取主机 package.unmask", lambda: (
    not real_source_visibility(
        "package.unmask", "app-misc/example", profile_mask=True)))

case("stable 源码快照接受 overlay 的测试关键字", lambda: (
    [field["CPV"] for field in real_source_visibility(
        source_keywords="amd64", overlay_keywords="~amd64")] ==
    ["app-misc/example-1"]))

case("stable 源码快照拒绝 Gentoo 主树的测试关键字", lambda: (
    not real_source_visibility(
        "make.conf", 'ACCEPT_KEYWORDS="~amd64"', repository="gentoo",
        source_keywords="amd64", overlay_keywords="~amd64")))

case("stable 源码快照接受 Gentoo 主树的稳定关键字", lambda: (
    [field["CPV"] for field in real_source_visibility(
        keywords="amd64", repository="gentoo", source_keywords="amd64",
        overlay_keywords="~amd64")] == ["app-misc/example-1"]))

case("源码快照明确接受源码包的许可证", lambda: (
    [field["CPV"] for field in real_source_visibility(
        license_name="all-rights-reserved")] == ["app-misc/example-1"]))

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
