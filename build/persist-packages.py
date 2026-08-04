#!/usr/bin/env python3

import argparse
import hashlib
import os
import pathlib
import re
import stat
import sys


def parse_index(text):
    header, separator, body = text.partition("\n\n")
    stanzas = body.split("\n\n") if separator else []
    paths = []
    for stanza in stanzas:
        path = re.findall(r"^PATH: (.+)$", stanza, re.M)
        if path:
            if len(path) != 1:
                raise ValueError("a Packages stanza has multiple PATH fields")
            paths.append(path[0])
    declared = re.search(r"^PACKAGES: ([0-9]+)$", header, re.M)
    if not declared or int(declared.group(1)) != len(paths):
        raise ValueError("Packages count does not match its PATH entries")
    if len(paths) != len(set(paths)):
        raise ValueError("Packages contains duplicate paths")
    return header, stanzas, paths


def safe_parts(value):
    path = pathlib.PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe package path: {value}")
    return list(path.parts)


def open_dirs(root, parts, create=False):
    current = os.dup(root)
    opened = [current]
    for part in parts:
        if create:
            try:
                os.mkdir(part, 0o755, dir_fd=current)
            except FileExistsError:
                pass
        current = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                          dir_fd=current)
        opened.append(current)
    return current, opened


def copy_package(source_root, target_root, relative, number):
    parts = safe_parts(relative)
    name = parts.pop()
    temporary = f".{name}.signed-{os.getpid()}-{number}"
    source_fds = []
    target_fds = []
    target_dir = None
    try:
        source_dir, source_fds = open_dirs(source_root, parts)
        target_dir, target_fds = open_dirs(target_root, parts, create=True)
        source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=source_dir)
        try:
            source_stat = os.fstat(source)
            if not stat.S_ISREG(source_stat.st_mode):
                raise ValueError(f"package is not a regular file: {relative}")
            target = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                             os.O_NOFOLLOW, 0o644, dir_fd=target_dir)
            digests = {"MD5": hashlib.md5(), "SHA1": hashlib.sha1()}
            size = 0
            with os.fdopen(target, "wb") as output:
                while True:
                    chunk = os.read(source, 1 << 20)
                    if not chunk:
                        break
                    output.write(chunk)
                    size += len(chunk)
                    for digest in digests.values():
                        digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
            os.utime(temporary, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
                     dir_fd=target_dir, follow_symlinks=False)
            os.replace(temporary, name, src_dir_fd=target_dir, dst_dir_fd=target_dir)
        finally:
            os.close(source)
    finally:
        if target_dir is not None:
            try:
                os.unlink(temporary, dir_fd=target_dir)
            except FileNotFoundError:
                pass
        for fd in reversed(source_fds + target_fds):
            os.close(fd)
    return {
        "MD5": digests["MD5"].hexdigest(),
        "SHA1": digests["SHA1"].hexdigest(),
        "SIZE": str(size),
        "MTIME": str(source_stat.st_mtime_ns // 1_000_000_000),
    }


def replace_field(stanza, name, value):
    line = f"{name}: {value}"
    if re.search(rf"^{name}: .*$", stanza, re.M):
        return re.sub(rf"^{name}: .*$", line, stanza, flags=re.M)
    return stanza.rstrip("\n") + "\n" + line


def update_index(root, header, stanzas, metadata):
    updated = []
    found = set()
    for stanza in stanzas:
        match = re.search(r"^PATH: (.+)$", stanza, re.M)
        path = match.group(1) if match else None
        if path in metadata:
            found.add(path)
            for name, value in metadata[path].items():
                stanza = replace_field(stanza, name, value)
        updated.append(stanza)
    missing = set(metadata) - found
    if missing:
        raise ValueError(f"source index is missing changed paths: {sorted(missing)[0]}")
    content = header + "\n\n" + "\n\n".join(updated)
    if not content.endswith("\n"):
        content += "\n"
    temporary = f".Packages.signed-{os.getpid()}"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o644, dir_fd=root)
    try:
        with os.fdopen(fd, "wb", closefd=False) as output:
            output.write(content.encode())
            output.flush()
            os.fsync(fd)
        os.replace(temporary, "Packages", src_dir_fd=root, dst_dir_fd=root)
    finally:
        os.close(fd)
        try:
            os.unlink(temporary, dir_fd=root)
        except FileNotFoundError:
            pass


def persist(source, target, changed_list):
    source_path = pathlib.Path(source)
    target_path = pathlib.Path(target)
    changed = [line.strip() for line in pathlib.Path(changed_list).read_text().splitlines()
               if line.strip()]
    if len(changed) != len(set(changed)):
        raise ValueError("changed package list contains duplicates")
    _source_header, _source_stanzas, indexed = parse_index(
        (source_path / "Packages").read_text())
    for relative in indexed:
        safe_parts(relative)
    if not set(changed).issubset(indexed):
        raise ValueError("changed package list contains an unindexed path")
    if not changed:
        return 0

    target_header, target_stanzas, target_indexed = parse_index(
        (target_path / "Packages").read_text())
    if not set(changed).issubset(target_indexed):
        raise ValueError("source PKGDIR index is missing a changed path")

    source_root = os.open(source_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    target_root = os.open(target_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        metadata = {relative: copy_package(source_root, target_root, relative, number)
                    for number, relative in enumerate(changed)}
        update_index(target_root, target_header, target_stanzas, metadata)
    finally:
        os.close(source_root)
        os.close(target_root)
    return len(changed)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("target")
    parser.add_argument("changed_list")
    args = parser.parse_args()
    try:
        count = persist(args.source, args.target, args.changed_list)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f">>> persisted {count} newly signed packages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
