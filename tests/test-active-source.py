#!/usr/bin/env python3

from active_source import active_text


shell = """\
# install ignored /comment
install kept /target # install ignored /inline
printf '%s#s' "#d" word#part
"""
parsed = active_text(shell, "shell")
assert "install ignored" not in parsed
assert "install kept /target" in parsed
assert "'%s#s'" in parsed and '"#d"' in parsed and "word#part" in parsed

systemd = active_text("# one\n ; two\nEnvironment=KEY=value\n", "systemd")
assert "one" not in systemd and "two" not in systemd
assert "Environment=KEY=value" in systemd

yaml = active_text("  # run: false\n  run: true\n", "yaml")
assert "false" not in yaml and "run: true" in yaml

try:
    active_text("text", "unknown")
except ValueError:
    pass
else:
    raise AssertionError("unknown source syntax must fail")

print("  有效源码解析：全部通过")
