/	BIOS INT 15h, EAX=E820h memory-map probe for the AT386 bootstrap.
/
/	This replaces the old page-by-page touchpage() scan (which is far too
/	slow over gigabyte-scale ranges) with the standard BIOS memory map.
/	The bootstrap runs as 16-bit code (with 0x66/0x67 operand/address-size
/	prefixes for 32-bit operands) inside a single <= 64K segment where
/	ss == ds == es == cs after goreal().  The E820 entry buffer is a static
/	here so that ES:DI can address it while in real mode.
/
/	Conventions match start.s: a `.byte 0x66' prefix selects a 32-bit
/	operand for the following 16-bit-mode instruction, paired with an
/	`l'-suffixed mnemonic (see start.s: `.byte 0x66; movl $0x201,%eax').
/	`.byte 0x67' selects a 32-bit address.
/
/	int e820_probe(void);
/		Fills e820_buf[] with up to E820_MAX 20-byte entries
/		(base[8], length[8], type[4]) and returns the entry count,
/		or 0 if the BIOS does not support E820.

	.file	"e820.s"

#include "bsymvals.h"

#define	E820_MAX	32
#define	E820_ENTSZ	20
#define	SMAP		0x534D4150

	.globl	goreal
	.globl	goprot

	.globl	e820_probe
e820_probe:
	push	%ebp			/ C entry
	mov	%esp,%ebp
	push	%edi
	push	%esi
	push	%ebx

	call	goreal
	sti

/	Real mode now (16-bit, ds==es==cs).  Walk the E820 map.
/	%ebx = continuation (starts 0), %esi = entry count, ES:DI = buffer.

	.byte	0x66
	xorl	%ebx, %ebx
	.byte	0x66
	xorl	%esi, %esi

	.byte	0x67
	.byte	0x66
	movl	$e820_buf, %edi

e820_loop:
	.byte	0x66
	movl	$0xE820, %eax
	.byte	0x66
	movl	$SMAP, %edx
	.byte	0x66
	movl	$E820_ENTSZ, %ecx
	int	$0x15			/ BIOS system services

	jc	e820_done		/ CF set -> end or unsupported

	.byte	0x66
	cmpl	$SMAP, %eax		/ EAX must read back 'SMAP'
	jne	e820_done

/	Valid entry: advance buffer pointer and counter.
	.byte	0x66
	incl	%esi
	.byte	0x67
	.byte	0x66
	addl	$E820_ENTSZ, %edi

/	Stop if the buffer is full.
	.byte	0x66
	cmpl	$E820_MAX, %esi
	jge	e820_done

/	EBX == 0 means that was the final entry.
	.byte	0x66
	cmpl	$0, %ebx
	jne	e820_loop

e820_done:
	.byte	0x66
	movl	%esi, %eax		/ return entry count

	cli
	.byte	0x66
	call	goprot

	pop	%ebx
	pop	%esi			/ C exit
	pop	%edi
	pop	%ebp
	ret

/	Static storage, reachable in real mode (within the bootstrap segment).
	.globl	e820_buf
e820_buf:
	.space	640
