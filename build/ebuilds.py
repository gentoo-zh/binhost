#!/usr/bin/env python3
"""Reading the overlay: masks, ebuild versions, keywords, RESTRICT.

Every script here needs the same handful of answers about an ebuild tree, and
each used to carry its own copy. The copies drifted, and the drift was not
visible: validate.py's RESTRICT pattern captured the wrong thing for every
ebuild in the overlay that carried bindist, so the one gate against publishing
something undistributable never fired, while gen-packages.py's pattern next to
it was correct.

Kept dependency-free apart from portage's vercmp, because it runs on the mirror
too, where only this file and a couple of scripts are installed.
"""

import pathlib
import re
import sys

try:
    from portage.versions import vercmp
except ImportError:  # 没有 portage 就没法正确比版本，宁可停下也不要读错 ebuild
    sys.exit("需要 sys-apps/portage：版本比较用 portage.versions.vercmp")

ATOM = re.compile(r"^[a-z0-9-]+/[A-Za-z0-9._+-]+$")

# Eclasses that mean the package is compiled here, versus repackaged from
# something upstream already built.
BUILD_ECLASS = {
    "cmake", "meson", "go-module", "cargo", "autotools", "gnome2",
    "distutils-r1", "dotnet-pkg", "qmake-utils", "waf-utils", "scons-utils",
}
PREBUILT_ECLASS = {"unpacker", "rpm", "java-pkg-simple"}


def read_mask(overlay):
    """category/package masked in profiles/package.mask.

    Only the package name, never the version constraint: the list is kept per
    package, and one masked version is reason enough not to take it on now.
    """
    p = pathlib.Path(overlay) / "profiles" / "package.mask"
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


def version_of(ebuild, pn):
    """Version part of an ebuild filename."""
    return ebuild.name[len(pn) + 1:-len(".ebuild")]


def newest_ebuild(pkgdir):
    """Highest non-live ebuild in the directory, or None.

    Uses portage's own vercmp rather than sorting filenames: string order puts
    1.10 before 1.9, and then the licence and RESTRICT come from the wrong file.
    """
    pkgdir = pathlib.Path(pkgdir)
    ebuilds = [e for e in pkgdir.glob("*.ebuild") if "9999" not in e.name]
    if not ebuilds:
        return None
    pn = pkgdir.name
    best = ebuilds[0]
    for e in ebuilds[1:]:
        if (vercmp(version_of(e, pn), version_of(best, pn)) or 0) > 0:
            best = e
    return best


def accepts_amd64(keywords):
    """Whether a KEYWORDS string covers amd64. `*` and `~*` count, `-*` clears."""
    ok = False
    for k in keywords.split():
        if k in ("*", "~*"):
            ok = True
        elif k == "-*":
            ok = False
        elif k.lstrip("~") == "amd64":
            ok = not k.startswith("-")
        elif k == "-amd64":
            ok = False
    return ok


def keywords_of(text):
    """The effective KEYWORDS of an ebuild, or None when it declares none.

    Takes the last assignment, the way bash would. Matches leading whitespace
    because plenty of ebuilds set it inside a conditional.
    """
    kw = re.findall(r'^\s*KEYWORDS="([^"\n]*)"', text, re.M)
    return kw[-1] if kw else None


def restricts_bindist(text):
    """Whether any RESTRICT assignment carries bindist.

    The closing quote is anchored to the same line. [^"]* spans newlines, so a
    pattern that lets the opening quote float runs past the end of the line and
    captures whatever sits between there and the next quote in the file: every
    ebuild in the overlay carrying bindist yielded '\\n\\nRDEPEND='.

    Any assignment counts, not the last one. A missed bindist ships something we
    may not redistribute; a false positive costs one look.
    """
    return any("bindist" in r
               for r in re.findall(r'^\s*RESTRICT="([^"\n]*)"', text, re.M))


def inherits(text):
    """Eclasses the ebuild inherits."""
    return set(" ".join(re.findall(r"^inherit (.+)$", text, re.M)).split())


def read_list(path):
    """One category/package per line, blank lines and comments dropped."""
    p = pathlib.Path(path)
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")]
