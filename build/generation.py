#!/usr/bin/env python3

import argparse
import hashlib
import json
import pathlib
import sys


FILES = ("Packages", "Packages.gz", "installed.txt", "official.txt", "source.txt")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            h.update(chunk)
    return {"sha256": h.hexdigest(), "size": path.stat().st_size}


def create(directory):
    directory = pathlib.Path(directory)
    data = {"schema": 1, "files": {name: digest(directory / name) for name in FILES}}
    target = directory / "generation.json"
    target.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n")
    return data


def verify(directory):
    directory = pathlib.Path(directory)
    try:
        data = json.loads((directory / "generation.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read generation.json: {error}") from error
    if data.get("schema") != 1 or set(data.get("files", {})) != set(FILES):
        raise ValueError("generation.json has an unsupported shape")
    for name in FILES:
        path = directory / name
        if not path.is_file() or data["files"][name] != digest(path):
            raise ValueError(f"generation mismatch: {name}")
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "verify"))
    parser.add_argument("directory")
    args = parser.parse_args()
    try:
        create(args.directory) if args.action == "create" else verify(args.directory)
    except (OSError, ValueError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
