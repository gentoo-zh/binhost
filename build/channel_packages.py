#!/usr/bin/env python3

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ebuilds import ATOM                                  # noqa: E402


def package_list(path):
    path = pathlib.Path(path)
    packages = []
    seen = set()
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if raw != value:
            raise ValueError(f"{path}:{lineno}: leading or trailing whitespace")
        if not ATOM.match(value):
            raise ValueError(f"{path}:{lineno}: invalid package: {value!r}")
        if value in seen:
            raise ValueError(f"{path}:{lineno}: duplicate package: {value}")
        seen.add(value)
        packages.append(value)
    if [value.lower() for value in packages] != sorted(
            value.lower() for value in packages):
        raise ValueError(f"{path}: packages are not sorted")
    return packages


def exclusions(path):
    path = pathlib.Path(path)
    result = {}
    previous = None
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        package, separator, reason = raw.partition("\t")
        package, reason = package.strip(), reason.strip()
        if not separator or not reason:
            raise ValueError(f"{path}:{lineno}: exclusion needs a tab and a reason")
        if not ATOM.match(package):
            raise ValueError(f"{path}:{lineno}: invalid package: {package!r}")
        if package in result:
            raise ValueError(f"{path}:{lineno}: duplicate exclusion: {package}")
        if previous is not None and package.lower() < previous:
            raise ValueError(f"{path}:{lineno}: exclusions are not sorted")
        result[package] = reason
        previous = package.lower()
    return result


def effective_packages(packages_path, exclusions_path):
    packages = package_list(packages_path)
    excluded = exclusions(exclusions_path)
    unknown = sorted(set(excluded) - set(packages))
    if unknown:
        raise ValueError(
            f"{exclusions_path}: not present in package list: {', '.join(unknown)}")
    return [package for package in packages if package not in excluded], excluded


def main(argv):
    if len(argv) != 4:
        sys.exit("usage: channel_packages.py PACKAGES EXCLUSIONS OUTPUT")
    output = pathlib.Path(argv[3])
    try:
        packages, excluded = effective_packages(argv[1], argv[2])
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.new")
        temporary.write_text("".join(f"{package}\n" for package in packages))
        temporary.replace(output)
    except (OSError, ValueError) as error:
        sys.exit(str(error))
    print(f">>> {len(packages)} stable packages ({len(excluded)} excluded)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
