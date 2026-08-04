#!/usr/bin/env python3

import argparse
import pathlib
import re


FIELDS = {
    "SLOT": "SLOT",
    "USE": "USE",
    "IUSE_EFFECTIVE": "IUSE",
    "EAPI": "EAPI",
    "repository": "REPO",
}


def clean(value):
    return " ".join(value.split())


def snapshot(root):
    root = pathlib.Path(root)
    stanzas = []
    for category in sorted(root.iterdir() if root.exists() else ()):
        if not category.is_dir():
            continue
        for package in sorted(category.iterdir()):
            if not package.is_dir() or not re.search(r"-[0-9]", package.name):
                continue
            values = {"CPV": f"{category.name}/{package.name}"}
            for source, target in FIELDS.items():
                path = package / source
                if path.is_file():
                    values[target] = clean(path.read_text(errors="replace"))
            if "IUSE" not in values:
                path = package / "IUSE"
                if path.is_file():
                    values["IUSE"] = clean(path.read_text(errors="replace"))
            values.setdefault("SLOT", "0")
            values.setdefault("USE", "")
            values.setdefault("IUSE", "")
            values.setdefault("EAPI", "0")
            values.setdefault("REPO", "")
            stanzas.append("\n".join(
                f"{key}: {values[key]}".rstrip() for key in
                ("CPV", "SLOT", "USE", "IUSE", "EAPI", "REPO")))
    header = f"PACKAGES: {len(stanzas)}\nVERSION: 1"
    return header + ("\n\n" + "\n\n".join(stanzas) if stanzas else "") + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("output")
    args = parser.parse_args()
    pathlib.Path(args.output).write_text(snapshot(args.root))


if __name__ == "__main__":
    main()
