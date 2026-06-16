/*
 * locore.s - machine-layer kernel core, assembled as a single translation unit.
 *
 * This is a thin assembler stub that #includes the generated symbol-value table
 * (symvals.s, the .set offsets emitted by tools/uts_symvals.py) followed by the
 * individual machine-layer fragments in their historical link order. Keeping
 * them in one assembler unit makes the symvals .set constants visible to every
 * fragment, exactly as the old build did by concatenating them into one file.
 *
 * Build it with: cc -x assembler-with-cpp (so the #include directives and the
 * fragments' own #include/#ifdef lines are preprocessed).
 */
	.file	"locore.s"

#include "symvals.s"

#include "ttrap.s"
#include "cswitch.s"
#include "misc.s"
#include "intr.s"
#ifdef VPIX
#include "v86gptrap.s"
#endif
#include "weitek.s"
#include "oemsup.s"
#include "string.s"
