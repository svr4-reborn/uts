#	Copyright (c) 1990 UNIX System Laboratories, Inc.
#	Copyright (c) 1984, 1986, 1987, 1988, 1989, 1990 AT&T
#	  All Rights Reserved

#	THIS IS UNPUBLISHED PROPRIETARY SOURCE CODE OF
#	UNIX System Laboratories, Inc.
#	The copyright notice above does not evidence any
#	actual or intended publication of such source code.

#ident	"@(#)kern-fp:tool/tools.mk	1.1"

SETFILTER_SCRIPT = ../../../../tools/legacy_setfilter.py

all:  setfilter

clean:	
	-/bin/rm setfilter.o

clobber: clean
	-/bin/rm setfilter

setfilter: setfilter.c
	cp ${SETFILTER_SCRIPT} setfilter
	chmod 755 setfilter

install:

