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
from ebuilds import read_mask  # noqa: E402


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


def select(entries, overlay=None, excluded=None):
    excluded = read_excluded() if excluded is None else excluded
    masked = read_mask(overlay) if overlay is not None else set()
    best = {}
    skipped = 0
    refused = []

    for f, s in entries:
        cpv = f["CPV"]

        if safe_path(f.get("PATH", "")) is None:
            return [], skipped, f"索引里的 PATH 不合法：{cpv} -> {f.get('PATH', '')!r}", []

        if f.get("REPO") != "gentoo-zh":
            skipped += 1
            continue

        if overlay is not None and not has_ebuild(overlay, cpv):
            skipped += 1
            continue

        cp = re.match(r"^([a-z0-9-]+/.+?)-[0-9]", cpv)
        if cp and cp.group(1) in excluded:
            skipped += 1
            continue

        if cp and cp.group(1) in masked:
            skipped += 1
            continue

        if "bindist" in f.get("RESTRICT", ""):
            refused.append(cpv)
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


def main(pkgdir, stage, overlay=None, rev=""):
    pkgdir, stage = pathlib.Path(pkgdir), pathlib.Path(stage)
    overlay = pathlib.Path(overlay) if overlay else None

    header, entries = parse((pkgdir / "Packages").read_text())
    kept, skipped, error, refused = select(entries, overlay)
    if error:
        sys.exit(error)
    for cpv in refused:
        print(f"!! 不发布 {cpv}：RESTRICT=bindist，不可再散布；该把它移出 packages.txt",
              file=sys.stderr)

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
    print(f">>> staged {len(stanzas)}, skipped {skipped} not ours to publish")
    if refused:
        print(f">>> 其中 {len(refused)} 个因 RESTRICT=bindist 被跳过")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2],
                  sys.argv[3] if len(sys.argv) > 3 else None,
                  os.environ.get("OVERLAY_REV", "")))
