/* 	Copyright (c) 1990 UNIX System Laboratories, Inc. */
/* 	Copyright (c) 1984, 1986, 1987, 1988, 1989, 1990 AT&T */
/* 	  All Rights Reserved */

/* 	THIS IS UNPUBLISHED PROPRIETARY SOURCE CODE OF */
/* 	UNIX System Laboratories, Inc. */
/* 	The copyright notice above does not evidence any */
/* 	actual or intended publication of such source code. */

/* 	Copyright (c) 1987, 1988 Microsoft Corporation */
/* 	  All Rights Reserved */

/* 	This Module contains Proprietary Information of Microsoft */
/* 	Corporation and should be treated as Confidential. */

	.ident	"@(#)kern-ml:uprt.s	1.3.2.2"

#include "symvals.h"

	.code16gcc

	.globl  _start
	.globl	pstart
	.globl	gdt
	.globl  gdtend
	.globl	idt
#ifdef VPIX
	.globl	idt2
#endif
	.globl	kpt0
	.globl	kptn
	.globl	mon1sel
	.globl	mon3sel
	.globl	mon1off
	.globl	mon3off
	.globl	monidt
	.globl	scall_dscr
	.globl	sigret_dscr
	.globl	df_stack
	.globl	Rgdtdscr
	.globl	Ridtdscr
	.globl	egafontptr

	.set	PROTBIT, 0x0001
	.set	PAGEBIT, 0x80000000
	.set    DFSTKSIZ,0x0FFE
	.set	IDTLIM, [8*256-1]
	.set	MONIDTLIM, [8*16-1]
	.set	JBTLOC, 0x0400
	.set	BM_BASE, 0
	.set	BM_EXTENT, 4
	.set	KPD_LOC, [KPTBL_LOC+0x1000]

	.text
/*  */
/* 	*** NOTICE *** NOTICE *** NOTICE *** NOTICE *** NOTICE *** */
/*  */
/* 		The instructions in pstart are reversed 16 <--> 32 */
/* 		bits.  This is because we are running pstart in */
/* 		REAL MODE.  By using long instructions, we generate */
/* 		opcodes that are 16 bit instructions when run */
/* 		in REAL MODE. */

/* 	More nice information: */
/* 		This code now only supports the BKI boot-kernel interface. */
/* 		This passes the magic number 0xff1234ff in %edi. */
/* 		All other info is passed in the bootinfo structure. */

pstart:
_start:

#	call	_rprint
#	.string	"Kernel started!\r\n"

	cmpl	$BKI_MAGIC, %edi
	je	BKI_ok

	/*  Bad magic number from bootstrap. */
	/*  Print a message, then halt. */
	/*  Unfortunately, this will only work on an AT386. */

	call	_rprint
	.string	"\r\nBootstrap too old.\r\n"
_halt:
	sti
	hlt
	jmp	_halt

_rprint:
	popl	%esi		# get pointer to message
	push    %eax        # save EAX (clobbered with %al)

	movb	$1, %bl		# foreground color
ploop:	
	movb	%cs:(%esi), %al	# get chr
	incl	%esi
	testb	%al, %al	# test for end of string
	jz	pend
	call _rputc
	jmp	ploop		# repeat for next chr
pend:
	popl	%eax		# restore EAX
	pushl	%esi
	ret

.section .comment
/*
 * Serial helpers: write characters to COM1 (0x3f8) and print hex values.
 *
 * Function conventions:
 *  - _rputc: Writes character in AL to COM1 port (0x3f8). Waits for THRE (LSR bit 5) before writing.
 *           Preserves EDX and EAX (pushed/popped). Does not modify other registers.
 *  - _rputhex: Prints EAX as 8 ASCII hex characters (MSB first). Uses EBX/ECX/EDX as scratch.
 *              Calls _rputc for each nibble. Preserves EBX/ECX/EDX; EAX is clobbered.
 *  - _rputhex16: Prints AX as 4 ASCII hex characters (MSB first). Uses EBX/ECX/EDX as scratch.
 *                Preserves EBX/ECX/EDX; EAX is clobbered.
 *  - _rputhex8: Prints AL as 2 ASCII hex characters (MSB first). Uses EBX/ECX/EDX as scratch.
 *               Preserves EBX/ECX/EDX; EAX is clobbered.
 *
 * Notes:
 *  - All functions call _rputc to send single characters to COM1; _rputc waits for the
 *    transmitter to be ready before writing so callers can use these functions without
 *    busy-waiting themselves.
 *  - Hex output uses uppercase letters (A-F) for 10..15.
 *  - `_rputhex` prints the entire 32-bit register value passed in EAX; `_rputhex16` prints
 *    lower 16-bits (AX), `_rputhex8` prints lower 8-bits (AL).
 */
.text
.globl  _rputc
_rputc:
	# _rputc
	# Input: AL contains ASCII character to output on COM1 (0x3f8)
	# Behavior: Waits for Transmitter Holding Register Empty (LSR bit 5) and writes the char
	# Clobbers: AL (obviously) and DX (used for port), preserves EAX & EDX to the caller via push/pop
	# Note: We push EAX to save char across the inb polling loop. This also preserves the
	#       caller's EAX, so _rputc returns with EAX restored.
	# Returns: None (no return value), preserves registers listed above.
	/* Save registers we clobber */
	pushl   %edx
	pushl   %eax
	/* Wait for Transmitter Holding Register Empty (LSR bit 5) */
	movl    $0x3fd, %edx      # LSR (com1 + 5)
wait_rputc:
	inb     %dx, %al
	testb   $0x20, %al
	jz      wait_rputc
	movl    $0x3f8, %edx      # COM1 data port
	popl    %eax              # restore char into AL
	outb    %al, %dx
	popl    %edx
	ret

.globl  _rputhex
_rputhex:
	# _rputhex
	# Input: EAX holds the 32-bit value to print as 8 hex ASCII chars. Most-significant nibble printed first.
	# Clobbers: EAX is preserved. EBX, ECX, EDX are used as work regs but preserved.
	# Implements: For 8 nibbles, extract top nibble (shift right 28), convert to ASCII with uppercase A-F,
	#            then call _rputc for each nibble.
	/* Print EAX as 8 hex digits (MSB first) */
	pushl   %ebx
	pushl   %ecx
	pushl   %edx
	pushl   %eax              # save original value
	movl    %eax, %ebx        # working copy
	movl    $8, %ecx
hex32_loop:
	movl    %ebx, %edx
	shrl    $28, %edx         # top nibble
	andl    $0xf, %edx
	cmpb    $9, %dl
	jg      hex32_alpha
	addb    $48, %dl
	jmp     hex32_out
hex32_alpha:
	addb    $55, %dl
hex32_out:
	movb    %dl, %al
	call    _rputc
	shll    $4, %ebx
	decl    %ecx
	jnz     hex32_loop

	/* Restore registers */
	popl    %eax
	popl    %edx
	popl    %ecx
	popl    %ebx
	ret

.globl  _rputhex16
_rputhex16:
	# _rputhex16
	# Input: EAX (lower 16 bits, AX) contains the value to print as 4 hex ASCII chars. MSB first.
	# Clobbers: EAX is preserved. EBX, ECX, EDX are used as work regs but are preserved by the function.
	/*
	 * The routine shifts the working copy right by 12 to select the current nibble then
	 * converts it to ASCII and calls _rputc. Repeats 4 times.
	 */
	pushl   %ebx
	pushl   %ecx
	pushl   %edx
	pushl   %eax
	movl    %eax, %ebx
	movl    $4, %ecx
hex16_loop:
	movl    %ebx, %edx
	shrl    $12, %edx         # top nibble for 16-bit
	andl    $0xf, %edx
	cmpb    $9, %dl
	jg      hex16_alpha
	addb    $48, %dl
	jmp     hex16_out
hex16_alpha:
	addb    $55, %dl
hex16_out:
	movb    %dl, %al
	call    _rputc
	shll    $4, %ebx
	decl    %ecx
	jnz     hex16_loop

	/* Restore registers */
	popl    %eax
	popl    %edx
	popl    %ecx
	popl    %ebx
	ret

.globl  _rputhex8
_rputhex8:
	# _rputhex8
	# Input: EAX (AL) contains the byte to print as 2 hex ASCII chars (MSB first)
	# Clobbers: EAX is preserved. EBX, ECX, EDX preserved by the routine.
	/*
	 * For each nibble (2 iterations), extract the top nibble, convert to uppercase ASCII
	 * and call _rputc.
	 */
	pushl   %ebx
	pushl   %ecx
	pushl   %edx
	pushl   %eax
	movl    %eax, %ebx
	movl    $2, %ecx
hex8_loop:
	movl    %ebx, %edx
	shrl    $4, %edx
	andl    $0xf, %edx
	cmpb    $9, %dl
	jg      hex8_alpha
	addb    $48, %dl
	jmp     hex8_out
hex8_alpha:
	addb    $55, %dl
hex8_out:
	movb    %dl, %al
	call    _rputc
	shll    $4, %ebx
	decl    %ecx
	jnz     hex8_loop

	/* Restore registers */
	popl    %eax
	popl    %edx
	popl    %ecx
	popl    %ebx
	ret

	#ifdef EARLY_BOOT_DEBUG
	/*
	 * Macro: DBG_PRINT_REG
	 *  - Usage: DBG_PRINT_REG "VALUE:", %eax
	 *  - Prints a string literal (first parameter) followed by the
	 *    32-bit register value (second parameter) in 8-hex digits,
	 *    and then prints a newline (CRLF), while preserving all
	 *    caller registers.
	 *
	 * Notes:
	 *  - The string parameter must be a quoted string literal (e.g. "VALUE:").
	 *  - The register parameter should be a 32-bit register name (e.g. %eax).
	 *  - The macro preserves the status of the following registers:
	 *      %eax, %ebx, %ecx, %edx, %esi, %edi, %ebp
	 *    (they are pushed/popped around the calls).
	 *  - The macro relies on the existing helpers: _rprint, _rputhex, _rputc.
	 */
	.macro DBG_PRINT_REG str, reg
		/* Save registers we must not clobber */
		pushf
		pushl   %eax
		pushl   %ebx
		pushl   %ecx
		pushl   %edx
		pushl   %esi
		pushl   %edi
		pushl   %ebp

		/* Print the string literal parameter using _rprint (call/.string pair). */
		call    _rprint
		.string "\str"

		/* Move requested register into EAX for _rputhex and print it */
		movl    \reg, %eax
		call    _rputhex

		/* Print CRLF (carriage return + newline) */
		movb    $'\r', %al
		call    _rputc
		movb    $'\n', %al
		call    _rputc

		/* Restore registers */
		popl    %ebp
		popl    %edi
		popl    %esi
		popl    %edx
		popl    %ecx
		popl    %ebx
		popl    %eax
		popf
	.endm

	/*
	 * Optional helper macro: DBG_PRINT_REG32
	 *  - Same as above but emphasizes 32-bit registers (just an alias)
	 */
	.macro DBG_PRINT_REG32 str, reg
		DBG_PRINT_REG "\str", \reg
	.endm

	/*
	 * Macro: DBG_PRINT_REG16
	 *  - Usage: DBG_PRINT_REG16 "VAL16:", %ax
	 *  - Prints a string and the 16-bit value in the given register (AX/BX/...)
	 *    using _rputhex16.
	 */
	.macro DBG_PRINT_REG16 str, reg
		pushf
		pushl   %eax
		pushl   %ebx
		pushl   %ecx
		pushl   %edx
		pushl   %esi
		pushl   %edi
		pushl   %ebp

		call    _rprint
		.string "\str"

		/* Move the 16-bit register value into AX and call _rputhex16 */
		movw    \reg, %ax
		call    _rputhex16

		/* Print CRLF */
		movb    $'\r', %al
		call    _rputc
		movb    $'\n', %al
		call    _rputc

		popl    %ebp
		popl    %edi
		popl    %esi
		popl    %edx
		popl    %ecx
		popl    %ebx
		popl    %eax
		popf
	.endm

	/*
	 * Macro: DBG_PRINT_REG8
	 *  - Usage: DBG_PRINT_REG8 "VAL8:", %al
	 *  - Prints a string and the 8-bit value in the given register (AL/BL/...)
	 *    using _rputhex8.
	 */
	.macro DBG_PRINT_REG8 str, reg
		pushf
		pushl   %eax
		pushl   %ebx
		pushl   %ecx
		pushl   %edx
		pushl   %esi
		pushl   %edi
		pushl   %ebp

		call    _rprint
		.string "\str"

		/* Move the 8-bit register into AL and call _rputhex8 */
		movb    \reg, %al
		call    _rputhex8

		/* Print CRLF */
		movb    $'\r', %al
		call    _rputc
		movb    $'\n', %al
		call    _rputc

		popl    %ebp
		popl    %edi
		popl    %esi
		popl    %edx
		popl    %ecx
		popl    %ebx
		popl    %eax
		popf
	.endm

	/*
	 * Macro: DBG_PRINT
	 *  - Usage: DBG_PRINT "Some message\r\n"
	 *  - Prints the given string literal using _rprint.
	 */
	.macro DBG_PRINT str
		pushf
		pushl   %eax
		call    _rprint
		.string "\str"
		popl    %eax
		popf
	.endm
	#else
	.macro DBG_PRINT_REG str, reg
	.endm

	.macro DBG_PRINT_REG32 str, reg
	.endm

	.macro DBG_PRINT_REG16 str, reg
	.endm

	.macro DBG_PRINT_REG8 str, reg
	.endm

	.macro DBG_PRINT str
	.endm
	#endif


	.align	8
Rusermon:
	.byte   0               # If you set this byte to non-zero
				/*  moninit will put the monitors vectors */
				/*  into idt(1) and idt(3), thus allowing */
				/*  user programs to be debugged with DMON. */
	.string	"<-Here"

	.align	8	# This is for ease of looking at memory.
Rgdtdscr:
	.short  [8*GDTSZ-1]       # We will re-compute this, but just in case...
	.long	gdt

	.align	8

Ridtdscr:
	.value	IDTLIM
	.long	idt

	.align	8
RIgdtdscr:			# This and the next entry are used to
	.value  [8*GDTSZ-1]       # initialize DMON
	.long	gdt

	.align	8
RIidtdscr:
	.value	IDTLIM
	.long	idt

	.align	8
RMidtdscr:
	.value	MONIDTLIM
	.long	monidt

	.align	8
R0idtdscr:
	.value	0xffff
	.long	0

/* 	EGA font pointers (these start as real mode pointers) */
/* 	The pointers point to the 8x8, 8x14, 9x14, 8x16 and */
/* 	the 9x16 fonts, respectively */

egafontptr:
	.long	0
	.long	0
	.long	0
	.long	0
	.long	0

BKI_ok:
/* 	Here we have to set up the kernel symbol page table */
/* 	according to the memused information passed by the bootstrap. */
/* 	After we're done, R_Set_Addr will be able to convert virtual */
/* 	addresses to physical addresses using this page table. */

#	call _rprint
#	.string "top of BKI_ok\r\n"

	xorl	%eax, %eax		# Load 0 into segment registers
	movw	%ax, %ds		#   so we get absolute addresses
	movw	%ax, %es
	movw	%ax, %fs
	cld

	movl	$KPTBL_LOC, %edi	# First zero out the page table & dir
#	DBG_PRINT_REG32 "Zeroing KPTBL at:", %edi
	movl	$2048, %ecx
	rep; sstol

	movl	$BOOTINFO_LOC, %ebx
	movl	memusedcnt(%ebx), %edx	# Get count of memused segments
	#DBG_PRINT_REG32 "BOOTINFO_LOC:", %ebx
	#DBG_PRINT_REG32 "Memused count:", %edx

	movl	%edx, %esi
	addl	$memused, %ebx		# Get pointer to first segment

	movl	$KPTBL_LOC, %edi	# "Reserved" segment maps at KVSBASE

kptbl_loop:
	movl	BM_EXTENT(%ebx), %ecx	# Compute # pages for this segment
	shrl	$12, %ecx

	movl	BM_BASE(%ebx), %eax	# Compute base pte for this segment
	andl	$0xfffff000, %eax
#	DBG_PRINT_REG32 "Segment base page addr:", %eax
	orl		$1, %eax			# Set present bit
#	DBG_PRINT_REG32 "Segment page count:", %ecx

kptseg_loop:
	sstol				# Store the next page table entry
	addl	$0x1000, %eax		# Advance to next physical page
	loop	kptseg_loop

	cmpl	%edx, %esi		# If moving on to 2nd segment,
	jne	kptbl_next		# Reset %esi for start of text

	movl	$stext, %edi		# Compute addr of page table
	shrl	$12-2, %edi		#  entry for start of kernel text
	andl	$0xffc, %edi
	addl	$KPTBL_LOC, %edi

kptbl_next:
	addl	$12, %ebx		# Advance to next segment
	decl	%edx
	jnz		kptbl_loop

kptbl_end:
	DBG_PRINT "\nFinished setting up kernel page table\r\n"
/* 	At this point, we are running on the bootloaders stack. */
/* 	We will now find our stack and switch to it. */
	movl	$df_stack, %eax
	call	R_Set_Addr

	movw	%ds, %ax
	movw	%ax, %ss
	addl	$DFSTKSIZ, %ebx
	movw	%bx, %sp

	/*  Print what we think the physical address of `_start` is, to make it obvious if there is a issue locating physical addresses. */
	movl	$_start, %eax
	DBG_PRINT_REG32 "_start virtual address:", %eax
	call	R_Virt_to_Phys
	DBG_PRINT_REG32 "_start physical address:", %eax

	/*  Print the physical address of the munge table function. */
	movl	$munge_table, %eax
	call	R_Virt_to_Phys
	DBG_PRINT_REG32 "munge_table physical address:", %eax

	/*  Print the physical address of the BKI_ok function. */
	movl	$BKI_ok, %eax
	call	R_Virt_to_Phys
	DBG_PRINT_REG32 "BKI_ok physical address:", %eax

	/*  Print the physical address of the kptbl_end label. */
	movl	$kptbl_end, %eax
	call	R_Virt_to_Phys
	DBG_PRINT_REG32 "kptbl_end physical address:", %eax

	/*  Print the physical address of the _start_gdt label. */
	movl	$_start_gdt, %eax
	call	R_Virt_to_Phys
	DBG_PRINT_REG32 "_start_gdt physical address:", %eax

	/* Print the physical address of the _set_gdt label. */
	movl	$_set_gdt, %eax
	call	R_Virt_to_Phys
	DBG_PRINT_REG32 "_set_gdt physical address:", %eax

	/* Print the physical address of the about_to_enable_paging label. */
	movl	$_about_to_enable_paging, %eax
	call	R_Virt_to_Phys
	DBG_PRINT_REG32 "about_to_enable_paging physical address:", %eax

	/*  Print the virtual and physical addresses of the GDT and IDT before munging. */
	movl	$gdt, %eax
	DBG_PRINT_REG32 "GDT virtual address before munging:", %eax
	call	R_Virt_to_Phys
	DBG_PRINT_REG32 "GDT physical address before munging:", %EAX

	/* Print the physical address of the end of the GDT. */
	movl	$gdtend, %eax
	call	R_Virt_to_Phys
	DBG_PRINT_REG32 "GDT end physical address before munging:", %EAX

	/*  Now, find the GDT so that we can rearrange it. */
_start_gdt:
	movl	$gdt, %eax

	movl	$gdtend, %ecx
	subl	%eax, %ecx
	subl	$1, %ecx

	/* Fixup the GDT descriptor length. */
	# movl	$Rgdtdscr, %eax
	# call	R_Set_Addr
	# movw	%cx, (%ebx)		# Write limit as 16-bit value only
	# DBG_PRINT_REG16 "GDT limit before munging:", %cx

	# Compute physical address of the GDT and write limit & base into Rgdtdscr
	#movl	$gdt, %eax
	#call	R_Virt_to_Phys		# EAX := physical address of gdt
	#pushl	%eax			# save physical base
#
	#movl	$Rgdtdscr, %eax
	#call	R_Set_Addr		# DS:EBX -> real-mode pointer to Rgdtdscr
	#popl	%eax			# restore physical base
#
	#movl	%eax, 4(%ebx)		# write base (32-bit)

	#DBG_PRINT_REG32 "GDT physical base set to:", %eax

	/*  Print what the linker put in the GDT limit field. */
	movl	$GDTSZ * 8, %eax
	subl	$1, %eax
	DBG_PRINT_REG32 "Linker GDT size - 1:", %eax

	movl	$gdt, %eax
	movl    $GDTSZ * 8 - 1, %ecx
	call	munge_table

	/*  Find the IDT so that we can rearrange it. */
	movl	$idt, %eax

	movl	$IDTLIM, %ecx
	call	munge_table
#ifdef VPIX
	/*  Find the IDT so that we can rearrange it. */
	movl	$idt2, %eax

	movl	$IDTLIM, %ecx
	call	munge_table
#endif

	/*  A couple of other interesting descriptors.  (scall_dscr) */
	movl    $scall_dscr, %eax
	movl	$1, %ecx
	call	munge_table

	/*  A couple of other interesting descriptors.  (sigret_dscr) */
	movl    $sigret_dscr, %eax
	movl	$1, %ecx
	call	munge_table

	/*  Now, we need to fix up the first, 3gig, and last entries in the */
	/*  page directory. */

	movl	$kpt0, %eax		# First, Page table 0
	DBG_PRINT_REG32 "kpt0 virtual address:", %eax
	call	R_Virt_to_Phys
	DBG_PRINT_REG32 "kpt0 physical address:", %eax
	andl	$0xfffff000, %eax    # ensure page-aligned PFN
	orl		$PG_P, %eax          # Set the present bit
	orl		$PG_RW, %eax         # Make the page writable
	movl	%eax, %fs:KPD_LOC   # Store full 32-bit PD entry
	DBG_PRINT_REG32 "PD[0] entry:", %eax
	movl	%eax, %fs:[KPD_LOC+3072]
	DBG_PRINT_REG32 "PD[768] entry:", %eax

				# Also, kernel address page table
	movl	$KPTBL_LOC+1, %eax	#   (with present bit set)
	orl		$PG_P, %eax          # set present
	orl		$PG_RW, %eax         # set writable
	movl	%eax, %fs:[KPD_LOC+3328]
	DBG_PRINT_REG32 "PD[832] entry (KVS):", %eax

	movl	$kptn, %eax		# Now, the last Page table
	call	R_Virt_to_Phys
	andl	$0xfffff000, %eax    # ensure page-aligned PFN
	orl		$PG_P, %eax          # Set present bit
	orl		$PG_RW, %eax         # Make the page writable
	movl	%eax, %fs:[KPD_LOC+4092]
	DBG_PRINT_REG32 "PD[last] entry:", %eax


#if defined (MB1) || defined (MB2)
/* 	The mon_init procedure will call into the monitor to allow it */
/* 	to initialize its vectors in the IDT and GDT.  Due to some */
/* 	'features' in DMON, gdtr and idtr will be handled in mon_init. */
/* 	data16 */
/* 	call	mon_init */
#endif /* MB1 */

	/*  Load IDTR and GDTR */
	movl    $Rgdtdscr, %eax
	call	R_Set_Addr
_set_gdt:
	lgdtl	(%ebx)

#ifdef AT386
/* 	Code to find font locations from the bios */
/* 	and to put them in egafonptr[] where the kd driver can find them. */

	movw	$0x1130, %ax	# set up bios call
	.value	0
	movw	$0x0300, %bx	# get pointer to 8x8 font
	.value	0
	int	$0x10

	movl	$egafontptr, %eax
	call	R_Set_Addr
	movl	%ebp, (%ebx)
	movw	%es, 2(%ebx)

	movw	$0x1130, %ax	# set up bios call
	.value	0
	movw	$0x0200, %bx	# get pointer to 8x14 font
	.value	0
	int	$0x10

	movl	$egafontptr+4, %eax
	call	R_Set_Addr
	movl	%ebp, (%ebx)
	movw	%es, 2(%ebx)

	movw	$0x1130, %ax	# set up bios call
	.value	0
	movw	$0x0500, %bx	# get pointer to 9x14 font
	.value	0
	int	$0x10

	movl	$egafontptr+8, %eax
	call	R_Set_Addr
	movl	%ebp, (%ebx)
	movw	%es, 2(%ebx)

	movw	$0x1130, %ax	# set up bios call
	.value	0
	movw	$0x0600, %bx	# get pointer to 8x16 font
	.value	0
	int	$0x10

	movl	$egafontptr+0xc, %eax
	call	R_Set_Addr
	movl	%ebp, (%ebx)
	movw	%es, 2(%ebx)

	movw	$0x1130, %ax	# set up bios call
	.value	0
	movw	$0x0700, %bx	# get pointer to 9x16 font
	.value	0
	int	$0x10

	movl	$egafontptr+0x10, %eax
	call	R_Set_Addr
	movl	%ebp, (%ebx)
	movw	%es, 2(%ebx)
#endif /* AT386 */

/* 	*** NOTICE *** NOTICE *** NOTICE *** NOTICE *** NOTICE *** */
/*  */
/* 		Do not try to single step past this point!!!! */
/* 		use a 'go till' command!!!! */
	movl    $Ridtdscr, %eax
	call	R_Set_Addr
	lidtl	(%ebx)
	smsw	%eax		# Get the MSW

	orl	$PROTBIT, %eax

	lmsw	%ax		# Kick us into protected mode
	jmp	qflush

qflush:			# Note that this point we are still
			/*  in 16 bit addressing mode. */

	movl	$KPD_LOC, %eax
	movl	%eax, %cr3

	DBG_PRINT "CR3 set to page directory at KPD_LOC\r\n"
	DBG_PRINT_REG32 "CR3 value:", %eax

	movl	%cr0, %eax
	orl		$PAGEBIT, %eax
_about_to_enable_paging:
	movl	%eax, %cr0

	DBG_PRINT "Enabled paging!\r\n"
	DBG_PRINT_REG32 "CR0 after enabling paging:", %eax

	movl	$JTSSSEL, %eax

	ltr	%ax

	DBG_PRINT "About to jump!"

/* 	This is a 16 bit long jump. */
	.byte	0xEA
	.value	0
	.value	KTSSSEL

/*  ********************************************************************* */
/*  */
/* 	munge_table: */
/* 		This procedure will 'munge' a descriptor table to */
/* 		change it from initialized format to runtime format. */
/*  */
/* 		Assumes: */
/* 			%eax -- contains the base address of table. */
/* 			%ecx -- contains size of table. */
/*  */
/*  ********************************************************************* */

munge_table:
        pushl   %ds

        DBG_PRINT_REG32 "Starting munge_table with base:", %eax
        DBG_PRINT_REG32 "  Table size (bytes):", %ecx

        /*
         * Use full 32-bit arithmetic for base/end and iterator so we do not
         * truncate addresses to 16-bits.  Inputs: %eax = base, %ecx = size/limit.
         * Save EDI (end marker) since the descriptor munging code uses EDX.
         */
        pushl   %edi            # Save edi; will use it for end marker
        addl    %eax, %ecx      # ecx := end = base + size (compute end address)
        movl    %ecx, %edi      # edi := end marker (preserved across descriptor munging)
        movl    %eax, %esi      # esi := current pointer (base)

moretable:
        cmpl    %edi, %esi              # if esi >= end, we're done
        jge     donetable

        movl    %esi, %eax              # pass full 32-bit address to R_Set_Addr
        call    R_Set_Addr

        movb    7(%ebx), %al    # Find the byte containing the type field
        testb   $0x10, %al      # See if this descriptor is a segment
        jne     notagate
        testb   $0x04, %al      # See if this destriptor is a gate
        je      notagate
                                /*  Rearrange a gate descriptor. */
        movl    6(%ebx), %eax   # Type (etc.) lifted out
        movl    4(%ebx), %edx   # Selector lifted out.
        movl    %eax, 4(%ebx)   # Type (etc.) put back
        movl    2(%ebx), %eax   # Grab Offset 16..31
        movl    %edx, 2(%ebx)   # Put back Selector
        movw    %ax, 6(%ebx)    # Offset 16..31 now in right place
        jmp     descdone

notagate:                       # Rearrange a non gate descriptor.
        movl    4(%ebx), %edx   # Limit 0..15 lifted out
        movb    %al, 5(%ebx)    # type (etc.) put back
        movl    2(%ebx), %eax   # Grab Base 16..31
        movb    %al, 4(%ebx)    # put back Base 16..23
        movb    %ah, 7(%ebx)    # put back Base 24..32
        movl    (%ebx), %eax    # Get Base 0..15
        movw    %ax, 2(%ebx)    # Base 0..15 now in right place
        movw    %dx, (%ebx)     # Limit 0..15 in its proper place

descdone:
        addl    $8, %esi        # Go for the next descriptor
        jmp     moretable

donetable:
        DBG_PRINT "Done munge_table\r\n"
        popl    %edi            # Restore edi (end marker)
        popl    %ds
        ret

#if defined (MB1) || defined (MB2)
/*  ********************************************************************* */
/*  */
/* 	mon_init: */
/*                This procedure will check a DMON flag in memory to */
/* 		find the entry point to sq$init_monitor and call it. */
/*  */
/* 		The steps performed are: */
/* 		1) Look at the start of the table to see if */
/* 		   the characters "JBT" are there.  If so, */
/* 		   this is DMON and we can call sq$mon_init. */
/* 		   If not, exit, we cannot use the monitor. */
/*  */
/* 		2) Load gdtr and idtr with the physical addresses */
/* 		   of the descriptor tables.  These addresses are not */
/* 		   the same as the linear addresses we will use, but */
/* 		   must be the physical addresses so that DMON can */
/* 		   find the tables. */
/*  ********************************************************************* */
mon_init:
	movl	$JBTLOC, %eax
	call	R_Set_Addr

	movw	(%ebx), %ax
	andw	$0xffff, %ax
	.value	0x00ff

	cmpl    $0x0054424a, %eax
	jne	no_monitor

	pushl   %ds             # Save the address of the DMON flag
	popl    %es
	movw	%bx, %cx

	/*  Load IDTR and GDTR with the physical addresses of the tables. */
	movl	$RIgdtdscr, %eax
	call	R_Set_Addr

	movw	2(%ebx), %ax
	call	R_Virt_to_Phys
	movw	%ax, 2(%ebx)

	lgdtl	(%ebx)

/* 	*** NOTICE *** NOTICE *** NOTICE *** NOTICE *** NOTICE *** */
/*  */
/* 		Do not try to single step past this point!!!! */
/* 		use a 'go till' command!!!! */
	/*  See if the user wants to use DMON on user processes. */
	movl	$Rusermon, %eax
	call	R_Set_Addr

	testb	$0xff, (%ebx)
	jz	normal_mon

	movl	$RIidtdscr, %eax
	movl	$idt, %edi
	jmp	chose_mon

normal_mon:
	movl	$RMidtdscr, %eax
	movl	$monidt, %edi

chose_mon:
	call	R_Set_Addr

	movw	2(%ebx), %ax
	call	R_Virt_to_Phys
	movw	%ax, 2(%ebx)

	lidtl	(%ebx)

/* 	Let the monitor initialize its vectors. */
/* 	.byte	0x9A */
/* 	.value	0x341 */
/* 	.value	0x80 */
	movl	%ecx, %ebx
	.byte	0x26		# Use es
	.byte	0xff
	.byte	0x5f
	.byte	0x18
/* 	call	%es:24(%cx) */

	movl	$R0idtdscr, %eax
	call	R_Set_Addr

	lidtl	(%ebx)

/*  Since we do not want DMON to use 0 linear for its data segment, */
/*  we must reset the base of gdt[3] to the linear area we have mapped */
/*  to 0 physical. */
	movl	$gdt, %eax
	call	R_Set_Addr

	movw	26(%ebx), %ax
	call	R_Virt_to_Phys
	movw	%ax, %cx
	xorw	%ax, %ax
	movb	31(%ebx), %al
	shlw	$24, %ax
	orw	%cx, %ax
	addw	$0x0000, %ax
	.value	0xFFF7
	movl	%eax, 26(%ebx)
	shrw	$16, %ax
	movb	%ah, 31(%ebx)
	movb	%al, 28(%ebx)

/*  Now, grab the selector and offset out of interrupt 1 and 3 */
/*  We will store them so the interrupt handlers can access them */
/*  at will. */
	movw	%di, %ax	# We loaded edi before the first lidt
	call	R_Set_Addr
	pushl	%ds
	popl	%es
	movw	%bx, %di

	movl	$mon1sel, %eax
	call	R_Set_Addr

	movl	%es:10(%edi), %eax
	movl	%eax, (%ebx)

	movl	$mon1off, %eax
	call	R_Set_Addr
	movl	%es:8(%edi), %eax
	movl	%eax, (%ebx)
	movl	%es:14(%edi), %eax
	movl	%eax, 2(%ebx)

	movl	$mon3sel, %eax
	call	R_Set_Addr

	movl	%es:26(%edi), %eax
	movl	%eax, (%ebx)

	movl	$mon3off, %eax
	call	R_Set_Addr
	movl	%es:24(%edi), %eax
	movl	%eax, (%ebx)
	movl	%es:30(%edi), %eax
	movl	%eax, 2(%ebx)

no_monitor:
	ret
#endif /* MB1 */

/*  ********************************************************************* */
/*  */
/* 	R_Virt_to_Phys: */
/* 		This procedure takes a 32 bit virtual address and */
/* 		converts it to a linear physical address by looking */
/* 		it up in the kernel page table. */
/*  */
/* 		Input: */
/* 			%eax -- virtual address. */
/*  */
/* 		Output: */
/* 			%eax -- physical address. */
/*  */
/*  ********************************************************************* */
R_Virt_to_Phys:
	pushl	%ebx
	movl	%eax, %ebx		# Save virtual address in %ebx
	subl	$KVSBASE, %eax		# If address is below KVSBASE,
	jb	vtop_done		#   assume it's physical

	shrl	$12-2, %eax		# Convert to page table offset
	andl	$0xffc, %eax

	movl	%fs:KPTBL_LOC(%eax), %eax  # Get physical page address
	andl	$0xfffff000, %eax

	andl	$0xfff, %ebx		# Get virtual page offset

	addl	%eax, %ebx		# Compute final virtual address

vtop_done:
	movl	%ebx, %eax
	popl	%ebx
	ret

/*  ********************************************************************* */
/*  */
/* 	R_Set_Addr: */
/* 		This procedure takes a 32 bit address and sets up ds:bx */
/* 		from it.  In the process, it will cut it down into */
/* 		the first megabyte. */
/*  */
/* 		Input: */
/* 			%eax -- 32-bit physical address. */
/*  */
/* 		Output: */
/* 			%ds:%ebx -- real-mode address. */
/* 			[ %eax not preserved ] */
/*  */
/*  ********************************************************************* */
R_Set_Addr:
	call	R_Virt_to_Phys	# Convert to a physical (linear) address.
	movw	%ax, %bx	# Remember the addr for the offset portion.
	shrw	$4, %ax		# Turn the address into a real mode selector.
	movw	%ax, %ds

	andl	$0xF, %ebx	# Now the offset portion

	ret
