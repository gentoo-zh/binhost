#!/usr/bin/env python3

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ebuilds import (                                       # noqa: E402
    ATOM, BUILD_ECLASS, PREBUILT_ECLASS,
    accepts_amd64, inherits, keywords_of, newest_ebuild,
    bindist_state, read_mask, usable_ebuilds, version_of, vercmp,
)


HERE = pathlib.Path(__file__).resolve().parent
LIST = HERE / "packages.txt"
EXCLUDED = HERE / "excluded.txt"



def read_excluded():
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
            notes.append(f"{EXCLUDED.name}:{lineno}: {cp} 已不在 overlay 中，可移除此记录")

    for lineno, raw in enumerate(LIST.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if raw != line:
            errors.append(f"{LIST.name}:{lineno}: 行首或行尾有多余空白： {raw!r}")
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

        usable = usable_ebuilds(pkgdir, masked)
        if not usable:
            if newest_ebuild(pkgdir) is None:
                errors.append(f"{LIST.name}:{lineno}: no non-live ebuild: {cp}")
            else:
                errors.append(
                    f"{LIST.name}:{lineno}: 没有一个版本可构建（全被 mask 或无 amd64）: {cp}")
            continue

        eb, _ = usable[0]
        text = eb.read_text(errors="ignore")

        states = {bindist_state(e.read_text(errors="ignore")) for e, _ in usable}
        if "unknown" in states:
            errors.append(
                f"{LIST.name}:{lineno}: RESTRICT 用了变量或条件式，无法静态判定： {cp}")
        elif states == {"yes"}:
            errors.append(f"{LIST.name}:{lineno}: RESTRICT=bindist, cannot be redistributed: {cp}")

        kw = keywords_of(text)
        if kw is not None and not accepts_amd64(kw):
            errors.append(
                f"{LIST.name}:{lineno}: KEYWORDS 未包含 amd64，建置机无法安装： {cp}")

        eclasses = inherits(text)
        if eclasses & PREBUILT_ECLASS:
            notes.append(f"  {cp:<44} 预编译重打包，收益有限")

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
