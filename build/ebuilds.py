#!/usr/bin/env python3

import functools
import pathlib
import re
import sys

try:
    from portage.versions import vercmp
except ImportError:
    sys.exit("需要 sys-apps/portage：版本比较用 portage.versions.vercmp")

ATOM = re.compile(r"^[a-z0-9-]+/[A-Za-z0-9._+-]+$")

BUILD_ECLASS = {
    "cmake", "meson", "go-module", "cargo", "autotools", "gnome2",
    "distutils-r1", "dotnet-pkg", "qmake-utils", "waf-utils", "scons-utils",
}
PREBUILT_ECLASS = {"unpacker", "rpm", "java-pkg-simple"}

COMPILE_PHASE = re.compile(r"^(src_configure|src_compile)\s*\(\)", re.M)


def builds_from_source(text):
    ecl = inherits(text)
    if ecl & PREBUILT_ECLASS:
        return False
    return bool(ecl & BUILD_ECLASS) or bool(COMPILE_PHASE.search(text))


MASK_OP = re.compile(r"^(!!|!|>=|<=|=|~|>|<)")
CPV_SPLIT = re.compile(r"^(?P<cp>.+?)-(?P<ver>[0-9][0-9a-zA-Z._+]*(?:-r[0-9]+)?)$")


def parse_atom(atom):
    """(cp, op, version) for one atom. op and version are None for a bare atom.

    A version is only legal after an operator, so a bare category/package
    always means every version.
    """
    m = MASK_OP.match(atom)
    op = m.group(1) if m else None
    rest = atom[len(op):] if op else atom
    star = rest.endswith("*")
    rest = rest.rstrip("*")
    rest = re.sub(r"\[[^\]]*\]$", "", rest)
    rest = re.split(r"::", rest, maxsplit=1)[0]
    rest = re.split(r":", rest, maxsplit=1)[0]
    if not op:
        return rest, None, None
    m = CPV_SPLIT.match(rest)
    if not m:
        return rest, None, None
    return m.group("cp"), ("=*" if star and op == "=" else op), m.group("ver")


class Masks:
    """package.mask entries, keeping the version constraint of each atom."""

    def __init__(self):
        self.whole = set()
        self.ranged = {}

    def add(self, atom):
        cp, op, ver = parse_atom(atom)
        if op is None:
            self.whole.add(cp)
        else:
            self.ranged.setdefault(cp, []).append((op, ver))

    def __contains__(self, cp):
        return cp in self.whole

    def named(self):
        return self.whole | set(self.ranged)

    def masks(self, cp, ver):
        if cp in self.whole:
            return True
        for op, mver in self.ranged.get(cp, ()):
            c = vercmp(ver, mver)
            if c is None:
                continue
            if op == "=*" and (ver == mver or ver.startswith(mver + ".")):
                return True
            if (op == "=" and c == 0) or (op == "~" and c == 0):
                return True
            if (op == ">=" and c >= 0) or (op == ">" and c > 0):
                return True
            if (op == "<=" and c <= 0) or (op == "<" and c < 0):
                return True
        return False


def read_mask(overlay):
    out = Masks()
    p = pathlib.Path(overlay) / "profiles" / "package.mask"
    if not p.exists():
        return out
    for raw in p.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.add(line.split()[0])
    return out


def split_cpv(cpv):
    """(cp, version) for a category/package-version string, or (cpv, None)."""
    m = CPV_SPLIT.match(cpv)
    return (m.group("cp"), m.group("ver")) if m else (cpv, None)


CP_ONLY = re.compile(r"^[a-z][a-z0-9+._-]*/[A-Za-z0-9][A-Za-z0-9+._-]*$")


def dep_atoms(text):
    """category/package named anywhere in a dependency string.

    A binary index writes fully qualified atoms such as
    >=sys-libs/glibc-2.43-r2:2.2/2.2=, so the version, the slot and any use
    dependency have to come off before the name is usable. Use conditionals
    are flattened rather than evaluated: this is used to decide what to keep,
    where naming one package too many costs disk and naming one too few
    leaves a dependency unpublished.
    """
    out = set()
    for token in text.split():
        if token in ("(", ")", "||", "&&") or token.endswith("?"):
            continue
        token = token.lstrip("!<>=~").split("[", 1)[0].split(":", 1)[0].rstrip("=*")
        if "/" not in token:
            continue
        cp = split_cpv(token)[0]
        if CP_ONLY.match(cp):
            out.add(cp)
    return out


def version_of(ebuild, pn):
    return ebuild.name[len(pn) + 1:-len(".ebuild")]


def newest_ebuild(pkgdir):
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


def usable_ebuilds(pkgdir, masks=None):
    """(ebuild, version), newest first, dropping 9999, masked and non-amd64.

    Used where "can we still build anything here" is the question, so that a
    mask or a dropped keyword on the newest version alone does not make the
    whole package look gone.
    """
    pkgdir = pathlib.Path(pkgdir)
    cp = f"{pkgdir.parent.name}/{pkgdir.name}"
    out = []
    for e in pkgdir.glob("*.ebuild"):
        if "9999" in e.name:
            continue
        ver = version_of(e, pkgdir.name)
        if masks is not None and masks.masks(cp, ver):
            continue
        kw = keywords_of(e.read_text(errors="ignore"))
        if kw is not None and not accepts_amd64(kw):
            continue
        out.append((e, ver))
    out.sort(key=functools.cmp_to_key(
        lambda a, b: vercmp(a[1], b[1]) or 0), reverse=True)
    return out


def accepts_amd64(keywords):
    ks = set(keywords.split())
    if "-amd64" in ks:
        return False
    if ks & {"amd64", "~amd64"}:
        return True
    return bool(ks & {"*", "~*"})


def keywords_of(text):
    kw = re.findall(r'^\s*KEYWORDS="([^"]*)"', text, re.M)
    return kw[-1] if kw else None


RESTRICT_ASSIGN = re.compile(
    r'(?P<pre>^[^\n#]*?)RESTRICT(?P<plus>\+?)='
    r'(?:"(?P<dq>[^"]*)"|\'(?P<sq>[^\']*)\'|(?P<bare>[^\s#;)]+))', re.M)

BLOCK_OPEN = re.compile(r"^\s*(if|for|while|until|case)\b|\{\s*$|\(\)\s*\{")
BLOCK_CLOSE = ("fi", "done", "esac", "}", ";;")


def _assignments(text):
    for m in RESTRICT_ASSIGN.finditer(text):
        val = next((m.group(k) for k in ("dq", "sq", "bare")
                    if m.group(k) is not None), "")
        yield m, val


def restrict_tokens(text):
    cur = []
    for m, val in _assignments(text):
        cur = cur + val.split() if m.group("plus") else val.split()
    return set(cur)


EXPANSION = re.compile(r"[$`]")


def restrict_uncertain(text):
    plain = [m for m, _ in _assignments(text) if not m.group("plus")]
    if len(plain) > 1:
        return True
    for m, val in _assignments(text):
        if EXPANSION.search(val):
            return True
        if m.group("pre").strip():
            return True
        depth = 0
        for line in text[:m.start()].splitlines():
            s = line.strip()
            if BLOCK_OPEN.search(line):
                depth += 1
            elif s in BLOCK_CLOSE:
                depth = max(0, depth - 1)
        if depth:
            return True
    return False


def restricts_bindist(text):
    return "bindist" in restrict_tokens(text)


def bindist_state(text):
    """yes / no / unknown. unknown when the value cannot be read statically.

    Callers must fail closed on unknown: do not publish it, and do not
    propose retiring it either.
    """
    if restrict_uncertain(text):
        return "unknown"
    return "yes" if restricts_bindist(text) else "no"


def inherits(text):
    return set(" ".join(re.findall(r"^inherit (.+)$", text, re.M)).split())


def read_list(path):
    p = pathlib.Path(path)
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")]
