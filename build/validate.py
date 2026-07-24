#!/usr/bin/env python3
"""Check packages.txt against the overlay.

Run by CI on every pull request. The point is that someone proposing a package
finds out here, not three hours into a build, and not after something
undistributable has already been published.
"""

import pathlib
import re
import sys

try:
    from portage.versions import vercmp
except ImportError:  # 没有 portage 就没法正确比版本，宁可停下也不要读错 ebuild
    sys.exit("需要 sys-apps/portage：版本比较用 portage.versions.vercmp")

HERE = pathlib.Path(__file__).resolve().parent
LIST = HERE / "packages.txt"
EXCLUDED = HERE / "excluded.txt"

ATOM = re.compile(r"^[a-z0-9-]+/[A-Za-z0-9._+-]+$")


def read_mask(overlay):
    """profiles/package.mask 里被屏蔽的 category/package。

    只取包名，不管版本限制：清单是按包收的，某个版本被屏蔽也说明这个包
    现在不适合收进来。
    """
    p = overlay / "profiles" / "package.mask"
    if not p.exists():
        return set()
    out = set()
    for raw in p.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.search(r"[a-z0-9-]+/[A-Za-z0-9._+-]+", line.lstrip("<>=~!"))
        if m:
            out.add(re.sub(r"-[0-9][^/]*$", "", m.group(0)))
    return out


def newest_ebuild(pkgdir):
    """目录里版本最高的非 live ebuild。

    用 portage 自己的 vercmp，不按文件名排序：字符串序会把 1.10 排在 1.9
    前面，读到的就是错的那个 ebuild，许可证和 RESTRICT 也就查错了。
    """
    ebuilds = [e for e in pkgdir.glob("*.ebuild") if "9999" not in e.name]
    if not ebuilds:
        return None
    pn = pkgdir.name
    best = ebuilds[0]
    for e in ebuilds[1:]:
        a = e.name[len(pn) + 1:-len(".ebuild")]
        b = best.name[len(pn) + 1:-len(".ebuild")]
        if (vercmp(a, b) or 0) > 0:
            best = e
    return best


def read_excluded():
    """category/package -> 原因。缺原因就是错误：写下来是为了给后来的人看。"""
    out = {}
    if not EXCLUDED.exists():
        return out
    for lineno, raw in enumerate(EXCLUDED.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = re.split(r"\s{2,}|\t", line, maxsplit=1)
        cp = parts[0].strip()
        reason = parts[1].strip() if len(parts) > 1 else ""
        out[cp] = (lineno, reason)
    return out


def main(overlay):
    overlay = pathlib.Path(overlay)
    if not (overlay / "profiles" / "repo_name").exists():
        sys.exit(f"not an ebuild repository: {overlay}")

    errors, notes = [], []
    atoms = []

    excluded = read_excluded()
    for cp, (lineno, reason) in excluded.items():
        if not ATOM.match(cp):
            errors.append(f"{EXCLUDED.name}:{lineno}: 不是 category/package: {cp!r}")
        elif not reason:
            errors.append(f"{EXCLUDED.name}:{lineno}: {cp} 没写原因")
        elif not (overlay / cp).is_dir():
            # 包已经从 overlay 移除了，这条也该删掉，否则清单只会越积越长
            notes.append(f"{EXCLUDED.name}:{lineno}: {cp} 已不在 overlay 里，可以删掉这条")

    for lineno, raw in enumerate(LIST.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # 构建脚本按原始行匹配（grep -E '^…$'），这里按 strip 后匹配。
        # 尾部有空白时 CI 会过而构建会静默少一个包，所以原始行也要严格。
        if raw != line:
            errors.append(f"{LIST.name}:{lineno}: 行首或行尾有多余空白: {raw!r}")
            continue
        if not ATOM.match(line):
            errors.append(f"{LIST.name}:{lineno}: not a category/package atom: {raw!r}")
            continue
        atoms.append((lineno, line))

    for lineno, cp in atoms:
        if cp in excluded:
            errors.append(
                f"{LIST.name}:{lineno}: {cp} 同时在 {EXCLUDED.name} 里"
                f"（{excluded[cp][1]}），两份清单互斥")

    seen = {}
    for lineno, cp in atoms:
        if cp in seen:
            errors.append(f"{LIST.name}:{lineno}: duplicate of line {seen[cp]}: {cp}")
        seen[cp] = lineno

    # 不分大小写地比。net-proxy/Xray 和 net-proxy/v2rayA 在 ASCII 序里
    # 大写会排到小写前面，但清单是按人眼顺序排的。
    names = [cp.lower() for _, cp in atoms]
    if names != sorted(names):
        for i in range(1, len(names)):
            if names[i] < names[i - 1]:
                errors.append(
                    f"{LIST.name}: out of order: {names[i]} should come before {names[i - 1]}")
                break

    masked = read_mask(overlay)

    for lineno, cp in atoms:
        pkgdir = overlay / cp
        if not pkgdir.is_dir():
            errors.append(f"{LIST.name}:{lineno}: not in the overlay: {cp}")
            continue

        # overlay 自己 mask 掉的包大多写着 masked for removal，收进来只会在
        # 构建时报「所有版本都被屏蔽」，然后包被删掉，清单里留一条死条目。
        if cp in masked:
            errors.append(f"{LIST.name}:{lineno}: overlay 的 package.mask 屏蔽了它: {cp}")
            continue
        eb = newest_ebuild(pkgdir)
        if eb is None:
            errors.append(f"{LIST.name}:{lineno}: no non-live ebuild: {cp}")
            continue

        text = eb.read_text(errors="ignore")

        # RESTRICT=bindist means upstream forbids redistributing what we build.
        # ACCEPT_LICENSE also gates this at build time, but by then someone has
        # already spent review effort on the pull request.
        restrict = re.search(r'^RESTRICT=(?:.*")([^"]*)"', text, re.M) or \
                   re.search(r'^RESTRICT="([^"]*)"', text, re.M)
        if restrict and "bindist" in restrict.group(1):
            errors.append(f"{LIST.name}:{lineno}: RESTRICT=bindist, cannot be redistributed: {cp}")

        lic = re.search(r'^LICENSE="([^"]*)"', text, re.M)
        notes.append(f"  {cp:<44} {lic.group(1) if lic else '(no LICENSE)'}")

    print(f">>> {len(atoms)} packages checked against {overlay}")
    if notes:
        print("\nLicences, for review:")
        print("\n".join(notes))

    if errors:
        print(f"\n!!! {len(errors)} problem(s):", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)
        return 1
    print("\n>>> ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/var/db/repos/gentoo-zh"))
