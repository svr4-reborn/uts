/*
 * idmkunix -- build the bootable "unix" image from the configured /etc/conf
 * tree.  This is a modern rewrite of the historical SVR4 idmkunix.
 *
 * The original tool drove the obsolete SVR4 Compilation System (idcpp/idcomp/
 * idas) through a tangle of COFF/ELF special cases, and its "-c cross_cc"
 * path was long-dead (#if 0'd out).  This port keeps the original command-line
 * interface and the same input/output file contract, but drives a single
 * modern C compiler ("cc -c") and ELF link-editor ("ld"), so it works both as
 * a host build tool (driven by the YAML kernel build with the i686 cross
 * toolchain) and natively on the target for on-the-fly kernel reconfiguration.
 *
 * Contract:
 *   input dir  (-i): holds the idconfig-generated glue and "direct" file
 *                    (conf.c, fsconf.c, vector.c, direct).  Defaults to
 *                    <root>/etc/conf/cf.d.
 *   output dir (-o): where conf.o/fsconf.o/vector.o and "unix" are written.
 *                    Defaults to the input dir.
 *   pack tree:       <root>/etc/conf/pack.d/<module>/ holds the prebuilt
 *                    objects.  pack.d/kernel holds the prelinked core blob
 *                    (kernel.o) plus the special start.o/locore.o/syms.o and
 *                    the vuifile link map.
 *
 * The link line mirrors the one the YAML build used previously:
 *   ld -m elf_i386 -dn -o unix -e _start -T <cf.d>/vuifile \
 *      <core objs> <module objs> conf.o fsconf.o vector.o
 * start.o and locore.o are pulled in by the vuifile linker script and so are
 * deliberately omitted from the object list.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/wait.h>

#ifndef PATH_MAX
#define PATH_MAX 1024
#endif

#define MAXOBJ	512		/* max objects on the kernel link line */
#define MAXDEF	16		/* max extra -D/-U passed through to cc */
#define MAXINC	16		/* max extra -I include dirs */
#define MAXXTRA	32		/* max extra -Y cc flags (codegen ABI etc.) */

/* error message formats */
#define USAGE	"Usage: idmkunix [-#] [-i dir] [-o dir] [-p pack.d] [-r dir] [-c cc] [-l ld] [-Idir] [-Yccflag] [-Ddefine] [-Udefine]\n"
#define EXISTF	"Directory '%s' does not exist\n"
#define FOPENF	"Cannot open '%s' for mode '%s'\n"
#define EFILE	"Cannot find Driver.o in driver package '%s'\n"
#define BADCOMP	"'%s' will not compile\n"
#define LINKF	"Cannot link-edit unix\n"

/* tool defaults; -c / -l override these (and the build passes the cross tools) */
static char *cc = "cc";
static char *ld = "ld";

static char root[PATH_MAX];	/* -r: root prepended to /etc/conf paths */
static char input[PATH_MAX];	/* -i: dir holding direct + generated glue */
static char output[PATH_MAX];	/* -o: dir receiving unix + .o glue */
static char confdir[PATH_MAX];	/* <root>/etc/conf */
static char packdir[PATH_MAX];	/* <root>/etc/conf/pack.d */

static int rflag, iflag, oflag, pflag, debug;

static char *predef[MAXDEF];	/* extra -D/-U flags passed through to cc */
static int npredef;

static char *incdir[MAXINC];	/* extra -I include dirs for the glue compile */
static int ninc;

static char *xtracc[MAXXTRA];	/* extra cc flags (-Y), e.g. codegen ABI */
static int nxtra;

static char *objs[MAXOBJ];	/* objects gathered for the kernel link */
static int nobj;

static char errbuf[256];

extern char *optarg;

/* ------------------------------------------------------------------ */

static void
fatal()
{
	fprintf(stderr, "ERROR: %s\n", errbuf);
	exit(1);
}

static char *
xstrdup(s)
char *s;
{
	char *p = malloc((unsigned)(strlen(s) + 1));
	if (p == NULL) {
		strcpy(errbuf, "out of memory\n");
		fatal();
	}
	strcpy(p, s);
	return (p);
}

static int
exists(path)
char *path;
{
	struct stat st;
	return (stat(path, &st) == 0);
}

/*
 * Run argv[] as a child process, waiting for it.  Returns the child exit
 * status (0 == success).  argv[0] is searched on PATH via execvp so plain
 * "cc"/"ld" and absolute cross-tool paths both work.
 */
static int
run(argv)
char *argv[];
{
	pid_t pid;
	int status;

	if (debug) {
		char **p;
		fprintf(stderr, "+");
		for (p = argv; *p != NULL; p++)
			fprintf(stderr, " %s", *p);
		fprintf(stderr, "\n");
	}

	pid = fork();
	if (pid == 0) {
		execvp(argv[0], argv);
		fprintf(stderr, "cannot exec %s: %s\n", argv[0], strerror(errno));
		_exit(127);
	} else if (pid < 0) {
		sprintf(errbuf, "cannot fork %s: %s\n", argv[0], strerror(errno));
		fatal();
	}

	if (waitpid(pid, &status, 0) != pid)
		return (-1);
	if (WIFEXITED(status))
		return (WEXITSTATUS(status));
	return (-1);
}

/*
 * Compile one source file in the configured kernel environment, writing the
 * object beside it (foo.c -> foo.o).  Mirrors the historical cpp defines so
 * the generated glue and per-driver space.c/stubs.c see the same kernel view.
 */
static void
compile(src, obj)
char *src, *obj;
{
	char *argv[64 + MAXDEF + MAXINC + MAXXTRA];
	char incbuf[PATH_MAX];
	int n = 0, i;

	argv[n++] = cc;
	argv[n++] = "-c";
	argv[n++] = "-DiAPX386";
	argv[n++] = "-DAT386";
	argv[n++] = "-DSYSV";
	argv[n++] = "-D_KERNEL";
	argv[n++] = "-DINKERNEL";
#ifdef VPIX
	argv[n++] = "-DVPIX";
#endif
#ifdef WEITEK
	argv[n++] = "-DWEITEK";
#endif
	for (i = 0; i < npredef; i++)
		argv[n++] = predef[i];

	/* extra cc flags: codegen ABI (-m32 ...) passed via -Y */
	for (i = 0; i < nxtra; i++)
		argv[n++] = xtracc[i];

	/* the output dir holds config.h and the generated glue */
	sprintf(incbuf, "-I%s", output);
	argv[n++] = xstrdup(incbuf);

	/* caller-supplied include dirs (kernel headers); on-target the historical
	 * <root>/usr/include is added automatically below. */
	for (i = 0; i < ninc; i++) {
		sprintf(incbuf, "-I%s", incdir[i]);
		argv[n++] = xstrdup(incbuf);
	}
	if (ninc == 0) {
		sprintf(incbuf, "-I%s/usr/include", rflag ? root : "");
		argv[n++] = xstrdup(incbuf);
	}

	argv[n++] = src;
	argv[n++] = "-o";
	argv[n++] = obj;
	argv[n] = NULL;

	if (run(argv) != 0) {
		sprintf(errbuf, BADCOMP, src);
		fatal();
	}
}

static void
addobj(path)
char *path;
{
	if (nobj >= MAXOBJ) {
		strcpy(errbuf, "too many objects on kernel link line\n");
		fatal();
	}
	objs[nobj++] = xstrdup(path);
}

/*
 * Gather one pack.d directory's objects.  "core" directories (kernel, pic)
 * contribute their prelinked blobs and special objects; module directories
 * contribute Driver.o/stubs.o plus an optional space.o.  start.o and locore.o
 * are intentionally left out -- the vuifile linker script pulls them in.
 */
static void
gather_dir(dir)
char *dir;
{
	char path[PATH_MAX];
	static char *names[] = { "syms.o", "kernel.o", "Driver.o", NULL };
	int i;

	/* prelinked core blob / special objects, in link order */
	for (i = 0; names[i] != NULL; i++) {
		sprintf(path, "%s/%s", dir, names[i]);
		if (exists(path))
			addobj(path);
	}

	/* compile space.c -> space.o if present */
	sprintf(path, "%s/space.c", dir);
	if (exists(path)) {
		char obj[PATH_MAX];
		sprintf(obj, "%s/space.o", dir);
		compile(path, obj);
		addobj(obj);
	}

	/* if no Driver.o, a configured-out package may carry stubs.c */
	sprintf(path, "%s/Driver.o", dir);
	if (!exists(path)) {
		sprintf(path, "%s/stubs.c", dir);
		if (exists(path)) {
			char obj[PATH_MAX];
			sprintf(obj, "%s/stubs.o", dir);
			compile(path, obj);
			addobj(obj);
		}
	}
}

/*
 * Read the idconfig-produced "direct" file (a list of absolute pack.d
 * paths to Driver.o / stubs.c / space.c).  Compile any .c entries and add the
 * resulting object to the link list.
 */
static void
read_direct()
{
	char directp[PATH_MAX];
	char line[PATH_MAX];
	FILE *fp;

	sprintf(directp, "%s/direct", input);
	fp = fopen(directp, "r");
	if (fp == NULL) {
		sprintf(errbuf, FOPENF, directp, "r");
		fatal();
	}

	while (fgets(line, sizeof(line), fp) != NULL) {
		char *nl = strchr(line, '\n');
		size_t len;
		if (nl)
			*nl = '\0';
		/* trim trailing whitespace */
		len = strlen(line);
		while (len > 0 && (line[len - 1] == ' ' || line[len - 1] == '\t'))
			line[--len] = '\0';
		if (len == 0)
			continue;

		if (len > 2 && strcmp(line + len - 2, ".c") == 0) {
			char obj[PATH_MAX];
			strcpy(obj, line);
			strcpy(obj + len - 1, "o");	/* .c -> .o */
			compile(line, obj);
			addobj(obj);
		} else {
			addobj(line);
		}
	}
	fclose(fp);
}

/* compile the idconfig-generated glue in the output directory */
static void
compout()
{
	static char *glue[] = { "conf", "fsconf", "vector", NULL };
	int i;

	for (i = 0; glue[i] != NULL; i++) {
		char src[PATH_MAX], obj[PATH_MAX];
		sprintf(src, "%s/%s.c", output, glue[i]);
		sprintf(obj, "%s/%s.o", output, glue[i]);
		if (!exists(src)) {
			sprintf(errbuf, FOPENF, src, "r");
			fatal();
		}
		compile(src, obj);
	}
}

/* link-edit the gathered objects + glue into "unix" */
static void
linkedit()
{
	char *argv[MAXOBJ + 32];
	char unixp[PATH_MAX], vuifile[PATH_MAX];
	char confo[PATH_MAX], fsconfo[PATH_MAX], vectoro[PATH_MAX];
	int n = 0, i;

	sprintf(unixp, "%s/unix", output);
	sprintf(vuifile, "%s/vuifile", input);
	sprintf(confo, "%s/conf.o", output);
	sprintf(fsconfo, "%s/fsconf.o", output);
	sprintf(vectoro, "%s/vector.o", output);

	argv[n++] = ld;
	argv[n++] = "-m";
	argv[n++] = "elf_i386";
	argv[n++] = "-dn";
	argv[n++] = "-o";
	argv[n++] = unixp;
	argv[n++] = "-e";
	argv[n++] = "_start";
	argv[n++] = "-T";
	argv[n++] = vuifile;
	for (i = 0; i < nobj; i++)
		argv[n++] = objs[i];
	argv[n++] = confo;
	argv[n++] = fsconfo;
	argv[n++] = vectoro;
	argv[n] = NULL;

	if (run(argv) != 0) {
		strcpy(errbuf, LINKF);
		fatal();
	}
}

/* build "<confdir>/<sub>" honoring -r root, into buf */
static void
under_conf(buf, sub)
char *buf, *sub;
{
	if (sub == NULL || *sub == '\0')
		strcpy(buf, confdir);
	else
		sprintf(buf, "%s/%s", confdir, sub);
}

int
main(argc, argv)
int argc;
char *argv[];
{
	int m;

	while ((m = getopt(argc, argv, "?#i:o:p:c:l:r:D:U:I:Y:")) != EOF) {
		switch (m) {
		case '#':
			debug++;
			break;
		case 'I':
			if (ninc < MAXINC)
				incdir[ninc++] = optarg;
			break;
		case 'Y': {
			/* -Y may carry several space-separated cc flags at once,
			 * so the YAML can pass the whole codegen flag list in one go. */
			char *tok = strtok(optarg, " \t");
			while (tok != NULL && nxtra < MAXXTRA) {
				xtracc[nxtra++] = tok;
				tok = strtok(NULL, " \t");
			}
			break;
		}
		case 'i':
			strcpy(input, optarg);
			iflag++;
			break;
		case 'o':
			strcpy(output, optarg);
			oflag++;
			break;
		case 'p':
			strcpy(packdir, optarg);
			pflag++;
			break;
		case 'c':
			cc = optarg;
			break;
		case 'l':
			ld = optarg;
			break;
		case 'r':
			strcpy(root, optarg);
			rflag++;
			break;
		case 'D':
		case 'U':
			if (npredef < MAXDEF) {
				char buf[PATH_MAX];
				sprintf(buf, "-%c%s", m, optarg);
				predef[npredef++] = xstrdup(buf);
			} else
				fprintf(stderr,
				    "too many -D/-U; '%s' ignored\n", optarg);
			break;
		case '?':
		default:
			fprintf(stderr, USAGE);
			exit(1);
		}
	}

	/* <root>/etc/conf, normalizing a trailing slash on root */
	if (rflag && strcmp(root, "/") != 0) {
		size_t rl = strlen(root);
		if (rl > 0 && root[rl - 1] == '/')
			root[rl - 1] = '\0';
		sprintf(confdir, "%s/etc/conf", root);
	} else {
		strcpy(confdir, "/etc/conf");
	}

	if (!iflag)
		under_conf(input, "cf.d");
	if (!oflag)
		strcpy(output, input);

	/*
	 * Locate pack.d.  Precedence: explicit -p; else, when an input dir was
	 * given (the YAML build points us at an arbitrary build-tree cf.d), it
	 * is the sibling <input>/../pack.d; otherwise the on-target
	 * <root>/etc/conf/pack.d.
	 */
	if (!pflag) {
		if (iflag)
			sprintf(packdir, "%s/../pack.d", input);
		else
			sprintf(packdir, "%s/pack.d", confdir);
	}

	if (!exists(input)) {
		sprintf(errbuf, EXISTF, input);
		fatal();
	}
	if (!exists(output)) {
		sprintf(errbuf, EXISTF, output);
		fatal();
	}

	/* core packages always link in, even though they are not in mdevice */
	{
		char kerneld[PATH_MAX], picd[PATH_MAX];
		sprintf(kerneld, "%s/kernel", packdir);
		sprintf(picd, "%s/pic", packdir);
		gather_dir(kerneld);
		if (exists(picd))
			gather_dir(picd);
	}

	/* configured driver/fs packages from the idconfig "direct" file */
	read_direct();

	/* compile the generated glue, then link */
	compout();
	linkedit();

	if (debug)
		fprintf(stderr, "idmkunix: wrote %s/unix\n", output);
	return (0);
}
