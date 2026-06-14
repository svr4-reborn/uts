# TODO

- Revisit the kernel device-numbering flow. The current build uses explicit
  major assignments in `master.d` so that the ported `idconfig` can validate a
  deterministic configuration, but this is still a fairly rigid way to manage
  STREAMS modules and device ABI. It would be worth deciding later whether
  there is a cleaner declarative scheme for reserving or allocating majors
  without hiding ABI decisions inside build helper scripts.
