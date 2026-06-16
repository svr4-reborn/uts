/*
 * boot.ld - link script for the AT386 bootstrap (fdboot/hdboot).
 *
 * Replaces the legacy AT&T `mapfile` + tools/legacy_ld.py translation, and also
 * subsumes uts_build_boot.py's old `apply_boot_sed` pass. That pass rewrote every
 * generated `.data`/`.data1`/`.rodata` directive to `.text` so the bootstrap is a
 * single contiguous blob loaded flat (cs:ip = base:0); we get the same layout by
 * folding those input sections into the output `.text` here, instead of editing
 * the compiler/assembler output. `.bss` (NOBITS) stays separate, as the old
 * mapfile (`bss = A0x4; bss:.bss;`) did. Linked with
 * `ld -m elf_i386 -dn -T boot.ld`; boot_rmhdr.py then strips the ELF header and
 * keeps the single PT_LOAD payload from offset 0.
 */
OUTPUT_FORMAT(elf32-i386)
SECTIONS
{
  . = 0x0;
  .text : {
    *(.text .text.*)
    *(.rodata .rodata.*)
    *(.data .data.* .data1)
  }
  . = ALIGN(0x4);
  .bss : { *(.bss .bss.* COMMON) }
}
