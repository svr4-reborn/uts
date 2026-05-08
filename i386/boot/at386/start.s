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

	.file	"start.s"

	.ident	"@(#)boot:boot/at386/start.s	1.1.3.2"

/ 	UNIX V.3/386 bootstrap

#include "bsymvals.h"


/	This is ground zero, the initial point where control is transfered
/	by the master boot loader.
/ 	Here we are running where we are originally loaded:
/	cs = 0x0, ip = 0x7c00.

	.text	

ZERO:
firststage:
	cli

/	A tremendous kludge, here; we hardcode "ljmp 0x7c0:restart" in
/	order to set us up in the new segment.

	.byte	0xea
	.value	0x6
	.value	0x7c0

/	Now we are running at 0x7c0:0 

restart:
	movw	%cs, %ax
	movw	%ax, %es
	movw	%ax, %ds
	movw	%ax, %ss	/ set up stack
/	this indicates a "true" 32 bit operation
	.byte	0x66
	movl	$STACK, %esp
	sti

	.byte	0x67
	movw	destseg, %ss
/	data16
/	mov	$STACK, %esp

	push	%ss			/ save for lret

/	read/relocate boot
	.byte	0x66
	call	readboot

	.byte	0x8d
	.byte	0x06
	.byte	0x00
	.byte	0x02			/ lea secondstage, %ax

	push	%eax

	lret				/ jump to second stage

	/ does not return


/	----------------------------------------------------
readboot:

/ 	Get the hard drive parameters; use int 13 function 8 to do this

	movb	$8, %ah			/ Return Drive Parameters function
	movb	$0x80, %dl		/ for Hard Drive 0

	int	$0x13			/ BIOS disk support

/	Save parameters in table
	.byte	0x67
	mov	%ecx, hd0parm
	.byte	0x67
	mov	%edx, hd0parm+2

	/ As a result of the BIOS call, the following parameters are now loaded:
	/   CL = max_sect  CH = max_cyl  DL = n_drives  DH = max_head

#ifdef WINI
/	# sectors per track
	.byte	0x66
	movzbl	%cl, %eax
	andb	$0x3F, %al

	.byte	0x67
	.byte	0x66
	movl	%eax, spt

/	# tracks per cylinder
	.byte	0x66
	movzbl	%dh, %eax
	incl	%eax

/	* # sectors per track
	.byte	0x67
	mulw	spt
/	32 bit moff, 32 bits of data
	.byte	0x67
	.byte	0x66
	movl	%eax, spc

/ 	Find the active partition

/	sector = partition table
	.byte	0x66
	movl	$1, %ecx
/	read 1 sector
	.byte	0x66
	movl	$0x201, %eax

/	32 bit moff
	.byte	0x67
	movw	destseg, %es

/	32 bit moff, move 32 bits of data
	.byte	0x67
	.byte	0x66
	movl	destoff, %ebx

/	from main wini drive 0x80
	.byte	0x66
	movl	$BOOTDRIVE, %edx

	int	$0x13			/ BIOS disk support

	jc	ioerr

	.byte	0x66
	movl	$FD_NUMPART, %ecx
	.byte	0x66
	addl	$BOOTSZ, %ebx

ostry:
	.byte	0x67
	movb    %es:BOOTIND(%ebx), %al
	cmpb	$ACTIVE, %al
	je	osfound

	.byte	0x66
	addl	$16, %ebx

	loop	ostry

/	no active partition found
	.byte	0x66
	movl	$nopart, %esi
	.byte	0x66
	jmp	fatal

osfound:
/	save relative sector number
	.byte	0x67
	.byte	0x66
	movl	%es:RELSECT(%ebx), %eax
	.byte	0x66
	.byte	0x67
	movl	%eax, unix_start
#else	/* WINI */

/	if we are supporting 3.5 inch drives, we must go through
/	the diskette parameter table to discover the # of sectors/track.
/	Recall that, for a diskette, sectors/cyl = 2 * sectors/track.

	.byte	0x66
	pusha

/	clear out %eax
	.byte	0x66
	xorl	%eax, %eax
	movb	$0x8, %ah		/ subfunction 8
	movb	$0, %dl			/ drive 0

	int	$0x13
	jc	typecheck_failed	/ assume 15 sec per track if fails
	
/	low 6 bits of %ecx are spt
	.byte	0x66
	and	$0x3f, %ecx

	.byte	0x67
	.byte	0x66
	movl	%ecx, spt

typecheck_failed:
	.byte	0x67
	.byte	0x66
	movl	spt, %ecx

/	set numsec to do one track at a time
	.byte	0x67
	.byte	0x66
	movl	numsec, %eax

	.byte	0x67
	.byte	0x66
	movl	%ecx, numsec

	.byte	0x66
	subl	%ecx, %eax

/	leftover sectors on second track
	.byte	0x67
	.byte	0x66
	movl	%eax, extrasec

	shl	$1, %ecx  		/ multiply spt by 2 to get spc

	.byte	0x67
	.byte	0x66
	movl	%ecx, spc

	.byte	0x66
	popa
#endif /* WINI */

/ 	call the BIOS to read the remainder of the bootstrap from disk

doio:
	.byte	0x67
	mov	numsec, %ebx
	push	%ebx			/ sector count: 16 bits

	.byte	0x67
	mov	destoff, %ebx
	push	%ebx			/ destination offset: 16 bits

	.byte	0x67
	.byte	0x66
	mov	destseg, %ebx
	push	%ebx			/ destination segment: 16 bits

	.byte	0x67
	.byte	0x66
	mov	unix_start, %ebx
	.byte	0x66
	push	%ebx			/ relative sector number: 32 bits

	.byte	0x66
	call	_disk			/ do the i/o

	.byte	0x66
	addl	$10, %esp		/ restore the stack

#ifndef WINI
/	extra sectors on second track
	.byte	0x67
	push	extrasec

/	clear %edx for multiplies
	.byte	0x66
	xorl	%edx, %edx

/	calculate new dest. offset
	.byte	0x67
	.byte	0x66
	mov	numsec, %eax

	.byte	0x66
	mov	$SECSIZE, %ebx		/ multiply by dev_gran

	.byte	0x66
	mul	%ebx	

/	add to original offset
	.byte	0x67
	.byte	0x66
	add	destoff, %eax

	push	%eax			/ destination offset: 16 bits

	.byte	0x67
	.byte	0x66
	mov	destseg, %ebx
	push	%ebx			/ destination segment: 16 bits

	.byte	0x67
	.byte	0x66
	mov	unix_start, %ebx

	.byte	0x67
	.byte	0x66
	addl	numsec, %ebx

	.byte	0x66
	push	%ebx			/ relative sector number: 32 bits

	.byte	0x66
	call	_disk			/ do the i/o

	.byte	0x66
	addl	$10, %esp		/ restore the stack
#endif

/	return to caller
	.byte	0x66
	ret

#ifndef WINI

/	Leave space at offset %ss:256, since the floppy BIOS
/	uses it as scratch.
/
fd_zero:
/	. = ZERO + 256
	.align	256
	.byte 0, 0, 0, 0
#endif

ioerr:
	.byte	0x66
	movl	$readerr, %esi
	.byte	0x66
	jmp	fatal



/	----------------------------------------------------
/ 	_puts:		put null-terminated string at si to console
/
	.globl	_puts
_puts:
	.byte	0x66
	pushl	%esi

	movb	$1, %bl		/ normal attribute
ploop:
	cld

/	get next msg byte
	.byte	0x67
	lodsb

/	chip bug workaround, errata 7
	.byte	0x67
	nop

	orb	%al,%al
	jz	pend		/ end of msg if NUL

	movb	$14, %ah	/ teletype putchar
	int	$0x10		/ issue request

	jmp	ploop

pend:
	.byte	0x66
	popl	%esi

	.byte	0x66
	ret			

/	----------------------------------------------------
/	_disk(secno, seg, offset, count)
/
/	Makes bios calls to read in one sector at a time to 
/	the segment:offset destination.  secno is 0 for the
/	first sector on the disk.  count is the number of
/	sectors to read.
/
	.globl	_disk
_disk:	
	.byte	0x66
	push	%ebp			
/	C-entry save stack frame
	.byte	0x66
	mov	%esp, %ebp

	push	%es

	.byte	0x66
	push	%ebx
/	save registers
	.byte	0x66
	push	%esi
	.byte	0x66
	push	%edi

retry:
	.byte	0x67
	mov	8(%ebp),%eax
	.byte	0x67
	mov	10(%ebp),%edx
/	cyl (%cx) = secno / spc
	.byte	0x67
	divw	spc
	mov	%eax, %ecx			/   temp (%dx) = secno % spc
	mov	%edx, %eax			/ head (%al) = temp / spt
/	sector (%ah) = temp % spt
	.byte	0x67
	divb	spt
	xchgb	%ch,%cl			/ low cylinder bits in %ch
	rorb	$1,%cl			/ high cyl bits in top 2 bits of %cl
	rorb	$1,%cl
	orb	%ah,%cl			/ sector in rest of %cl
	incb	%cl			/ convert to 1-based
	movb	%al,%dh			/ head

/	segment
	.byte	0x67
	movw	12(%ebp), %es
/	starting offset
	.byte	0x67
	mov	14(%ebp), %ebx
/	number of sectors to read
	.byte	0x67
	movb	16(%ebp), %al
	movb	$2, %ah			/ function code for reading sectors
	movb	$BOOTDRIVE, %dl		/ from which drive 

	int	$0x13			/ BIOS disk support

	jnb	okread			/ retry if error

	movb	$0, %ah			/ reset controller
	int	$0x13
	jmp	retry

okread:
/	restore registers
	.byte	0x66
	pop	%edi
	.byte	0x66
	pop	%esi
	.byte	0x66
	pop	%ebx

	pop	%es

	.byte	0x66
	pop	%ebp

/	return
	.byte	0x66
	ret

/	----------------------------------------------------
/	Routine to read the requested byte (in %al) from the CMOS ram, 
/	return result in %al

rdcmos:
	xorb	%ah, %ah
 	outb	$0x70
 	inb	$0x71

	.byte	0x66
	ret

/	----------------------------------------------------
/	halt()
/
/	Stop everything, an error occured.
/

fatal:
/	print error message
	.byte	0x66
	call	_puts
					/ fall through to...
	.align	4
	.globl	halt

halt:	cli				/ allow int's
/	hlt				/ stop.
	jmp	halt			/ STOP.

readerr:	.string		"boot: Error reading bootstrap\r\n"
#ifdef WINI
nopart:		.string		"boot: No active partition on hard disk\r\n"
#endif

	.globl	destseg			/ for use by goreal()

destseg:	.long	0x100		/ put bootstrap at 4K
destoff:	.long	0

numsec:		.long	29
#ifndef WINI
extrasec:	.long	0
#endif

/	Raw disk parameters from BIOS

	.globl	hd0parm
	.globl	hd0maxsec
	.globl	hd0maxcyl
	.globl	hd0ndisk
	.globl	hd0maxhd
	.globl	hd1parm
	.globl	hd1maxsec
	.globl	hd1maxcyl
	.globl	hd1ndisk
	.globl	hd1maxhd

hd0parm:
hd0maxsec:	.byte	0
hd0maxcyl:	.byte	0
hd0ndisk:	.byte	0
hd0maxhd:	.byte	0

hd1parm:
hd1maxsec:	.byte	0
hd1maxcyl:	.byte	0
hd1ndisk:	.byte	0
hd1maxhd:	.byte	0

/ 	The following are used in the high level disk driver

	.globl	spt
	.globl	spc
	.globl	dev_gran
	.globl	unix_start

spt:		.long	15
spc:		.long	15\*2
dev_gran:	.long	SECSIZE
unix_start:	.long	0

/ 	The code immediately below tags this as a "boot block" for DOS
/ 	master boot block loader

/  ------------------------------------------------------------------
/
/	The following '.align' directives do not work with the
/	i386 assembler, load i6.
/
/	As a short-term workaround (i.e., until we get a fixed
/	assembler from CPLU) we will use the code that follows.
/
/  ----------------- <begin commented-out section> -------------------
/#ifndef WINI
/	.align	510
/#else
/	.align	506
/#endif
/  ----------------- < end  commented-out section> -------------------
/
/  ----------------- < begin replacement code > ----------------------
	. = ZERO + 510

/  ----------------- < end  replacement code > -----------------------
	.byte 0x55
	.byte 0xaa

/	----------------------------------------------------

/	This is the second stage of the bootstrap, where we jump once
/	the bootstrap has been complete read into memory and relocated.
/	The code above guarentees that 'secondstage' is at offset 0x200.

secondstage:

/	need to copy variables from first stage that were changed

	int	$0x12			/ BIOS memory size call
/	already relocated, do not add cs
	.byte	0x67
	.byte	0x66
	mov	%eax, %cs:memsz
/	copy hd0parm into relocated data
	.byte	0x67
	.byte	0x66
	mov	hd0parm, %eax
	.byte	0x67
	.byte	0x66
	mov	%eax, %cs:hd0parm
/	copy spt into relocated data
	.byte	0x67
	.byte	0x66
	mov	spt, %eax
	.byte	0x67
	.byte	0x66
	mov	%eax, %cs:spt
/	copy spc into relocated data
	.byte	0x67
	.byte	0x66
	mov	spc, %eax
	.byte	0x67
	.byte	0x66
	mov	%eax, %cs:spc
/	copy dev_gran into relocated data
	.byte	0x67
	.byte	0x66
	mov	dev_gran, %eax
	.byte	0x67
	.byte	0x66
	mov	%eax, %cs:dev_gran
/	copy destseg into relocated data
	.byte	0x67
	.byte	0x66
	mov	destseg, %eax
	.byte	0x67
	.byte	0x66
	mov	%eax, %cs:destseg
/	copy unix_start into relocated data
	.byte	0x67
	.byte	0x66
	mov	unix_start, %eax
	.byte	0x67
	.byte	0x66
	mov	%eax, %cs:unix_start

/	set up the segment registers

	movw	%cs, %ax			/ Want CS = DS = ES = SS
	movw	%ax, %ds			
	movw	%ax, %es			
 	movw	%ax, %ss

	.byte	0x66
	mov	$STACK, %esp

#ifdef DEBUG
	.byte	0x66
	mov	$banner2, %esi
	.byte	0x66
	call	_puts
#endif

/	get hard disk parameters for drive 1 to pass to the kernel

	movb	$8, %ah			/ Return Drive Parameters function
	movb	$0x81, %dl		/ for Hard Drive 1

	int	$0x13			/ BIOS disk support

/	Save parameters in table
	.byte	0x67
	mov	%ecx, hd1parm
	.byte	0x67
	mov	%edx, hd1parm+2

/	start up the C code

/	enter protected mode
	.byte	0x66
	call	goprot
	cli

	call	main			/ jump to the C code; shouldn't return

	sti
	call	goreal			/ we should never reach this point

	jmp	halt

#ifdef DEBUG
banner2:	.string	"boot [second stage]:\r\n"
#endif
	.globl  memsz
memsz:		.long   0
