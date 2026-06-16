#!/usr/bin/env python3
"""Post-install layout fixups for the /etc/conf tree.

Meson custom_target install cannot rename, but several outputs must land under a
basename different from their (necessarily unique) Ninja output name:

  - <module>.Driver.o            -> pack.d/<module>/Driver.o
  - kernel.o/locore.o/...        -> pack.d/kernel/<obj>
  - <dotdir>__<module>           -> <dotdir>/<module>      (cpp'd fragments)
  - cfd__<name>                  -> cf.d/<name>            (cf inputs, kernmap, vuifile)
  - agg__<name>                  -> cf.d/<name>            (aggregates)

The Driver.o/kernel objects are copied straight from the build dir (they are not
otherwise installed). The frag/cf/agg files are already installed by Meson under
their prefixed names; this just renames them in place. Runs as a meson install
script; the prefix (honoring DESTDIR) is MESON_INSTALL_DESTDIR_PREFIX.
"""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--build-dir', required=True)
    ap.add_argument('--pack-subdir', required=True)
    ap.add_argument('--conf-subdir', required=True)
    ap.add_argument('--modules', required=True)
    args = ap.parse_args()

    build = Path(args.build_dir)
    prefix = Path(os.environ['MESON_INSTALL_DESTDIR_PREFIX'])
    conf = prefix / args.conf_subdir if args.conf_subdir else prefix
    pack = prefix / args.pack_subdir

    # 1. Driver.o objects (copied from build dir; not installed by Meson).
    for module in filter(None, args.modules.split(';')):
        dst = pack / module / 'Driver.o'
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(build / f'{module}.Driver.o', dst)

    # 2. kernel core + ml objects.
    kernel_dir = pack / 'kernel'
    kernel_dir.mkdir(parents=True, exist_ok=True)
    for obj in ('kernel.o', 'locore.o', 'start.o', 'syms.o'):
        shutil.copy2(build / obj, kernel_dir / obj)

    # 3. Rename the prefixed staged files installed by Meson into final names.
    #    <dotdir>__<name>  (e.g. mdevice.d__asy -> mdevice.d/asy)
    for dotdir in ('mdevice.d', 'sdevice.d', 'mfsys.d', 'sfsys.d', 'node.d',
                   'init.d', 'rc.d', 'sd.d'):
        d = conf / dotdir
        if not d.is_dir():
            continue
        for p in list(d.iterdir()):
            marker = f'{dotdir}__'
            if p.name.startswith(marker):
                p.rename(d / p.name[len(marker):])

    #    cfd__<name> and agg__<name> -> cf.d/<name>
    cfd = conf / 'cf.d'
    if cfd.is_dir():
        for p in list(cfd.iterdir()):
            for marker in ('cfd__', 'agg__'):
                if p.name.startswith(marker):
                    p.rename(cfd / p.name[len(marker):])
                    break

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
