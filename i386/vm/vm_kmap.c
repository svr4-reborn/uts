/*
 * Temporary physical-page mapping layer.  See vm/kmap.h for the rationale.
 *
 * The kernel keeps no permanent identity map of physical memory; code that
 * needs the contents of a physical frame maps it here on demand.  This is a
 * uniprocessor kernel, so the window is a single shared bank of slots backed
 * by one kernel page table.  Mappings are short-lived and must not be held
 * across a context switch; callers raise spl for the duration.
 */

#include "sys/types.h"
#include "sys/param.h"
#include "sys/systm.h"
#include "sys/immu.h"
#include "sys/inline.h"
#include "sys/cmn_err.h"
#include "sys/debug.h"
#include "vm/page.h"
#include "vm/kmap.h"

/*
 * Only a handful of mappings are ever live at once (page zero/copy, page
 * table zeroing, fault-time frame access), so we keep the live-slot count
 * small to make the free-slot/occupant scans trivial.  The remainder of the
 * page table is left unused.
 */
#define	NKMAP_LIVE	16		/* normal slots actually used	*/

#define	KMAP_FREE	((u_int)-1)	/* "slot is free" occupant value */

extern pte_t	*kmapptbl;		/* page table for the kmap window */

STATIC u_int	kmap_occupant[NKMAP_LIVE];	/* pfn mapped in each slot */
STATIC int	kmap_inited = 0;
STATIC int	atomic_next = 0;

extern int	splhi(/* void */);
extern void	splx(/* int */);

STATIC void
kmap_firstuse()
{
	int i;

	for (i = 0; i < NKMAP_LIVE; i++)
		kmap_occupant[i] = KMAP_FREE;
	kmap_inited = 1;
}

/* Slot index <-> kernel virtual address. */
#define	KMAP_KVA(idx)	((caddr_t)(KMAPSEGS + (u_int)(idx) * NBPP))
#define	KMAP_IDX(kva)	(((u_int)(kva) - KMAPSEGS) >> PNUMSHFT)

/*
 * Write the PTE for kmap slot `idx' to map frame `pfn' (or invalidate it if
 * pfn == KMAP_FREE) and flush the corresponding virtual address from the TLB.
 */
STATIC caddr_t
kmap_setslot(idx, pfn)
	int idx;
	u_int pfn;
{
	caddr_t kva = KMAP_KVA(idx);

	if (pfn == KMAP_FREE)
		kmapptbl[idx].pg_pte = 0;
	else
		kmapptbl[idx].pg_pte = mkpte(PG_V | PG_RW, pfn);
	invlpg((unsigned long)kva);
	return (kva);
}

/*
 * Raw frame-number mapping.  Usable before the page-frame database exists.
 */
caddr_t
kmap_pfn(pfn)
	u_int pfn;
{
	int s, i;

	s = splhi();
	if (!kmap_inited)
		kmap_firstuse();
	for (i = 0; i < NKMAP_LIVE; i++) {
		if (kmap_occupant[i] == KMAP_FREE) {
			kmap_occupant[i] = pfn;
			splx(s);
			return (kmap_setslot(i, pfn));
		}
	}
	splx(s);
	cmn_err(CE_PANIC, "kmap_pfn: out of mapping slots");
	/* NOTREACHED */
	return (NULL);
}

void
kunmap_pfn(kva)
	caddr_t kva;
{
	u_int idx = KMAP_IDX(kva);
	int s;

	ASSERT(idx < NKMAP_LIVE);
	s = splhi();
	kmap_occupant[idx] = KMAP_FREE;
	(void) kmap_setslot((int)idx, KMAP_FREE);
	splx(s);
}

/*
 * Map the physical frame backing `pp' into the kmap window and return its
 * kernel virtual address.  Must be paired with kunmap(pp).
 */
caddr_t
kmap(pp)
	page_t *pp;
{
	ASSERT(pp != NULL);
	return (kmap_pfn(page_pptonum(pp)));
}

/*
 * Release the mapping previously established for `pp' by kmap().
 */
void
kunmap(pp)
	page_t *pp;
{
	u_int pfn;
	int s, i;

	ASSERT(pp != NULL);
	pfn = page_pptonum(pp);
	s = splhi();
	for (i = 0; i < NKMAP_LIVE; i++) {
		if (kmap_occupant[i] == pfn) {
			kmap_occupant[i] = KMAP_FREE;
			(void) kmap_setslot(i, KMAP_FREE);
			splx(s);
			return;
		}
	}
	splx(s);
	cmn_err(CE_PANIC, "kunmap: page not mapped");
}

/*
 * Interrupt-safe mapping.  Uses a separate set of slots at the top of the
 * window so it can never collide with an in-progress kmap().
 */
caddr_t
kmap_atomic(pp, slot)
	page_t *pp;
	struct kmap_slot *slot;
{
	int s, idx;
	u_int pfn;

	ASSERT(pp != NULL);
	pfn = page_pptonum(pp);

	s = splhi();
	idx = NKMAP_NORMAL + atomic_next;
	atomic_next = (atomic_next + 1) % NKMAP_ATOMIC;
	splx(s);

	slot->slot_idx = idx;
	slot->kva = kmap_setslot(idx, pfn);
	return (slot->kva);
}

void
kunmap_atomic(slot)
	struct kmap_slot *slot;
{
	if (slot->slot_idx < 0)
		return;
	(void) kmap_setslot(slot->slot_idx, KMAP_FREE);
	slot->slot_idx = -1;
}
