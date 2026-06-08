/*	Copyright (c) 1990 UNIX System Laboratories, Inc.	*/
/*	Copyright (c) 1984, 1986, 1987, 1988, 1989, 1990 AT&T	*/
/*	  All Rights Reserved  	*/

/*	THIS IS UNPUBLISHED PROPRIETARY SOURCE CODE OF     	*/
/*	UNIX System Laboratories, Inc.                     	*/
/*	The copyright notice above does not evidence any   	*/
/*	actual or intended publication of such source code.	*/

#ident	"@(#)mouse:io/mse_subr.c	1.3.2.1"

#include "sys/param.h"
#include "sys/types.h"
#include "sys/signal.h"
#include "sys/errno.h"
#include "sys/file.h"
#include "sys/termio.h"
#include "sys/stream.h"
#include "sys/stropts.h"
#include "sys/strtty.h"
#include "sys/debug.h"
#include "sys/cred.h"
#include "sys/proc.h"
#include "sys/ws/chan.h"
#include "sys/mouse.h"
#include "mse.h"
#include "sys/cmn_err.h"
#include "sys/ddi.h"


extern int wakeup();

#ifndef MSE_SUBR_DEBUG
#define	MSE_SUBR_DEBUG	0
#endif

int mse_subr_debug = MSE_SUBR_DEBUG;

void
mse_iocack(qp, mp, iocp, rval)
queue_t *qp;
mblk_t *mp;
struct iocblk *iocp;
int rval;
{
	mblk_t	*tmp;

	mp->b_datap->db_type = M_IOCACK;
	iocp->ioc_rval = rval;
	iocp->ioc_count = iocp->ioc_error = 0;
	qreply(qp,mp);
}

void
mse_iocnack(qp, mp, iocp, error, rval)
queue_t *qp;
mblk_t *mp;
struct iocblk *iocp;
int error;
int rval;
{
	mp->b_datap->db_type = M_IOCNAK;
	iocp->ioc_rval = rval;
	iocp->ioc_error = error;
	qreply(qp,mp);
}

void
mse_copyout(qp, mp, nmp, size, state)
queue_t *qp;
register mblk_t *mp, *nmp;
uint size;
unsigned long state;
{
	register struct copyreq *cqp;
	struct strmseinfo *cp;
	struct msecopy	*copyp;

#ifdef DEBUG
	cmn_err(CE_NOTE,"In mse_copyout");
#endif 
	cp = (struct strmseinfo *) qp->q_ptr;
	copyp = &cp->copystate;
	copyp->state = state;
	cqp = (struct copyreq *) mp->b_rptr;
	cqp->cq_size = size;
	cqp->cq_addr = (caddr_t) * (long *) mp->b_cont->b_rptr;
	cqp->cq_flag = 0;
	cqp->cq_private = (mblk_t *)copyp;

	mp->b_wptr = mp->b_rptr + sizeof(struct copyreq);
	mp->b_datap->db_type = M_COPYOUT;

	if (mp->b_cont) freemsg(mp->b_cont);
	mp->b_cont = nmp;

	qreply(qp, mp);
#ifdef DEBUG
	cmn_err(CE_NOTE,"leaving mse_copyout");
#endif 
}


void
mse_copyin(qp, mp, size, state)
queue_t *qp;
register mblk_t *mp;
int size;
unsigned long state;
{
	register struct copyreq *cqp;
	struct msecopy *copyp;
	struct strmseinfo *cp;

#ifdef DEBUG
	cmn_err(CE_NOTE,"in mse_copyin");
#endif 
	cp = (struct strmseinfo *) qp->q_ptr;
	copyp = &cp->copystate;

	copyp->state = state;
	cqp = (struct copyreq *) mp->b_rptr;
	cqp->cq_size = size;
	cqp->cq_addr = (caddr_t) * (long *) mp->b_cont->b_rptr;
	cqp->cq_flag = 0;
	cqp->cq_private = (mblk_t *)copyp;

	if (mp->b_cont)
		 freemsg(mp->b_cont);

	mp->b_datap->db_type = M_COPYIN;
	mp->b_wptr = mp->b_rptr + sizeof(struct copyreq);

	qreply(qp, mp);
#ifdef DEBUG
	cmn_err(CE_NOTE,"leaving mse_copyin");
#endif 
}

void
mseproc(qp)
struct strmseinfo *qp;
{
	register mblk_t 	*bp;
	register mblk_t 	*mp;
	register int oldpri;
	struct ch_protocol	*protop;
	struct mse_event 	*minfo;

#ifdef DEBUG1
	cmn_err(CE_NOTE,"In mseproc");
#endif
/* If no change, don't load a new event */
	if (qp->x | qp->y)
		qp->type = MSE_MOTION;
	else if (qp->button != qp->old_buttons)
		qp->type = MSE_BUTTON;
	else {
		if (mse_subr_debug)
			cmn_err(CE_CONT,
				"mse: no event button=%x old=%x dx=%d dy=%d\n",
				qp->button, qp->old_buttons, qp->x, qp->y);
		return;
	}

	if (mse_subr_debug)
		cmn_err(CE_CONT,
			"mse: event type=%d button=%x old=%x dx=%d dy=%d status=%x\n",
			qp->type, qp->button, qp->old_buttons, qp->x, qp->y,
			qp->mseinfo.status);

	qp->mseinfo.status = (~qp->button & 7) | ((qp->button ^ qp->old_buttons) << 3) | (qp->mseinfo.status & BUTCHNGMASK) | (qp->mseinfo.status & MOVEMENT);

	if (qp->type == MSE_MOTION) {
		register int sum;

        qp->mseinfo.status |= MOVEMENT;

		/*
		** See sys/mouse.h for UPPERLIM = 127 and LOWERLIM = -128
		*/

		sum = qp->mseinfo.xmotion + qp->x;

		if (sum > UPPERLIM)
            qp->mseinfo.xmotion = UPPERLIM;
		else if (sum < LOWERLIM)
            qp->mseinfo.xmotion = LOWERLIM;
		else
            qp->mseinfo.xmotion = sum;

		sum = qp->mseinfo.ymotion + qp->y;

		if (sum > UPPERLIM)
            qp->mseinfo.ymotion = UPPERLIM;
		else if (sum < LOWERLIM)
            qp->mseinfo.ymotion = LOWERLIM;
		else
            qp->mseinfo.ymotion = sum;
	}
			/* Note the button state */
	qp->old_buttons = qp->button;
	if((bp = allocb(sizeof(struct ch_protocol),BPRI_MED)) == NULL){ 
		if (mse_subr_debug)
			cmn_err(CE_CONT, "mse: allocb ch_protocol failed\n");
		return;
	}
	bp->b_datap->db_type = M_PROTO;
	bp->b_wptr += sizeof(struct ch_protocol);
	protop = (struct ch_protocol *) bp->b_rptr;
	protop->chp_type = CH_DATA;
	protop->chp_stype = CH_MSE;
	drv_getparm(LBOLT,&protop->chp_tstmp);
	if((mp = allocb(sizeof(struct mse_event),BPRI_MED)) == NULL){ 
		if (mse_subr_debug)
			cmn_err(CE_CONT, "mse: allocb mse_event failed\n");
		freemsg(bp);
		return;
	}
	bp->b_cont = mp;
	minfo = (struct mse_event *)mp->b_rptr;
	minfo->type = qp->type;	
	minfo->code = qp->button;	
	minfo->x = qp->x;	
	minfo->y = qp->y;	
	mp->b_wptr += sizeof(struct mse_event);
	if (mse_subr_debug)
		cmn_err(CE_CONT,
			"mse: putnext CH_MSE type=%d code=%x x=%d y=%d rqp=%x\n",
			minfo->type, minfo->code, minfo->x, minfo->y, qp->rqp);
	putnext(qp->rqp, bp);
}
