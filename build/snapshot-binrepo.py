#!/usr/bin/env python3

import argparse
import configparser
import os
import pathlib
import re
import shutil
import urllib.parse


def index_path(config_path, cache_root, repository):
    config = configparser.ConfigParser(interpolation=None)
    if not config.read(config_path) or repository not in config:
        raise ValueError(f"binrepo configuration has no {repository} section")
    uri = config[repository].get("sync-uri", "").rstrip("/")
    parsed = urllib.parse.urlsplit(uri)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"unsupported sync-uri for {repository}: {uri}")
    root = pathlib.Path(cache_root).resolve()
    path = (root / parsed.netloc / parsed.path.lstrip("/") / "Packages").resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ValueError("binrepo index resolves outside its cache") from error
    return path


def validate(path):
    text = path.read_text()
    declared = re.search(r"^PACKAGES: ([0-9]+)$", text, re.M)
    actual = len(re.findall(r"^CPV: .+$", text, re.M))
    if not declared or int(declared.group(1)) != actual or actual == 0:
        raise ValueError(f"invalid binrepo index: {path}")


def capture(config_path, cache_root, output, repository="gentoo"):
    source = index_path(config_path, cache_root, repository)
    validate(source)
    target = pathlib.Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.new")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("cache")
    parser.add_argument("output")
    parser.add_argument("--repository", default="gentoo")
    args = parser.parse_args()
    try:
        source = capture(args.config, args.cache, args.output, args.repository)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    print(f">>> captured binrepo index from {source}")


if __name__ == "__main__":
    main()
