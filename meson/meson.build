project('uts-kernel', 'c',
  # The kernel is written in C89, and with any warnings enabled it spews a
  # huge amount of stuff. We should address this at some point.
  # Also, build fails with -O3, also a thing we should address, lol
  default_options: ['c_std=gnu89', 'optimization=2', 'warning_level=0',
   'werror=false'],
)

#
# HERE BE CLANKER
#
# I did look over this to make sure I know what it does, and it looks right,
# but just like the previous build system, it was basically done with the help
# of Claude. (Too lazy to make it myself)


fs = import('fs')
py = import('python').find_installation('python3')
cc = meson.get_compiler('c')

kernel_root = meson.current_source_dir() / '..'
i386 = kernel_root / 'i386'
arch = kernel_root / 'arch/at/i386'

# TODO: remove the source tree overlay thingy.
# Should probably do that when I do the huge source tree refactor (tm)
view_inc = ['-I' + i386, '-I' + arch]

# Kernel is compiled with a lot of flags, but they can be summarized as:
#  "make this stuff run on a 386" lol
kernel_codegen = [
  '-std=gnu89', '-fcommon', '-fno-builtin', '-fno-tree-vectorize', '-O2',
  '-m32', '-mno-mmx', '-mno-sse', '-mno-sse2', '-fno-PIC', '-fno-PIE',
  '-fno-unwind-tables', '-fno-asynchronous-unwind-tables',
  '-mgeneral-regs-only', '-nostdinc', '-nostdlib',

# Kernel release/version is set here. The source code dump I got identifies
# itself as Release 4, Version 3, but from looking through it, and the stuff
# I could find on the interwebs, I think it might have been a dump from
# somewhere between 2.1 and 3. This really doesn't matter, but given the install
# images I could find are 2.1, I like choosing this one more.
  '-DREL="4"', '-DVER="2.1"', '-DSYSV',
]

# TODO: make the subsystems take a single set of defines
# I did this back when I originally got it running for the first time.
# I'm pretty sure that I could probably get away with ['-D_KERNEL', '-DAT386',
# 'i386, '-DWEITEK'] for everything except FS, but given that FS itself is kinda
# evidence that having per-subsytem defines *could* maybe be a good idea to,
# since it has its own 'QUOATE' define, I'm leaving it as-is for now.
subsystem_defines = {
  'os'     : ['-D_KERNEL', '-DAT386', '-DWEITEK'],
  'vm'     : ['-D_KERNEL', '-Dnotnow', '-DAT386'],
  'exec'   : ['-D_KERNEL', '-DAT386'],
  'io'     : ['-D_KERNEL', '-DSYSV', '-DSVR40', '-DWEITEK', '-DAT386'],
  'fs'     : ['-D_KERNEL', '-DQUOTA', '-DAT386'],
  'disp'   : ['-D_KERNEL', '-DAT386'],
  'vx'     : ['-D_KERNEL', '-DAT386'],
  'des'    : ['-D_KERNEL', '-DSYSV', '-DAT386'],
  'rpc'    : ['-D_KERNEL', '-DSYSV', '-DAT386'],
  'ktli'   : ['-D_KERNEL', '-DSYSV', '-DAT386'],
  'klm'    : ['-D_KERNEL', '-DSYSV', '-DAT386'],
  'netinet': ['-D_KERNEL', '-DSYSV', '-Di386', '-DAT386'],
  'kdb'    : ['-D_KERNEL', '-DAT386'],
}

partial_link = files('partial_link.py')
gen_groups   = files('gen_groups.py')
gen_ml       = files('gen_ml.py')
module_map   = files('kernel-modules.json')
empty_c      = files('empty.c')
symvals      = kernel_root / 'tools/uts_symvals.py'

# The conf tree root, relative to the install prefix. idtools installs with
# --prefix=/etc/conf, so the default '' makes the prefix itself the conf root
# (cf.d, pack.d, mdevice.d, ... directly under it). idconfig/idmkunix (run as a
# later xbstrap step) consume <conf>/pack.d/<module>/Driver.o etc.
conf_root = get_option('conf_subdir')
pack_d = conf_root != '' ? conf_root / 'pack.d' : 'pack.d'

# ml has its own set of flags. I honestly forgot exactly why I haven't gone over
# the code yet to not have any warnings and such, but ml is already a hot mess
# of stuff that sticks together with hopes and prayers, so yikes, too lazy
kernel_recompile_cflags = ' '.join([
  '-std=gnu89', '-fcommon', '-fno-builtin', '-fno-tree-vectorize', '-O2',
  '-m32', '-mno-mmx', '-mno-sse', '-mno-sse2',
  '-D_KERNEL', '-DAT386', '-DWEITEK', '-DWEITEK_EMULATOR', '-DSYSV', '-DSVR40',
])

# --------------------------------------------------------------------------
# idmkunix.conf: the data-driven home of the variable compile/link settings
# idmkunix needs to recompile the glue + per-driver space.c/stubs.c and relink
# `unix`. The same file is shipped into the conf tree (cf.d/) so the build-time
# relink and the on-system `idbuild` reconfigure drive an *identical* compile/
# link -- no flags hardcoded at either call site. See uts/idtools/idmkunix.c.
#
#   CFLAGS  : codegen ABI only. -nostdinc isolates the ancient kernel headers
#             (shipped under <conf>/inc, see gen_headers.py) from the mlibc
#             C-library headers, which closely collide; idmkunix adds the
#             kernel -D defines (AT386 etc.) intrinsically, so they are not
#             repeated here -- DEFINES carries only the build-specific extras.
#   DEFINES : the extra kernel defines the old recipe passed via -D.
#   INCDIRS : conf-tree-relative; idmkunix hangs them off the conf root, so the
#             one value resolves to conf-root/inc at build and /etc/conf/inc on
#             target. inc = i386 headers, inc/arch = arch/at/i386 overlay.
#   CC/LD   : the cross toolchain (overridable on the target via idbuild's env).
idmkunix_cflags = ' '.join([
  '-std=gnu89', '-fcommon', '-fno-builtin', '-fno-tree-vectorize', '-O2',
  '-m32', '-mno-mmx', '-mno-sse', '-mno-sse2', '-nostdinc',
])
idmkunix_defines = '-DWEITEK_EMULATOR -DSVR40 -DRAMD_BOOT'
idmkunix_incdirs = 'inc inc/arch'
idmkunix_cc = 'i686-pc-sysv4-mlibc-gcc'
idmkunix_ld = 'i686-pc-sysv4-mlibc-ld'

idmkunix_conf = configure_file(
  input: 'idmkunix.conf.in',
  output: 'idmkunix.conf',
  configuration: {
    'CFLAGS'  : idmkunix_cflags,
    'DEFINES' : idmkunix_defines,
    'INCDIRS' : idmkunix_incdirs,
    'CC'      : idmkunix_cc,
    'LD'      : idmkunix_ld,
  },
  install: true,
  install_dir: conf_root / 'cf.d',
  install_tag: 'meta',
)

# Linker for the partial (-Ur) Driver.o/kernel.o links. The COMMON-allocation
# requirement (kernel asm uses symbol+offset) needs ld.bfd; the cross ld is bfd.
# Resolved from the cross-file (-Dkernel_ld=...) or PATH, defaulting to ld.
kernel_ld = get_option('kernel_ld')
if kernel_ld == ''
  kernel_ld = find_program('i686-pc-sysv4-mlibc-ld', 'ld', native: false).full_path()
endif

# --------------------------------------------------------------------------
# Object grouping. gen_groups.py resolves the per-driver source lists + the
# kernel.o remainder from the declarative module map, asserting at configure
# time that every compiled source belongs to exactly one bucket and has a
# subsystem (=> compile flags). check:true => `meson setup` aborts on drift.
# The whole of uts_driver_compose.py's bucketing, done declaratively. Output
# captured from stdout (no file written into the source tree).
# --------------------------------------------------------------------------
groups = run_command(
  py, gen_groups,
  '--kernel-root', kernel_root,
  '--module-map', module_map,
  '--format', 'meson',
  check: true,
).stdout().strip()

# Per-source object compile. Returns the built .o for one "src|subsystem" token.
# (Meson has no user functions; we inline the body in the loops below, but keep
# the compile recipe in one place via this variable documenting the shape.)
#   cc <kernel_codegen> <view_inc> <subsystem_defines[sub]> -c <src> -o <out>

# Walk the plan: build each source object, group into Driver.o / kernel.o.
driver_objs = {}  # module -> Driver.o target
driver_obj_list = []  # same targets as a list (older meson lacks dict.values())
kernel_objs = []
obj_cache = {}    # src -> built object target (sources are unique per bucket)

foreach line : groups.split('\n')
  parts = line.split(':')
  kind = parts[0]     # 'driver' or 'kernel'
  module = parts[1]   # module name, '' for kernel
  payload = parts[2]  # 'src|sub;src|sub;...'
  objs = []
  if payload != ''
    foreach tok : payload.split(';')
      sv = tok.split('|')
      src = sv[0]
      sub = sv[1]
      defs = subsystem_defines[sub]
      # Stable, collision-free object name from the source path.
      objname = '_'.join(src.split('/')) + '.o'
      obj = custom_target(objname,
        input: kernel_root / src,
        output: objname,
        command: [cc.cmd_array(), kernel_codegen, view_inc, defs,
                  '-c', '@INPUT@', '-o', '@OUTPUT@'],
      )
      objs += obj
    endforeach
  endif
  if kind == 'driver'
    # pack.d/<module>/Driver.o  (partial link; ld.bfd -Ur). Metadata-only modules
    # (empty payload) get no Driver.o here -- idmkunix handles their space.c/stubs.c.
    if objs.length() > 0
      # Output name is unique (Ninja's target namespace is flat); the install
      # script below lays each out as pack.d/<module>/Driver.o for idconfig/idmkunix.
      t = custom_target('Driver-' + module,
        input: objs,
        output: module + '.Driver.o',
        command: [py, partial_link, '--ld', kernel_ld, '-o', '@OUTPUT@', '@INPUT@'],
        build_by_default: true,
      )
      driver_objs += {module: t}
      driver_obj_list += t
    endif
  elif kind == 'empty'
    # Empty Driver.o placeholder: idconfig demands a Driver.o for a configured-in,
    # non-NODRIVE module even when it only supplies space.c (gendisp). Compile an
    # empty object with the kernel codegen (matches build.py's _compile_empty_object).
    t = custom_target('Driver-' + module,
      input: empty_c,
      output: module + '.Driver.o',
      command: [cc.cmd_array(), kernel_codegen, '-c', '@INPUT@', '-o', '@OUTPUT@'],
      build_by_default: true,
    )
    driver_objs += {module: t}
    driver_obj_list += t
  else
    kernel_objs = objs
  endif
endforeach

# pack.d/kernel/kernel.o : the prelinked core blob.
kernel_o = custom_target('kernel.o',
  input: kernel_objs,
  output: 'kernel.o',
  command: [py, partial_link, '--ld', kernel_ld, '-o', '@OUTPUT@', '@INPUT@'],
  build_by_default: true,
)

# --------------------------------------------------------------------------
# ml-at386: the low-level machine-layer objects (locore.o/start.o/syms.o) that
# also live in pack.d/kernel/. gen_ml.py runs the fixed symvals->compile->
# assemble->partial-link pipeline (see that script). One custom_target with the
# three outputs; @OUTDIR@ is the per-target build dir.
# --------------------------------------------------------------------------
ml_objs = custom_target('ml-at386',
  output: ['locore.o', 'start.o', 'syms.o'],
  command: [py, gen_ml,
    '--kernel-root', kernel_root,
    '--cc', cc.cmd_array(),
    '--ld', kernel_ld,
    '--cflags', kernel_recompile_cflags,
    '--symvals', symvals,
    '--out-dir', '@OUTDIR@'],
  build_by_default: true,
)

# Make every Driver.o a default build target too.
foreach module, tgt : driver_objs
  alias_target('drv-' + module, tgt)
endforeach
alias_target('drivers', driver_obj_list)

# --------------------------------------------------------------------------
# master.d staging. Produces the rest of the on-disk /etc/conf tree so that
# `idbuild` (idconfig + idmkunix) over the installed tree rebuilds `unix`:
#   - pack.d/<module>/{space.c,stubs.c}   (copied module sources)
#   - mdevice.d/sdevice.d/mfsys.d/sfsys.d/node.d/<module>  (cpp'd fragments)
#   - cf.d/{mdevice,mfsys,sdevice,sfsys}  (aggregates of those)
#   - cf.d/{sassign,stune,mtune,init.base}  (cpp'd top-level inputs)
# gen_staging.py emits the data-driven plan; each line becomes a custom_target
# (cpp via stage_fragment.py) or install_data (verbatim copies). This is the
# native port of uts_stage_master_at386.py + the idfiles aggregation.
# --------------------------------------------------------------------------
gen_staging   = files('gen_staging.py')
stage_fragment = files('stage_fragment.py')
stage_aggregate = files('stage_aggregate.py')

# Preprocessor for the metadata fragments. The cross-file's "cpp" binary is the
# C++ compiler (g++), so we drive the C compiler in -E mode instead (stage_
# fragment.py adds -E -P -x c). cc.cmd_array() may be multi-element; join to one
# shell-splittable string for --cpp.
frag_cpp = ' '.join(cc.cmd_array())
frag_cpp_flags = ['-DAT386', '-DWEITEK', '-DWEITEK_EMULATOR']
frag_cpp_args = []
foreach f : frag_cpp_flags
  frag_cpp_args += '--cpp-flag=' + f
endforeach

staging = run_command(py, gen_staging, '--kernel-root', kernel_root,
  check: true).stdout().strip()

# Collect fragment targets per .d dir so the aggregates can depend on them.
dotdir_frags = {}  # dotdir -> [custom_target]

foreach line : staging.split('\n')
  f = line.split('\t')
  kind = f[0]
  if kind == 'copy'
    # space.c / stubs.c: install the source file verbatim into pack.d/<module>/.
    install_data(kernel_root / f[1], install_dir: conf_root / f[2], rename: f[3],
      install_tag: 'pack')
  elif kind == 'frag'
    # cpp'd module fragment -> <dotdir>/<module>. Output name = module (f[3]).
    dotdir = f[2]
    t = custom_target('frag-' + dotdir + '-' + f[3],
      input: kernel_root / f[1],
      output: dotdir + '__' + f[3],
      command: [py, stage_fragment, '--mode', f[4], '--cpp', frag_cpp,
                frag_cpp_args, '--in', '@INPUT@', '--out', '@OUTPUT@'],
      install: true,
      install_dir: conf_root / dotdir,
      install_tag: 'meta',
    )
    dotdir_frags += {dotdir: dotdir_frags.get(dotdir, []) + [t]}
  elif kind == 'cf'
    # top-level cf.d input (sassign/stune/mtune/init.base), mode=cf.
    custom_target('cf-' + f[2],
      input: kernel_root / f[1],
      output: 'cfd__' + f[2],
      command: [py, stage_fragment, '--mode', f[3], '--cpp', frag_cpp,
                frag_cpp_args, '--in', '@INPUT@', '--out', '@OUTPUT@'],
      install: true,
      install_dir: conf_root / 'cf.d',
      install_tag: 'meta',
    )
  endif
endforeach

# The install basename must be the module name / cf name, not the unique build
# output name (dotdir__mod / cfd__name). A rename install isn't possible from a
# custom_target, so fix names in the post-install script alongside pack.d.
# (We pass the staging plan again so it knows the intended dest names.)
foreach line : staging.split('\n')
  f = line.split('\t')
  if f[0] == 'agg'
    # cf.d/<name> = plain concat of the staged <dotdir>/* fragments (sorted).
    cfname = f[1]
    dotdir = f[2]
    custom_target('agg-' + cfname,
      input: dotdir_frags.get(dotdir, []),
      output: 'agg__' + cfname,
      command: [py, stage_aggregate, '-o', '@OUTPUT@', '@INPUT@'],
      install: true,
      install_dir: conf_root / 'cf.d',
      install_tag: 'meta',
    )
  endif
endforeach

# kernmap / vuifile: preprocessed kernel config inputs (cf.d/). The old kernmap-
# at386 profile used cwd-relative -I.; the sources live in i386/, so -I i386.
# Preprocess with the C compiler (-E -P -x c, as the cross "cpp" is g++).
foreach name : ['kernmap', 'vuifile']
  custom_target('cfd-' + name,
    input: i386 / name,
    output: 'cfd__' + name,
    command: [cc.cmd_array(), '-E', '-P', '-x', 'c', '-I' + i386, '-D_KERNEL',
              '-DAT386', '-DWEITEK', '-DWEITEK_EMULATOR', '@INPUT@', '-o', '@OUTPUT@'],
    install: true,
    install_dir: conf_root / 'cf.d',
    install_tag: 'meta',
  )
endforeach

# --------------------------------------------------------------------------
# Isolated kernel headers under <conf>/inc (+ inc/arch). idmkunix's INCDIRS
# point here so the on-system glue/space.c/stubs.c recompile resolves the same
# "sys/*" headers the build compiles against -- WITHOUT putting them on a normal
# include path (they collide with mlibc). gen_headers.py emits one line per .h;
# install_data preserves the per-.h subdir so "sys/foo.h" includes still work.
# --------------------------------------------------------------------------
gen_headers = files('gen_headers.py')
headers = run_command(py, gen_headers, '--kernel-root', kernel_root,
  check: true).stdout().strip()
foreach line : headers.split('\n')
  h = line.split('\t')
  # h[0] = src relpath from kernel_root, h[1] = dest subdir under inc/ ('' = top)
  hdest = h[1] == '' ? conf_root / 'inc' : conf_root / 'inc' / h[1]
  install_data(kernel_root / h[0],
    install_dir: hdest,
    install_tag: 'meta',
  )
endforeach

# --------------------------------------------------------------------------
# Install the object tree as pack.d/<module>/Driver.o + pack.d/kernel/*.o.
# A post-install script does the layout: Ninja output names are flat
# (<module>.Driver.o) and must be renamed to Driver.o under per-module dirs,
# which install_data/custom_target install cannot express directly.
# stage_pack.py reads the build dir and writes into MESON_INSTALL_DESTDIR_PREFIX.
# --------------------------------------------------------------------------
meson.add_install_script('stage_pack.py',
  '--build-dir', meson.current_build_dir(),
  '--pack-subdir', pack_d,
  '--conf-subdir', conf_root,
  '--modules', ';'.join(driver_objs.keys()),
)

# --------------------------------------------------------------------------
# Boot pipeline (fdboot/hdboot, bootlib, initprog, bsymvals). Native port of the
# old tools/uts_build_boot.py + uts_boot_initprog.py + uts_boot_symvals.py shell-
# out; see meson/boot/meson.build.
# --------------------------------------------------------------------------
subdir('boot')
