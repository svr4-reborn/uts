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

#ident "@(#)kern-os:fp.c	1.3.1.2"

/*
 * Dual-Mode Floating Point support:
 * Copyright (c) 1989 Phoenix Technologies Ltd.
 * All Rights Reserved
 */

/*
** routines that deal with floating point
*/

#include "sys/param.h"
#include "sys/types.h"
#include "sys/sysmacros.h"
#include "sys/systm.h"
#include "sys/dir.h"
#include "sys/signal.h"
#include "sys/cred.h"
#include "sys/user.h"
#include "sys/errno.h"
#include "sys/trap.h"
#include "sys/seg.h"
#include "sys/sysinfo.h"
#include "sys/immu.h"
#include "sys/proc.h"
#include "sys/fp.h"
#include "sys/cmn_err.h"
#include "sys/reg.h"
#include "sys/tss.h"
#include "sys/debug.h"
#ifdef VPIX
#include "sys/v86.h"
#endif
#ifdef WEITEK
#include "sys/weitek.h"
#endif
#include "sys/cpuid.h"
#include "sys/kmem.h"

#include "vm/faultcatch.h"

char fp_kind;         /* kind of floating point hardware              */
struct proc *fp_proc; /* owner of floating point extension            */
int finitstate;       /* control word temporary during initialization */
int mxcsrinit = 0x1f80; /* default SSE control/status word             */
int fpsw;             /* status word temporary                        */

#ifdef VPIX
extern char v86procflag;
#endif

/* This is a workaround for the 80386 B1 stepping bug errata #21
 * which needs either a special PAL on the motherboard or
 * 0x80000000 set in cr3 to prevent a hang in the kernel
 * while trying to save the 387 state.
 * It is conditionally initialized during machine initialization.
 */

paddr_t fp387cr3 = 0;

/*
** fpnoextflt
**      handle a processor extension not present fault
**
**      This fault occurs when there is a floating point processor
**      extension, and a floating point instruction is encountered when
**      the task-switched (TS) bit is set.  We save and restore floating
**      point states.
**
**  r0ptr: pointer to registers on stack
*/
void fpnoextflt(int *r0ptr) {
  long vmflag; /* returning to v86 mode? */
#ifdef VPIX
  v86_t *v86p;
#endif

  asm(" clts"); /* clear TS bit in CR0  */

  vmflag = r0ptr[EFL] & PS_VM;

  /* check for no floating point support */
  if (fp_kind == FP_NO) {
    /*
     * If we do not have a processor extension, kill the process
     * or panic if the kernel took the trap.
     */
#ifdef VPIX
    if (vmflag) {
      v86setint(u.u_procp->p_v86, V86VI_COPROC);
      return;
    } else if (USERMODE(r0ptr[CS])) {
#else
    if (vmflag || USERMODE(r0ptr[CS])) {
#endif
      psignal(u.u_procp, SIGFPE);
      return;
    } else
      cmn_err(CE_PANIC, "NOEXTFLT in kernel mode, no FP support");
  }

#ifdef VPIX
  v86p = (v86_t *)u.u_procp->p_v86;
#endif

  /*
   * If the current process does not own the processor extension,
   * save the fp state in the owner's user structure,
   * and restore or establish the current process's fp state.
   * 
   * TODO: if we ever support multiple processors, this will need to be reworked
   */
  if (fp_proc != u.u_procp) {
    /* Check if there is a process that actually owns the floating point
     * unit. If so, save its state.
     */
    if (fp_proc)
      fpsave();
    
    /* Set the current process as the owner of the floating point unit */
    fp_proc = u.u_procp;

    /* TODO: do we need to re-init the floating point unit for the new owner? 
     * fnsave does reset the unix, fxsave and xsave do not.
     */

    /*
     * If the current process' state is valid, restore
     * it. Otherwise, this is the first time this
     * process has executed a fp instruction,
     * so initialize the fp unit for it.
     */
#ifdef VPIX
    if ((u.u_fpvalid && !vmflag) || (v86p && v86p->vp_fpvalid && vmflag))
#else
    if (u.u_fpvalid)
#endif
      fprestore(vmflag);
    else
      fpinit();
#ifdef VPIX
  } else
    /*
     * The current process owns the floating point unit.  If
     * it is a dual-mode process, determine if we are switching
     * between components of the process.
     */
    if (v86procflag) {
      /* v86 -> v86 = no work */
      if ((v86p->vp_fpproc == V86FPP_V86LAST) && vmflag)
        return;

      /* ECT -> ECT = no work */
      if ((v86p->vp_fpproc == V86FPP_ECTLAST) && !vmflag)
        return;

      /* Switching component use of floating point */
      fpsave();
      if ((vmflag && v86p->vp_fpvalid == V86FPV_VALID) ||
          (!vmflag && u.u_fpvalid))
        fprestore(vmflag);

      /* Set vp_fpproc to new process mode */
      v86p->vp_fpproc = vmflag ? V86FPP_V86LAST : V86FPP_ECTLAST;
#endif
    }
}

/*
** fpextovrflt
**      handle a processor extension overrun fault
*/
void fpextovrflt(int *r0ptr) {
  printf("\nEXTOVRFLT: eip = 0x%x\n", r0ptr[EIP]);

  asm("  clts    "); /* clear TS bit in CR0  */

  /* Error out quickly if the system doesn't support floating point */
  if (fp_kind == FP_NO) {
    printf("\nEXTOVRFLT WARNING: no FP support\n");
    return;
  }

  /* re-initialize the extension */
  fpinit();

  /* send segmentation violation error signal to the process
   * that owns the processor extension
   */
  if (fp_proc) {
    psignal(fp_proc, SIGSEGV);
  } else {
    printf("\nEXTOVRFLT WARNING: no FP process\n");
    return;
  }

  /* if the current process is not the process that owns the extension,
   * set the TS bit.
   */
  if (fp_proc != u.u_procp)
    setts();
}

/*
** fpexterrflt
**      handle a processor extension error fault
*/
void fpexterrflt(void) {
  asm("clts"); /* clear TS bit in CR0  */

  if (fp_kind == FP_NO) {
    cmn_err(CE_WARN, "EXTERRFLT: no FP support");
    return;
  }

  fpsw = 0; /* clear temporary for status word */

  asm("fnstsw %0" : "=m" (fpsw)); /* store co-processor status word */
  asm("fnclex");       /* clear processor exceptions */

  if (fp_proc != u.u_procp) {
    setts();
  }

  if (fp_proc == (proc_t *)NULL) {
    cmn_err(CE_WARN, "EXTERRFLT: no FP process");
    return;
  }

#ifdef VPIX
  /*
   * This is not a dual-mode process OR it is and the ECT
   * is using the floating point.
   */
  if (!fp_proc->p_v86 || (fp_proc->p_v86->vp_fpproc == V86FPP_ECTLAST)) {
#endif

    /*
     * Log the faulting process and decode which x87 exception
     * fired from the saved status word.  The low six status-word
     * bits share positions with the control-word mask bits
     * (FPINV/FPDNO/FPZDIV/FPOVR/FPUNR/FPPRE), so we reuse those.
     * An unmasked exception reaching here usually means stricter
     * FPU masking than userland expects (see fpinit()).
     */
    cmn_err(
        CE_WARN,
        "SIGFPE (x87 exception) in user process \"%s\" pid %d: "
        "status=0x%.4x%s%s%s%s%s%s",
        PTOU(fp_proc)->u_comm, fp_proc->p_pid, fpsw & 0xffff,
        (fpsw & FPINV) ? " invalid" : "", (fpsw & FPDNO) ? " denormal" : "",
        (fpsw & FPZDIV) ? " zerodivide" : "", (fpsw & FPOVR) ? " overflow" : "",
        (fpsw & FPUNR) ? " underflow" : "", (fpsw & FPPRE) ? " precision" : "");

    /*
     * Send a floating-point error signal to the process
     * that owns the processor extension.
     */
    psignal(fp_proc, SIGFPE);

    /* Save the status word in owner's u block. */
    CATCH_FAULTS(CATCH_SEGU_FAULT)
    PTOU(fp_proc)->u_fps.u_fpstate.status = fpsw;
    END_CATCH();
#ifdef VPIX
  } else
    /*
     * This is a dual-mode process and the virtual 86 task
     * is using the floating point.
     */
    if (fp_proc->p_v86 && (fp_proc->p_v86->vp_fpproc == V86FPP_V86LAST)) {

      /*
       * Send a psuedorupt to the virtual 86 task,
       * and store the floating point unit status
       * in vp_fpu.vp_fpstate.status.
       */
      v86setint(fp_proc->p_v86, V86VI_COPROC);
      fp_proc->p_v86->vp_fpu.vp_fpstate.status = fpsw;
    }
#endif
}

#ifdef AT386
/*
** fpintr
**      handle a processor extension error interrupt on the AT386
**
**      this comes in on line 5 of the slave PIC at SPL1
*/
void fpintr(void) {
  oem_fclex(); /* Clear NDP BUSY latch */

#ifdef WEITEK
  if (weitek_kind != WEITEK_NO) {
    /*
     * wtl 1167 and 80387 errors are or'd and the result
     * is sent to the PIC.  therefore, we
     * need to check whether this interrupt is from
     * weitek or 387
     * we'll do this by looking at the 387 status reg.
     */
    int stat387;

    if (fp_kind == FP_NO) {
      /* with no 387 support, assume weitek */
      weitek_reset_intr();
      weitintr(0);
      return;
    }
    stat387 = get87();
    if ((stat387 & FPS_ES) == 0) { /* no 387 error */
      weitek_reset_intr();
      weitintr(0);
      return;
    }
  }
#endif
  fpexterrflt();
}
#endif

/*
** fpsetup
**      do more advanced setup of the floating point unit, mostly for MMX/SSE
*/

void fpsetup(void) {
  /* If the early boot code detected nothing, we quite obviously have nothing
   * to setup.
   */
  if (fp_kind == FP_NO)
    return;

  cmn_err(CE_CONT, "here 1");
  /* If we don't have CPUID, the CPU will absolutely predate anything other than
   * x87.
   */
  if (!x86_has_cpuid())
    return;
  cmn_err(CE_CONT, "here 2");
  /* We support CPUID, check the highest supported function */
  unsigned int highest_func;
  x86_cpuid(CPUID_GETVENDORSTRING, 0, &highest_func, NULL, NULL, NULL);
  cmn_err(CE_CONT, "here 3");
  /* Check whether we support the CPUID_GETFEATURES function */
  if (highest_func >= CPUID_GETFEATURES) {
    unsigned int features;
    x86_cpuid(CPUID_GETFEATURES, 0, NULL, NULL, NULL, &features);
    cmn_err(CE_CONT, "here 4");
    if (features & CPUID_FEAT_EDX_FXSR) {
      /* We have fxsave/fxrstor support, so use that instead of fnsave/frstor */
      fp_kind = FP_FXSAVE;

      /* Actually enable support for fxsave/fxrstor, and sse and stuff while
       * we're at it.
       */
      asm volatile("mov %%cr4,%%eax\n\t"
                  "or  $0x600,%%eax\n\t"   /* 0x200 OSFXSR | 0x400 OSXMMEXCPT */
                  "mov %%eax,%%cr4" : : : "eax");

      cmn_err(CE_NOTE, "fpsetup: CPU supports fxsave/fxrstor,"
        " using those for FP state save/restore");
    }
  }
}

/*
** fpinit
**	initialize the floating point unit for this user
*/
void fpinit(void) {
  if (fp_kind == FP_NO)
    cmn_err(CE_PANIC, "fpinit: no FP support");

  asm("  fninit");

  /*
   * Mask all the exceptions and set the control word to modern defaults.
   * The old SVR4 control word settings didn't mask several interrupts,
   * which caused modern userland that expects simple NaN responses and stuff
   * to get SIGFPE instead.
   * TODO: really, this only affected mesa. I don't know what POSIX says
   * about this but if POSIX doesn't mind, perhaps following what newer UNIX
   * versions did here would be more in spirit of this project
   */
  asm("  fstcw   finitstate");

  finitstate &= ~(FPPC);
  /*
   * Modern i386 toolchains compile normal floating-point expressions for
   * x87 extended evaluation (FLT_EVAL_METHOD == 2).  Keeping the old SVR4
   * 53-bit precision control causes libm algorithms that rely on extended
   * intermediates, such as floor(), to round away small integer values.
   */
  finitstate |= (FPSIG64 | FPIC);

  asm("  fldcw   finitstate");

  if (fp_kind == FP_FXSAVE) {
    asm("  ldmxcsr mxcsrinit");
    asm("  xorps %xmm0, %xmm0");
    asm("  xorps %xmm1, %xmm1");
    asm("  xorps %xmm2, %xmm2");
    asm("  xorps %xmm3, %xmm3");
    asm("  xorps %xmm4, %xmm4");
    asm("  xorps %xmm5, %xmm5");
    asm("  xorps %xmm6, %xmm6");
    asm("  xorps %xmm7, %xmm7");
  }

  /* to fill FP stack with zeros as before, un-comment the following: */
  /*
  for( i=0; i<8; i++) {
          asm( "  fldz" );
  }
  */
}

/*
** fpsave
**      save the floating point state into fp_proc's appropriate
**	storage area.
**
**      fp_proc must be valid!
*/
void fpsave(void) {
  struct user *fp_u;
#ifdef VPIX
  v86_t *v86p;
#endif

  /* Something has obviously gone very wrong if we try to save the floating
   * point state and there is no current owner.
   */
  if (fp_proc == NULL)
    cmn_err(CE_PANIC, "fpsave: no fp_proc");

#ifdef VPIX
  /*
   * The process that owns the floating point unit
   * is not a dual-mode process OR it is and the ECT
   * was the last user of floating point.
   */
  if (!(v86p = fp_proc->p_v86) || v86p->vp_fpproc == V86FPP_ECTLAST) {
#endif
    /* Get access to the extension owner's u block. */
    fp_u = PTOU(fp_proc);

    CATCH_FAULTS(CATCH_SEGU_FAULT) {
      /* if chip present, save its state */
      if (fp_kind & FP_HW) {
        /* If available, save with fxsave */
        if (fp_kind == FP_FXSAVE) {
          /* If the fxsave area hasn't been allocated yet, do so now */
          if (fp_u->u_fxsave_area == NULL) {
            /* fxsave needs 16 byte alignment, and kmem actually does that,
             * so we don't need to do anything special here.
             */
            fp_u->u_fxsave_area = kmem_alloc(512, KM_NOSLEEP);
            cmn_err(CE_CONT, "fpsave: allocated fxsave area at %p\n", fp_u->u_fxsave_area);
            /* TODO: handle this allocation failing properly.
              * For now, just panic, since this is a pretty serious error.
             */
            if (fp_u->u_fxsave_area == NULL) {
              cmn_err(CE_PANIC, "fpsave: failed to allocate fxsave area");
            }
          }
          fxsave(fp_u->u_fxsave_area);
        } else {
          /* We have no fxsave support; just do the old thing. */
          fnsave(fp_u->u_fps.u_fpstate.state);
        }
      }
        
      /* say that the saved state is valid */
      fp_u->u_fpvalid = 1;
    }
    END_CATCH();
#ifdef VPIX
  } else
    /*
     * The process that owns the floating point unit
     * is a dual-mode process and the virtual 86 task
     * was the last user of floating point.
     */
    if (v86p && v86p->vp_fpproc == V86FPP_V86LAST) {

      /* if chip present, save its state */
      if (fp_kind & FP_HW)
        fnsave(v86p->vp_fpu.vp_fpstate.state);

      /* say that the saved state is valid */
      v86p->vp_fpvalid = V86FPV_VALID;
    }
#endif

  /* Now nobody owns the fp unit */
  fp_proc = 0;
}

/*
** fprestore
**	restore the floating point state from the current
**	appropriate storage area.
*/
void fprestore(int vmflag) /* Are we returning to a virtual 86 task? */
{
#ifdef VPIX
  v86_t *v86p;
#endif

#ifdef VPIX
  /*
   * The process that needs the floating point unit
   * is not a dual-mode process OR it is and the ECT
   * is going to use the floating point unit.
   */
  if (!v86procflag || !vmflag) {
#endif
    /* if chip present, restore its state */
    if (fp_kind & FP_HW) {
      /* If available, restore with fxrstor */
      if (fp_kind == FP_FXSAVE) {
        /* If the fxsave area hasn't been allocated yet, just reset it. */
        if (u.u_fxsave_area == NULL) {
          fpinit();
        } else {
          /* We can now restore this. */
          fxrstor(u.u_fxsave_area);
        }
      } else {
        /* We have no fxsave support; just do the old thing. */
        frstor(u.u_fps.u_fpstate.state);
      }
    }
      
    /* say that the saved state is not valid */
    u.u_fpvalid = 0;
#ifdef VPIX
  } else
    /*
     * The process that needs the floating point unit
     * is a dual-mode process and the virtual 86 task
     * was the last user of floating point.
     */
    if (v86procflag && vmflag) {
      v86p = u.u_procp->p_v86;

      /* if chip present, restore its state */
      if (fp_kind & FP_HW)
        frstor(v86p->vp_fpu.vp_fpstate.state);

      /* say that the saved state is not valid */
      v86p->vp_fpvalid = V86FPV_NOTVALID;
    }
#endif
}

/*
** fpksave
**      Save the floating point state into fp_proc's user structure,
**      and re-initialize for kernel use.  Process must not sleep
**      before calling fpkreset().  Called by Weitek emulator.
*/
void fpksave(void) {
  if (fp_proc)
    fpsave();
  asm("  clts    "); /* clear TS bit in CR0  */
  fpinit();
}

/*
** fpkreset
**      Reset after a fpksave().
**      Called by Weitek emulator.
*/
void fpkreset(void) {
  fp_proc = 0;
  setts();
}

/*
** fnsave
**      old way to save the x87 state. called from fpsave(), for machines not
**      supporting more modern ways.
*/
void fnsave(int *addr) {
  asm volatile("clts\n\t"
               "fnsave (%0)\n\t"
               "fwait"
               :
               : "r"(addr)
               : "memory");
}

/*
** frstor
**      old way to restore the x87 state. called from fprestore(), for machines
**      not supporting more modern ways.
*/
void frstor(int *addr) {
  asm volatile("clts\n\t"
               "frstor (%0)\n\t"
               "fwait"
               :
               : "r"(addr)
               : "memory");
}

/*
** fxsave
**      save the x87/MMX/SSE state using the FXSAVE instruction.
*/
void fxsave(void *addr) {
  asm volatile("clts\n\t"
               "fxsave (%0)"
               :
               : "r"(addr)
               : "memory");
  fpinit();
}

/*
** fxrstor
**      restore the x87/MMX/SSE state using the FXRSTOR instruction.
*/
void fxrstor(void *addr) {
  asm volatile("clts\n\t"
               "fxrstor (%0)\n\t"
               :
               : "r"(addr)
               : "memory");
}

/*
** setts
**      asm code to set the ts bit in CR0
*/
void setts(void) {
  asm volatile("movl %%cr0, %%eax\n\t"
               "orl $0x08, %%eax\n\t"
               "movl %%eax, %%cr0"
               :
               :
               : "eax", "memory");
}
