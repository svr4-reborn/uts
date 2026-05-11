#ifndef _SYS_RANDOM_H
#define _SYS_RANDOM_H

enum random_source {
    RANDSRC_BOOT = 1,
    RANDSRC_CLOCK,
};

void random_init();

void random_add_entropy(enum random_source source, const void *data, size_t size);
void random_get_bytes(void *buffer, size_t size);

#endif /* _SYS_RANDOM_H */