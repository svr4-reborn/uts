/*	Copyright (c) 1990 UNIX System Laboratories, Inc.	*/
/*	Copyright (c) 1984, 1986, 1987, 1988, 1989, 1990 AT&T	*/
/*	  All Rights Reserved  	*/

/*	THIS IS UNPUBLISHED PROPRIETARY SOURCE CODE OF     	*/
/*	UNIX System Laboratories, Inc.                     	*/
/*	The copyright notice above does not evidence any   	*/
/*	actual or intended publication of such source code.	*/

#ifndef _SYS_FP_H
#define _SYS_FP_H

#ident	"@(#)head.sys:sys/fp.h	1.1.2.1"

/*
 * 80287/80387 floating point processor definitions
 */

/*
 * values that go into fp_kind
 * These are chosen so that FP_HW can be used as a mask to determine if any
 * floating point hardware is present.
 * TODO: can we simplify this?
 */
#define FP_NO   0       /* no fp chip                                   */
#define FP_HW   2       /* chip present bit                             */
#define FP_287  2       /* 80287 chip present                           */
#define FP_387  3       /* 80387 chip present                           */
#define FP_FXSAVE 6     /* fxsave/fxrstor support                        */

/*
 * masks for 80387 control word
 */
#define FPINV   0x00000001      /* invalid operation                    */
#define FPDNO   0x00000002      /* denormalized operand                 */
#define FPZDIV  0x00000004      /* zero divide                          */
#define FPOVR   0x00000008      /* overflow                             */
#define FPUNR   0x00000010      /* underflow                            */
#define FPPRE   0x00000020      /* precision                            */
#define FPPC    0x00000300      /* precision control                    */
#define FPRC    0x00000C00      /* rounding control                     */
#define FPIC    0x00001000      /* infinity control                     */
#define WFPDE   0x00000080      /* data chain exception                 */

/*
 * precision, rounding, and infinity options in control word
 */
#define FPSIG24 0x00000000      /* 24-bit significand precision (short) */
#define FPSIG53 0x00000200      /* 53-bit significand precision (long)  */
#define FPSIG64 0x00000300      /* 64-bit significand precision (temp)  */
#define FPRTN   0x00000000      /* round to nearest or even             */
#define FPRD    0x00000400      /* round down                           */
#define FPRU    0x00000800      /* round up                             */
#define FPCHOP  0x00000C00      /* chop (truncate toward zero)          */
#define FPP     0x00000000      /* projective infinity                  */
#define FPA     0x00001000      /* affine infinity                      */
#define WFPB17  0x00020000      /* bit 17                               */
#define WFPB24  0x01000000      /* bit 24                               */

/*
 * masks for 80387 status word
 */
#define FPS_ES	0x00000080      /* error summary bit                    */

extern char fp_kind;            /* kind of fp support                   */
extern struct proc *fp_proc;    /* process that owns the fp unit        */

extern void fpnoextflt(int *);
extern void fpextovrflt(int *);
extern void fpexterrflt(void);
#ifdef AT386
extern void fpintr(void);
#endif
/* More advanced setup of the floating point unit, mostly for MMX/SSE */
extern void fpsetup(void);
/* Init/reset the floating point unit */
extern void fpinit(void);
/* Save and restore the state of the floating point unit for a process. */
extern void fpsave(void);
extern void fprestore(int);
extern void fpksave(void);
extern void fpkreset(void);
extern void setts(void);

/* Old x87 save/restore functions */
extern void fnsave(int *);
extern void frstor(int *);

/* Slightly-newer MMX/early SSE fxsave stuff */
extern void fxsave(void *);
extern void fxrstor(void *);

#endif	/* _SYS_FP_H */
