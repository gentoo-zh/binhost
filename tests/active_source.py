#!/usr/bin/env python3

"""Remove comments before tests inspect executable source text."""


def _shell_line(line):
    single = False
    double = False
    escaped = False
    word_start = True

    for index, char in enumerate(line):
        if escaped:
            escaped = False
            word_start = False
            continue
        if single:
            if char == "'":
                single = False
            continue
        if double:
            if char == "\\":
                escaped = True
            elif char == '"':
                double = False
            continue
        if char == "\\":
            escaped = True
            word_start = False
        elif char == "'":
            single = True
            word_start = False
        elif char == '"':
            double = True
            word_start = False
        elif char == "#" and word_start:
            return line[:index].rstrip()
        elif char.isspace() or char in ";|&()<>":
            word_start = True
        else:
            word_start = False
    return line.rstrip()


def active_text(text, syntax):
    """Return source text with comments for the selected syntax removed."""
    lines = []
    for line in text.splitlines():
        if syntax == "shell":
            line = _shell_line(line)
        elif syntax == "systemd":
            if line.lstrip().startswith(("#", ";")):
                line = ""
        elif syntax == "yaml":
            if line.lstrip().startswith("#"):
                line = ""
        else:
            raise ValueError(f"unsupported source syntax: {syntax}")
        lines.append(line)
    return "\n".join(lines)
