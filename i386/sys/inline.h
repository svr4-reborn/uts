/*	Copyright (c) 1990 UNIX System Laboratories, Inc.	*/
/*	Copyright (c) 1984, 1986, 1987, 1988, 1989, 1990 AT&T	*/
/*	  All Rights Reserved  	*/

/*	THIS IS UNPUBLISHED PROPRIETARY SOURCE CODE OF     	*/
/*	UNIX System Laboratories, Inc.                     	*/
/*	The copyright notice above does not evidence any   	*/
/*	actual or intended publication of such source code.	*/

#ifndef _SYS_INLINE_H
#define _SYS_INLINE_H

#ident	"@(#)head.sys:sys/inline.h	11.9.5.1"

static __inline__ void
flushtlb(void)
{
	__asm__ __volatile__(
		"movl %%cr3, %%eax\n\t"
		"movl %%eax, %%cr3"
		:
		:
		: "eax", "memory");
}

static __inline__ unsigned long
_cr0(void)
{
	unsigned long value;

	__asm__ __volatile__("movl %%cr0, %0" : "=r"(value));
	return value;
}

static __inline__ unsigned long
_cr2(void)
{
	unsigned long value;

	__asm__ __volatile__("movl %%cr2, %0" : "=r"(value));
	return value;
}

static __inline__ unsigned long
_cr3(void)
{
	unsigned long value;

	__asm__ __volatile__("movl %%cr3, %0" : "=r"(value));
	return value & 0x7fffffffUL;
}

static __inline__ void
invlpg(unsigned long vaddr)
{
	__asm__ __volatile__("invlpg (%0)" : : "r"(vaddr) : "memory");
}

static __inline__ void
_wdr0(unsigned long value)
{
	__asm__ __volatile__("movl %0, %%db0" : : "r"(value));
}

static __inline__ void
_wdr1(unsigned long value)
{
	__asm__ __volatile__("movl %0, %%db1" : : "r"(value));
}

static __inline__ void
_wdr2(unsigned long value)
{
	__asm__ __volatile__("movl %0, %%db2" : : "r"(value));
}

static __inline__ void
_wdr3(unsigned long value)
{
	__asm__ __volatile__("movl %0, %%db3" : : "r"(value));
}

static __inline__ void
_wdr6(unsigned long value)
{
	__asm__ __volatile__("movl %0, %%db6" : : "r"(value));
}

static __inline__ void
_wdr7(unsigned long value)
{
	__asm__ __volatile__("movl %0, %%db7" : : "r"(value));
}

static __inline__ unsigned long
_dr0(void)
{
	unsigned long value;

	__asm__ __volatile__("movl %%dr0, %0" : "=r"(value));
	return value;
}

static __inline__ unsigned long
_dr1(void)
{
	unsigned long value;

	__asm__ __volatile__("movl %%dr1, %0" : "=r"(value));
	return value;
}

static __inline__ unsigned long
_dr2(void)
{
	unsigned long value;

	__asm__ __volatile__("movl %%dr2, %0" : "=r"(value));
	return value;
}

static __inline__ unsigned long
_dr3(void)
{
	unsigned long value;

	__asm__ __volatile__("movl %%dr3, %0" : "=r"(value));
	return value;
}

static __inline__ unsigned long
_dr6(void)
{
	unsigned long value;

	__asm__ __volatile__("movl %%dr6, %0" : "=r"(value));
	return value;
}

static __inline__ unsigned long
_dr7(void)
{
	unsigned long value;

	__asm__ __volatile__("movl %%dr7, %0" : "=r"(value));
	return value;
}

static __inline__ void
loadtr(unsigned short selector)
{
	__asm__ __volatile__("ltr %w0" : : "r"(selector) : "memory");
}

static __inline__ void
outl(unsigned short port, unsigned long value)
{
	__asm__ __volatile__("outl %0, %w1" : : "a"(value), "Nd"(port) : "memory");
}

static __inline__ void
outw(unsigned short port, unsigned short value)
{
	__asm__ __volatile__("outw %0, %w1" : : "a"(value), "Nd"(port) : "memory");
}

static __inline__ void
outb(unsigned short port, unsigned char value)
{
	__asm__ __volatile__("outb %0, %w1" : : "a"(value), "Nd"(port) : "memory");
}

static __inline__ unsigned long
inl(unsigned short port)
{
	unsigned long value;

	__asm__ __volatile__("inl %w1, %0" : "=a"(value) : "Nd"(port) : "memory");
	return value;
}

static __inline__ unsigned short
inw(unsigned short port)
{
	unsigned short value;

	__asm__ __volatile__("inw %w1, %0" : "=a"(value) : "Nd"(port) : "memory");
	return value;
}

static __inline__ unsigned char
inb(unsigned short port)
{
	unsigned char value;

	__asm__ __volatile__("inb %w1, %0" : "=a"(value) : "Nd"(port) : "memory");
	return value;
}

static __inline__ void
intr_disable(void)
{
	__asm__ __volatile__("pushfl\n\tcli" : : : "memory");
}

static __inline__ void
intr_restore(void)
{
	__asm__ __volatile__("popfl" : : : "memory", "cc");
}

static __inline__ void
intr_enable(void)
{
	__asm__ __volatile__("popfl\n\tsti" : : : "memory", "cc");
}

static __inline__ int
struct_zero(void *addr, unsigned int len)
{
	unsigned char *cursor;
	unsigned int remaining;

	cursor = (unsigned char *)addr;
	for (remaining = 0; remaining < len; ++remaining)
		cursor[remaining] = 0;

	return 0;
}

/*
 *	Very fast byte-at-a-time copy, as opposed to bcopy, which is
 *	longword-at-a-time. For controler boards which can't handle 32 bit accesses.
 */
static __inline__ void
copy_bytes(const void *from, void *to, unsigned int count)
{
	const unsigned char *source;
	unsigned char *destination;
	unsigned int index;

	source = (const unsigned char *)from;
	destination = (unsigned char *)to;
	for (index = 0; index < count; ++index)
		destination[index] = source[index];
}

#ifdef	KPERF	/* This is for kernel performance tool */
static __inline__ int
get_spl(void)
{
	int value;

	__asm__ __volatile__("movl ipl, %0" : "=r"(value));
	return value;
}
#endif	/* KPERF */

#endif	/* _SYS_INLINE_H */
