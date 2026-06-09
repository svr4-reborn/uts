/*	Copyright (c) 1990 UNIX System Laboratories, Inc.	*/
/*	Copyright (c) 1984, 1986, 1987, 1988, 1989, 1990 AT&T	*/
/*	  All Rights Reserved  	*/

/*	THIS IS UNPUBLISHED PROPRIETARY SOURCE CODE OF     	*/
/*	UNIX System Laboratories, Inc.                     	*/
/*	The copyright notice above does not evidence any   	*/
/*	actual or intended publication of such source code.	*/

/*	Copyright (c) 1987, 1988 Microsoft Corporation	*/
/*	  All Rights Reserved	*/

/*	This Module contains Proprietary Information of Microsoft  */
/*	Corporation and should be treated as Confidential.	   */

#ident	"@(#)boot:boot/at386/memsize.c	1.1.4.1"

#include "../sys/boot.h"
#include "sys/param.h"

/* SGN(a) returns the sign of the number a: 1 if positive, -1 if negative */

#define	SGN(a)			((a) < 0 ? -1 : ((a) > 0 ? 1 : 0))

/*
 * memsize(): 	here we size memory, using the MEMRANGE information we have 
 *		garnered from the defaults file ("/etc/default/boot").
 *		The original memrng entries can have negative extents, 
 *		in which case we size downwards. However, the resulting
 *		memsize extents are strictly positive.
 *
 *		We find only the first memory extent in the supplied memrange.
 */

/*
 * The E820 entry layout as filled by e820.s: 64-bit base, 64-bit length,
 * 32-bit type.  We are a 32-bit (sub-4GB) kernel, so we only consume the
 * low halves and clip anything reaching at/above 4GB.
 */
struct e820ent {
	unsigned long	base_lo;
	unsigned long	base_hi;
	unsigned long	len_lo;
	unsigned long	len_hi;
	unsigned long	type;
};

extern struct e820ent	e820_buf[];
extern int		e820_probe();

#define	E820_RAM	1		/* usable memory */
#define	ADDR_MAX	0xFFFFF000UL	/* highest page-aligned 32-bit addr */
#define	DMA16_LIMIT	0x01000000UL	/* 16MB ISA DMA boundary */

static void bmemsize_probe();

/*
 * Carve the bootstrap region out of a single memavail[] entry, splitting it
 * in two if the bootstrap lies in the middle.  Returns the (possibly
 * advanced) memavail index.
 */
static int
carve_bootstrap(j, bootstrap)
	int		j;
	paddr_t		bootstrap;
{
	paddr_t	abase = binfo.memavail[j].base;
	paddr_t	aend  = abase + binfo.memavail[j].extent;

	if (bootstrap < abase || bootstrap >= aend)
		return (j);		/* bootstrap not in this region */

	binfo.memavail[j].extent = bootstrap - abase;
	binfo.memavail[j].flags |= B_MEM_BOOTSTRAP;
	if (aend > bootstrap + BOOTSIZE) {
		binfo.memavail[++j].base = bootstrap + BOOTSIZE;
		binfo.memavail[j].extent = aend - (bootstrap + BOOTSIZE);
		binfo.memavail[j].flags = 0;
	}
	return (j);
}

/*
 * Build binfo.memavail[] from the BIOS INT 15h E820 memory map.  Returns the
 * number of available regions found, or -1 if E820 is unavailable.
 */
static int
bmemsize_e820()
{
	int		n, i, j;
	int		memtotal;
	paddr_t		bootstrap = physaddr(0);
	unsigned long	base, len, end;

	n = e820_probe();
	if (n <= 0)
		return (-1);

	memtotal = 0;
	for (i = 0, j = 0; i < n && j < B_MAXARGS; i++) {

		if (e820_buf[i].type != E820_RAM)
			continue;
		/* Skip regions that start at or above 4GB. */
		if (e820_buf[i].base_hi != 0)
			continue;

		base = e820_buf[i].base_lo;
		len  = e820_buf[i].len_lo;

		/* Clip a region that extends past the 32-bit limit. */
		if (e820_buf[i].len_hi != 0 || base + len < base ||
		    base + len > ADDR_MAX)
			end = ADDR_MAX;
		else
			end = base + len;

		/* Page-align inward (round base up, end down). */
		base = (base + NBPC - 1) & ~(NBPC - 1);
		end  = end & ~(NBPC - 1);
		if (end <= base)
			continue;

		/*
		 * Split the region at the 16MB ISA-DMA boundary and flag the
		 * part above it B_MEM_NODMA.  This lets the kernel prefer high
		 * (non-DMA) memory for the page-frame database and other large
		 * allocations (see non_dma_page()), keeping the scarce <16MB
		 * DMA-able pages free.  Without this, at large RAM the page-DB
		 * consumes all sub-16MB memory and the DMA bounce-buffer setup
		 * (dma_page_init) finds no DMA-able region and panics.
		 */
		if (base < DMA16_LIMIT && end > DMA16_LIMIT) {
			binfo.memavail[j].base = base;
			binfo.memavail[j].extent = DMA16_LIMIT - base;
			binfo.memavail[j].flags = 0;
			memtotal += binfo.memavail[j].extent;
			j = carve_bootstrap(j, bootstrap);
			j++;
			if (j >= B_MAXARGS)
				break;
			base = DMA16_LIMIT;
		}

		binfo.memavail[j].base = base;
		binfo.memavail[j].extent = end - base;
		binfo.memavail[j].flags = (base >= DMA16_LIMIT) ? B_MEM_NODMA : 0;
		memtotal += binfo.memavail[j].extent;

		j = carve_bootstrap(j, bootstrap);
		j++;
	}

	binfo.memavailcnt = j;

	if (memreq > 0 && memreq > memtotal) {
		printf("\n\n%s\n", mreqmsg1);
		printf("%s\n\n", mreqmsg2);
		halt();
	}
	return (j);
}

bmemsize()
{
	/* Prefer the BIOS E820 map; fall back to the legacy probe. */
	if (bmemsize_e820() >= 0)
		return;
	bmemsize_probe();
}

static void
bmemsize_probe()
{
	int		i, j;
	int		bootFound;
	struct bootmem 	*r;
	paddr_t		bootstrap, p, start;
	int		memtotal;

	memtotal=0;
	bootstrap = physaddr(0);

	for ( i = 0, j = 0; i < memrngcnt; i++ ) {

		r = &memrng[i];

		/* 
		 * if we are sizing downwards, we must start one click down 
		 * from the base (since the base is therefore the high address,
		 * and thus not included in the range)
		 */

		p = start = (r->extent > 0) ? (r->base) : (r->base - NBPC);

		debug(printf("Looking for memory in the range: %lx to %lx\n",
			r->base, r->base + r->extent)); 

		/* touch memory while in the interval */

		bootFound = FALSE;
		for ( ;INTERVAL(r->base, r->extent, p); 
				p += SGN( r->extent )*NBPC ) {

			/* 
			 * Don't try to touch memory where the bootstrap lives
		 	 */

			if ( INTERVAL( bootstrap, BOOTSIZE, p ) ) {
				bootFound = TRUE;
				continue;
			}

			/* if no response, done */

			if ( !touchpage(p) ) {
				break;
			}
		}

		/* nothing found */

		if ( p == start )
			continue;

		/* found memory; set up binfo.memavail */

		if ( r->extent < 0 ) {	/* sizing down */
			binfo.memavail[j].extent = ((long)r->base - p) - NBPC;
			binfo.memavail[j].base = p + NBPC;
		} else {		/* sizing up */
			binfo.memavail[j].extent = (p - (long)r->base);
			binfo.memavail[j].base = r->base;
		}
		memtotal += binfo.memavail[j].extent;

		binfo.memavail[j].flags = r->flags;

		/* 
		 * If the area occupied by the bootstrap is in the free
		 * area just found, temporarily remove the bootstrap space
		 * from memavail; this prevents programs from being loaded
		 * over the bootstrap.
		 */

		if ( bootFound ) {
			p = binfo.memavail[j].base + binfo.memavail[j].extent;
			binfo.memavail[j].extent = bootstrap -
						binfo.memavail[j].base;
			binfo.memavail[j].flags |= B_MEM_BOOTSTRAP;
			if (p > bootstrap + BOOTSIZE) {
				binfo.memavail[++j].base = bootstrap + BOOTSIZE;
				binfo.memavail[j].extent = p -
						binfo.memavail[j].base;
				binfo.memavail[j].flags = r->flags;
			}
		}

		j++;
	}
	binfo.memavailcnt = j;

	if (memreq > 0 && memreq > memtotal) {
		printf("\n\n%s\n", mreqmsg1);
		printf("%s\n\n", mreqmsg2);
		halt();		
	}
}
