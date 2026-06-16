#include "sys/types.h"
#include "sys/param.h"
#include "sys/systm.h"
#include "sys/errno.h"
#include "sys/signal.h"
#include "sys/tss.h"
#include "sys/immu.h"
#include "sys/reg.h"
#include "sys/seg.h"
#include "sys/proc.h"
#include "sys/user.h"
#include "sys/vnode.h"
#include "sys/file.h"
#include "sys/cred.h"
#include "sys/class.h"
#include "sys/time.h"
#include "sys/kmem.h"
#include "sys/fp.h"
#include "sys/cmn_err.h"

#ifdef WEITEK
#include "sys/weitek.h"
#endif

/*
 * User threads are represented as normal proc_t entries that share the
 * parent's address space.  That keeps the scheduler, signal delivery, and
 * u-block machinery in one model instead of inventing a second execution
 * object.  These entries are marked STHREAD so waitid() ignores them and
 * segu_release() can reap them after their final context switch.
 *
 * The public ABI is intentionally split into small syscalls rather than a
 * private multiplexor.  Thread creation/lifetime and futex waits are distinct
 * kernel services with different argument shapes; separate syscalls make the
 * contract visible in sysent and easier to trace when debugging old binaries.
 */

struct thread_createa {
	caddr_t entry;
	caddr_t stack;
};

struct futex_waita {
	int *uaddr;
	int expected;
	timestruc_t *timeoutp;
};

struct futex_wakea {
	int *uaddr;
	int all;
};

struct futex_waiter {
	struct futex_waiter *next;
	struct as *as;
	int *uaddr;
	proc_t *procp;
	int woken;
	int timed_out;
	int timeout_id;
};

int futex_debug = 0;
static struct futex_waiter *futex_waiters;

static void futex_remove(struct futex_waiter *waiter);
static void futex_timeout(caddr_t arg);
static int do_futex_wait(int *uaddr, int expected, timestruc_t *timeoutp);
static int do_futex_wake(int *uaddr, int all, rval_t *rvp);
static int do_thread_create(caddr_t entry, caddr_t stack, rval_t *rvp);

void thread_exit_current(void);

static void
futex_remove(waiter)
	struct futex_waiter *waiter;
{
	struct futex_waiter **linkp;

	for (linkp = &futex_waiters; *linkp; linkp = &(*linkp)->next) {
		if (*linkp == waiter) {
			*linkp = waiter->next;
			waiter->next = NULL;
			return;
		}
	}
}

static void
futex_timeout(arg)
	caddr_t arg;
{
	struct futex_waiter *waiter = (struct futex_waiter *)arg;
	int s;

	/*
	 * The timeout callback races with futex_wake().  Both sides hold splhi()
	 * while touching the waiter state so the sleeping thread observes exactly
	 * one terminal reason: woken, timed out, or interrupted by a signal.
	 */
	s = splhi();
	if (!waiter->woken) {
		waiter->timed_out = 1;
		if (futex_debug)
			cmn_err(CE_CONT,
			    "^futex timeout: waiter=%x pid=%d proc=%x "
			    "uaddr=%x p_stat=%x p_wchan=%x\n",
			    waiter, waiter->procp ? waiter->procp->p_pid : -1,
			    waiter->procp, waiter->uaddr,
			    waiter->procp ? waiter->procp->p_stat : -1,
			    waiter->procp ? waiter->procp->p_wchan : 0);
		wakeprocs((caddr_t)waiter, PRMPT);
	}
	splx(s);
}

static int
do_futex_wait(uaddr, expected, timeoutp)
	int *uaddr;
	int expected;
	timestruc_t *timeoutp;
{
	struct futex_waiter *waiter;
	timestruc_t timeout_value;
	long ticks = 0;
	long nsec_per_tick;
	int value;
	int error = 0;
	int s;

	if (uaddr == NULL)
		return EINVAL;

	if (timeoutp != NULL) {
		if (copyin((caddr_t)timeoutp, (caddr_t)&timeout_value,
		    sizeof(timeout_value)))
			return EFAULT;
		if (timeout_value.tv_sec < 0 || timeout_value.tv_nsec < 0 ||
		    timeout_value.tv_nsec >= 1000000000L)
			return EINVAL;

		/* Convert the relative timespec into old kernel clock ticks. */
		nsec_per_tick = 1000000000L / HZ;
		ticks = timeout_value.tv_sec * HZ +
		    (timeout_value.tv_nsec + nsec_per_tick - 1) / nsec_per_tick;
		if (ticks <= 0)
			return ETIMEDOUT;
	}

	waiter = (struct futex_waiter *)kmem_zalloc(
	    sizeof(struct futex_waiter), KM_SLEEP);
	waiter->as = u.u_procp->p_as;
	waiter->uaddr = uaddr;
	waiter->procp = u.u_procp;

	if (futex_debug)
		cmn_err(CE_CONT,
		    "^futex wait enter: pid=%d proc=%x as=%x uaddr=%x "
		    "expected=%x timeoutp=%x ticks=%x waiter=%x\n",
		    u.u_procp->p_pid, u.u_procp, waiter->as, uaddr,
		    expected, timeoutp, ticks, waiter);

	/*
	 * Check the user word and enqueue atomically with respect to futex_wake().
	 * This prevents the classic lost wakeup where a waker runs between the
	 * userspace compare and the kernel sleep.
	 */
	s = splhi();
	value = fuword(uaddr);
	if (value == -1 && fubyte((caddr_t)uaddr) == -1) {
		splx(s);
		if (futex_debug)
			cmn_err(CE_CONT,
			    "^futex wait fault: pid=%d proc=%x uaddr=%x "
			    "waiter=%x\n",
			    u.u_procp->p_pid, u.u_procp, uaddr, waiter);
		kmem_free((caddr_t)waiter, sizeof(struct futex_waiter));
		return EFAULT;
	}
	if (value != expected) {
		splx(s);
		if (futex_debug)
			cmn_err(CE_CONT,
			    "^futex wait again: pid=%d proc=%x uaddr=%x "
			    "expected=%x value=%x waiter=%x\n",
			    u.u_procp->p_pid, u.u_procp, uaddr, expected,
			    value, waiter);
		kmem_free((caddr_t)waiter, sizeof(struct futex_waiter));
		return EAGAIN;
	}

	waiter->next = futex_waiters;
	futex_waiters = waiter;
	if (ticks > 0)
		waiter->timeout_id = timeout(futex_timeout, (caddr_t)waiter, ticks);
	if (futex_debug)
		cmn_err(CE_CONT,
		    "^futex wait queued: pid=%d proc=%x as=%x uaddr=%x "
		    "value=%x waiter=%x timeout_id=%x\n",
		    u.u_procp->p_pid, u.u_procp, waiter->as, uaddr,
		    value, waiter, waiter->timeout_id);
	splx(s);

	while (!waiter->woken && !waiter->timed_out) {
		if (futex_debug)
			cmn_err(CE_CONT,
			    "^futex wait sleep: pid=%d proc=%x waiter=%x "
			    "woken=%d timed_out=%d p_stat=%x p_wchan=%x\n",
			    u.u_procp->p_pid, u.u_procp, waiter,
			    waiter->woken, waiter->timed_out,
			    u.u_procp->p_stat, u.u_procp->p_wchan);
		if (sleep((caddr_t)waiter, PZERO | PCATCH)) {
			error = EINTR;
			if (futex_debug)
				cmn_err(CE_CONT,
				    "^futex wait intr: pid=%d proc=%x "
				    "waiter=%x woken=%d timed_out=%d\n",
				    u.u_procp->p_pid, u.u_procp, waiter,
				    waiter->woken, waiter->timed_out);
			break;
		}
		if (futex_debug)
			cmn_err(CE_CONT,
			    "^futex wait woke: pid=%d proc=%x waiter=%x "
			    "woken=%d timed_out=%d p_stat=%x p_wchan=%x\n",
			    u.u_procp->p_pid, u.u_procp, waiter,
			    waiter->woken, waiter->timed_out,
			    u.u_procp->p_stat, u.u_procp->p_wchan);
	}

	/*
	 * Always unlink before freeing.  A woken waiter remains visible to other
	 * wake calls until this thread removes it, so skipping this step leaves a
	 * stale pointer in the global futex list.
	 */
	s = splhi();
	if (waiter->timeout_id && !waiter->timed_out)
		(void)untimeout(waiter->timeout_id);
	futex_remove(waiter);
	if (!error && waiter->timed_out)
		error = ETIMEDOUT;
	if (futex_debug)
		cmn_err(CE_CONT,
		    "^futex wait exit: pid=%d proc=%x waiter=%x error=%d "
		    "woken=%d timed_out=%d\n",
		    u.u_procp->p_pid, u.u_procp, waiter, error,
		    waiter->woken, waiter->timed_out);
	splx(s);

	kmem_free((caddr_t)waiter, sizeof(struct futex_waiter));
	return error;
}

static int
do_futex_wake(uaddr, all, rvp)
	int *uaddr;
	int all;
	rval_t *rvp;
{
	struct futex_waiter *waiter;
	struct as *as = u.u_procp->p_as;
	int count = 0;
	int s;

	if (uaddr == NULL)
		return EINVAL;

	/* Futex keys are process-local: same address-space plus same user VA. */
	if (futex_debug)
		cmn_err(CE_CONT,
		    "^futex wake enter: pid=%d proc=%x as=%x uaddr=%x all=%d\n",
		    u.u_procp->p_pid, u.u_procp, as, uaddr, all);
	s = splhi();
	for (waiter = futex_waiters; waiter; waiter = waiter->next) {
		if (waiter->as != as || waiter->uaddr != uaddr || waiter->woken)
			continue;
		if (futex_debug)
			cmn_err(CE_CONT,
			    "^futex wake match: pid=%d proc=%x target_pid=%d "
			    "target_proc=%x waiter=%x target_stat=%x "
			    "target_wchan=%x woken=%d timed_out=%d\n",
			    u.u_procp->p_pid, u.u_procp,
			    waiter->procp ? waiter->procp->p_pid : -1,
			    waiter->procp, waiter,
			    waiter->procp ? waiter->procp->p_stat : -1,
			    waiter->procp ? waiter->procp->p_wchan : 0,
			    waiter->woken, waiter->timed_out);
		waiter->woken = 1;
		count++;
		wakeprocs((caddr_t)waiter, PRMPT);
		if (!all)
			break;
	}
	splx(s);

	if (futex_debug)
		cmn_err(CE_CONT,
		    "^futex wake exit: pid=%d proc=%x as=%x uaddr=%x "
		    "all=%d count=%d\n",
		    u.u_procp->p_pid, u.u_procp, as, uaddr, all, count);

	rvp->r_val1 = count;
	rvp->r_val2 = 0;
	return 0;
}

static int
do_thread_create(entry, stack, rvp)
	caddr_t entry;
	caddr_t stack;
	rval_t *rvp;
{
	pid_t newpid;
	int error = 0;
	int npcond;

	if (entry == NULL || stack == NULL)
		return EINVAL;

	/*
	 * newproc() already knows how to create a schedulable execution context.
	 * NP_SHARE keeps the address space common with the parent, and NP_THREAD
	 * marks the child so exit/wait cleanup uses thread semantics instead of
	 * process semantics.
	 */
	npcond = NP_FAILOK | NP_SHARE | NP_THREAD |
	    ((u.u_cred->cr_uid && u.u_cred->cr_ruid) ? NP_NOLAST : 0);

	switch (newproc(npcond, &newpid, &error)) {
	case 1:
		/* Child: resume to the requested user entry point and stack. */
		u.u_ar0[EIP] = (int)entry;
		u.u_ar0[UESP] = (int)stack;
		u.u_ar0[CS] = USER_CS;
		u.u_ar0[DS] = u.u_ar0[ES] = u.u_ar0[SS] = USER_DS;
		u.u_ar0[FS] = u.u_ar0[GS] = 0;
		u.u_ar0[EFL] &= ~PS_D;
		rvp->r_val1 = 0;
		rvp->r_val2 = 0;
		return 0;
	case 0:
		/* Parent: return the new proc pid as the user-visible thread id. */
		rvp->r_val1 = newpid;
		rvp->r_val2 = 0;
		return 0;
	default:
		return error ? error : EAGAIN;
	}
}

void
thread_exit_current(void)
{
	proc_t *p = u.u_procp;
	struct ufchunk *ufp;
	struct ufchunk *next_ufp;

	/*
	 * This is deliberately smaller than exit().  A thread must release its
	 * per-u-block references, but it must not call relvm(), orphan children, or
	 * signal the parent as a normal process zombie.  The final proc_t removal
	 * happens in segu_release() after swtch() has stopped using this u-block.
	 */
	p->p_flag &= ~STRC;
	p->p_clktim = 0;
	sigfillset(&p->p_ignore);
	sigemptyset(&p->p_sig);
	sigemptyset(&p->p_sigmask);
	sigdelq(p, 0);

	closeall(1);

	ufp = u.u_flist.uf_next;
	u.u_flist.uf_next = (struct ufchunk *)NULL;
	while (ufp) {
		next_ufp = ufp->uf_next;
		kmem_free((caddr_t)ufp, sizeof(struct ufchunk));
		ufp = next_ufp;
	}

	(void)punlock();
	VN_RELE(u.u_cdir);
	u.u_cdir = rootdir;
	if (u.u_rdir) {
		VN_RELE(u.u_rdir);
		u.u_rdir = NULLVP;
	}

	if (p == fp_proc)
		fp_proc = NULL;
#ifdef WEITEK
	u.u_weitek = WEITEK_NO;
	if (p == weitek_proc)
		weitek_proc = NULL;
#endif

	if (p->p_exec) {
		VN_RELE(p->p_exec);
		p->p_exec = NULLVP;
	}

	crfree(u.u_cred);
	p->p_stat = SZOMB;
	p->p_wcode = 0;
	p->p_wdata = 0;
	CL_EXITCLASS(p, p->p_clproc);
	swtch();

	/* NOTREACHED */
	__builtin_unreachable();
}

int
thread_create(uap, rvp)
	struct thread_createa *uap;
	rval_t *rvp;
{
	return do_thread_create(uap->entry, uap->stack, rvp);
}

int
thread_exit(uap, rvp)
	int *uap;
	rval_t *rvp;
{
	(void)uap;
	(void)rvp;
	thread_exit_current();
	return 0;
}

int
thread_self(uap, rvp)
	int *uap;
	rval_t *rvp;
{
	(void)uap;
	rvp->r_val1 = u.u_procp->p_pid;
	rvp->r_val2 = 0;
	return 0;
}

int
futex_wait(uap, rvp)
	struct futex_waita *uap;
	rval_t *rvp;
{
	(void)rvp;
	return do_futex_wait(uap->uaddr, uap->expected, uap->timeoutp);
}

int
futex_wake(uap, rvp)
	struct futex_wakea *uap;
	rval_t *rvp;
{
	return do_futex_wake(uap->uaddr, uap->all, rvp);
}
