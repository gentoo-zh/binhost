#!/usr/bin/env python3

import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parent.parent


def block(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


base = (ROOT / "build" / "base-image.sh").read_text()
base_build = block(base, "${DOCKER} run -i", "INNER\n")
assert "--privileged" not in base_build
assert "--security-opt=no-new-privileges" in base_build
assert "${PUBLIC_KEY}:/tmp/binhost.asc:ro" in base_build
assert "${SIGNING_GNUPGHOME}:" not in base_build

container = (ROOT / "build" / "build-container.sh").read_text()
untrusted = block(container, "${DOCKER} run --rm -i", "INNER\n")
assert "--privileged" not in untrusted
assert "--security-opt=no-new-privileges" in untrusted
assert "SIGNING_GNUPGHOME" not in untrusted
assert "SIGNING_KEY" not in untrusted
assert "snapshot-vdb.py" in untrusted
untrusted_body = block(container, "<<'INNER'\n\n", "\nINNER\n")
assert untrusted_body.index("python3 /usr/local/bin/snapshot-vdb") \
    < untrusted_body.index('if "${EMERGE[@]}"')

trusted = block(container, "${DOCKER} run --rm --network none --read-only", "'; then")
assert "--privileged" not in trusted
assert "--cap-drop=ALL" in trusted
assert "--security-opt=no-new-privileges" in trusted
assert '--user "${sign_uid}:${sign_gid}"' in trusted
assert '"${SIGNING_IMAGE}" /bin/bash' in trusted
assert '"${BASE}" /bin/bash' not in trusted
assert re.search(r'SIGNING_IMAGE=.*@sha256:[0-9a-f]{64}', container)
assert "SIGNING_GNUPGHOME" not in trusted
assert "signing-private.gpg:ro" in trusted
assert "signing-public.asc:ro" in trusted
assert "sign-packages.py" in trusted and "verify-signatures.py" in trusted
assert "--import-ownertrust" in trusted
assert "--check-trustdb" in trusted
assert "BINPKG_GPG_SIGNING_GPG_HOME=/run/gnupg" in trusted
assert "BINPKG_GPG_VERIFY_GPG_HOME=/run/gnupg" in trusted
assert '${TREE}:' not in trusted and '${OVERLAY}:' not in trusted
assert '${PKGDIR}:' not in trusted
assert "--export-secret-keys" in container
assert "persist-packages.py" in container
assert container.index('python3 "$(dirname "$0")/verify-signatures.py"') \
    < container.index('python3 "$(dirname "$0")/persist-packages.py"')

print("  ebuild 容器无特权，签名使用固定干净映像并由宿主机独立验签")
