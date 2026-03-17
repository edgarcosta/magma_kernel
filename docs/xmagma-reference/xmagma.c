#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <stdint.h>
#include <signal.h>
#include <errno.h>

// Pipe endpoints
#define	READ_END	0
#define	WRITE_END	1

typedef	uint32_t	boolean;

#define	FALSE		((boolean)0)
#define	TRUE		((boolean)1)

#define	MAGMA_BUF_SIZE	4096

typedef enum
{
    XTAG_OUTPUT,
    XTAG_READY,
    XTAG_INPUT_RECEIVED,
    XTAG_RUN,
    XTAG_QUIT,
    XTAG_TRACEBACK,
    XTAG_ERROR_POSITION,	// lies, all lies
    XTAG_ERROR_RUNTIME,
    XTAG_ERROR_PARSE,
    XTAG_HISTORY_POS,
    XTAG_ERROR_USER,
    XTAG_ERROR_INTERNAL,
    XTAG_LIST_OUTPUT,
    XTAG_SIGNATURE,
    XTAG_INTERRUPT,
    XTAG_RESET,
    XTAG_ERROR_AT_END,
    XTAG_DEBUG_READY,
    XTAG_DEBUG_TRACEBACK,
    XTAG_DEBUG_ERROR,
    XTAG_READ_PROMPT,
    XTAG_READ_INPUT,
    XTAG_READI_PROMPT,
    XTAG_READI_INPUT,
    XTAG_READI_ERROR,
    XTAG_NUM_TAGS
} e_xtag;

typedef enum
{
    XTAG_KIND_OUTPUT,
    XTAG_KIND_STATUS,
    XTAG_KIND_ARGS
} e_xtag_kind;

typedef struct
{
    e_xtag	tag;
    char	*name;
    e_xtag_kind	kind;
    int		nargs;
} s_tag_info;

s_tag_info xtag_info[XTAG_NUM_TAGS] =
{
    { XTAG_OUTPUT,		"OUT",		XTAG_KIND_OUTPUT,	0 },
    { XTAG_READY,		"RDY",		XTAG_KIND_ARGS,		5 },
    { XTAG_INPUT_RECEIVED,	"IR",		XTAG_KIND_STATUS,	0 },
    { XTAG_RUN,			"RUN",		XTAG_KIND_ARGS,		6 },
    { XTAG_QUIT,		"QUIT",		XTAG_KIND_STATUS,	0 },
    { XTAG_TRACEBACK,		"TB",		XTAG_KIND_OUTPUT,	0 },
    { XTAG_ERROR_POSITION,	"EPO",		XTAG_KIND_OUTPUT,	0 },
    { XTAG_ERROR_RUNTIME,	"ER",		XTAG_KIND_OUTPUT,	0 },
    { XTAG_ERROR_PARSE,		"ERP",		XTAG_KIND_ARGS,		4 },
    { XTAG_HISTORY_POS,		"POS",		XTAG_KIND_ARGS,		2 },
    { XTAG_ERROR_USER,		"EU",		XTAG_KIND_OUTPUT,	0 },
    { XTAG_ERROR_INTERNAL,	"EI",		XTAG_KIND_OUTPUT,	0 },
    { XTAG_LIST_OUTPUT,		"LST",		XTAG_KIND_OUTPUT,	0 },
    { XTAG_SIGNATURE,		"SIG",		XTAG_KIND_OUTPUT,	0 },
    { XTAG_INTERRUPT,		"INT",		XTAG_KIND_STATUS,	0 },
    { XTAG_RESET,		"RES",		XTAG_KIND_STATUS,	0 },
    { XTAG_DEBUG_READY,		"DRDY",		XTAG_KIND_STATUS,	0 },
    { XTAG_DEBUG_TRACEBACK,	"DTB",		XTAG_KIND_OUTPUT,	0 },
    { XTAG_DEBUG_ERROR,		"DE",		XTAG_KIND_OUTPUT,	0 },
    { XTAG_ERROR_AT_END,	"ENE",		XTAG_KIND_STATUS,	0 },
    { XTAG_READ_PROMPT,		"RD_PR",	XTAG_KIND_OUTPUT,	0 },
    { XTAG_READ_INPUT,		"RD_IN",	XTAG_KIND_STATUS,	0 },
    { XTAG_READI_PROMPT,	"RDI_PR",	XTAG_KIND_OUTPUT,	0 },
    { XTAG_READI_INPUT,		"RDI_IN",	XTAG_KIND_STATUS,	0 },
    { XTAG_READI_ERROR,		"RDI_ER",	XTAG_KIND_OUTPUT,	0 },
};

#define	XTAG_MAX_ARGS	6

#define	CHAR_CAST(n)		((char)(unsigned char)(unsigned int)(n))
#define	XMAGMA_TAG_BYTE		CHAR_CAST(129)
#define	XMAGMA_EOF_BYTE		CHAR_CAST(4)
#define	XMAGMA_CONT_BYTE	CHAR_CAST('C')

typedef struct
{
    pid_t	pid;
    int		to_child,
    		from_child;

    boolean	fc_eof,		// got EOF while reading from child
    		fc_error;	// got error while reading from child
    int		fc_errno;	// saved errno value from read

    char	fc_buf[MAGMA_BUF_SIZE];	// buffer for data read from the child
    uint32_t	fc_start,	// index of next unprocessed byte in fc_buf
    		fc_end;		// index just past last stored byte in fc_buf

    char	*fc_line;	// current line data read from child
    uint32_t	fc_line_nalloc,	// number of bytes alloced for line
    		fc_line_len;	// actual bytes currently used by line

    e_xtag	fc_tag;
    boolean	fc_tag_continuation;
    int		fc_tag_indent;
    uint32_t	fc_tag_text_start;
    uint64_t	fc_tag_args[XTAG_MAX_ARGS];

    boolean	ready;		// ready for user input
    boolean	continuable;	// whether continuation lines make sense
    e_xtag	ready_or_run;	// which of ready or run was most recent
    boolean	in_debugger;	// whether the debugger is active
    boolean	read_input;	// whether a read/readi directive is in process

    boolean	fu_eof,		// got EOF while reading from user
    		fu_error;	// got error while reading from user
    int		fu_errno;	// saved errno value from user read

    char	*fu_text;	// input text read from user
    uint32_t	fu_text_nalloc,	// number of bytes alloced for input text
    		fu_text_len;	// actual bytes currently used by input text
} s_magma;

// Unsafe macros
#define	USM_MAGMA_BUF_START(M)		((M)->fc_buf + (M)->fc_start)
#define	USM_MAGMA_BUF_SIZE(M)		((M)->fc_end - (M)->fc_start)

#define	USM_MAGMA_LINE_NAVAIL(M)	((M)->fc_line_nalloc - (M)->fc_line_len)
#define	USM_MAGMA_LINE_END(M)		((M)->fc_line + (M)->fc_line_len)

#define	USM_MAGMA_USER_NAVAIL(M)	((M)->fu_text_nalloc - (M)->fu_text_len)
#define	USM_MAGMA_USER_END(M)		((M)->fu_text + (M)->fu_text_len)

typedef enum
{
    PARSE_SUCCESS,
    PARSE_NO_TAG_MARKER,
    PARSE_NO_TAG,
    PARSE_UNKNOWN_TAG,
    PARSE_BAD_FORMAT,
    PARSE_EXCESS_DATA,
} e_parse_status;

typedef struct
{
    char	*line;
    uint32_t	len,
    		pos;
} s_parse_info;


void perror_exit(char *desc)
{
    perror(desc);
    exit(1);
}

void usage_exit(char *progname)
{
    char	*bname;

    bname = strrchr(progname, '/');
    if (bname == NULL)
	bname = progname;
    else
	bname++;

    fprintf(stderr, "Usage: %s [path-to-magma]\n", bname);
    exit(1);
}


void magma_init(s_magma *magma, pid_t pid, int to_child, int from_child)
{
    magma->pid = pid;
    magma->to_child = to_child;
    magma->from_child = from_child;

    magma->fc_eof = FALSE;
    magma->fc_error = FALSE;
    magma->fc_errno = 0;

    magma->fc_start = 0;
    magma->fc_end = 0;

    magma->fc_line = NULL;
    magma->fc_line_nalloc = 0;
    magma->fc_line_len = 0;

    magma->ready = FALSE;
    magma->continuable = FALSE;
    magma->ready_or_run = XTAG_READY;
    magma->in_debugger = FALSE;
    magma->read_input = FALSE;

    magma->fu_eof = FALSE;
    magma->fu_error = FALSE;
    magma->fu_errno = 0;

    magma->fu_text = NULL;
    magma->fu_text_nalloc = 0;
    magma->fu_text_len = 0;
}


void spawn_magma(char *progname, s_magma *magma)
{
    int		to_child[2],
    		from_child[2],
		exec_test[2];
    pid_t	pid;
    ssize_t	n;
    char	buf[1];

    if (pipe(to_child) < 0)
	perror_exit("pipe");
    if (pipe(from_child) < 0)
	perror_exit("pipe");
    if (pipe(exec_test) < 0)
	perror_exit("pipe");

    pid = fork();
    if (pid < 0)
	perror_exit("fork");

    if (pid == 0)	// child
    {
	char	*argv[3];

	close(to_child[WRITE_END]);
	close(from_child[READ_END]);
	if (dup2(to_child[READ_END], STDIN_FILENO) < 0)
	    perror_exit("dup2");
	if (dup2(from_child[WRITE_END], STDOUT_FILENO) < 0)
	    perror_exit("dup2");
	close(to_child[READ_END]);
	close(from_child[WRITE_END]);

	close(exec_test[READ_END]);
	fcntl(exec_test[WRITE_END], F_SETFD, FD_CLOEXEC);

	argv[0] = progname;
	argv[1] = "-x";
	argv[2] = NULL;

	execvp(progname, argv);
	write(exec_test[WRITE_END], "x", 1);
	perror_exit(progname);
    }

    // parent
    close(to_child[READ_END]);
    close(from_child[WRITE_END]);
    close(exec_test[WRITE_END]);

    n = read(exec_test[READ_END], buf, 1);
    if (n < 0)
	perror_exit("read");
    if (n > 0)	// child failed to exec, will have printed error
	exit(1);
    close(exec_test[READ_END]);

    magma_init(magma, pid, to_child[WRITE_END], from_child[READ_END]);
}


void append_line_from_magma(s_magma *magma, char *data, uint32_t len)
{
    if (len == 0)
	return;

    if (USM_MAGMA_LINE_NAVAIL(magma) < len)
    {
	uint32_t	new_nalloc;
	char		*p;

	new_nalloc = magma->fc_line_len + len;
	if (new_nalloc < len)	// overflow
	{
	    // Yes, I know I should use PRIu32 here, but it looks so ugly
	    fprintf(stderr, "Output line too long (at least %u + %u bytes)\n",
		    magma->fc_line_len, len);
	    exit(1);
	}

	p = realloc(magma->fc_line, new_nalloc);
	if (p == NULL)
	{
	    fprintf(stderr, "Failed trying to realloc() %u bytes\n",
		new_nalloc);
	    exit(1);
	}

	magma->fc_line = p;
	magma->fc_line_nalloc = new_nalloc;
    }
    memcpy(USM_MAGMA_LINE_END(magma), data, len);
    magma->fc_line_len += len;
}

boolean read_line_from_magma(s_magma *magma)
{
    char	*bufstart, *p;
    uint32_t	bufsize, n;

    magma->fc_line_len = 0;
    for (;;)
    {
	if (magma->fc_start >= magma->fc_end)
	{
	    ssize_t	nread;

	    magma->fc_start = 0;
	    magma->fc_end = 0;
	    if (!(magma->fc_eof || magma->fc_error))
	    {
		nread = read(magma->from_child, magma->fc_buf, MAGMA_BUF_SIZE);
		if (nread < 0)
		{
		    magma->fc_error = TRUE;
		    magma->fc_errno = errno;
		}
		else if (nread == 0)
		{
		    magma->fc_eof = TRUE;
		}
		else
		{
		    magma->fc_end = (uint32_t)(size_t)nread;
		}
	    }

	    if (magma->fc_eof || magma->fc_error)
	    {
		// return partial line if we have one; defer error handling
		// to main loop
		if (magma->fc_line_len > 0)
		    return TRUE;

		return FALSE;
	    }
	}

	bufstart = USM_MAGMA_BUF_START(magma);
	bufsize = USM_MAGMA_BUF_SIZE(magma);
	p = memchr(bufstart, '\n', bufsize);
	if (p != NULL)
	{
	    n = (uint32_t)(p - bufstart);
	    append_line_from_magma(magma, bufstart, n);
	    magma->fc_start += n + 1;		// skip the newline
	    return TRUE;
	}

	append_line_from_magma(magma, bufstart, bufsize);
	magma->fc_start = 0;
	magma->fc_end = 0;
    }
    /* NOTREACHED */
}

boolean parse_match_char(s_parse_info *pinfo, char c)
{
    if (pinfo->pos >= pinfo->len)
	return FALSE;
    if (pinfo->line[pinfo->pos] != c)
	return FALSE;
    pinfo->pos++;
    return TRUE;
}

boolean parse_get_tag_name(s_parse_info *pinfo, char **tagp, uint32_t *lenp)
{
    char	*line, *tagptr;
    uint32_t	pos, len, taglen;

    line = pinfo->line;
    len = pinfo->len;
    pos = pinfo->pos;

    tagptr = line + pos;
    while ((pos < len) && (isupper(line[pos]) || line[pos] == '_'))
	pos++;
    taglen = pos - pinfo->pos;
    pinfo->pos = pos;
    if (taglen == 0)
	return FALSE;

    *tagp = tagptr;
    *lenp = taglen;
    return TRUE;
}

boolean parse_get_integer(s_parse_info *pinfo, uint64_t *xp)
{
    char	*line;
    uint32_t	pos, len;
    int64_t	x;

    line = pinfo->line;
    len = pinfo->len;
    pos = pinfo->pos;
    x = 0;
    // I'm ignoring overflow here; yes, it's technically possible
    for (; (pos < len) && isdigit(line[pos]); pos++)
	x = 10*x + (uint64_t)(line[pos] - '0');

    if (pos == pinfo->pos)	// no digit bytes
	return FALSE;
    pinfo->pos = pos;

    *xp = x;
    return TRUE;
}

boolean parse_complete(s_parse_info *pinfo)
{
    return (pinfo->pos == pinfo->len);
}

e_parse_status parse_magma_line(s_magma *magma)
{
    s_parse_info	pinfo;
    char		*tagptr;
    uint32_t		i, taglen;
    s_tag_info		*taginfo;
    uint64_t		ilevel;

    pinfo.line = magma->fc_line;
    pinfo.len = magma->fc_line_len;
    pinfo.pos = 0;

    if (!parse_match_char(&pinfo, XMAGMA_TAG_BYTE))
	return PARSE_NO_TAG_MARKER;

    if (!parse_get_tag_name(&pinfo, &tagptr, &taglen))
	return PARSE_NO_TAG;

    for (i = 0; i < XTAG_NUM_TAGS; i++)
	if (!strncmp(xtag_info[i].name, tagptr, taglen))
	    break;
    if (i == XTAG_NUM_TAGS)
	return PARSE_UNKNOWN_TAG;
    taginfo = &(xtag_info[i]);

    magma->fc_tag = taginfo->tag;
    switch (taginfo->kind)
    {
    case XTAG_KIND_OUTPUT:
	if (!parse_match_char(&pinfo, ' '))
	    return PARSE_BAD_FORMAT;
	magma->fc_tag_continuation = FALSE;
	magma->fc_tag_indent = 0;
	if (parse_match_char(&pinfo, XMAGMA_CONT_BYTE))
	    magma->fc_tag_continuation = TRUE;
	else if (parse_get_integer(&pinfo, &ilevel))
	    magma->fc_tag_indent = (int)ilevel;
	else
	    return PARSE_BAD_FORMAT;
	if (!parse_match_char(&pinfo, XMAGMA_TAG_BYTE))
	    return PARSE_BAD_FORMAT;
	magma->fc_tag_text_start = pinfo.pos;
	break;

    case XTAG_KIND_STATUS:
	if (!parse_complete(&pinfo))
	    return PARSE_EXCESS_DATA;
	break;

    case XTAG_KIND_ARGS:
	for (i = 0; i < taginfo->nargs; i++)
	{
	    if (!parse_match_char(&pinfo, ' '))
		return PARSE_BAD_FORMAT;
	    if (!parse_get_integer(&pinfo, &(magma->fc_tag_args[i])))
		return PARSE_BAD_FORMAT;
	}
	if (!parse_complete(&pinfo))
	    return PARSE_EXCESS_DATA;
	break;
    }

    return PARSE_SUCCESS;
}

void print_parse_error(s_magma *magma, e_parse_status status)
{
    switch (status)
    {
    case PARSE_SUCCESS:
	return;

    case PARSE_NO_TAG_MARKER:
	fprintf(stderr, "Parse error: No tag marker.  Possibly output from subprocess?\n", status);
	break;

    case PARSE_NO_TAG:
	fprintf(stderr, "Parse error: No tag found.\n");
	break;

    case PARSE_UNKNOWN_TAG:
	fprintf(stderr, "Parse error: Unknown/unhandled tag value.\n");
	break;

    case PARSE_BAD_FORMAT:
	fprintf(stderr, "Parse error: Bad format.\n");
	break;

    case PARSE_EXCESS_DATA:
	fprintf(stderr, "Parse error: Extra data after tag fields.\n");
	break;

    default:
	fprintf(stderr, "[unknown parse error code %d]:\n", status);
	break;
    }
    fprintf(stderr, "%.*s\n", magma->fc_line_len, magma->fc_line);
}

void process_output_tag(s_magma *magma)
{
    int		i;
    uint32_t	start;

    if (magma->continuable && !magma->fc_tag_continuation)
	printf("\n");
    for (i = 0; i < magma->fc_tag_indent; i++)
	printf("    ");
    start = magma->fc_tag_text_start;
    printf("%.*s", magma->fc_line_len - start, magma->fc_line + start);
    magma->continuable = TRUE;
}

void process_line(s_magma *magma)
{
    int		i;
    uint32_t	start, end;

    switch (magma->fc_tag)
    {
    case XTAG_TRACEBACK:
	// hacky attempt to fix the indent level, which is lost in tracebacks
	start = magma->fc_tag_text_start;
	end = magma->fc_line_len;
	if ((magma->fc_tag_indent == 0)
	&& (end > start)
	&& (magma->fc_line[start] != ')')
	&& (magma->fc_line[end - 1] != '(')
	)
	    magma->fc_tag_indent = 1;
	// fall through
    case XTAG_OUTPUT:
    case XTAG_ERROR_POSITION:
    case XTAG_ERROR_RUNTIME:
    case XTAG_ERROR_USER:
    case XTAG_ERROR_INTERNAL:
    case XTAG_LIST_OUTPUT:
    case XTAG_SIGNATURE:
    case XTAG_DEBUG_TRACEBACK:
    case XTAG_DEBUG_ERROR:
    case XTAG_READ_PROMPT:
    case XTAG_READI_PROMPT:
	process_output_tag(magma);
	break;

    case XTAG_READY:
	magma->ready = TRUE;
	magma->ready_or_run = XTAG_READY;
	magma->in_debugger = FALSE;
	break;

    case XTAG_INPUT_RECEIVED:
    case XTAG_RESET:
	break;

    case XTAG_RUN:
	magma->ready_or_run = XTAG_RUN;
	break;

    case XTAG_QUIT:
	// slight hack, but it's conceptually the same thing
	magma->fc_eof = TRUE;
	break;

    case XTAG_ERROR_PARSE:
	// do nothing for now.  TODO: Store the positions and use them
	// in the actual error printing.
	break;

    case XTAG_HISTORY_POS:
	// do nothing for now.  TODO: Store the position and use them
	// in the actual error printing.
	break;

    case XTAG_INTERRUPT:
	if (magma->ready_or_run == XTAG_RUN)
	{
	    if (magma->continuable)
		printf("\n");
	    printf("[interrupted]\n");
	    magma->continuable = FALSE;
	}
	magma->read_input = FALSE;
	magma->in_debugger = FALSE;
	break;

    case XTAG_ERROR_AT_END:
	if (magma->continuable)
	    printf("\n");
	printf("User error: Incomplete or unparseable code at end of input\n");
	magma->continuable = FALSE;
	break;

    case XTAG_DEBUG_READY:
	magma->in_debugger = TRUE;
	magma->ready = TRUE;
	break;

    case XTAG_READI_ERROR:
	process_output_tag(magma);
	// the Magma error message needs a newline after all, alas
	printf("\n");
	// fall through
    case XTAG_READ_INPUT:
    case XTAG_READI_INPUT:
	magma->read_input = TRUE;
	magma->ready = TRUE;
	break;

    default:
	fprintf(stderr, "Unhandled tag type %d\n", magma->fc_tag);
	fprintf(stderr, "%.*s\n", magma->fc_line_len, magma->fc_line);
	break;
    }
}

void print_prompt(s_magma *magma)
{
    if (magma->in_debugger)
	printf("debug> ");
    else
	printf("> ");
    fflush(stdout);
}

void append_text_from_user(s_magma *magma, char *data, uint32_t len)
{
    if (len == 0)
	return;

    if (USM_MAGMA_USER_NAVAIL(magma) < len)
    {
	uint32_t	new_nalloc;
	char		*p;

	new_nalloc = magma->fu_text_len + len;
	if (new_nalloc < len)	// overflow
	{
	    // Yes, I know I should use PRIu32 here, but it looks so ugly
	    fprintf(stderr, "User input too long (at least %u + %u bytes)\n",
		    magma->fu_text_len, len);
	    exit(1);
	}

	p = realloc(magma->fu_text, new_nalloc);
	if (p == NULL)
	{
	    fprintf(stderr, "Failed trying to realloc() %u bytes\n",
		    new_nalloc);
	    exit(1);
	}

	magma->fu_text = p;
	magma->fu_text_nalloc = new_nalloc;
    }
    memcpy(USM_MAGMA_USER_END(magma), data, len);
    magma->fu_text_len += len;
}

void read_text_from_user(s_magma *magma)
{
    boolean	new_line;
    char	buf[MAGMA_BUF_SIZE];
    char	*p;
    uint32_t	nbytes;

    magma->fu_text_len = 0;
    if (magma->fu_eof || magma->fu_error)
	return;

    new_line = TRUE;
    for (;;)
    {
	// don't prompt if we are in a read/readi directive
	if (new_line && !magma->read_input)
	    print_prompt(magma);

	p = fgets(buf, MAGMA_BUF_SIZE, stdin);
	if (p == NULL)
	{
	    if (feof(stdin))
		magma->fu_eof = TRUE;
	    if (ferror(stdin))
	    {
		magma->fu_error = TRUE;
		magma->fu_errno = errno;
	    }
	    return;
	}

	nbytes = (uint32_t)strlen(buf);

	if (magma->in_debugger || magma->read_input)
	{
	    append_text_from_user(magma, buf, nbytes);
	    break;
	}

	// We use a blank line from the user to indicate the end of an
	// input set
	if (new_line && nbytes == 1 && buf[0] == '\n')
	    break;

	new_line = (nbytes > 0 && buf[nbytes-1] == '\n')
		|| (nbytes == 0 && new_line);
	append_text_from_user(magma, buf, nbytes);
    }
}

void write_buffer(int fd, char *buf, uint32_t len)
{
    ssize_t	nwritten;
    uint32_t	n;

    while (len > 0)
    {
	nwritten = write(fd, buf, len);
	if (nwritten < 0)
	    perror_exit("write");
	n = (uint32_t)nwritten;
	buf += n;
	len -= n;
    }
}

void send_user_text_to_child(s_magma *magma)
{
    char	eofbyte;

    eofbyte = XMAGMA_EOF_BYTE;
    write_buffer(magma->to_child, magma->fu_text, magma->fu_text_len);
    if (!magma->in_debugger && !magma->read_input)
	write_buffer(magma->to_child, &eofbyte, 1);
    if (magma->read_input)
	magma->read_input = FALSE;
}

void io_loop(s_magma *magma)
{
    /*
    Simplistic loop: Read from magma until ready (and send to user),
    then read from user until blank line (and send to magma).
    */
    for (;;)
    {
	magma->ready = FALSE;
	magma->continuable = FALSE;
	while (read_line_from_magma(magma))
	{
	    e_parse_status	status;

	    status = parse_magma_line(magma);
	    if (status != PARSE_SUCCESS)
	    {
		print_parse_error(magma, status);
	    }
	    else
	    {
		process_line(magma);
		if (magma->ready)
		    break;
	    }
	}
	// don't print a newline if we have a prompt for user input
	if (magma->continuable && !magma->read_input)
	    printf("\n");

	// Handle any pending read error
	if (magma->fc_error)
	{
	    errno = magma->fc_errno;
	    magma->fc_errno = 0;
	    perror_exit("read");
	}

	// Handle non-error EOF; QUIT sets this as a slight hack
	if (magma->fc_eof)
	    break;


	read_text_from_user(magma);
	if (magma->fu_text_len == 0)
	{
	    if (magma->fu_error)
	    {
		errno = magma->fu_errno;
		magma->fu_errno = 0;
		perror_exit("fgets");
	    }
	    // We don't exit on EOF in order to pick up any trailing
	    // output from magma
	    if (magma->fu_eof)
		close(magma->to_child);
	}
	else
	    send_user_text_to_child(magma);
    }
}

int main(int argc, char *argv[])
{
    char	*progname;
    s_magma	magma;

    if (argc > 2)
	usage_exit(argv[0]);
    progname = "magma";
    if (argc == 2)
	progname = argv[1];

    signal(SIGPIPE, SIG_IGN);
    spawn_magma(progname, &magma);
    io_loop(&magma);

    return 0;
}
