/*
 * start.s - kernel entry / user-page-table startup, assembled as one unit.
 *
 * Thin assembler stub: #include the generated symbol-value table (symvals.s)
 * so its .set constants are visible, then the startup fragment uprt.s. Assemble
 * with cc -x assembler-with-cpp.
 */
	.file	"uprt.s"

#include "symvals.s"

#include "uprt.s"
