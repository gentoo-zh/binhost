#!/usr/bin/env python3

"""Drop packages the overlay masks outright from a build list.

A package whose every version is masked cannot be built, and emerge fails on
it. That failure used to sink the whole round: the build finished, the failure
classifier called it an ebuild problem, and nothing was published.

Only a bare atom counts. `=cat/pkg-1.2` masks one version and the package still
builds from another, so a versioned entry is left alone and emerge picks what
it can. The list is not rewritten in the repository: a mask that stays is a
decision for excluded.txt, and the line printed here is what asks for it.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ebuilds import read_mask                             # noqa: E402


def split_masked(packages, overlay):
    masked = read_mask(overlay)
    kept, dropped = [], []
    for package in packages:
        (dropped if package in masked else kept).append(package)
    return kept, dropped


def main(argv):
    if len(argv) != 4:
        sys.exit("usage: drop_masked.py PACKAGES OVERLAY OUTPUT")
    source, overlay, output = pathlib.Path(argv[1]), argv[2], pathlib.Path(argv[3])
    try:
        packages = [line.strip() for line in source.read_text().splitlines()
                    if line.strip() and not line.startswith("#")]
        kept, dropped = split_masked(packages, overlay)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.name}.new")
        temporary.write_text("".join(f"{package}\n" for package in kept))
        temporary.replace(output)
    except (OSError, ValueError) as error:
        sys.exit(str(error))
    for package in dropped:
        print(f"::: {package} 被 overlay 整包屏蔽，本轮跳过；确认长期屏蔽后补进 excluded.txt")
    print(f">>> {len(kept)} packages ({len(dropped)} masked)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
