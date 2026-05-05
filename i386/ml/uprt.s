#* Copyright (c) 1990 UNIX System Laboratories, Inc. */
#* Copyright (c) 1984, 1986, 1987, 1988, 1989, 1990 AT&T */
#* All Rights Reserved */

#* THIS IS UNPUBLISHED PROPRIETARY SOURCE CODE OF */
#* UNIX System Laboratories, Inc. */
#* The copyright notice above does not evidence any */
#* actual or intended publication of such source code. */

#* Copyright (c) 1987, 1988 Microsoft Corporation */
#* All Rights Reserved */

#* This Module contains Proprietary Information of Microsoft */
#* Corporation and should be treated as Confidential. */

	.ident	"@(#)kern-ml:uprt.s	1.3.2.2"

#include "symvals.h"

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
	.set	PAGEBIT, 0x8000
	.set    DFSTKSIZ,0x0FFE
	.set	IDTLIM, [8*256-1]
	.set	MONIDTLIM, [8*16-1]
	.set	JBTLOC, 0x0400
	.set	BM_BASE, 0
	.set	BM_EXTENT, 4
	.set	KPD_LOC, [KPTBL_LOC+0x1000]

	.text
#* */
#* *** NOTICE *** NOTICE *** NOTICE *** NOTICE *** NOTICE *** */
#* */
#* The instructions in pstart are reversed 16 <--> 32 */
#* bits.  This is because we are running pstart in */
#* REAL MODE.  By using long instructions, we generate */
#* opcodes that are 16 bit instructions when run */
#* in REAL MODE. */

#* More nice information: */
#* This code now only supports the BKI boot-kernel interface. */
#* This passes the magic number 0xff1234ff in %edi. */
#* All other info is passed in the bootinfo structure. */

pstart:
_start:

	.byte	0x66
	cmpl	$BKI_MAGIC, %edi
	.byte	0x66
	je	BKI_ok

#* Bad magic number from bootstrap. */
#* Print a message, then halt. */
#* Unfortunately, this will only work on an AT386. */

	.byte	0x66
	call	_rprint
	.string	"\r\nBootstrap too old.\r\n"
_halt:
	sti
	hlt
	jmp	_halt

_rprint:
	.byte	0x66
	popl	%esi		# get pointer to message

	movb	$1, %bl		# foreground color
ploop:	.byte	0x67
	movb	%cs:(%esi), %al	# get chr
	.byte	0x66
	incl	%esi
	testb	%al, %al	# test for end of string
	jz	pend
	movb	$14, %ah	# setup call to bios
	int	$0x10		# print chr
	jmp	ploop		# repeat for next chr
pend:
	.byte	0x66
	pushl	%esi
	.byte	0x66
	ret


	.align	8
Rusermon:
	.byte   0               # If you set this byte to non-zero
#* moninit will put the monitors vectors */
#* into idt(1) and idt(3), thus allowing */
#* user programs to be debugged with DMON. */
	.string	"<-Here"

	.align	8	# This is for ease of looking at memory.
Rgdtdscr:
	.value  [8*GDTSZ-1]       # We will re-compute this, but just in case...
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

#* EGA font pointers (these start as real mode pointers) */
#* The pointers point to the 8x8, 8x14, 9x14, 8x16 and */
#* the 9x16 fonts, respectively */

egafontptr:
	.long	0
	.long	0
	.long	0
	.long	0
	.long	0
	
BKI_ok:
#* Here we have to set up the kernel symbol page table */
#* according to the memused information passed by the bootstrap. */
#* After we're done, R_Set_Addr will be able to convert virtual */
#* addresses to physical addresses using this page table. */

	.byte	0x66
	xorl	%eax, %eax		# Load 0 into segment registers
	movw	%ax, %ds		#   so we get absolute addresses
	movw	%ax, %es
	movw	%ax, %fs
	cld

	.byte	0x66
	movl	$KPTBL_LOC, %edi	# First zero out the page table & dir
	.byte	0x66
	movl	$2048, %ecx
	.byte	0x67
	.byte	0x66
	rep; sstol

	.byte	0x66
	movl	$BOOTINFO_LOC, %ebx
	.byte	0x66
	.byte	0x67
	movl	memusedcnt(%ebx), %edx	# Get count of memused segments
	.byte	0x66
	movl	%edx, %esi
	.byte	0x66
	addl	$memused, %ebx		# Get pointer to first segment

	.byte	0x66
	movl	$KPTBL_LOC, %edi	# "Reserved" segment maps at KVSBASE

kptbl_loop:
	.byte	0x66
	.byte	0x67
	movl	BM_EXTENT(%ebx), %ecx	# Compute # pages for this segment
	.byte	0x66
	shrl	$12, %ecx

	.byte	0x66
	.byte	0x67
	movl	BM_BASE(%ebx), %eax	# Compute base pte for this segment
	.byte	0x66
	andl	$0xfffff000, %eax
	incl	%eax			# Set present bit

kptseg_loop:
	.byte	0x67
	.byte	0x66
	sstol				# Store the next page table entry
	.byte	0x66
	addl	$0x1000, %eax		# Advance to next physical page
	loop	kptseg_loop

	.byte	0x66
	cmpl	%edx, %esi		# If moving on to 2nd segment,
	jne	kptbl_next		# Reset %esi for start of text

	.byte	0x66
	movl	$stext, %edi		# Compute addr of page table
	.byte	0x66
	shrl	$12-2, %edi		#  entry for start of kernel text
	.byte	0x66
	andl	$0xffc, %edi
	.byte	0x66
	addl	$KPTBL_LOC, %edi

kptbl_next:
	.byte	0x66
	addl	$12, %ebx		# Advance to next segment
	decl	%edx
	.byte	0x66
	jnz	kptbl_loop

#* At this point, we are running on the bootloaders stack. */
#* We will now find our stack and switch to it. */
	.byte	0x66
	movl	$df_stack, %eax
	.byte	0x66
	call	R_Set_Addr

	movw	%ds, %ax
	movw	%ax, %ss
	.byte	0x66
	addl	$DFSTKSIZ, %ebx
	movw	%bx, %sp

#* Now, find the GDT so that we can rearrange it. */
	.byte	0x66
	movl	$gdt, %eax

	.byte	0x66
	movl    $gdtend, %ecx
	subw	%ax, %cx
	subw	$1, %cx

	.byte	0x66
	movl	$Rgdtdscr, %eax
	.byte	0x66
	call	R_Set_Addr
	.byte	0x67
	movl	%ecx, (%ebx)

	.byte	0x66
	movl	$gdt, %eax
	.byte	0x66
	call	munge_table

#* Find the IDT so that we can rearrange it. */
	.byte	0x66
	movl	$idt, %eax

	.byte	0x66
	movl	$IDTLIM, %ecx
	.byte	0x66
	call	munge_table
#ifdef VPIX
#* Find the IDT so that we can rearrange it. */
	.byte	0x66
	movl	$idt2, %eax

	.byte	0x66
	movl	$IDTLIM, %ecx
	.byte	0x66
	call	munge_table
#endif

#* A couple of other interesting descriptors.  (scall_dscr) */
	.byte	0x66
	movl    $scall_dscr, %eax
	.byte	0x66
	movl	$1, %ecx
	.byte	0x66
	call	munge_table

#* A couple of other interesting descriptors.  (sigret_dscr) */
	.byte	0x66
	movl    $sigret_dscr, %eax
	.byte	0x66
	movl	$1, %ecx
	.byte	0x66
	call	munge_table

#* Now, we need to fix up the first, 3gig, and last entries in the */
#* page directory. */

	.byte	0x66
	movl	$kpt0, %eax		# First, Page table 0
	.byte	0x66
	call	R_Virt_to_Phys
	incl	%eax			# Set the present bit
	.byte	0x67
	movw	%ax, %fs:KPD_LOC
	.byte	0x67
	movw	%ax, %fs:[KPD_LOC+3072]

	.byte	0x66			# Also, kernel address page table
	movl	$KPTBL_LOC+1, %eax	#   (with present bit set)
	.byte	0x67
	movw	%ax, %fs:[KPD_LOC+3328]

	.byte	0x66
	movl	$kptn, %eax		# Now, the last Page table
	.byte	0x66
	call	R_Virt_to_Phys
	incl	%eax			# Set the present bit
	.byte	0x67
	movw	%ax, %fs:[KPD_LOC+4092]


#if defined (MB1) || defined (MB2)
#* The mon_init procedure will call into the monitor to allow it */
#* to initialize its vectors in the IDT and GDT.  Due to some */
#* 'features' in DMON, gdtr and idtr will be handled in mon_init. */
#* data16 */
#* call	mon_init */
#endif

#* Load IDTR and GDTR */
	.byte	0x66
	movl    $Rgdtdscr, %eax
	.byte	0x66
	call	R_Set_Addr
	.byte	0x67
	.byte	0x66
	lgdt	(%ebx)

#ifdef AT386
#* Code to find font locations from the bios */
#* and to put them in egafonptr[] where the kd driver can find them. */

	movw	$0x1130, %ax	# set up bios call
	.value	0
	movw	$0x0300, %bx	# get pointer to 8x8 font
	.value	0
	int	$0x10

	.byte	0x66
	movl	$egafontptr, %eax
	.byte	0x66
	call	R_Set_Addr
	.byte	0x67
	movl	%ebp, (%ebx)
	.byte	0x67
	movw	%es, 2(%ebx)

	movw	$0x1130, %ax	# set up bios call
	.value	0
	movw	$0x0200, %bx	# get pointer to 8x14 font
	.value	0
	int	$0x10

	.byte	0x66
	movl	$egafontptr+4, %eax
	.byte	0x66
	call	R_Set_Addr
	.byte	0x67
	movl	%ebp, (%ebx)
	.byte	0x67
	movw	%es, 2(%ebx)

	movw	$0x1130, %ax	# set up bios call
	.value	0
	movw	$0x0500, %bx	# get pointer to 9x14 font
	.value	0
	int	$0x10

	.byte	0x66
	movl	$egafontptr+8, %eax
	.byte	0x66
	call	R_Set_Addr
	.byte	0x67
	movl	%ebp, (%ebx)
	.byte	0x67
	movw	%es, 2(%ebx)

	movw	$0x1130, %ax	# set up bios call
	.value	0
	movw	$0x0600, %bx	# get pointer to 8x16 font
	.value	0
	int	$0x10

	.byte	0x66
	movl	$egafontptr+0xc, %eax
	.byte	0x66
	call	R_Set_Addr
	.byte	0x67
	movl	%ebp, (%ebx)
	.byte	0x67
	movw	%es, 2(%ebx)

	movw	$0x1130, %ax	# set up bios call
	.value	0
	movw	$0x0700, %bx	# get pointer to 9x16 font
	.value	0
	int	$0x10

	.byte	0x66
	movl	$egafontptr+0x10, %eax
	.byte	0x66
	call	R_Set_Addr
	.byte	0x67
	movl	%ebp, (%ebx)
	.byte	0x67
	movw	%es, 2(%ebx)
#endif

#* *** NOTICE *** NOTICE *** NOTICE *** NOTICE *** NOTICE *** */
#* */
#* Do not try to single step past this point!!!! */
#* use a 'go till' command!!!! */
	.byte	0x66
	movl    $Ridtdscr, %eax
	.byte	0x66
	call	R_Set_Addr
	.byte	0x67
	.byte	0x66
	lidt	(%ebx)
	.byte	0x67
	smsw %ax		# Get the MSW

	.byte	0x66
	orl	$PROTBIT, %eax

	.byte	0x67
	lmsw %ax		# Kick us into protected mode
	jmp	qflush

qflush:			# Note that this point we are still
#* in 16 bit addressing mode. */

	.byte	0x66
	movl	$KPD_LOC, %eax
	.byte	0x67
	movl	%eax, %cr3

	.byte	0x67
	movl	%cr0, %eax
	orw	$0, %ax
	.value	PAGEBIT
	.byte	0x67
	movl	%eax, %cr0

	.byte	0x66
	movl	$JTSSSEL, %eax

	ltr	%ax

#* This is a 16 bit long jump. */
	.byte	0xEA
	.value	0
	.value	KTSSSEL

#* ********************************************************************* */
#* */
#* munge_table: */
#* This procedure will 'munge' a descriptor table to */
#* change it from initialized format to runtime format. */
#* */
#* Assumes: */
#* %eax -- contains the base address of table. */
#* %ecx -- contains size of table. */
#* */
#* ********************************************************************* */
munge_table:
	pushl	%ds

	.byte	0x66
	andl	$0xFFFF, %ecx
	addw	%ax, %cx
	movw	%ax, %si

moretable:
	cmpw	%si, %cx
	jl	donetable		# Have we done every descriptor??

	movw	%si, %ax
	.byte	0x66
	call	R_Set_Addr

	.byte	0x67
	movb	7(%ebx), %al	# Find the byte containing the type field
	testb	$0x10, %al	# See if this descriptor is a segment
	jne	notagate
	testb	$0x04, %al	# See if this destriptor is a gate
	je	notagate
#* Rearrange a gate descriptor. */
	.byte	0x67
	movl	6(%ebx), %eax	# Type (etc.) lifted out
	.byte	0x67
	movl	4(%ebx), %edx	# Selector lifted out.
	.byte	0x67
	movl	%eax, 4(%ebx)	# Type (etc.) put back
	.byte	0x67
	movl	2(%ebx), %eax	# Grab Offset 16..31
	.byte	0x67
	movl	%edx, 2(%ebx)	# Put back Selector
	.byte	0x67
	movl	%eax, 6(%ebx)	# Offset 16..31 now in right place
	jmp	descdone

notagate:			# Rearrange a non gate descriptor.
	.byte	0x67
	movl	4(%ebx), %edx	# Limit 0..15 lifted out
	.byte	0x67
	movb	%al, 5(%ebx)	# type (etc.) put back
	.byte	0x67
	movl	2(%ebx), %eax	# Grab Base 16..31
	.byte	0x67
	movb	%al, 4(%ebx)	# put back Base 16..23
	.byte	0x67
	movb	%ah, 7(%ebx)	# put back Base 24..32
	.byte	0x67
	movl	(%ebx), %eax	# Get Base 0..15
	.byte	0x67
	movl	%eax, 2(%ebx)	# Base 0..15 now in right place
	.byte	0x67
	movl	%edx, (%ebx)	# Limit 0..15 in its proper place

descdone:
	.byte	0x66
	addl	$8, %esi	# Go for the next descriptor
	jmp	moretable

donetable:
	popl	%ds
	.byte	0x66
	ret

#if defined (MB1) || defined (MB2)
#* ********************************************************************* */
#* */
#* mon_init: */
#* This procedure will check a DMON flag in memory to */
#* find the entry point to sq$init_monitor and call it. */
#* */
#* The steps performed are: */
#* 1) Look at the start of the table to see if */
#* the characters "JBT" are there.  If so, */
#* this is DMON and we can call sq$mon_init. */
#* If not, exit, we cannot use the monitor. */
#* */
#* 2) Load gdtr and idtr with the physical addresses */
#* of the descriptor tables.  These addresses are not */
#* the same as the linear addresses we will use, but */
#* must be the physical addresses so that DMON can */
#* find the tables. */
#* ********************************************************************* */
mon_init:
	.byte	0x66
	movl	$JBTLOC, %eax
	.byte	0x66
	call	R_Set_Addr

	.byte	0x67
	movw	(%ebx), %ax
	andw	$0xffff, %ax
	.value	0x00ff

	.byte	0x66
	cmpl    $0x0054424a, %eax
	jne	no_monitor

	pushl   %ds             # Save the address of the DMON flag
	popl    %es
	movw	%bx, %cx

#* Load IDTR and GDTR with the physical addresses of the tables. */
	.byte	0x66
	movl	$RIgdtdscr, %eax
	.byte	0x66
	call	R_Set_Addr

	.byte	0x67
	movw	2(%ebx), %ax
	.byte	0x66
	call	R_Virt_to_Phys
	.byte	0x67
	movw	%ax, 2(%ebx)

	.byte	0x67
	.byte	0x66
	lgdt	(%ebx)

#* *** NOTICE *** NOTICE *** NOTICE *** NOTICE *** NOTICE *** */
#* */
#* Do not try to single step past this point!!!! */
#* use a 'go till' command!!!! */
#* See if the user wants to use DMON on user processes. */
	.byte	0x66
	movl	$Rusermon, %eax
	.byte	0x66
	call	R_Set_Addr

	.byte	0x67
	testb	$0xff, (%ebx)
	jz	normal_mon

	.byte	0x66
	movl	$RIidtdscr, %eax
	.byte	0x66
	movl	$idt, %edi
	jmp	chose_mon

normal_mon:
	.byte	0x66
	movl	$RMidtdscr, %eax
	.byte	0x66
	movl	$monidt, %edi

chose_mon:
	.byte	0x66
	call	R_Set_Addr

	.byte	0x67
	movw	2(%ebx), %ax
	.byte	0x66
	call	R_Virt_to_Phys
	.byte	0x67
	movw	%ax, 2(%ebx)

	.byte	0x67
	.byte	0x66
	lidt	(%ebx)

#* Let the monitor initialize its vectors. */
#* .byte	0x9A */
#* .value	0x341 */
#* .value	0x80 */
	movl	%ecx, %ebx
	.byte	0x26		# Use es
	.byte	0xff
	.byte	0x5f
	.byte	0x18
#* call	%es:24(%cx) */

	.byte	0x66
	movl	$R0idtdscr, %eax
	.byte	0x66
	call	R_Set_Addr

	.byte	0x67
	.byte	0x66
	lidt	(%ebx)

#* Since we do not want DMON to use 0 linear for its data segment, */
#* we must reset the base of gdt[3] to the linear area we have mapped */
#* to 0 physical. */
	.byte	0x66
	movl	$gdt, %eax
	.byte	0x66
	call	R_Set_Addr

	.byte	0x67
	movw	26(%ebx), %ax
	.byte	0x66
	call	R_Virt_to_Phys
	movw	%ax, %cx
	xorw	%ax, %ax
	.byte	0x67
	movb	31(%ebx), %al
	shlw	$24, %ax
	orw	%cx, %ax
	addw	$0x0000, %ax
	.value	0xFFF7
	.byte	0x67
	movl	%eax, 26(%ebx)
	shrw	$16, %ax
	.byte	0x67
	movb	%ah, 31(%ebx)
	.byte	0x67
	movb	%al, 28(%ebx)

#* Now, grab the selector and offset out of interrupt 1 and 3 */
#* We will store them so the interrupt handlers can access them */
#* at will. */
	movw	%di, %ax	# We loaded edi before the first lidt
	.byte	0x66
	call	R_Set_Addr
	pushl	%ds
	popl	%es
	movw	%bx, %di

	.byte	0x66
	movl	$mon1sel, %eax
	.byte	0x66
	call	R_Set_Addr

	.byte	0x67
	movl	%es:10(%edi), %eax
	.byte	0x67
	movl	%eax, (%ebx)

	.byte	0x66
	movl	$mon1off, %eax
	.byte	0x66
	call	R_Set_Addr
	.byte	0x67
	movl	%es:8(%edi), %eax
	.byte	0x67
	movl	%eax, (%ebx)
	.byte	0x67
	movl	%es:14(%edi), %eax
	.byte	0x67
	movl	%eax, 2(%ebx)

	.byte	0x66
	movl	$mon3sel, %eax
	.byte	0x66
	call	R_Set_Addr

	.byte	0x67
	movl	%es:26(%edi), %eax
	.byte	0x67
	movl	%eax, (%ebx)

	.byte	0x66
	movl	$mon3off, %eax
	.byte	0x66
	call	R_Set_Addr
	.byte	0x67
	movl	%es:24(%edi), %eax
	.byte	0x67
	movl	%eax, (%ebx)
	.byte	0x67
	movl	%es:30(%edi), %eax
	.byte	0x67
	movl	%eax, 2(%ebx)

no_monitor:
	.byte	0x66
	ret
#endif

#* ********************************************************************* */
#* */
#* R_Virt_to_Phys: */
#* This procedure takes a 32 bit virtual address and */
#* converts it to a linear physical address by looking */
#* it up in the kernel page table. */
#* */
#* Input: */
#* %eax -- virtual address. */
#* */
#* Output: */
#* %eax -- physical address. */
#* */
#* ********************************************************************* */
R_Virt_to_Phys:
	.byte	0x66
	pushl	%ebx
	.byte	0x66
	movl	%eax, %ebx		# Save virtual address in %ebx
	.byte	0x66
	subl	$KVSBASE, %eax		# If address is below KVSBASE,
	jb	vtop_done		#   assume it's physical

	.byte	0x66
	shrl	$12-2, %eax		# Convert to page table offset
	.byte	0x66
	andl	$0xffc, %eax

	.byte	0x66
	.byte	0x67
	movl	%fs:KPTBL_LOC(%eax), %eax  # Get physical page address
	.byte	0x66
	andl	$0xfffff000, %eax

	.byte	0x66
	andl	$0xfff, %ebx		# Get virtual page offset

	.byte	0x66
	addl	%eax, %ebx		# Compute final virtual address

vtop_done:
	.byte	0x66
	movl	%ebx, %eax
	.byte	0x66
	popl	%ebx
	.byte	0x66
	ret

#* ********************************************************************* */
#* */
#* R_Set_Addr: */
#* This procedure takes a 32 bit address and sets up ds:bx */
#* from it.  In the process, it will cut it down into */
#* the first megabyte. */
#* */
#* Input: */
#* %eax -- 32-bit physical address. */
#* */
#* Output: */
#* %ds:%ebx -- real-mode address. */
#* [ %eax not preserved ] */
#* */
#* ********************************************************************* */
R_Set_Addr:
	.byte	0x66
	call	R_Virt_to_Phys	# Convert to a physical (linear) address.
	movw	%ax, %bx	# Remember the addr for the offset portion.
	shrw	$4, %ax		# Turn the address into a real mode selector.
	movw	%ax, %ds

	.byte	0x66
	andl	$0xF, %ebx	# Now the offset portion

	.byte	0x66
	ret
