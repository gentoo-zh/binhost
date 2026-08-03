#!/usr/bin/env python3

import functools
import pathlib
import re
import sys

try:
    from portage.dep import Atom, match_from_list, use_reduce
    from portage.exception import InvalidAtom, PortageException
    from portage.versions import _pkg_str, vercmp
except ImportError:
    sys.exit("需要 sys-apps/portage：原子匹配与版本比较都用 portage 提供的实现")

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


CPV_SPLIT = re.compile(r"^(?P<cp>.+?)-(?P<ver>[0-9][0-9a-zA-Z._+]*(?:-r[0-9]+)?)$")


def _cp_of(atom):
    """category/package of an atom, with operator, version and slot removed."""
    rest = atom.lstrip("!<>=~").rstrip("*")
    rest = re.sub(r"\[[^\]]*\]$", "", rest)
    rest = re.split(r"::?", rest, maxsplit=1)[0]
    m = CPV_SPLIT.match(rest)
    return m.group("cp") if m else rest


class Masks:
    """package.mask entries, matched through Portage rather than by hand.

    An earlier version compared operators itself and disagreed with Portage on
    revisions: ~pkg-1.2 has to match 1.2-r1, and =pkg-1* has to match 1-r1.
    """

    def __init__(self):
        self.atoms = {}

    def add(self, atom):
        cp = _cp_of(atom)
        self.atoms.setdefault(cp, []).append(atom)

    def __contains__(self, cp):
        """True only when every version is masked, that is a bare atom."""
        return any(a == cp for a in self.atoms.get(cp, ()))

    def named(self):
        return set(self.atoms)

    def masks(self, cp, ver):
        cpv = f"{cp}-{ver}"
        for atom in self.atoms.get(cp, ()):
            try:
                if match_from_list(Atom(atom), [cpv]):
                    return True
            except (InvalidAtom, PortageException):
                continue
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


def runtime_atoms(text):
    """The dependency atoms in a binary package's runtime fields.

    USE conditionals are kept unevaluated and every branch is taken: a binary
    package's own fields are already evaluated, so anything left applies.
    || groups survive as a ["||", ...] node for the caller to decide.

    No EAPI is imposed. The index carries ::repo qualified atoms, which no
    EAPI allows in an ebuild but Portage writes into binary package metadata.
    """
    try:
        return use_reduce(text, matchall=True, opconvert=True, eapi=None,
                          token_class=Atom, is_valid_flag=lambda f: True)
    except PortageException:
        return None


INDEX_FIELDS = ("SLOT", "USE", "IUSE", "KEYWORDS", "EAPI")
"""The stanza fields atom matching reads.

USE and IUSE decide use dependencies, and EAPI decides how a missing IUSE is
read; with neither IUSE nor EAPI present a [flag] dependency matches nothing.
Most stanzas carry no SLOT, which portage already reads as slot 0.
"""


def index_db(fields):
    """A fakedbapi holding the index, so atoms match through Portage.

    Version, revision, slot, sub-slot, repository and USE dependencies are all
    handled by Portage's own matching rather than by taking atoms apart here.
    """
    import portage
    from portage.dbapi.virtual import fakedbapi
    # exclusive_slots would keep only the newest build per slot, and then an
    # exact atom on an older cached version would match nothing at all.
    db = fakedbapi(settings=portage.settings, exclusive_slots=False)
    for f in fields:
        meta = {k: f.get(k, "") for k in INDEX_FIELDS}
        meta["repository"] = f.get("REPO", "")
        cpv = _pkg_str(f["CPV"], metadata=meta, settings=portage.settings)
        db.cpv_inject(cpv, metadata=meta)
    return db


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


GENTOO_TREE = "/var/db/repos/gentoo"


class MetadataUnavailable(Exception):
    pass


def pinned_portdbapi(overlay, tree=GENTOO_TREE):
    """A portdbapi reading exactly the two trees given, not the host's config.

    Locations go through an explicit config so the result does not depend on
    repos.conf or on whether something else imported portage first, and the
    resolved paths are checked afterwards because a silently different tree
    would be answered from with no error.
    """
    import os
    import portage
    env = dict(os.environ)
    env["PORTAGE_REPOSITORIES"] = (
        "[DEFAULT]\nmain-repo = gentoo\n\n"
        f"[gentoo]\nlocation = {tree}\n\n"
        f"[gentoo-zh]\nlocation = {overlay}\nmasters = gentoo\n")
    try:
        db = portage.portdbapi(mysettings=portage.config(env=env))
    except Exception as e:                                  # noqa: BLE001
        raise MetadataUnavailable(str(e)) from e
    for name, want in (("gentoo", str(tree)), ("gentoo-zh", str(overlay))):
        got = db.getRepositoryPath(name)
        if got != want:
            raise MetadataUnavailable(f"{name} resolved to {got}, expected {want}")
    return db
