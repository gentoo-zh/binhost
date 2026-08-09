#!/usr/bin/env python3
"""Read and verify kernel archive entries from a Gentoo Manifest."""

import argparse
import hashlib
import pathlib
import sys


class ManifestError(ValueError):
    pass


def manifest_entry(manifest, filename):
    matches = []
    try:
        lines = pathlib.Path(manifest).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ManifestError(f"cannot read Manifest: {exc}") from exc

    for line in lines:
        fields = line.split()
        if len(fields) >= 4 and fields[:2] == ["DIST", filename]:
            matches.append(fields)
    if len(matches) != 1:
        raise ManifestError(
            f"Manifest must contain exactly one DIST entry for {filename}"
        )

    fields = matches[0]
    try:
        size = int(fields[2])
        digest_fields = fields[3:]
        if len(digest_fields) % 2:
            raise ValueError
        digests = dict(zip(digest_fields[::2], digest_fields[1::2]))
    except (ValueError, TypeError) as exc:
        raise ManifestError(f"invalid Manifest entry for {filename}") from exc
    for algorithm in ("SHA512", "BLAKE2B"):
        digest = digests.get(algorithm)
        if digest:
            return size, algorithm, digest.lower()
    raise ManifestError(f"Manifest has no supported digest for {filename}")


def verify_file(manifest, filename, path):
    size, algorithm, expected = manifest_entry(manifest, filename)
    source = pathlib.Path(path)
    try:
        actual_size = source.stat().st_size
        digest = hashlib.new(algorithm.lower())
        with source.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ManifestError(f"cannot read {path}: {exc}") from exc
    if actual_size != size:
        raise ManifestError(
            f"{filename}: size {actual_size} does not match Manifest size {size}"
        )
    if digest.hexdigest() != expected:
        raise ManifestError(f"{filename}: {algorithm} does not match Manifest")


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    entry = subparsers.add_parser("entry")
    entry.add_argument("manifest")
    entry.add_argument("filename")
    verify = subparsers.add_parser("verify")
    verify.add_argument("manifest")
    verify.add_argument("filename")
    verify.add_argument("path")
    args = parser.parse_args()

    try:
        if args.command == "entry":
            print(*manifest_entry(args.manifest, args.filename), sep="\t")
        else:
            verify_file(args.manifest, args.filename, args.path)
    except ManifestError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
