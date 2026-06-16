#!/usr/bin/env python3
"""Emit the kernel-header install plan for meson.build to foreach over.

The on-system `idbuild` (idconfig + idmkunix) recompiles the per-driver
space.c/stubs.c and the generated glue (conf.c/fsconf.c/vector.c) when tunables
or the configured driver set change. Those sources #include kernel headers
("sys/types.h", ...) that, at build time, idmkunix finds via -I on the source
tree (i386/ and arch/at/i386/). For the same relink to work on a real system,
those headers must ship -- but in an isolated tree, never on a normal include
path: the ancient SVR4 kernel headers collide with the mlibc C-library headers,
so they must not land in /usr/include. We install them under <conf>/inc and
<conf>/inc/arch (mirroring the two build-time -I roots), and only idmkunix ever
adds those dirs to a search path (via INCDIRS in idmkunix.conf, with -nostdinc
in CFLAGS keeping the default/mlibc path out).

This emits one line per .h file (only headers -- the .c kernel sources that share
these dirs are not shipped), tab-separated:

  <src-relpath-from-kernel-root>\t<dest-dir-relative-to-conf-inc-root>

meson.build turns each into an install_data into conf_root/inc/<destdir> (or
conf_root/inc/arch/<destdir> for the arch tree). Keeping the per-.h subdir
structure preserves "sys/foo.h" style includes.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The two -I roots the kernel build compiles against (meson.build view_inc),
# mapped to their destination under <conf>/inc. The arch overlay goes under
# inc/arch so the two stay distinguishable, exactly as the two -I dirs are.
ROOTS = [
    ("i386", ""),
    ("arch/at/i386", "arch"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel-root", required=True)
    args = ap.parse_args()

    kroot = Path(args.kernel_root).resolve()
    lines = []
    for root, dest_prefix in ROOTS:
        base = kroot / root
        if not base.is_dir():
            continue
        for h in sorted(base.rglob("*.h")):
            rel = h.relative_to(base)            # e.g. sys/types.h
            destdir = rel.parent.as_posix()      # e.g. sys  ('.' at top level)
            if destdir == ".":
                destdir = ""
            if dest_prefix:
                destdir = (dest_prefix + "/" + destdir).rstrip("/")
            src = h.relative_to(kroot).as_posix()
            lines.append(f"{src}\t{destdir}")

    sys.stdout.write("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
