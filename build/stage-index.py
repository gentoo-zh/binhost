#!/usr/bin/env python3
"""Pick what gets published out of the build cache, and write the index for it.

PKGDIR holds every dependency built or fetched along the way. Those are not ours
to publish and of no use to our users, so a filter decides what leaves this
machine. That decision is the last thing standing between the build cache and
what users install, which is why it lives in its own file with its own cases
instead of inside a shell heredoc.

    stage-index.py <pkgdir> <stage> [overlay]

`overlay` is optional; when given, packages whose category/package no longer
exists there are dropped.
"""

import os
import pathlib
import re
import shutil
import sys
import time


def parse(text):
    """Packages index -> (header, [(fields, stanza), ...])."""
    stanzas = text.split("\n\n")
    out = []
    for s in stanzas[1:]:
        if not s.strip():
            continue
        f = dict(re.findall(r"^(\w+): (.*)$", s, re.M))
        if f.get("CPV"):
            out.append((f, s))
    return stanzas[0], out


def read_excluded():
    """category/package that excluded.txt says outright not to collect.

    PKGDIR keeps whatever was ever built. A package that was built once and only
    later excluded stays there and is republished every round, because nothing
    downstream reads the list: the publisher deletes by what the index names,
    and the index is what this file produces. app-text/wiki2man_on_rust was
    served that way for as long as it had been excluded.
    """
    f = pathlib.Path(__file__).with_name("excluded.txt")
    if not f.exists():
        return set()
    return {l.split()[0] for l in f.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")}


def select(entries, overlay=None, excluded=None):
    """Which entries to publish. Returns (kept, skipped, error).

    error is a string when something must stop the whole round rather than be
    quietly dropped.
    """
    excluded = read_excluded() if excluded is None else excluded
    best = {}       # cpv -> (build_id, fields, stanza)
    skipped = 0

    for f, s in entries:
        cpv = f["CPV"]

        # Decide by REPO, not by whether the overlay has a directory of that
        # name. A directory check misses two cases: the overlay carries only a
        # -9999 while what actually built is ::gentoo's release (fcitx, librime),
        # and the overlay's version is lower than ::gentoo's so portage picked
        # ::gentoo (libdatrie, libthai). Both deliver a ::gentoo build.
        if f.get("REPO") != "gentoo-zh":
            skipped += 1
            continue

        # A package treecleaned from the overlay stays in PKGDIR forever, and
        # the publisher deletes by what the index names, so without this it
        # would be served indefinitely.
        if overlay is not None:
            cp = re.match(r"^([a-z0-9-]+/.+?)-[0-9]", cpv)
            if cp and not (overlay / cp.group(1)).is_dir():
                skipped += 1
                continue

        # Never publish what excluded.txt rules out, whenever that decision was
        # made. Being in PKGDIR only says it built once.
        cp = re.match(r"^([a-z0-9-]+/.+?)-[0-9]", cpv)
        if cp and cp.group(1) in excluded:
            skipped += 1
            continue

        # ACCEPT_LICENSE should have stopped these at build time. Check again
        # rather than let one gate stand between us and a licensing problem.
        if "bindist" in f.get("RESTRICT", ""):
            return [], skipped, f"refusing to stage RESTRICT=bindist package: {cpv}"

        # binpkg-multi-instance gives every rebuild of one version a new
        # BUILD_ID and leaves the old one in PKGDIR's index. Publishing both
        # puts two entries for one CPV in the index, and the cleanup step cannot
        # remove either -- it decides what to keep from the index. Keep the
        # highest BUILD_ID.
        bid = int(f.get("BUILD_ID", 0))
        prev = best.get(cpv)
        if prev and prev[0] >= bid:
            skipped += 1
            continue
        if prev:
            skipped += 1
        best[cpv] = (bid, f, s)

    return list(best.values()), skipped, None


def rewrite_header(header, count, rev):
    """Fix up the header for this generation.

    Copying it as-is leaves PACKAGES at the build cache's total, dependencies
    included, several times what actually ships. TIMESTAMP has the same problem:
    what is wanted is this generation's time, not when the cache was last
    written.

    REPO_REVISIONS records which overlay commit these packages were built from.
    Portage writes it per package, not in the header, and only for repositories
    it synced itself; ours is a read-only mount, so what lands there is an empty
    {}. With it in the header the index says for itself which revision it came
    from.

    It is inserted when absent rather than substituted. A substitution against a
    line that is not there does nothing and says nothing, and the published
    header carried no REPO_REVISIONS for exactly that reason.
    """
    header = re.sub(r"^PACKAGES: .*$", f"PACKAGES: {count}", header, flags=re.M)
    header = re.sub(r"^TIMESTAMP: .*$", f"TIMESTAMP: {int(time.time())}", header, flags=re.M)
    if rev:
        line = 'REPO_REVISIONS: {"gentoo-zh": "%s"}' % rev
        if re.search(r"^REPO_REVISIONS: ", header, re.M):
            header = re.sub(r"^REPO_REVISIONS: .*$", line, header, flags=re.M)
        else:
            # The header is sorted, so keep it that way rather than appending.
            lines = header.splitlines()
            at = next((i for i, l in enumerate(lines) if l > line), len(lines))
            lines.insert(at, line)
            header = "\n".join(lines)
    return header


def main(pkgdir, stage, overlay=None, rev=""):
    pkgdir, stage = pathlib.Path(pkgdir), pathlib.Path(stage)
    overlay = pathlib.Path(overlay) if overlay else None

    header, entries = parse((pkgdir / "Packages").read_text())
    kept, skipped, error = select(entries, overlay)
    if error:
        sys.exit(error)

    stanzas = []
    for _, f, s in kept:
        dst = stage / f["PATH"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(pkgdir / f["PATH"], dst)
        stanzas.append(s)

    (stage / "Packages").write_text(
        rewrite_header(header, len(stanzas), rev) + "\n\n" + "\n\n".join(stanzas) + "\n")
    print(f">>> staged {len(stanzas)}, skipped {skipped} not ours to publish")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2],
                  sys.argv[3] if len(sys.argv) > 3 else None,
                  os.environ.get("OVERLAY_REV", "")))
