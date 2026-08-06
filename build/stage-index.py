#!/usr/bin/env python3
"""
stage-index.py <pkgdir> <stage> [overlay]
"""

import argparse
import hashlib
import os
import pathlib
import re
import stat
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from ebuilds import (                                       # noqa: E402
    BINARY_LICENSES, Masks, MetadataUnavailable, candidate_key,
    effective_license, index_db, pinned_portdbapi, read_mask, runtime_atoms,
    read_list, source_only, split_cpv, vercmp,
)
from portage.dep import paren_enclose                       # noqa: E402


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


def read_excluded(path=None):
    f = (pathlib.Path(path) if path is not None
         else pathlib.Path(__file__).with_name("excluded.txt"))
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
IMMEDIATE_QUARANTINE_STATES = frozenset({"yes", "license", "unknown"})

RUNTIME_FIELDS = ("RDEPEND", "PDEPEND", "IDEPEND")


def portage_policy(overlay):
    """Return current RESTRICT and binary-license policy readers.

    The repository is selected per stanza because the same CPV can exist in
    both trees with different metadata. The license reader evaluates the
    current expression with the USE flags recorded in the cached binpkg.
    """
    db = pinned_portdbapi(overlay, GENTOO_TREE, accept_license=BINARY_LICENSES)

    def get_restrict(cpv, repo):
        try:
            return db.aux_get(cpv, ["RESTRICT"], myrepo=repo or None)[0]
        except Exception:                                  # noqa: BLE001
            return None

    def get_license(cpv, f):
        repo = f.get("REPO", "")
        try:
            current, current_slot = db.aux_get(
                cpv, ["LICENSE", "SLOT"], myrepo=repo or None)
        except Exception:                                  # noqa: BLE001
            return "unknown"
        return effective_license(cpv, f, current, current_slot, db.settings)

    return get_restrict, get_license


def portage_restrict(overlay):
    return portage_policy(overlay)[0]


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


def preferred(db, matches):
    """One candidate per slot: newest version, this overlay before the tree.

    A resolver installs one package per slot, so pulling in every match would
    publish versions nothing actually depends on. When both trees carry the
    same version the overlay's build is the one our own packages were built
    against.
    """
    best = {}
    for pkg in matches:
        slot = db.aux_get(pkg, ["SLOT"])[0].split("/", 1)[0]
        cur = best.get(slot)
        if cur is None or _better(pkg, cur):
            best[slot] = pkg
    return {candidate_key(p) for p in best.values()}


def _better(pkg, other):
    cmp = vercmp(split_cpv(str(pkg))[1], split_cpv(str(other))[1])
    if cmp != 0:
        return cmp > 0
    if (pkg.repo == "gentoo-zh") != (other.repo == "gentoo-zh"):
        return pkg.repo == "gentoo-zh"
    return (pkg.build_id or 0) > (other.build_id or 0)


def runtime_closure(candidates, seeds):
    """(candidate keys reachable from seeds, the atoms nothing can satisfy).

    Build-time dependencies are deliberately left out: someone installing a
    binary package never needs the compiler that produced it.

    Atoms keep their version, slot, repository and USE constraints and are
    matched by Portage against the candidates. Only publishable candidates are
    passed in, so a || branch whose packages may not be redistributed simply
    does not match and the next branch is taken.

    Whatever the build machine did not package, glibc and the rest of the
    stage3 base, has no match and is reported. A caller must not claim the
    published set is dependency complete while that list is not empty.
    """
    db = index_db(f for _bid, f, _s in candidates.values())
    unresolved = {}

    def resolve(node):
        """The candidates this node needs, or None when nothing satisfies it."""
        if isinstance(node, list):
            if node and node[0] == "||":
                for branch in node[1:]:
                    got = resolve(branch)
                    if got is not None:
                        return got
                return None
            out = set()
            for child in node:
                got = resolve(child)
                if got is None:
                    return None
                out |= got
            return out
        if node.blocker:
            return set()
        matched = db.match(node)
        return preferred(db, matched) if matched else None

    seen = set()
    queue = list(seeds)
    while queue:
        key = queue.pop()
        if key in seen or key not in candidates:
            continue
        seen.add(key)
        f = candidates[key][1]
        nodes = runtime_atoms(" ".join(f.get(k, "") for k in RUNTIME_FIELDS))
        if nodes is None:
            unresolved.setdefault(f"<{key[0]} 的依赖无法解析>", set()).add(key[0])
            continue
        for node in nodes:
            got = resolve(node)
            if got is None:
                unresolved.setdefault(paren_enclose([node], opconvert=True),
                                      set()).add(key[0])
                continue
            queue.extend(k for k in got if k not in seen)
    return seen, unresolved


def select(entries, overlay=None, excluded=None, with_deps=None, lookup=None,
           license_lookup=None, seed_packages=None):
    excluded = read_excluded() if excluded is None else excluded
    masked = read_mask(overlay) if overlay is not None else Masks()
    if lookup is None:
        try:
            if overlay is None:
                raise MetadataUnavailable("no overlay to resolve gentoo-zh against")
            lookup, license_lookup = portage_policy(overlay)
        except MetadataUnavailable as e:
            return [], 0, f"Portage metadata unavailable, nothing published: {e}", [], {}
    elif license_lookup is None:
        license_lookup = lambda _cpv, _fields: "yes"
    if with_deps is None:
        with_deps = os.environ.get("PUBLISH_DEPS", "1") == "1"
    skipped = 0
    refused = []

    for f, _ in entries:
        if safe_path(f.get("PATH", "")) is None:
            return ([], skipped,
                    f"索引里的 PATH 不合法：{f['CPV']} -> {f.get('PATH', '')!r}", [], {})

    # One candidate per (CPV, repository). Keying on the CPV alone lets a
    # stanza from the other tree win on BUILD_ID and be published in place of
    # the one an overlay seed authorised.
    newest = {}
    paths_by_key = {}
    for f, s in entries:
        key = (f["CPV"], f.get("REPO", ""))
        paths_by_key.setdefault(key, set()).add(str(safe_path(f["PATH"])))
        bid = int(f.get("BUILD_ID", 0))
        prev = newest.get(key)
        if prev is None:
            newest[key] = (bid, f, s)
            continue
        skipped += 1
        if bid > prev[0]:
            newest[key] = (bid, f, s)

    # Publishing policy is applied before anything reads the candidates, so a
    # dependency can never be resolved to something we then refuse to publish.
    candidates = {}
    for key, (bid, f, s) in newest.items():
        cp, ver = split_cpv(key[0])
        repo = f.get("REPO")
        repository_tree = None
        if repo == "gentoo-zh" and overlay is not None:
            repository_tree = overlay
        elif repo == "gentoo" and pathlib.Path(GENTOO_TREE).is_dir():
            repository_tree = pathlib.Path(GENTOO_TREE)
        current_exists = (has_ebuild(repository_tree, key[0])
                          if repository_tree is not None else None)

        lifecycle_state = None
        if repo == "gentoo-zh" and cp in excluded:
            lifecycle_state = "excluded"
        elif (repo == "gentoo-zh" and ver is not None
              and masked.masks(cp, ver)):
            lifecycle_state = "masked"
        elif source_only(key[0]):
            lifecycle_state = "source"
        elif current_exists is False:
            lifecycle_state = "removed"

        bindist = effective_bindist(key[0], f, lookup)
        if bindist == "yes":
            state = bindist
        elif (bindist == "unknown" and lifecycle_state is not None
              and current_exists is False):
            state = lifecycle_state
        elif bindist == "unknown":
            state = bindist
        else:
            license_state = license_lookup(key[0], f)
            if license_state != "yes":
                state = "license" if license_state == "no" else license_state
            elif lifecycle_state is not None:
                state = lifecycle_state
            else:
                state = "publish"
        if state != "publish":
            refused.extend((key[0], path, state)
                           for path in sorted(paths_by_key[key]))
            skipped += 1
            continue
        candidates[key] = (bid, f, s)

    def ours(f):
        cpv = f["CPV"]
        if f.get("REPO") != "gentoo-zh":
            return False
        if overlay is not None and not has_ebuild(overlay, cpv):
            return False
        cp, ver = split_cpv(cpv)
        if seed_packages is not None and cp not in seed_packages:
            return False
        if cp in excluded:
            return False
        return not (ver is not None and masked.masks(cp, ver))

    seeds = {key for key, (_b, f, _s) in candidates.items() if ours(f)}
    if with_deps:
        keep, unresolved = runtime_closure(candidates, seeds)
    else:
        keep, unresolved = set(seeds), {}

    skipped += len(candidates) - len(keep)
    return ([candidates[k] for k in sorted(keep)], skipped, None, refused, unresolved)


DIGESTS = ("SHA1", "MD5")


def copy_digest(src, dst):
    """Copy and hash in the same pass; the bytes are read either way."""
    hashes = {name: hashlib.new(name.lower()) for name in DIGESTS}
    while True:
        chunk = src.read(1 << 20)
        if not chunk:
            break
        dst.write(chunk)
        for h in hashes.values():
            h.update(chunk)
    dst.flush()
    return {name: h.hexdigest() for name, h in hashes.items()}


def digest_mismatch(f, digest):
    """A reason to refuse, or None.

    The stanza describes the package the index promises. If the copy does not
    hash to that, the source changed under us and the stanza no longer
    describes what we would publish.
    """
    declared = []
    mismatches = []
    for name in DIGESTS:
        want = f.get(name, "").strip().lower()
        if not want:
            continue
        declared.append(name)
        if want != digest[name]:
            mismatches.append(
                f"{name} 与索引不符：索引 {want}，复制后 {digest[name]}")
    if not declared:
        return "索引没有给出 MD5 或 SHA1，无法确认复制的内容"
    return "；".join(mismatches) or None


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


def main(pkgdir, stage, overlay=None, rev="", lookup=None, seed_file=None,
         excluded_files=()):
    pkgdir, stage = pathlib.Path(pkgdir), pathlib.Path(stage)
    overlay = pathlib.Path(overlay) if overlay else None

    header, entries = parse((pkgdir / "Packages").read_text())
    excluded = read_excluded()
    for path in excluded_files:
        excluded.update(read_excluded(path))
    seed_packages = set(read_list(seed_file)) if seed_file is not None else None
    kept, skipped, error, refused, unresolved = select(
        entries, overlay, excluded=excluded, lookup=lookup,
        seed_packages=seed_packages)
    if error:
        sys.exit(error)
    reported = set()
    for cpv, _, state in refused:
        if (cpv, state) in reported:
            continue
        reported.add((cpv, state))
        if state == "unknown":
            print(f"!! 不发布 {cpv}：无法确认当前 RESTRICT 或 LICENSE",
                  file=sys.stderr)
        elif state == "license":
            print(f"!! 不发布 {cpv}：LICENSE 不属于 @BINARY-REDISTRIBUTABLE",
                  file=sys.stderr)
        elif state == "source":
            print(f"!! 不发布 {cpv}：该类别应在使用者系统本地安装",
                  file=sys.stderr)
        elif state == "masked":
            print(f"!! 不发布 {cpv}：该版本已被 overlay 屏蔽", file=sys.stderr)
        elif state == "excluded":
            print(f"!! 不发布 {cpv}：该包列在排除清单", file=sys.stderr)
        elif state == "removed":
            print(f"!! 不发布 {cpv}：该版本已从源仓库移除", file=sys.stderr)
        else:
            print(f"!! 不发布 {cpv}：RESTRICT=bindist，不发布 binpkg", file=sys.stderr)
    (stage / "quarantine.txt").write_text(
        "".join(f"{rel}\n" for _, rel, state in sorted(refused)
                if state in IMMEDIATE_QUARANTINE_STATES))

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
                                    digest = copy_digest(fh, out)
                                written = os.fstat(dfd).st_size
                            finally:
                                os.close(dfd)
                            if written != os.fstat(sfd).st_size:
                                sys.exit(f"拒绝 stage：{rel} 复制后大小不符")
                            bad = digest_mismatch(f, digest)
                            if bad:
                                sys.exit(f"拒绝 stage：{rel} {bad}")
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
    (stage / "unresolved.txt").write_text(
        "".join(f"{atom}\t{' '.join(sorted(who))}\n"
                for atom, who in sorted(unresolved.items())))

    ours = sum(1 for _, f, _ in kept if f.get("REPO") == "gentoo-zh")
    # The site reports how many overlay packages have a binary package, so the
    # published count is per package. One package can have several stanzas.
    ours_packages = len({split_cpv(f["CPV"])[0] for _, f, _ in kept
                         if f.get("REPO") == "gentoo-zh"})
    (stage / "counts.txt").write_text(
        f"{ours_packages}\n{len(stanzas) - ours}\n")
    print(f">>> staged {len(stanzas)}（overlay {ours}，运行期依赖 {len(stanzas) - ours}），"
          f"skipped {skipped} not ours to publish")
    if refused:
        print(f">>> 其中 {len(refused)} 个因发布策略或无法确认被跳过")
    if unresolved:
        print(f">>> {len(unresolved)} 个依赖原子在索引中没有匹配，"
              f"由基础系统提供或未构建，见 unresolved.txt；"
              f"因此不能宣称已发布的内容依赖完整")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pkgdir")
    parser.add_argument("stage")
    parser.add_argument("overlay", nargs="?")
    parser.add_argument("--seeds")
    parser.add_argument("--exclude-file", action="append", default=[])
    args = parser.parse_args()
    sys.exit(main(args.pkgdir, args.stage, args.overlay,
                  os.environ.get("OVERLAY_REV", ""),
                  seed_file=args.seeds, excluded_files=args.exclude_file))
