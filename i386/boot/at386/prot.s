/	Copyright (c) 1990 UNIX System Laboratories, Inc.
/	Copyright (c) 1984, 1986, 1987, 1988, 1989, 1990 AT&T
/	  All Rights Reserved

/	THIS IS UNPUBLISHED PROPRIETARY SOURCE CODE OF
/	UNIX System Laboratories, Inc.
/	The copyright notice above does not evidence any
/	actual or intended publication of such source code.

/	Copyright (c) 1987, 1988 Microsoft Corporation
/	  All Rights Reserved

/	This Module contains Proprietary Information of Microsoft
/	Corporation and should be treated as Confidential.

	.file	"prot.s"

	.ident	"@(#)boot:boot/at386/prot.s	1.1.3.1"

#include "bsymvals.h"

/	----------------------------------------------------
/ Enter protected mode.
/
/ We must set up the GDTR
/
/ When we enter this routine, 	ss == ds == cs == "codebase", 
/	when we leave,  	ss == ds = 0x10, es = 0x08, cs = 0x18
/
/ Trashes %ax, %bx.

	.globl	goprot
goprot:

/	get return %eip, for later use
	.byte	0x66
	popl	%ebx

/	load the GDTR

	.byte	0x67
	.byte	0x66
	lgdt	GDTptr

	mov	%cr0, %eax

	.byte	0x66
	or	$PROTMASK, %eax

	mov	%eax, %cr0 

	jmp	qflush			/ flush the prefetch queue

/ 	Set up the segment registers, so we can continue like before;
/ 	if everything works properly, this shouldn't change anything.
/ 	Note that we're still in 16 bit operand and address mode, here, 
/ 	and we will continue to be until the new %cs is established. 

qflush:
	.byte	0x66
	mov	$0x10, %eax
	movw	%ax, %es
	movw	%ax, %ds
	movw	%ax, %ss		/ don't need to set %sp

/ 	Now, set up %cs by fiddling with the return stack and doing an lret

/	push %cs
	.byte	0x66
	pushl	$0x18

/	push %eip
	.byte	0x66
	pushl	%ebx

	.byte	0x66
	lret

/	----------------------------------------------------
/ 	Re-enter real mode.
/ 
/ 	We assume that we are executing code in a segment that
/ 	has a limit of 64k. Thus, the CS register limit should
/ 	be set up appropriately for real mode already. We also
/ 	assume that paging has *not* been turned on.
/ 	Set up %ss, %ds, %es, %fs, and %gs with a selector that
/ 	points to a descriptor containing the following values
/
/	Limit = 64k
/	Byte Granular 	( G = 0 )
/	Expand up	( E = 0 )
/	Writable	( W = 1 )
/	Present		( P = 1 )
/	Base = any value

	.globl	goreal
goreal:

/ 	To start off, transfer control to a 16 bit code segment

	ljmp	$0x20, $set16cs
set16cs:			/ 16 bit addresses and operands 

/	need to have all segment regs sane before we can enter real mode
	.byte	0x66
	movl	$0x10, %eax
	movw	%ax, %es

	.byte	0x66
	mov	%cr0, %eax

/	clear the protection bit
	.byte	0x66
	and 	$NOPROTMASK, %eax

	.byte	0x66
	mov	%eax, %cr0

/ 	We want to do a long ret here, to reestablish %cs in real mode
/	Check destseg to find out where we want to go.

	.byte	0x67
	.byte	0x66
	pushl	destseg

	.byte	0x66
	pushl	$restorecs

	.byte	0x66
	lret

/ 	Now we've returned to real mode, so everything is as it 
/	should be. Set up the segment registers and so on.
/	The stack pointer can stay where it was, since we have fiddled
/	the segments to be compatible.

restorecs:

	movw	%cs, %ax
	movw	%ax, %ss
	movw	%ax, %ds
	movw	%ax, %es

/	return to whence we came; it was a 32 bit call
	.byte	0x66
	ret
