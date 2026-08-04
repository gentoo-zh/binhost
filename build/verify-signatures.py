#!/usr/bin/env python3

import argparse
import pathlib
import re
import subprocess
import sys
import tarfile
import tempfile


def normalize(value):
    return value.replace(" ", "").upper()


def index_paths(index):
    text = pathlib.Path(index).read_text()
    declared = re.search(r"^PACKAGES: ([0-9]+)$", text, re.M)
    paths = re.findall(r"^PATH: (.+)$", text, re.M)
    if not declared or int(declared.group(1)) != len(paths):
        raise ValueError("Packages count does not match its PATH entries")
    if len(paths) != len(set(paths)):
        raise ValueError("Packages contains duplicate paths")
    for value in paths:
        path = pathlib.PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe package path: {value}")
    return paths


def import_key(home, public_key, fingerprint):
    subprocess.run(["gpg", "--homedir", str(home), "--batch", "--import",
                    str(public_key)], check=True, stdout=subprocess.DEVNULL)
    output = subprocess.run(
        ["gpg", "--homedir", str(home), "--batch", "--with-colons",
         "--fingerprint", "--list-keys"], check=True, capture_output=True,
        text=True).stdout.splitlines()
    primary = None
    expect_fpr = False
    for line in output:
        kind, *_rest = line.split(":")
        if kind == "pub" and primary is not None:
            raise ValueError("the verification keyring contains multiple primary keys")
        if kind == "pub":
            expect_fpr = True
        elif kind == "fpr" and expect_fpr:
            primary = line.split(":")[9]
            expect_fpr = False
    if normalize(primary or "") != normalize(fingerprint):
        raise ValueError("the exported public key does not match SIGNING_KEY")


def valid_signature(home, signature, payload, fingerprint):
    result = subprocess.run(
        ["gpg", "--homedir", str(home), "--batch", "--no-auto-key-retrieve",
         "--status-fd", "1", "--verify", str(signature), str(payload)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    wanted = normalize(fingerprint)
    for line in result.stdout.splitlines():
        if not line.startswith("[GNUPG:] VALIDSIG "):
            continue
        values = line.split()
        signer = normalize(values[2])
        primary = normalize(values[-1])
        if result.returncode == 0 and wanted in (signer, primary):
            return True
    return False


def verify_package(path, home, fingerprint, scratch):
    with tarfile.open(path, "r") as archive:
        files = {member.name: member for member in archive.getmembers()
                 if member.isfile()}
        payloads = [name for name in files
                    if not name.endswith(".sig")
                    and pathlib.PurePosixPath(name).name not in ("gpkg-1", "Manifest")]
        if not payloads:
            raise ValueError(f"{path}: no signed payloads")
        kinds = {pathlib.PurePosixPath(name).name.split(".tar", 1)[0]
                 for name in payloads}
        if not {"metadata", "image"}.issubset(kinds):
            raise ValueError(f"{path}: metadata or image payload is missing")
        for number, name in enumerate(payloads):
            signature = f"{name}.sig"
            if signature not in files:
                raise ValueError(f"{path}: unsigned payload {name}")
            payload_file = scratch / f"payload-{number}"
            signature_file = scratch / f"signature-{number}"
            with archive.extractfile(files[name]) as source:
                payload_file.write_bytes(source.read())
            with archive.extractfile(files[signature]) as source:
                signature_file.write_bytes(source.read())
            if not valid_signature(home, signature_file, payload_file, fingerprint):
                raise ValueError(f"{path}: signature is not from SIGNING_KEY")


def verify(directory, public_key, fingerprint):
    directory = pathlib.Path(directory)
    paths = index_paths(directory / "Packages")
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        home = root / "gnupg"
        home.mkdir(mode=0o700)
        import_key(home, public_key, fingerprint)
        for number, relative in enumerate(paths):
            package = directory / relative
            if not package.is_file():
                raise ValueError(f"missing package: {relative}")
            scratch = root / str(number)
            scratch.mkdir()
            verify_package(package, home, fingerprint, scratch)
    return len(paths)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("public_key")
    parser.add_argument("fingerprint")
    args = parser.parse_args()
    try:
        count = verify(args.directory, args.public_key, args.fingerprint)
    except (OSError, ValueError, tarfile.TarError, subprocess.CalledProcessError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f">>> verified {count} packages with the isolated keyring")
    return 0


if __name__ == "__main__":
    sys.exit(main())
