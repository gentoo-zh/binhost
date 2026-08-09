#!/usr/bin/env python3
"""Rewrite a published generation so it stops naming files that were removed.

publish.sh takes products that may not be redistributed out of the public path
before it does anything else, because compliance comes before availability.
The generation that is live at that moment still lists them, and a reader
following the index is sent to a file that is gone. Rewriting that generation
is what lets both hold at once.

Prints how many stanzas were dropped. Writes nothing when the answer is zero.
"""

import argparse
import gzip
import importlib.util
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("generation", HERE / "generation.py")
generation = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generation)


def prune(directory, denied):
    directory = pathlib.Path(directory)
    text = (directory / "Packages").read_text()
    header, separator, body = text.partition("\n\n")
    if not separator:
        raise ValueError("索引没有头部与内容之间的空行")

    kept = []
    dropped = 0
    for stanza in body.split("\n\n"):
        stanza = stanza.rstrip("\n")
        if not stanza.strip():
            continue
        if any(path in denied for path in re.findall(r"^PATH: (.*)$", stanza, re.M)):
            dropped += 1
            continue
        kept.append(stanza)

    if not dropped:
        return 0
    if not kept:
        raise ValueError("移除之后索引不含任何软件包，不改写")

    header = re.sub(r"^PACKAGES: .*$", f"PACKAGES: {len(kept)}", header, flags=re.M)
    out = header + "\n\n" + "\n\n".join(kept) + "\n"
    (directory / "Packages").write_text(out)
    # mtime=0 so the same input gives the same bytes; only the decompressed
    # content is ever compared, but a stable result is easier to reason about.
    (directory / "Packages.gz").write_bytes(gzip.compress(out.encode(), mtime=0))
    generation.create(directory)
    return dropped


def read_denied(path):
    lines = pathlib.Path(path).read_text().split("\n")
    return {line.strip() for line in lines if line.strip()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", help="一份完整代际的本地副本")
    parser.add_argument("denied", help="每行一个不再提供的相对路径")
    args = parser.parse_args()
    try:
        print(prune(args.directory, read_denied(args.denied)))
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
