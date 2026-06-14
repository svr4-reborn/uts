# idtools - SVR4 kernel configuration tools

These build the bootable `unix` image from a configured `/etc/conf` tree, and
let an installed system **reconfigure and relink its own kernel** (add/remove
drivers, change tunables) the way the real UNIX did. **This doesn't rebuild the
entire kernel**, which does make the old, original "The UNIX system is now being
rebuilt" messages a bit misleading, but they have been kept for authenticity.

They are used in two places:

- **Host build tools** - the YAML-driven kernel build (`uts/build.py`) invokes
  `idconfig` and `idmkunix` with the i686 cross toolchain to produce the shipped
   `unix`.
- **Target binaries** - the same sources are cross-compiled and installed into
  `/etc/conf/bin` so a booted system can rebuild its kernel via `idbuild`. This
  depends on a working C compiler and a working linker, ergo, this depends on
  GCC and binutils.

Thus, they are shipped both as a tool (host-idtools) and as a package (idtools)
by our distro.

## Tools

| tool       | origin                  | what it does |
|------------|-------------------------|--------------|
| `idconfig` | ported from SVR4 idcmd  | reads `mdevice`/`sdevice.d`/`sfsys.d`/`mfsys.d`/`mtune`/`stune`/`sassign`; writes `conf.c`, `config.h`, `fsconf.c`, `vector.c`, `direct` |
| `idmkunix` | rewritten               | compiles the generated glue + per-driver `space.c`/`stubs.c` and link-edits `unix` against the prebuilt `pack.d` objects |
| `idval`    | ported from SVR4 idcmd  | numeric compare helper used by `idtune` |
| `idbuild`  | SVR4 shell script       | top-level reconfigure driver: cats `sdevice.d/*`, runs `idconfig` + `idmkunix` |
| `idtune`   | SVR4 shell script       | set a tunable in `cf.d/stune` (bounds-checked against `mtune`) |
| `idreboot` | SVR4 shell script       | prompt + initiate a reboot after a reconfigure |

## Porting notes

Sources were adapted from `cmd/idcmd/` in the original SVR4 source dump. They
are not 100% identical (idmkunix, for example, was fully rewritten), but work in
about the same way.

The historical install-side tools (`idinstall`, `idmknod`, `idmkenv`, `idcheck`,
`idmaster`, `idspace`) were **not** ported - they are only needed for packaged
add-on driver install/removal, not for the build-and-relink flow.
This needs to be revisted if we later want on-target driver-package
installation.
