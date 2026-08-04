#!/usr/bin/env python3

import importlib.util
import pathlib
import tempfile


ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "build" / "snapshot-binrepo.py"
spec = importlib.util.spec_from_file_location("snapshot_binrepo", SCRIPT)
snapshot_binrepo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot_binrepo)


with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    cache = root / "cache"
    source = cache / "example.invalid" / "binpkgs" / "x86-64" / "Packages"
    source.parent.mkdir(parents=True)
    source.write_text(
        "PACKAGES: 1\nTIMESTAMP: 1\n\n"
        "CPV: app-misc/a-1\nPATH: app-misc/a/a-1-1.gpkg.tar\n"
    )
    config = root / "gentoo.conf"
    config.write_text(
        "[gentoo]\n"
        "sync-uri = https://example.invalid/binpkgs/x86-64\n"
    )
    output = root / "captured"
    assert snapshot_binrepo.capture(config, cache, output) == source
    assert output.read_bytes() == source.read_bytes()

    source.write_text("PACKAGES: 2\n\nCPV: app-misc/a-1\n")
    try:
        snapshot_binrepo.capture(config, cache, output)
    except ValueError:
        pass
    else:
        raise AssertionError("an incomplete binrepo index was captured")

print("  官方 binrepo 快照按配置定位，并拒绝不完整的索引")
