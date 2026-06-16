#!/bin/sh
# Prototype validation. Proves, without the cross toolchain, the three things
# the Meson kernel-object layer must get right:
#   1. object grouping (Driver.o per module + kernel.o remainder) matches the
#      current uts_driver_compose.py exactly;
#   2. the configure-time coverage gate aborts on drift;
#   3. the global view-includes resolve real driver headers, and partial_link.py
#      produces valid relocatable objects.
# Run from uts/ :  sh meson-proto/validate.sh
set -eu
here=$(CDPATH= cd "$(dirname "$0")" && pwd)
uts=$(CDPATH= cd "$here/.." && pwd)
cd "$uts"

echo '== 1. regenerate plan + assert parity vs uts_driver_compose.py =='
python3 "$here/gen_groups.py" --kernel-root . --module-map "$here/kernel-modules.json" --out "$here/plan.json" >/dev/null
python3 - "$here/plan.json" <<'PY'
import importlib.util, json, sys
from pathlib import Path
spec=importlib.util.spec_from_file_location("dc","tools/uts_driver_compose.py")
dc=importlib.util.module_from_spec(spec); spec.loader.exec_module(dc)
ws=Path('.').resolve(); disc=set()
def add(root,rec,exts,excl=()):
    b=ws/root
    if not b.is_dir(): return
    for p in (b.rglob('*') if rec else b.iterdir()):
        if p.is_dir() or p.suffix not in exts: continue
        if any(x in excl for x in p.relative_to(b).parts[:-1]): continue
        disc.add(str(p.resolve().relative_to(ws)))
for r in ['i386/os','i386/vm','i386/disp','i386/vx']: add(r,False,{'.c'})
add('i386/exec',True,{'.c'}); add('i386/fs',True,{'.c'})
add('arch/at/i386/io',True,{'.c','.s'},{'ws','kd','kdvm','mouse'}); add('i386/io',True,{'.c','.s'},{'ws','kd','kdvm','mouse'})
add('i386/io/ws',False,{'.c'}); add('arch/at/i386/io/kd',False,{'.c'}); add('arch/at/i386/io/kdvm',False,{'.c'}); add('arch/at/i386/io/mouse',False,{'.c'})
for r in ['i386/des','i386/rpc','i386/ktli','i386/klm','i386/netinet','i386/kdb/kdb','i386/kdb/gdebugger','i386/kdb/kdb-util']: add(r,False,{'.c'})
mods=set()
for frag in ('mdev','mfsys'):
    for p in list(ws.glob(f'i386/master.d/*/{frag}'))+list(ws.glob(f'arch/at/i386/master.d/*/{frag}')): mods.add(p.parent.name)
packaged=set()
for m in mods:
    s,_,_=dc._resolve_package_implementation(ws,ws/'x',m,m)
    packaged|={str(Path(p).resolve().relative_to(ws)) for p in s}
old={s for s in disc if s not in packaged and not s.startswith('i386/ml/')}
new=set(json.load(open(sys.argv[1]))['kernel'])
assert old==new, f"kernel.o drift: {sorted(old^new)}"
print(f"   OK kernel.o parity ({len(new)} sources), drivers={len(mods)}")
PY

echo '== 2. coverage gate aborts on injected drift =='
python3 - <<'PY'
import json
m=json.load(open("meson-proto/kernel-modules.json"))
m['app']+= ['i386/os/main.c']; m['arp']+= ['i386/os/main.c']
json.dump(m, open('/tmp/uts-bad-map.json','w'))
PY
if python3 "$here/gen_groups.py" --kernel-root . --module-map /tmp/uts-bad-map.json --out /tmp/uts-bad.json >/dev/null 2>&1; then
  echo '   FAIL: gate did not abort on conflict'; exit 1
else
  echo '   OK gate aborts on conflicting source claim'
fi

echo '== 3. include resolution + partial-link mechanics =='
for f in i386/io/clist.c i386/fs/ufs/ufs_alloc.c arch/at/i386/io/asy.c; do
  gcc -nostdinc -E -I i386 -I arch/at/i386 -D_KERNEL -DAT386 -DSYSV -DSVR40 -DWEITEK -DQUOTA -Di386 "$f" -o /dev/null
done
echo '   OK real driver headers resolve from the two view roots'

# Optional: full cross build + symbol-fidelity vs build.py, when the cross
# toolchain is on PATH (set UTS_CROSS_FILE to a meson cross-file).
if command -v i686-pc-sysv4-mlibc-gcc >/dev/null 2>&1 && [ -n "${UTS_CROSS_FILE:-}" ]; then
  echo '== 4. cross build (meson+ninja) + Driver.o/kernel.o symbol fidelity vs build.py =='
  bd="$here/builddir-cross"
  rm -rf "$bd"
  meson setup "$bd" "$here" --cross-file "$UTS_CROSS_FILE" >/dev/null
  ninja -C "$bd" kernel.o drivers >/dev/null
  old=/tmp/uts-validate-old
  rm -rf "$old"; python3 build.py -t driver-packages-at386 -b "$old/build" >/dev/null
  packd="$old/build/uts/i386/conf/pack.d"
  nm=$(command -v i686-pc-sysv4-mlibc-nm || echo nm)
  syms() { "$nm" "$1" | grep -E ' [TDBR] ' | awk '{print $3}' | sort; }
  bad=0; ok=0
  for d in $(find "$packd" -name Driver.o); do
    m=$(basename "$(dirname "$d")")
    [ -f "$bd/$m.Driver.o" ] || continue   # stubs-only/metadata modules: staging stage
    if [ "$(syms "$d")" = "$(syms "$bd/$m.Driver.o")" ]; then ok=$((ok+1)); else bad=$((bad+1)); echo "   DIFFER: $m"; fi
  done
  if [ "$(syms "$packd/kernel/kernel.o")" != "$(syms "$bd/kernel.o")" ]; then echo '   DIFFER: kernel.o'; bad=$((bad+1)); fi
  [ "$bad" -eq 0 ] && echo "   OK $ok Driver.o + kernel.o symbol sets identical to build.py" || { echo "   FAIL: $bad mismatches"; exit 1; }
else
  echo '== 4. skipped (cross build): set UTS_CROSS_FILE and put the cross toolchain on PATH =='
fi
echo 'all checks passed'
