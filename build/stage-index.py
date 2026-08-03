#!/usr/bin/env python3
"""
stage-index.py <pkgdir> <stage> [overlay]
"""

import os
import pathlib
import re
import shutil
import stat
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from ebuilds import (                                       # noqa: E402
    Masks, dep_atoms, read_mask, split_cpv,
)


def parse(text):
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
    f = pathlib.Path(__file__).with_name("excluded.txt")
    if not f.exists():
        return set()
    return {l.split()[0] for l in f.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")}


def has_ebuild(overlay, cpv):
    m = re.match(r"^([a-z0-9-]+/.+?)-[0-9]", cpv)
    if not m:
        return False
    d = overlay / m.group(1)
    name = cpv.split("/", 1)[1]
    if (d / f"{name}.ebuild").exists():
        return True
    return (d / f"{name}-r0.ebuild").exists()


def _open_dirs(root_fd, parts, create=False):
    fds = []
    fd = root_fd
    try:
        for part in parts:
            if create:
                try:
                    os.mkdir(part, 0o755, dir_fd=fd)
                except FileExistsError:
                    pass
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            fds.append(fd)
        return fd, fds
    except OSError:
        for f in fds:
            os.close(f)
        raise


def safe_path(value):
    if not value or value != value.strip():
        return None
    p = pathlib.PurePosixPath(value)
    if p.is_absolute() or "\0" in value:
        return None
    if any(part in ("", "..") for part in p.parts):
        return None
    return p


GENTOO_TREE = os.environ.get("GENTOO_TREE", "/var/db/repos/gentoo")

RUNTIME_FIELDS = ("RDEPEND", "PDEPEND", "IDEPEND")


class MetadataUnavailable(Exception):
    pass


def portage_restrict(overlay):
    """(cpv, repo) -> RESTRICT from Portage metadata, eclasses included.

    The repository is selected per stanza because the same CPV can exist in
    both trees with different RESTRICT. Locations are pinned to the trees this
    build used rather than whichever checkouts the host has registered, and are
    passed through an explicit config so the result does not depend on whether
    something else imported portage first.

    USE conditionals are left unevaluated, so bindist behind any flag counts.
    """
    env = dict(os.environ)
    env["PORTAGE_REPOSITORIES"] = (
        "[DEFAULT]\nmain-repo = gentoo\n\n"
        f"[gentoo]\nlocation = {GENTOO_TREE}\n\n"
        f"[gentoo-zh]\nlocation = {overlay}\nmasters = gentoo\n")
    try:
        import portage
        db = portage.portdbapi(mysettings=portage.config(env=env))
        for name, want in (("gentoo", GENTOO_TREE), ("gentoo-zh", str(overlay))):
            got = db.getRepositoryPath(name)
            if got != want:
                raise MetadataUnavailable(f"{name} resolved to {got}, expected {want}")
    except MetadataUnavailable:
        raise
    except Exception as e:                                 # noqa: BLE001
        raise MetadataUnavailable(str(e)) from e

    def get(cpv, repo):
        try:
            return db.aux_get(cpv, ["RESTRICT"], myrepo=repo or None)[0]
        except Exception:                                  # noqa: BLE001
            return None
    return get


def effective_bindist(cpv, f, lookup):
    """yes / no / unknown, where unknown is withheld exactly like yes.

    The union of both sources. The cached stanza records what RESTRICT was
    when the binary package was built, and upstream adding bindist afterwards
    does not by itself make Portage rebuild it, so neither source alone is
    sufficient.
    """
    if "bindist" in f.get("RESTRICT", "").split():
        return "yes"
    restrict = lookup(cpv, f.get("REPO"))
    if restrict is None:
        return "unknown"
    return "yes" if "bindist" in restrict.split() else "no"


def runtime_closure(entries, seeds):
    """CPVs reachable from seeds through RDEPEND and PDEPEND.

    Build-time dependencies are deliberately left out: someone installing a
    binary package never needs the compiler that produced it. Resolution is
    against the index itself, so anything the build machine did not package
    (glibc and the rest of the stage3 base) simply does not appear.
    """
    by_cp = {}
    fields = {}
    for f, _ in entries:
        cpv = f["CPV"]
        fields[cpv] = f
        by_cp.setdefault(split_cpv(cpv)[0], []).append(cpv)

    seen = set()
    queue = list(seeds)
    while queue:
        cpv = queue.pop()
        if cpv in seen or cpv not in fields:
            continue
        seen.add(cpv)
        text = " ".join(fields[cpv].get(k, "") for k in RUNTIME_FIELDS)
        for cp in dep_atoms(text):
            queue.extend(c for c in by_cp.get(cp, []) if c not in seen)
    return seen


def select(entries, overlay=None, excluded=None, with_deps=None, lookup=None):
    excluded = read_excluded() if excluded is None else excluded
    masked = read_mask(overlay) if overlay is not None else Masks()
    if lookup is None:
        try:
            if overlay is None:
                raise MetadataUnavailable("no overlay to resolve gentoo-zh against")
            lookup = portage_restrict(overlay)
        except MetadataUnavailable as e:
            return [], 0, f"Portage metadata unavailable, nothing published: {e}", []
    if with_deps is None:
        with_deps = os.environ.get("PUBLISH_DEPS", "1") == "1"
    best = {}
    skipped = 0
    refused = []

    for f, _ in entries:
        if safe_path(f.get("PATH", "")) is None:
            return ([], skipped,
                    f"索引里的 PATH 不合法：{f['CPV']} -> {f.get('PATH', '')!r}", [])

    def ours(f):
        cpv = f["CPV"]
        if f.get("REPO") != "gentoo-zh":
            return False
        if overlay is not None and not has_ebuild(overlay, cpv):
            return False
        cp, ver = split_cpv(cpv)
        if cp in excluded:
            return False
        return not (ver is not None and masked.masks(cp, ver))

    seeds = {f["CPV"] for f, _ in entries if ours(f)}
    keep = runtime_closure(entries, seeds) if with_deps else set(seeds)

    for f, s in entries:
        cpv = f["CPV"]

        if cpv not in keep:
            skipped += 1
            continue

        state = effective_bindist(cpv, f, lookup)
        if state != "no":
            refused.append((cpv, str(safe_path(f.get("PATH", ""))), state))
            skipped += 1
            continue

        bid = int(f.get("BUILD_ID", 0))
        prev = best.get(cpv)
        if prev and prev[0] >= bid:
            skipped += 1
            continue
        if prev:
            skipped += 1
        best[cpv] = (bid, f, s)

    return list(best.values()), skipped, None, refused


def rewrite_header(header, count, rev):
    header = re.sub(r"^PACKAGES: .*$", f"PACKAGES: {count}", header, flags=re.M)
    header = re.sub(r"^TIMESTAMP: .*$", f"TIMESTAMP: {int(time.time())}", header, flags=re.M)
    if rev:
        line = 'REPO_REVISIONS: {"gentoo-zh": "%s"}' % rev
        if re.search(r"^REPO_REVISIONS: ", header, re.M):
            header = re.sub(r"^REPO_REVISIONS: .*$", line, header, flags=re.M)
        else:
            lines = header.splitlines()
            at = next((i for i, l in enumerate(lines) if l > line), len(lines))
            lines.insert(at, line)
            header = "\n".join(lines)
    return header


def main(pkgdir, stage, overlay=None, rev="", lookup=None):
    pkgdir, stage = pathlib.Path(pkgdir), pathlib.Path(stage)
    overlay = pathlib.Path(overlay) if overlay else None

    header, entries = parse((pkgdir / "Packages").read_text())
    kept, skipped, error, refused = select(entries, overlay, lookup=lookup)
    if error:
        sys.exit(error)
    for cpv, _, state in refused:
        if state == "unknown":
            print(f"!! 不发布 {cpv}：读不到它的 RESTRICT，无法确认可否散布",
                  file=sys.stderr)
        else:
            print(f"!! 不发布 {cpv}：RESTRICT=bindist，不可再散布", file=sys.stderr)
    (stage / "quarantine.txt").write_text(
        "".join(f"{rel}\n" for _, rel, _ in sorted(refused)))

    stanzas = []
    src_root = os.open(pkgdir, os.O_RDONLY | os.O_DIRECTORY)
    dst_root = os.open(stage, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for _, f, s in kept:
            rel = safe_path(f["PATH"])
            parts = list(rel.parts)
            name = parts.pop()
            try:
                src_dir, src_fds = _open_dirs(src_root, parts)
                try:
                    dst_dir, dst_fds = _open_dirs(dst_root, parts, create=True)
                    try:
                        sfd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=src_dir)
                        try:
                            st = os.fstat(sfd)
                            if not stat.S_ISREG(st.st_mode):
                                sys.exit(f"拒绝 stage：{rel} 不是普通文件")
                            dfd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC
                                          | os.O_NOFOLLOW, 0o644, dir_fd=dst_dir)
                            try:
                                with open(sfd, "rb", closefd=False) as fh, \
                                     open(dfd, "wb", closefd=False) as out:
                                    shutil.copyfileobj(fh, out)
                                    out.flush()
                                written = os.fstat(dfd).st_size
                            finally:
                                os.close(dfd)
                            if written != os.fstat(sfd).st_size:
                                sys.exit(f"拒绝 stage：{rel} 复制后大小不符")
                            os.utime(name, ns=(st.st_atime_ns, st.st_mtime_ns),
                                     dir_fd=dst_dir, follow_symlinks=False)
                        finally:
                            os.close(sfd)
                    finally:
                        for fd in dst_fds:
                            os.close(fd)
                finally:
                    for fd in src_fds:
                        os.close(fd)
            except OSError as e:
                sys.exit(f"拒绝 stage：{rel} 无法按路径逐层打开（{e.strerror}）")
            stanzas.append(s)
    finally:
        os.close(src_root)
        os.close(dst_root)

    (stage / "Packages").write_text(
        rewrite_header(header, len(stanzas), rev) + "\n\n" + "\n\n".join(stanzas) + "\n")
    ours = sum(1 for _, f, _ in kept if f.get("REPO") == "gentoo-zh")
    (stage / "counts.txt").write_text(f"{ours}\n{len(stanzas) - ours}\n")
    print(f">>> staged {len(stanzas)}（overlay {ours}，运行期依赖 {len(stanzas) - ours}），"
          f"skipped {skipped} not ours to publish")
    if refused:
        print(f">>> 其中 {len(refused)} 个因不可散布或无法确认被跳过")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2],
                  sys.argv[3] if len(sys.argv) > 3 else None,
                  os.environ.get("OVERLAY_REV", "")))
