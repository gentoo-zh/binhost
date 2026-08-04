#!/usr/bin/env python3

import pathlib


ROOT = pathlib.Path(__file__).resolve().parent.parent


def block(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


base = (ROOT / "build" / "base-image.sh").read_text()
base_build = block(base, "${DOCKER} run -i --privileged", "INNER\n")
assert "${PUBLIC_KEY}:/tmp/binhost.asc:ro" in base_build
assert "${SIGNING_GNUPGHOME}:" not in base_build

container = (ROOT / "build" / "build-container.sh").read_text()
untrusted = block(container, "${DOCKER} run --rm -i --privileged", "INNER\n")
assert "SIGNING_GNUPGHOME" not in untrusted
assert "SIGNING_KEY" not in untrusted
assert "snapshot-vdb.py" in untrusted
untrusted_body = block(container, "<<'INNER'\n\n", "\nINNER\n")
assert untrusted_body.index("python3 /usr/local/bin/snapshot-vdb") \
    < untrusted_body.index('if "${EMERGE[@]}"')

trusted = block(container, "${DOCKER} run --rm --network none --read-only", "'; then")
assert "--privileged" not in trusted
assert "SIGNING_GNUPGHOME" in trusted
assert "sign-packages.py" in trusted and "verify-signatures.py" in trusted
assert '${TREE}:' not in trusted and '${OVERLAY}:' not in trusted
assert '${PKGDIR}:' not in trusted
assert trusted.index("python3 /usr/local/bin/sign-packages") \
    < trusted.index("python3 /usr/local/bin/verify-signatures")
assert "persist-packages.py" in container
assert container.index("python3 /usr/local/bin/verify-signatures") \
    < container.index('python3 "$(dirname "$0")/persist-packages.py"')

print("  私钥仅进入无网络、非 privileged 的独立签名阶段")
