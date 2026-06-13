/* SVr4-reborn: C stubs */
/* Licensed under the MIT License, Copyright (c) 2025 Alexander Richards */

/*
 * This file contains implementations of C library functions that the compiler is permitted to implicitly build function calls for.
 * Mostly, these are added as they are needed, and are generally functions such as memcpy, memset, memmove, etc. that the compiler may generate calls to when optimizing code.
 * These functions are implemented in C because I am too lazy to implement these in assembly. Additionally, not sure how to do this in a fast way that works with different ix86 targets.
 */

void* memcpy(void* dest, const void* src, unsigned long n) {
    char* d = (char*)dest;
    const char* s = (const char*)src;
    unsigned long i;
    for (i = 0; i < n; i++) {
        d[i] = s[i];
    }
    return dest;
}
