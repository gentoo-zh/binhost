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


def index(entries):
    stanzas = [
        (f"CPV: {cpv}\n"
         f"PATH: {relative}\n"
         "MD5: old\nSHA1: old\nSIZE: 3\nMTIME: 1")
        for cpv, relative in entries
    ]
    return (f"PACKAGES: {len(stanzas)}\nVERSION: 0\n\n"
            + "\n\n".join(stanzas) + "\n")


with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    source = root / "source"
    target = root / "target"
    entries = [
        ("app-misc/a-1", "app-misc/a/a-1-1.gpkg.tar"),
        ("app-misc/b-2", "app-misc/b/b-2-1.gpkg.tar"),
    ]
    target_only = ("app-misc/kept-3", "app-misc/kept/kept-3-1.gpkg.tar")
    payloads = {
        entries[0][1]: b"new signed package a\n",
        entries[1][1]: b"new signed package b\n",
    }
    for directory in (source, target):
        for relative, payload in payloads.items():
            package = directory / relative
            package.parent.mkdir(parents=True, exist_ok=True)
            package.write_bytes(payload if directory == source else b"old")
    kept = target / target_only[1]
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"target only")
    (source / "Packages").write_text(index(entries))
    (target / "Packages").write_text(index(entries + [target_only]))
    changed = root / "changed.txt"
    changed.write_text("\n".join(relative for _cpv, relative in entries) + "\n")

    assert persist_packages.persist(source, target, changed) == 2
    for relative, payload in payloads.items():
        assert (target / relative).read_bytes() == payload
    refreshed = (target / "Packages").read_text()
    for payload in payloads.values():
        assert f"MD5: {hashlib.md5(payload).hexdigest()}" in refreshed
        assert f"SHA1: {hashlib.sha1(payload).hexdigest()}" in refreshed
        assert f"SIZE: {len(payload)}" in refreshed
    _header, _stanzas, indexed = persist_packages.parse_index(refreshed)
    assert set(indexed) == {relative for _cpv, relative in entries + [target_only]}
    assert kept.read_bytes() == b"target only"

    before = (target / entries[0][1]).stat().st_mtime_ns
    changed.write_text("")
    assert persist_packages.persist(source, target, changed) == 0
    assert (target / entries[0][1]).stat().st_mtime_ns == before

with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    source = root / "source"
    target = root / "target"
    outside = root / "outside"
    relative = "app-misc/a/a-1-1.gpkg.tar"
    package = source / relative
    package.parent.mkdir(parents=True)
    package.write_bytes(b"signed")
    entries = [("app-misc/a-1", relative)]
    (source / "Packages").write_text(index(entries))
    target.mkdir()
    outside.mkdir()
    (target / "app-misc").symlink_to(outside, target_is_directory=True)
    (target / "Packages").write_text(index(entries))
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
