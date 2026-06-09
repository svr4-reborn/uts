#ifndef _VM_KMAP_H
#define _VM_KMAP_H

#include "vm/page.h"

/*
 * Temporary physical-page mapping layer.
 *
 * The kernel no longer keeps a permanent identity map of all physical
 * memory.  To touch the contents of an arbitrary physical frame, the
 * caller maps it through a small bank of reserved kernel virtual
 * addresses (the "kmap window"), uses the returned virtual address, and
 * then unmaps it.  This is the i386 analogue of the BSD pmap_zero_page /
 * pmap_copy_page (sf_buf) temporary mappings.
 *
 * This kernel is uniprocessor, so the window is a single shared bank of
 * slots protected by raising the interrupt priority level (the caller is
 * expected not to sleep while holding a mapping).  kmap()/kunmap() are
 * the normal (process-context) interface; kmap_atomic()/kunmap_atomic()
 * use a separate reserved slot and may be used from interrupt context.
 *
 * The kmap window lives in the otherwise-unused virtual range that used
 * to be reserved for the Olivetti "extended memory" alias (KVXBASE).
 */

#define	KMAPSEGS	0xC8000000U	/* base of the kmap window	*/
#define	NKMAP_SLOTS	1024		/* one page table's worth (4 MB) */
#define	NKMAP_ATOMIC	4		/* slots reserved for kmap_atomic */
#define	NKMAP_NORMAL	(NKMAP_SLOTS - NKMAP_ATOMIC)

/* Opaque handle returned to atomic callers so kunmap_atomic can find the slot. */
struct kmap_slot {
	caddr_t	kva;
	int	slot_idx;	/* -1 means "no slot was used" */
};

extern void	kmap_init(/* void */);	/* boot-time window initialization */

/*
 * Raw (page-frame-number) mapping.  Unlike kmap(), this does not require a
 * page_t and so may be used during early boot before the page-frame database
 * exists, or to reach frames that have no page struct.  Returns the kernel
 * virtual address for the frame; pair with kunmap_pfn() on the same address.
 */
extern caddr_t	kmap_pfn(/* u_int pfn */);
extern void	kunmap_pfn(/* caddr_t kva */);

extern caddr_t	kmap(/* page_t *pp */);
extern void	kunmap(/* page_t *pp */);

extern caddr_t	kmap_atomic(/* page_t *pp, struct kmap_slot *slot */);
extern void	kunmap_atomic(/* struct kmap_slot *slot */);

#endif /* _VM_KMAP_H */
