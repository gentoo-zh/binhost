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


def safe_source(pkgdir, rel):
    src = pkgdir / rel
    try:
        st = src.lstat()
    except OSError:
        return None, f"{rel}: 无法读取"
    if stat.S_ISLNK(st.st_mode):
        return None, f"{rel}: 是符号链接"
    if not stat.S_ISREG(st.st_mode):
        return None, f"{rel}: 不是普通文件"
    root = pkgdir.resolve(strict=True)
    try:
        real = src.resolve(strict=True)
    except OSError:
        return None, f"{rel}: 无法解析"
    if real != root / rel:
        return None, f"{rel}: 解析后落在 {real}，不在 {root} 之下"
    for part in rel.parents:
        if part == pathlib.PurePosixPath("."):
            continue
        if (pkgdir / part).is_symlink():
            return None, f"{rel}: 路径中的 {part} 是符号链接"
    return src, ""


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

    for f, s in entries:
        cpv = f["CPV"]

        if safe_path(f.get("PATH", "")) is None:
            return [], skipped, f"索引里的 PATH 不合法：{cpv} -> {f.get('PATH', '')!r}"

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
            return [], skipped, f"refusing to stage RESTRICT=bindist package: {cpv}"

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
    kept, skipped, error = select(entries, overlay)
    if error:
        sys.exit(error)

    stanzas = []
    for _, f, s in kept:
        rel = safe_path(f["PATH"])
        src, why = safe_source(pkgdir, rel)
        if src is None:
            sys.exit(f"拒绝 stage：{why}")
        dst = stage / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(src, "rb", opener=lambda p, fl: os.open(p, fl | os.O_NOFOLLOW)) as fh:
            before = os.fstat(fh.fileno())
            with open(dst, "wb") as out:
                shutil.copyfileobj(fh, out)
            after = os.fstat(fh.fileno())
        if (before.st_ino, before.st_dev, before.st_size) != (
                after.st_ino, after.st_dev, after.st_size):
            sys.exit(f"拒绝 stage：{rel} 在复制期间被换掉")
        if dst.stat().st_size != before.st_size:
            sys.exit(f"拒绝 stage：{rel} 复制后大小不符")
        shutil.copystat(src, dst, follow_symlinks=False)
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
