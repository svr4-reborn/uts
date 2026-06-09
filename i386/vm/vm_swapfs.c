/*
 * VM - memory-backed virtual swap ("swapfs").
 *
 * Historically every anonymous page had to be backed 1:1 by a slot on a
 * physical swap device: anon_alloc() pulled a slot off a disk swapinfo's
 * free list, and the page's <vnode,offset> identity pointed at that disk
 * slot.  That made usable anonymous memory roughly equal to the amount of
 * configured disk swap, which is unreasonable for large RAM.
 *
 * This file adds a memory-backed swap source.  It is an ordinary swapinfo
 * (so swap_alloc()/swap_xlate() and all their callers work unchanged), but
 * its vnode is the synthetic "swapfs" vnode below rather than a disk device.
 * An anonymous page bound to this source lives purely in RAM:
 *
 *	- A fresh (never written) page reads as zero; swapfs_getpage()
 *	  produces a zero-filled page on demand, exactly like a zero-fill
 *	  fault, without touching any backing store.
 *	- Because there is no disk slot, such a page currently cannot be
 *	  paged out: swapfs_putpage() keeps it resident.  Reservation
 *	  accounting (anon_resv/anoninfo) bounds the total so the system
 *	  reports out-of-memory rather than deadlocking.
 *
 * The structure deliberately mirrors the disk swap path so that lazily
 * binding a real disk slot at pageout time (the full SunOS swapfs model)
 * can be added later without reworking this: the hook is the "no backing
 * store" branch in swapfs_putpage().
 */

#include "sys/types.h"
#include "sys/param.h"
#include "sys/systm.h"
#include "sys/errno.h"
#include "sys/vnode.h"
#include "sys/vfs.h"
#include "sys/cred.h"
#include "sys/kmem.h"
#include "sys/swap.h"
#include "sys/tuneable.h"
#include "sys/cmn_err.h"
#include "sys/debug.h"
#include "sys/immu.h"
#include "sys/buf.h"
#include "sys/mman.h"
#include "sys/vmmeter.h"
#include "sys/vm.h"

#include "vm/page.h"
#include "vm/pvn.h"
#include "vm/rm.h"
#include "vm/seg.h"
#include "vm/anon.h"

#include "fs/fs_subr.h"

extern struct anoninfo	anoninfo;
extern int		availrmem;
extern int		availsmem;
extern int		physmem;

extern struct swapinfo	*swapinfo;
extern struct swapinfo	*silast;

extern void	pagezero();

/*
 * The single swapfs vnode.  Every memory-backed anon translates (via
 * swap_xlate) to <swapfs_vp, offset>.
 */
struct vnode	swapfs_vnode;
struct vnode	*swapfs_vp = &swapfs_vnode;

STATIC int	swapfs_getpage();
STATIC int	swapfs_putpage();
STATIC void	swapfs_inactive();
STATIC int	swapfs_getattr();

struct vnodeops swapfs_vnodeops = {
	fs_nosys,		/* open */
	fs_nosys,		/* close */
	fs_nosys,		/* read */
	fs_nosys,		/* write */
	fs_nosys,		/* ioctl */
	fs_nosys,		/* setfl */
	swapfs_getattr,		/* getattr */
	fs_nosys,		/* setattr */
	fs_nosys,		/* access */
	fs_nosys,		/* lookup */
	fs_nosys,		/* create */
	fs_nosys,		/* remove */
	fs_nosys,		/* link */
	fs_nosys,		/* rename */
	fs_nosys,		/* mkdir */
	fs_nosys,		/* rmdir */
	fs_nosys,		/* readdir */
	fs_nosys,		/* symlink */
	fs_nosys,		/* readlink */
	fs_nosys,		/* fsync */
	swapfs_inactive,	/* inactive */
	fs_nosys,		/* fid */
	fs_rwlock,		/* rwlock */
	fs_rwunlock,		/* rwunlock */
	fs_nosys,		/* seek */
	fs_cmp,			/* cmp */
	fs_nosys,		/* frlock */
	fs_nosys,		/* space */
	fs_nosys,		/* realvp */
	swapfs_getpage,		/* getpage */
	swapfs_putpage,		/* putpage */
	fs_nosys,		/* map */
	fs_nosys,		/* addmap */
	fs_nosys,		/* delmap */
	fs_nosys,		/* poll */
	fs_nosys,		/* dump */
	fs_nosys,		/* pathconf */
	fs_nosys,		/* allocstore */
	fs_nosys, fs_nosys, fs_nosys, fs_nosys, fs_nosys,
	fs_nosys, fs_nosys, fs_nosys, fs_nosys, fs_nosys,
	fs_nosys, fs_nosys, fs_nosys, fs_nosys, fs_nosys,
	fs_nosys, fs_nosys, fs_nosys, fs_nosys, fs_nosys,
	fs_nosys, fs_nosys, fs_nosys, fs_nosys, fs_nosys,
	fs_nosys, fs_nosys, fs_nosys, fs_nosys, fs_nosys,
	fs_nosys
};

/*
 * Page in (or zero-fill) a memory-backed swap page.  Mirrors the resident
 * path of anon_getpage(): if the page is already in the cache at
 * <swapfs_vp, off> hand it back, otherwise (a never-written page, or one
 * we kept resident) allocate and zero a fresh frame.  We never read from a
 * backing device because there is none.
 */
STATIC int
swapfs_getpage(vp, off, len, protp, pl, plsz, seg, addr, rw, cred)
	struct vnode *vp;
	u_int off;
	u_int len;
	u_int *protp;
	page_t *pl[];
	u_int plsz;
	struct seg *seg;
	addr_t addr;
	enum seg_rw rw;
	struct cred *cred;
{
	register page_t *pp;

	ASSERT(vp == swapfs_vp);

again:
	pp = page_lookup(vp, off);
	if (pp == NULL) {
		pp = rm_allocpage(seg, addr, PAGESIZE, P_CANWAIT);
		if (pp == NULL)
			return (ENOMEM);
		if (page_enter(pp, vp, off)) {
			PAGE_RELE(pp);
			goto again;
		}
		pagezero(pp, 0, PAGESIZE);
		cnt.v_zfod++;
	} else {
		PAGE_HOLD(pp);
	}

	if (protp != NULL)
		*protp = PROT_ALL;
	pl[0] = pp;
	pl[1] = NULL;
	return (0);
}

/*
 * Write out a memory-backed swap page.
 *
 * A memory-backed anon page has no backing store of its own.  When the
 * pager wants to evict one, we bind a real *disk* swap slot to it lazily
 * (the same relocation the swap-device-delete path uses): allocate a disk
 * anon slot, rename the page to the disk slot's <vnode,offset> identity,
 * and set up the an_bap indirection so the anon now resolves to disk.  The
 * page then carries a disk vnode identity, so we hand the actual write off
 * to that vnode's VOP_PUTPAGE and the page becomes reclaimable.
 *
 * If there is no disk swap to migrate to, the page's only copy is this
 * frame, so we keep it resident (clean pages may still be discarded and
 * regenerated as zero-fill).  Reservation accounting bounds the amount of
 * such non-evictable anon so the system reports out-of-memory rather than
 * deadlocking.
 */
/* ARGSUSED */
STATIC int
swapfs_putpage(vp, off, len, flags, cred)
	struct vnode *vp;
	u_int off;
	u_int len;
	int flags;
	struct cred *cred;
{
	register page_t *pp;
	struct anon *ap, *dap;
	struct vnode *dvp;
	u_int doff;
	int i;

	ASSERT(vp == swapfs_vp);

	pp = page_lookup(vp, off);
	if (pp == NULL)
		return (0);

	/*
	 * A clean page can simply be discarded when the pager asks to free or
	 * invalidate it - it regenerates as zero-fill (or, if it was migrated
	 * to disk earlier, it carries the disk identity and we would not be
	 * here).  Otherwise just drop our hold and leave it resident.
	 */
	if (pp->p_mod == 0) {
		if (flags & (B_FREE | B_INVAL)) {
			page_lock(pp);
			page_free(pp, (flags & B_DONTNEED));
		} else {
			PAGE_RELE(pp);
		}
		return (0);
	}

	/*
	 * Dirty page.  Try to bind a disk swap slot and migrate to it.
	 */
	ap = swap_anon(vp, off);
	if (ap == NULL) {
		/*
		 * No anon owns this any more (e.g. last reference gone).
		 * Treat as discardable.
		 */
		page_lock(pp);
		page_free(pp, (flags & B_DONTNEED));
		return (0);
	}

	ALOCK(ap);

	dap = swap_alloc_disk();
	if (dap == NULL) {
		/*
		 * No disk swap available: keep the page resident, since this
		 * frame is its only copy.
		 */
		AUNLOCK(ap);
		PAGE_RELE(pp);
		return (0);
	}

	swap_xlate(dap, &dvp, &doff);

	page_lock(pp);

	/* Give the page the disk slot's identity (cf. delswap relocation). */
	page_hashout(pp);
	while (page_enter(pp, dvp, doff)) {
		page_t *npp = page_find(dvp, doff);
		if (npp != NULL)
			page_abort(npp);
	}
	for (i = 0; i < PAGESIZE / NBPSCTR; i++)
		pp->p_dblist[i] = -1;

	/* anon now resolves to the disk slot via the indirection. */
	ap->an_bap = dap;
	dap->an_bap = ap;

	pp->p_mod = 1;
	page_unlock(pp);
	AUNLOCK(ap);

	/*
	 * The page now belongs to the disk swap vnode; let that vnode write
	 * it out and free/invalidate it per the requested flags.
	 */
	return (VOP_PUTPAGE(dvp, doff, PAGESIZE, flags, cred));
}

/* ARGSUSED */
STATIC void
swapfs_inactive(vp, cred)
	struct vnode *vp;
	struct cred *cred;
{
	/* The swapfs vnode is a permanent singleton; never goes inactive. */
}

/* ARGSUSED */
STATIC int
swapfs_getattr(vp, vap, flags, cred)
	struct vnode *vp;
	struct vattr *vap;
	int flags;
	struct cred *cred;
{
	bzero((caddr_t)vap, sizeof (*vap));
	vap->va_type = VREG;
	vap->va_size = (u_long)ctob(swapfs_npages());
	return (0);
}

/*
 * How many pages of memory-backed swap to provide.  Sized from physical
 * memory: anonymous memory may be reserved up to (this + any disk swap),
 * decoupling anon from a 1:1 disk-swap requirement.  A reserve is left so
 * the kernel itself always has resident memory to work with.
 */
int
swapfs_npages()
{
	int n;

	/*
	 * Use the bulk of physical memory.  availrmem at init time reflects
	 * user-allocatable RAM; keep a small reserve below it.
	 */
	n = physmem - (physmem / 16);
	if (n < 0)
		n = 0;
	return (n);
}

/*
 * Create the memory-backed swap source.  Called once at boot, before any
 * disk swap is configured, so that anonymous memory works even with no
 * swap device.  Builds a swapinfo whose vnode is swapfs_vp and whose anon
 * array provides the synthetic slots that swap_xlate() hands out.
 */
void
swapfs_init()
{
	register struct swapinfo *nsip;
	register struct anon *ap, *ap2;
	register uint pages;

	pages = (uint)swapfs_npages();
	if (pages == 0)
		return;

	swapfs_vp->v_op = &swapfs_vnodeops;
	swapfs_vp->v_type = VREG;
	swapfs_vp->v_flag = VISSWAP;
	swapfs_vp->v_count = 1;

	nsip = (struct swapinfo *)kmem_zalloc(sizeof (struct swapinfo), KM_SLEEP);
	nsip->si_vp = swapfs_vp;
	nsip->si_svp = swapfs_vp;
	nsip->si_soff = 0;
	nsip->si_eoff = ctob(pages);
	nsip->si_flags = ST_MEMORY;
	nsip->si_pname = "swapfs";

	nsip->si_anon = (struct anon *)
		kmem_zalloc(pages * sizeof (struct anon), KM_SLEEP);
	nsip->si_eanon = nsip->si_anon + (pages - 1);

	/* Thread the free list, head at the front of the array. */
	ap = nsip->si_eanon;
	ap2 = nsip->si_anon;
	while (--ap >= ap2)
		ap->un.an_next = ap + 1;
	nsip->si_free = ap + 1;
	nsip->si_npgs = pages;
	nsip->si_nfpgs = pages;

	/*
	 * Link as the first swap source.  Any disk swap added later via
	 * swapadd() appends after it and adds to the same anoninfo pool.
	 */
	nsip->si_next = swapinfo;
	swapinfo = nsip;
	if (silast == NULL)
		silast = nsip;

	/*
	 * Raise the anon reservation ceiling by the memory-backed capacity.
	 * We deliberately do NOT add to availsmem: availsmem already accounts
	 * for this physical RAM (it was set to all free RAM at boot), and it
	 * is the shared pool the kernel allocators draw from.  Adding here
	 * would double-count the RAM.  Previously ani_max only grew with disk
	 * swap, which is what forced the ~1:1 RAM:swap requirement; raising it
	 * from RAM is exactly what decouples anon from disk swap.  anon_resv()
	 * still decrements availsmem and honours t_minasmem, so total anon
	 * remains bounded by real memory.
	 */
	anoninfo.ani_max += pages;
	anoninfo.ani_free += pages;
}
