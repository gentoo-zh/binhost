#!/usr/bin/env python3

import argparse
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tarfile
import tempfile

from portage.exception import PortageException


VERIFY_SCRIPT = pathlib.Path(__file__).with_name("verify-signatures.py")
spec = importlib.util.spec_from_file_location("verify_signatures", VERIFY_SCRIPT)
verify_signatures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_signatures)


def parse_index(text):
    header, _, body = text.partition("\n\n")
    stanzas = []
    for stanza in body.split("\n\n"):
        fields = dict(re.findall(r"^(\w+): (.*)$", stanza, re.M))
        if fields.get("CPV") and fields.get("PATH"):
            stanzas.append(fields)
    return header, stanzas


def safe_relative(value):
    path = pathlib.PurePosixPath(value)
    return bool(value and not path.is_absolute() and ".." not in path.parts)


def read_revisions(header):
    match = re.search(r"^REPO_REVISIONS: (.*)$", header, re.M)
    if not match:
        return {}
    revisions = json.loads(match.group(1))
    if not isinstance(revisions, dict) or not all(
            isinstance(name, str) and isinstance(value, str)
            for name, value in revisions.items()):
        raise ValueError("invalid REPO_REVISIONS")
    return revisions


def restore_revisions(index, revisions):
    text = index.read_text()
    line = f"REPO_REVISIONS: {json.dumps(revisions, sort_keys=True)}"
    if re.search(r"^REPO_REVISIONS: ", text, re.M):
        text = re.sub(r"^REPO_REVISIONS: .*$", line, text, flags=re.M)
    else:
        header, separator, body = text.partition("\n\n")
        lines = header.splitlines()
        lines.append(line)
        text = "\n".join(sorted(lines)) + separator + body
    index.write_text(text)


def signature_valid(path, home, fingerprint, scratch):
    try:
        verify_signatures.verify_package(path, home, fingerprint, scratch)
    except (OSError, ValueError, tarfile.TarError):
        return False
    return True


def sign(directory, revision, public_key, fingerprint, changed_list):
    directory = pathlib.Path(directory)
    index = directory / "Packages"
    header, stanzas = parse_index(index.read_text())
    revisions = read_revisions(header)
    if revision:
        revisions["gentoo-zh"] = revision
    declared = re.search(r"^PACKAGES: ([0-9]+)$", index.read_text(), re.M)
    if not declared or int(declared.group(1)) != len(stanzas):
        raise ValueError("Packages count does not match its stanzas")

    import portage
    from portage.gpkg import gpkg

    changed = []
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        home = root / "gnupg"
        home.mkdir(mode=0o700)
        verify_signatures.import_key(home, public_key, fingerprint)
        for number, fields in enumerate(stanzas):
            if not safe_relative(fields["PATH"]):
                raise ValueError(f"unsafe package path: {fields['PATH']}")
            path = directory / fields["PATH"]
            if not path.is_file():
                raise ValueError(f"missing package: {fields['PATH']}")
            scratch = root / str(number)
            scratch.mkdir()
            if signature_valid(path, home, fingerprint, scratch):
                continue
            gpkg(portage.settings, gpkg_file=str(path),
                 verify_signature=False).update_signature(
                     keep_current_signature=False)
            changed.append(fields["PATH"])

    env = dict(os.environ, PKGDIR=str(directory))
    subprocess.run(["emaint", "binhost", "--fix"], check=True, env=env)
    if revisions:
        restore_revisions(index, revisions)
    _header, refreshed = parse_index(index.read_text())
    original_paths = {fields["PATH"] for fields in stanzas}
    refreshed_paths = {fields["PATH"] for fields in refreshed}
    if len(original_paths) != len(stanzas) or refreshed_paths != original_paths:
        raise ValueError("emaint changed the indexed package set")
    pathlib.Path(changed_list).write_text("".join(f"{path}\n" for path in changed))
    return len(changed), len(refreshed)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--revision", default="")
    parser.add_argument("--public-key", required=True)
    parser.add_argument("--fingerprint", required=True)
    parser.add_argument("--changed-list", required=True)
    args = parser.parse_args()
    try:
        changed, total = sign(args.directory, args.revision, args.public_key,
                              args.fingerprint, args.changed_list)
    except (OSError, PortageException, RuntimeError, ValueError,
            subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f">>> re-signed {changed} of {total} packages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
