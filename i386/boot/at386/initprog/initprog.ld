/*
 * initprog.ld - link script for the AT386 initprog programs (at386/att/compaq).
 *
 * Verbatim port of the script tools/uts_boot_initprog.py used to write inline
 * (write_linker_script). Linked with `ld -m elf_i386 -e initprog -T initprog.ld`.
 */
OUTPUT_FORMAT(elf32-i386)
ENTRY(initprog)
SECTIONS
{
  . = 0x0;
  .text : { *(.text .text.*) }
  . = ALIGN(0x1000);
  .rodata : { *(.rodata .rodata.*) }
  . = ALIGN(0x1000);
  .data : { *(.data .data.*) }
  . = ALIGN(0x1000);
  .bss : { *(.bss .bss.* COMMON) }
}
