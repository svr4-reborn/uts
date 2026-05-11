/*
 * This file contains the random number generator sytem for the SVR4-reborn kernel.
 * 
 * Copyright 2026 Alex Richards, licenced under MIT.
 * For copyright and licence information, see LICENCE.md in the root of this repository.
 */

#include "sys/systm.h"
#include "sys/random.h"

struct random_state {
    unsigned int seed;
};

static struct random_state rng_state;

void random_init() {
    bzero((caddr_t)&rng_state, sizeof(rng_state));
}

void random_add_entropy(enum random_source source, const void *data, size_t size) {
    // For simplicity, we just mix the data into the seed using XOR.
    const unsigned char *bytes = (const unsigned char *)data;
    size_t i;
    for (i = 0; i < size; i++) {
        rng_state.seed ^= bytes[i] + (i * 31) + source;
    }
}

void random_get_bytes(void *buffer, size_t size) {
    unsigned char *bytes = (unsigned char *)buffer;
    size_t i;
    for (i = 0; i < size; i++) {
        // Simple linear congruential generator for demonstration purposes.
        rng_state.seed = (rng_state.seed * 1103515245 + 12345) & 0x7fffffff;
        bytes[i] = (rng_state.seed >> 16) & 0xFF;
    }
}
