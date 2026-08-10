#!/usr/bin/env python3
"""Execute container command lines and inspect their effective arguments."""

import os
import pathlib
import re
import shlex
import stat
import subprocess
import sys
import tempfile


ROOT = (pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else
        pathlib.Path(__file__).resolve().parent.parent)


def section(text, start, end):
    first = text.index(start)
    last = text.index(end, first) + len(end)
    return text[first:last]


def executable_lines(text):
    return "\n".join(line for line in text.splitlines()
                     if line.strip() and not line.lstrip().startswith("#"))


def make_command(directory, name, body):
    path = pathlib.Path(directory, name)
    path.write_text("#!/bin/bash\nset -eu\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def execute(snippet, values, extra="", with_python=False):
    with tempfile.TemporaryDirectory() as directory:
        directory = pathlib.Path(directory)
        argv_log = directory / "argv"
        stdin_log = directory / "stdin"
        call_log = directory / "calls"
        docker = make_command(directory, "docker", """
printf 'docker\n' >> "${CALL_LOG}"
printf '%s\\0' "$@" > "${ARGV_LOG}"
cat > "${STDIN_LOG}"
""")
        path = os.environ.get("PATH", "")
        if with_python:
            make_command(directory, "python3", """
printf 'python3 %s\n' "$*" >> "${CALL_LOG}"
""")
            path = f"{directory}:{path}"
        assignments = [f"DOCKER={shlex.quote(str(docker))}"]
        assignments += [f"{name}={shlex.quote(value)}"
                        for name, value in values.items()]
        script = "set -euo pipefail\n" + "\n".join(assignments) + "\n"
        script += extra + "\n" + snippet + "\n"
        env = {
            **os.environ,
            "PATH": path,
            "ARGV_LOG": str(argv_log),
            "STDIN_LOG": str(stdin_log),
            "CALL_LOG": str(call_log),
        }
        result = subprocess.run(["bash", "-c", script], env=env,
                                stdin=subprocess.DEVNULL, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                check=False)
        assert result.returncode == 0, result.stdout
        argv = argv_log.read_bytes().split(b"\0")
        if argv and not argv[-1]:
            argv.pop()
        calls = call_log.read_text().splitlines()
        return [word.decode() for word in argv], stdin_log.read_text(), calls


def mounts(argv):
    return [argv[index + 1] for index, value in enumerate(argv[:-1])
            if value == "-v"]


def destinations(argv):
    return {value.rsplit(":", 2)[-2] for value in mounts(argv)}


base = (ROOT / "build" / "base-image.sh").read_text()
base_command = section(base, "${DOCKER} run -i", "\nINNER\n")
base_argv, _, _ = execute(base_command, {
    "TREE": "/tree", "OVERLAY": "/overlay", "DISTDIR": "/distfiles",
    "PKGDIR": "/packages", "PUBLIC_KEY": "/public.asc",
    "MAKEOPTS": "-j2", "JOBS": "2", "SIGNING_KEY": "KEY",
    "CHANNEL_ACCEPT_KEYWORDS": "amd64",
    "CHANNEL_OVERLAY_KEYWORDS": "~amd64", "STAGE3": "stage3@test",
    "container": "base-build",
})
assert "--privileged" not in base_argv
assert "--security-opt=no-new-privileges" in base_argv, base_argv
assert "/public.asc:/tmp/binhost.asc:ro" in mounts(base_argv)
assert not any("SIGNING_GNUPGHOME" in value for value in base_argv)

container = (ROOT / "build" / "build-container.sh").read_text()
untrusted_command = section(container, "${DOCKER} run --rm -i", "\nINNER\n")
untrusted_argv, untrusted_stdin, _ = execute(untrusted_command, {
    "TREE": "/tree", "OVERLAY": "/overlay", "DISTDIR": "/distfiles",
    "PKGDIR": "/packages", "GENTOO_BINPKGS": "/gentoo-packages",
    "LIST": "/packages.txt", "COMMON_PACKAGE_USE": "/package.use",
    "LOGDIR": "/logs", "CHANNEL": "unstable", "MAKEOPTS": "-j2",
    "JOBS": "2", "BASE": "base@test",
}, "channel_mounts=()")
assert "--privileged" not in untrusted_argv
assert "--security-opt=no-new-privileges" in untrusted_argv
assert not any("SIGNING_GNUPGHOME" in value or "SIGNING_KEY" in value
               for value in untrusted_argv)
assert "/tree:/var/db/repos/gentoo:ro" in mounts(untrusted_argv)
assert "/overlay:/var/db/repos/gentoo-zh:ro" in mounts(untrusted_argv)
assert "/usr/local/bin/snapshot-vdb" in destinations(untrusted_argv)
untrusted_body = executable_lines(untrusted_stdin)
assert untrusted_body.index("python3 /usr/local/bin/snapshot-vdb") \
    < untrusted_body.index('if "${EMERGE[@]}"')

trusted_if = section(
    container, "if ! ${DOCKER} run --rm --network none --read-only", "'; then")
trusted_command = trusted_if.removeprefix("if ! ").removesuffix("; then")
values = {
    "STAGE": "/stage", "SIGNING_INPUT": "/signing", "sign_uid": "1000",
    "sign_gid": "1000", "SIGNING_KEY": "KEY", "OVERLAY_REV": "REV",
    "SIGNING_IMAGE": "stage3@sha256:" + "a" * 64,
}
trusted_argv, _, _ = execute(trusted_command, values)
assert "--privileged" not in trusted_argv
assert "--network" in trusted_argv and trusted_argv[trusted_argv.index("--network") + 1] == "none"
assert "--read-only" in trusted_argv
assert "--cap-drop=ALL" in trusted_argv
assert "--security-opt=no-new-privileges" in trusted_argv
assert "--user" in trusted_argv and trusted_argv[trusted_argv.index("--user") + 1] == "1000:1000"
trusted_mounts = mounts(trusted_argv)
assert "/stage.new:/var/cache/binpkgs" in trusted_mounts
assert "/signing/private.gpg:/run/signing-private.gpg:ro" in trusted_mounts
assert "/signing/public.asc:/run/signing-public.asc:ro" in trusted_mounts
assert "/usr/local/bin/sign-packages.py" in destinations(trusted_argv)
assert "/usr/local/bin/verify-signatures.py" in destinations(trusted_argv)
assert not destinations(trusted_argv) & {
    "/var/db/repos/gentoo", "/var/db/repos/gentoo-zh",
}
assert not any(value.startswith("/packages:") for value in trusted_mounts)
shell_index = trusted_argv.index("/bin/bash")
assert trusted_argv[shell_index - 1].startswith("stage3@sha256:")
inline = executable_lines(trusted_argv[trusted_argv.index("-c") + 1])
for command in ("--import-ownertrust", "--check-trustdb",
                "BINPKG_GPG_SIGNING_GPG_HOME=/run/gnupg",
                "BINPKG_GPG_VERIFY_GPG_HOME=/run/gnupg",
                "python3 /usr/local/bin/sign-packages.py"):
    assert command in inline

flow = section(container,
               "if ! ${DOCKER} run --rm --network none --read-only",
               "cleanup_signing_input")
_, _, calls = execute(flow, values | {"PKGDIR": "/packages"},
                      "cleanup_signing_input() { :; }", with_python=True)
assert calls[0] == "docker"
verify_call = shlex.split(calls[1])
persist_call = shlex.split(calls[2])
assert pathlib.Path(verify_call[1]).name == "verify-signatures.py"
assert verify_call[2:] == ["/stage.new", "/signing/public.asc", "KEY"]
assert pathlib.Path(persist_call[1]).name == "persist-packages.py"
assert persist_call[2:] == [
    "/stage.new", "/packages", "/stage.new/.signed-packages",
]

assignment = executable_lines(container)
assert re.search(
    r'^SIGNING_IMAGE="\$\{SIGNING_IMAGE:-[^"}]+@sha256:[0-9a-f]{64}\}"$',
    assignment, re.M)

print("  容器参数来自实际命令，签名后再由宿主机验签并持久化")
