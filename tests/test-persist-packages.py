#!/usr/bin/env python3

import hashlib
import importlib.util
import pathlib
import tempfile


ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "build" / "persist-packages.py"
spec = importlib.util.spec_from_file_location("persist_packages", SCRIPT)
persist_packages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(persist_packages)


def index(relative, content):
    return (
        "PACKAGES: 1\nVERSION: 0\n\n"
        "CPV: app-misc/a-1\n"
        f"PATH: {relative}\n"
        "MD5: old\nSHA1: old\nSIZE: 3\nMTIME: 1\n"
    )


with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    source = root / "source"
    target = root / "target"
    relative = "app-misc/a/a-1-1.gpkg.tar"
    payload = b"new signed package\n"
    for directory, content in ((source, payload), (target, b"old")):
        package = directory / relative
        package.parent.mkdir(parents=True)
        package.write_bytes(content)
        (directory / "Packages").write_text(index(relative, content))
    changed = root / "changed.txt"
    changed.write_text(relative + "\n")

    assert persist_packages.persist(source, target, changed) == 1
    assert (target / relative).read_bytes() == payload
    refreshed = (target / "Packages").read_text()
    assert f"MD5: {hashlib.md5(payload).hexdigest()}" in refreshed
    assert f"SHA1: {hashlib.sha1(payload).hexdigest()}" in refreshed
    assert f"SIZE: {len(payload)}" in refreshed

    before = (target / relative).stat().st_mtime_ns
    changed.write_text("")
    assert persist_packages.persist(source, target, changed) == 0
    assert (target / relative).stat().st_mtime_ns == before

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    source = root / "source"
    target = root / "target"
    outside = root / "outside"
    relative = "app-misc/a/a-1-1.gpkg.tar"
    package = source / relative
    package.parent.mkdir(parents=True)
    package.write_bytes(b"signed")
    (source / "Packages").write_text(index(relative, b"signed"))
    target.mkdir()
    outside.mkdir()
    (target / "app-misc").symlink_to(outside, target_is_directory=True)
    (target / "Packages").write_text(index(relative, b"old"))
    changed = root / "changed.txt"
    changed.write_text(relative + "\n")
    try:
        persist_packages.persist(source, target, changed)
    except OSError:
        pass
    else:
        raise AssertionError("a symlinked target directory was followed")
    assert not any(outside.iterdir())

print("  已验签的软件包会安全地持久化，空变更不会重写文件")
