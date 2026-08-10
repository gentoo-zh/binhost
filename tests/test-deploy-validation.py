#!/usr/bin/env python3
"""Validate deployed schedules with the parsers that consume them."""

import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


ROOT = (pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else
        pathlib.Path(__file__).resolve().parent.parent)
UNITS = ROOT / "deploy" / "systemd"
CRON = ROOT / "deploy" / "cron.d-binhost"
EXPECTED_EXECUTABLES = {
    "binhost-alert@.service": "/var/lib/binhost/ops/alert-failed.sh",
    "binhost-build-unstable.service": "/var/lib/binhost/build/cycle.sh",
    "binhost-build.service": "/var/lib/binhost/build/cycle.sh",
    "binhost-kernel.service": "/var/lib/binhost/build/kernel-archive.sh",
    "binhost-status.service": "/usr/local/bin/binhost-status",
}

failed = 0


def check(name, condition, detail=""):
    global failed
    if condition:
        print("  ✓ " + name)
        return
    print("  ✗ " + name + ("\n      " + detail if detail else ""))
    failed += 1


def executable_of(line):
    value = line.split("=", 1)[1]
    words = shlex.split(value)
    if not words:
        raise ValueError(f"empty ExecStart: {line}")
    return words[0].lstrip("-+!:@")


def verify_units(root):
    units = sorted((root / "etc" / "systemd" / "system").glob("binhost-*"))
    return subprocess.run(
        ["systemd-analyze", f"--root={root}", "verify", *map(str, units)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)


def systemd_checks():
    if shutil.which("systemd-analyze") is None:
        check("系统提供 systemd-analyze", False)
        return

    with tempfile.TemporaryDirectory() as directory:
        root = pathlib.Path(directory)
        target = root / "etc" / "systemd" / "system"
        target.mkdir(parents=True)
        for source in sorted(UNITS.glob("binhost-*.service")) + \
                sorted(UNITS.glob("binhost-*.timer")):
            shutil.copyfile(source, target / source.name)

        for name in ("sysinit.target", "basic.target", "timers.target",
                     "multi-user.target", "network-online.target"):
            (target / name).write_text("[Unit]\nDescription=fixture\n")

        actual = {}
        for unit in target.glob("binhost-*.service"):
            starts = [executable_of(line) for line in unit.read_text().splitlines()
                      if line.startswith("ExecStart=")]
            if len(starts) == 1:
                actual[unit.name] = starts[0]
        check("服务使用部署脚本的固定路径", actual == EXPECTED_EXECUTABLES,
              repr(actual))
        for executable in EXPECTED_EXECUTABLES.values():
            stub = root / executable.lstrip("/")
            stub.parent.mkdir(parents=True, exist_ok=True)
            stub.write_text("#!/bin/sh\nexit 0\n")
            stub.chmod(0o755)

        result = verify_units(root)
        check("systemd 单元通过完整验证", result.returncode == 0,
              result.stdout.strip())

        mutated = target / "binhost-build.service"
        mutated.write_text(mutated.read_text().replace(
            "ExecStart=/var/lib/binhost/build/cycle.sh",
            "ExecStart=/definitely/missing/binhost-command"))
        result = verify_units(root)
        check("不存在的 ExecStart 会使验证失败",
              result.returncode != 0 and "not executable" in result.stdout,
              result.stdout.strip())


NAMES = {
    "month": {name: number for number, name in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun",
         "jul", "aug", "sep", "oct", "nov", "dec"), 1)},
    "weekday": {name: number for number, name in enumerate(
        ("sun", "mon", "tue", "wed", "thu", "fri", "sat"))},
}
RANGES = ((0, 59, None), (0, 23, None), (1, 31, None),
          (1, 12, "month"), (0, 7, "weekday"))


def cron_value(value, names):
    lowered = value.lower()
    if names and lowered in NAMES[names]:
        return NAMES[names][lowered]
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError(f"invalid value {value!r}")
    return int(value)


def cron_field(field, minimum, maximum, names):
    for item in field.split(","):
        base, separator, step = item.partition("/")
        if separator:
            if not re.fullmatch(r"[0-9]+", step) or int(step) < 1:
                raise ValueError(f"invalid step {step!r}")
        if base == "*":
            continue
        start, separator, end = base.partition("-")
        first = cron_value(start, names)
        last = cron_value(end, names) if separator else first
        if not minimum <= first <= last <= maximum:
            raise ValueError(f"value outside {minimum}-{maximum}: {base!r}")


def cron_errors(text):
    errors = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", line):
            continue
        fields = line.split(maxsplit=6)
        if len(fields) != 7:
            errors.append(f"line {number}: expected five fields, user and command")
            continue
        for position, (minimum, maximum, names) in enumerate(RANGES):
            try:
                cron_field(fields[position], minimum, maximum, names)
            except ValueError as error:
                errors.append(f"line {number}: {error}")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*\$?", fields[5]):
            errors.append(f"line {number}: invalid user {fields[5]!r}")
        if not fields[6].strip():
            errors.append(f"line {number}: empty command")
    return errors


def cron_checks():
    errors = cron_errors(CRON.read_text())
    check("cron.d-binhost 的时间与命令可解析", not errors, "\n      ".join(errors))
    mutation = "99 99 * * * root /bin/true\n"
    check("越界的 cron 时间会使验证失败", bool(cron_errors(mutation)))


print("== systemd")
systemd_checks()
print("== cron")
cron_checks()
print()
print("  部署设定：全部通过" if not failed else f"  {failed} 项不通过")
raise SystemExit(1 if failed else 0)
