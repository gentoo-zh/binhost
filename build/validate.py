#!/usr/bin/env python3
"""Check packages.txt against the overlay.

Run by CI on every pull request. The point is that someone proposing a package
finds out here, not three hours into a build, and not after something
undistributable has already been published.
"""

import pathlib
import re
import sys

# Shared module in the same directory. Only it and a couple of scripts are
# installed on the mirror, so it pulls in nothing extra.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ebuilds import (                                       # noqa: E402
    ATOM, BUILD_ECLASS, PREBUILT_ECLASS,
    accepts_amd64, inherits, keywords_of, newest_ebuild,
    read_mask, restricts_bindist, version_of, vercmp,
)


HERE = pathlib.Path(__file__).resolve().parent
LIST = HERE / "packages.txt"
EXCLUDED = HERE / "excluded.txt"



def read_excluded():
    """category/package -> reason. A missing reason is an error: it is written
    down for whoever comes next."""
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
            # The package is gone from the overlay, so this entry should go
            # too, or the list only grows.
            notes.append(f"{EXCLUDED.name}:{lineno}: {cp} 已不在 overlay 里，可以删掉这条")

    for lineno, raw in enumerate(LIST.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # The build script matches the raw line (grep -E '^...$') while this
        # matches after stripping. Trailing whitespace would pass CI and then
        # silently drop a package from the build, so be strict about the raw
        # line too.
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

    # Compare case-insensitively. In ASCII order net-proxy/Xray sorts before
    # net-proxy/v2rayA, but the list is kept in the order a reader expects.
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

        # A package the overlay masks itself usually says masked for removal.
        # Taking it on only produces all ebuilds masked at build time, and then
        # the package is deleted and the list keeps a dead entry.
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
        if restricts_bindist(text):
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
