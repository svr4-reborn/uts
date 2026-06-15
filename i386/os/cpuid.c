/*
 * SVreborn CPUID definitions for i386
 * Copyright (c) 2025 Alexander Richards, licensed under the MIT license.
 */

#include "sys/cpuid.h"

#define X86_EFLAGS_ID   0x00200000u

int x86_has_cpuid(void) {
    unsigned long before, after;

    __asm__ volatile (
        "pushfl\n\t"
        "popl  %0\n\t"          /* %0 = original EFLAGS */
        "movl  %0, %1\n\t"      /* %1 = saved original EFLAGS */
        "xorl  $0x00200000, %0\n\t"
        "pushl %0\n\t"
        "popfl\n\t"             /* try toggling ID */
        "pushfl\n\t"
        "popl  %0\n\t"          /* %0 = new EFLAGS */
        "pushl %1\n\t"
        "popfl\n\t"             /* restore original EFLAGS */
        : "=&r"(after), "=&r"(before)
        :
        : "cc", "memory"
    );

    return ((before ^ after) & X86_EFLAGS_ID) != 0;
}

void x86_cpuid(unsigned int code, unsigned int subleaf, 
    unsigned int *a, unsigned int *b, unsigned int *c, unsigned int *d) {
    unsigned int eax = code, ebx, ecx = subleaf, edx;

#if defined(__i386__) && defined(__PIC__)
    /* Preserve EBX, which may be the GOT register in 32-bit PIC code. */
    __asm__ volatile (
        "xchgl %%ebx, %1\n\t"
        "cpuid\n\t"
        "xchgl %%ebx, %1\n\t"
        : "+a"(eax), "=&r"(ebx), "+c"(ecx), "=d"(edx)
        :
        : "cc", "memory"
    );
#else
    __asm__ volatile (
        "cpuid"
        : "+a"(eax), "=b"(ebx), "+c"(ecx), "=d"(edx)
        :
        : "cc", "memory"
    );
#endif

    if (a)
        *a = eax;
    if (b)
        *b = ebx;
    if (c)
        *c = ecx;
    if (d)
        *d = edx;
}
