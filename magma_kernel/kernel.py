import html
import os
import re
import traceback
from urllib.parse import quote

from ipykernel.kernelbase import Kernel

from . import __version__
from .protocol import (
    InputAborted,
    MagmaCallbacks,
    MagmaProcess,
    MagmaState,
)

# Block openers and their closers for do_is_complete
_BLOCK_OPENERS = {"for", "if", "while", "function", "procedure", "try", "case", "repeat"}
_BLOCK_CLOSERS = {
    "for": "end for",
    "if": "end if",
    "while": "end while",
    "function": "end function",
    "procedure": "end procedure",
    "try": "end try",
    "case": "end case",
    "repeat": "until",
}

# Regex to strip strings and comments for keyword balancing.
# Block comments (/* ... */) are handled separately by _strip_block_comments
# because Magma supports nesting and regex cannot handle that.
_STRING_OR_COMMENT_RE = re.compile(r'"[^"]*"|//[^\n]*')

# Regex to find keywords (whole words only)
_KEYWORD_RE = re.compile(
    r"\b(end\s+for|end\s+if|end\s+while|end\s+function|end\s+procedure|"
    r"end\s+try|end\s+case|until|for|if|while|function|procedure|try|case(?!<)|repeat)\b",
    re.IGNORECASE,
)


# Parse "Runtime error in 'foo': message" style errors
_ERROR_RE = re.compile(
    r"^((?:Runtime|User|Internal) error[^:\n]*):\s*(.*)",
    re.MULTILINE,
)

# Line magic pattern: %magic [args]
_LINE_MAGIC_RE = re.compile(r"^%(\w+)\s*(.*)", re.DOTALL)

_HANDBOOK_BASE = (
    "http://magma.maths.usyd.edu.au/magma/handbook/search?"
    "chapters=1&examples=1&intrinsics=1&query="
)


def _strip_block_comments(code):
    """Remove /* ... */ block comments, handling Magma's nesting."""
    result = []
    depth = 0
    i = 0
    while i < len(code):
        if code[i:i+2] == "/*":
            depth += 1
            i += 2
        elif code[i:i+2] == "*/" and depth > 0:
            depth -= 1
            i += 2
        elif depth == 0:
            result.append(code[i])
            i += 1
        else:
            i += 1
    return "".join(result)


def _extract_token(code, cursor_pos):
    """Extract the token at cursor_pos for completion/inspection."""
    token = code[:cursor_pos]
    for sep in ["\n", ";", " ", "(", ","]:
        token = token.rpartition(sep)[-1]
    return token


def _format_error_position(code, erp):
    """Build a caret line showing the error position within the input.

    *erp* is a 4-tuple ``(start_line, start_col, err_line, err_col)``
    from the ERP tag (0-based).  Returns a string with the offending
    source line and a caret pointer, or empty string if positions are
    out of range.
    """
    _, _, err_line, err_col = erp
    lines = code.splitlines()
    if err_line < 0 or err_line >= len(lines):
        return ""
    src_line = lines[err_line]
    caret = " " * err_col + "^"
    return f"  {src_line}\n  {caret}\n"


class MagmaKernel(Kernel):
    implementation = "magma_kernel"
    implementation_version = __version__

    def _ok_reply(self):
        return {
            "status": "ok",
            "execution_count": self.execution_count,
            "payload": [],
            "user_expressions": {},
        }

    language_info = {
        "name": "magma",
        "codemirror_mode": "pascal",
        "mimetype": "text/x-magma",
        "file_extension": ".m",
        "pygments_lexer": "magma",
    }

    help_links = [
        {"text": "Magma Handbook", "url": "http://magma.maths.usyd.edu.au/magma/handbook/"},
        {"text": "Magma Tutorial", "url": "http://magma.maths.usyd.edu.au/magma/pdf/first.pdf"},
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._history = []  # list of (session, line_number, code)
        self._history_count = 0
        self._start_magma()

    def _start_magma(self):
        magma_path = os.environ.get("MAGMA_PATH", "magma")
        self.process = MagmaProcess(magma_path=magma_path, logger=self.log)
        self.process.start()

        # Query version
        output_parts = []
        cb = MagmaCallbacks(on_stdout=lambda s: output_parts.append(s))
        self.process.send_input(
            'Sprintf("%o.%o-%o", a, b, c) where a, b, c := GetVersion();'
        )
        self.process.process_until_ready(cb)
        lang_version = "".join(output_parts).strip()

        self.banner = "Magma kernel connected to Magma " + lang_version
        self.language_info = dict(self.language_info, version=lang_version)
        self.language_version = lang_version

    def _magma_eval(self, code):
        """Send code to Magma and return (stdout, stderr) strings.

        Logs a warning if Magma dies during the call; callers that need
        to react to a crash should check ``self.process.alive`` afterwards.
        """
        out, err = [], []
        self.process.send_input(code)
        result = self.process.process_until_ready(MagmaCallbacks(
            on_stdout=lambda s: out.append(s),
            on_stderr=lambda s: err.append(s),
        ))
        if result.state == MagmaState.DEAD:
            self.log.warning("Magma process died during evaluation of: %s", code)
        return "".join(out), "".join(err)

    def do_shutdown(self, restart):
        self.process.stop(force=True)
        if restart:
            self._start_magma()
        return {"status": "ok", "restart": restart}

    def do_history(self, hist_access_type, output, raw, session=None,
                   start=None, stop=None, n=None, pattern=None, unique=False):
        if hist_access_type == "tail":
            entries = self._history[-(n or 10):]
        elif hist_access_type == "range":
            lo = 0 if start is None else start
            hi = len(self._history) if stop is None else stop
            entries = self._history[lo:hi]
        elif hist_access_type == "search":
            import fnmatch
            entries = [
                e for e in self._history
                if fnmatch.fnmatch(e[2], pattern or "*")
            ]
            if unique:
                seen = set()
                deduped = []
                for e in reversed(entries):
                    if e[2] not in seen:
                        seen.add(e[2])
                        deduped.append(e)
                entries = list(reversed(deduped))
        else:
            entries = []
        return {"status": "ok", "history": entries}

    def do_is_complete(self, code):
        code = code.strip()
        if not code:
            return {"status": "incomplete", "indent": ""}

        if not code.endswith(";"):
            # No trailing semicolon — could be mid-block or incomplete
            return {"status": "incomplete", "indent": "    "}

        # Strip strings and comments, then count block keywords
        stripped = _strip_block_comments(_STRING_OR_COMMENT_RE.sub("", code))
        depth = 0
        for m in _KEYWORD_RE.finditer(stripped):
            kw = re.sub(r"\s+", " ", m.group(1)).lower()
            if kw in _BLOCK_OPENERS:
                depth += 1
            elif kw in _BLOCK_CLOSERS.values():
                depth -= 1

        if depth == 0:
            return {"status": "complete"}
        elif depth > 0:
            return {"status": "incomplete", "indent": "    "}
        else:
            # More closers than openers — odd, let Magma decide
            return {"status": "unknown"}

    def do_inspect(self, code, cursor_pos, detail_level=0, omit_sections=()):
        token = _extract_token(code, cursor_pos)
        if not token or not self.process.alive:
            return {"status": "ok", "found": False, "data": {}, "metadata": {}}

        # Evaluating "Token;" on an intrinsic gives its signatures via SIG tags
        stdout, stderr = self._magma_eval(f'{token};')

        if stderr or not stdout.strip():
            # Not an intrinsic or errored — fall back to handbook link
            url = _HANDBOOK_BASE + quote(token)
            safe = html.escape(token)
            return {
                "status": "ok",
                "found": True,
                "data": {
                    "text/plain": f"Magma: {token} (see handbook)",
                    "text/html": f'<a href="{url}" target="magma_help">'
                                 f'Magma handbook: {safe}</a>',
                },
                "metadata": {},
            }

        return {
            "status": "ok",
            "found": True,
            "data": {"text/plain": stdout.strip()},
            "metadata": {},
        }

    def _do_help(self, keyword):
        url_keyword = quote(keyword)
        safe_keyword = html.escape(keyword)
        URL = _HANDBOOK_BASE + url_keyword
        content = {
            "data": {
                "text/html": '<a href="{}" target="magma_help">Magma help on {}</a>'.format(
                    URL, safe_keyword
                ),
                "text/plain": "Link to {}".format(URL),
            },
            "metadata": {},
        }
        self.send_response(self.iopub_socket, "display_data", content)

    def _handle_magic(self, code, silent, allow_stdin):
        """Try to handle a line magic. Returns a reply dict, or None."""
        m = _LINE_MAGIC_RE.match(code.lstrip())
        if not m:
            return None

        magic = m.group(1).lower()
        args = m.group(2).strip()

        if magic == "time":
            return self._magic_time(args, silent, allow_stdin)
        elif magic == "load":
            return self._magic_load(args, silent, allow_stdin)
        elif magic in ("who", "whos"):
            return self._magic_who(silent)
        elif magic == "reset":
            return self._magic_reset(silent)
        else:
            return None  # unknown magic, treat as Magma code

    def _magic_time(self, code, silent, allow_stdin):
        """Time execution of code."""
        if not code:
            if not silent:
                self.send_response(
                    self.iopub_socket, "stream",
                    {"name": "stderr", "text": "Usage: %time <code>\n"},
                )
            return self._ok_reply()

        if not code.endswith(";"):
            code += ";"

        original_code = code
        prefix = "__t := Cputime(); "
        timed_code = f"{prefix}{code} Cputime(__t);"
        return self._execute_code(
            timed_code, silent, allow_stdin,
            original_code=original_code, _erp_col_offset=len(prefix),
        )

    def _magic_load(self, args, silent, allow_stdin):
        """Load a .m file into the cell."""
        filename = args.strip().strip("'\"")
        if not filename:
            if not silent:
                self.send_response(
                    self.iopub_socket, "stream",
                    {"name": "stderr", "text": "Usage: %load <filename>\n"},
                )
            return self._ok_reply()

        try:
            with open(filename) as f:
                code = f.read()
        except OSError as exc:
            if not silent:
                self.send_response(
                    self.iopub_socket, "stream",
                    {"name": "stderr", "text": f"Cannot read {filename}: {exc}\n"},
                )
            return {
                "status": "error",
                "execution_count": self.execution_count,
                "ename": "FileError",
                "evalue": str(exc),
                "traceback": [],
            }

        return self._execute_code(code, silent, allow_stdin)

    def _magic_who(self, silent):
        """List user-defined identifiers."""
        if not self.process.alive:
            return self._ok_reply()

        stdout, _ = self._magma_eval(
            'S := GetIdentifierNames("assigned_below"); '
            'for s in S do print s; end for;'
        )

        if not silent and stdout.strip():
            self.send_response(
                self.iopub_socket, "stream",
                {"name": "stdout", "text": stdout},
            )

        return self._ok_reply()

    def _magic_reset(self, silent):
        """Restart the Magma process."""
        self.process.stop(force=True)
        self._start_magma()
        if not silent:
            self.send_response(
                self.iopub_socket, "stream",
                {"name": "stderr", "text": "Magma process restarted.\n"},
            )
        return self._ok_reply()

    def _execute_code(self, code, silent, allow_stdin, original_code=None,
                       _erp_col_offset=0):
        """Execute Magma code and return a Jupyter reply dict.

        *original_code* is the user's raw input used for error position
        annotation.  *_erp_col_offset* adjusts ERP column positions on
        the first line (e.g. when code is wrapped with a prefix for
        ``%time``).
        """
        if not self.process.alive:
            self.send_response(
                self.iopub_socket, "stream",
                {"name": "stderr", "text": "Magma process died. Restarting...\n"},
            )
            self._start_magma()

        stderr_parts = []

        def on_stdout(text):
            if not silent:
                self.send_response(
                    self.iopub_socket, "stream",
                    {"name": "stdout", "text": text},
                )

        def on_stderr(text):
            stderr_parts.append(text)
            if not silent:
                self.send_response(
                    self.iopub_socket, "stream",
                    {"name": "stderr", "text": text},
                )

        def on_input_request(prompt):
            if allow_stdin:
                return self.raw_input(prompt)
            else:
                on_stderr(
                    "read/readi directive requires interactive input, "
                    "but this session does not support stdin\n"
                )
                self.process.interrupt()
                raise InputAborted()

        callbacks = MagmaCallbacks(
            on_stdout=on_stdout,
            on_stderr=on_stderr,
            on_input_request=on_input_request,
        )

        try:
            self.process.send_input(code)
        except KeyboardInterrupt:
            # Interrupt arrived during write — input may be incomplete.
            # Kill and restart to avoid a deadlocked pipe.
            self.process.stop(force=True)
            on_stderr("Interrupted during send. Magma process restarted.\n")
            self._start_magma()
            return {"status": "abort", "execution_count": self.execution_count}

        try:
            result = self.process.process_until_ready(callbacks)
        except KeyboardInterrupt:
            self.process.interrupt()
            try:
                result = self.process.process_until_ready(callbacks)
            except KeyboardInterrupt:
                # Second interrupt during recovery — kill and restart
                self.process.stop(force=True)
                on_stderr("Double interrupt. Magma process restarted.\n")
                self._start_magma()
                return {"status": "abort", "execution_count": self.execution_count}

        # Auto-exit debugger, preserving the initial error state.
        # In current Magma under -x, a single "q" always exits the debugger
        # fully and discards buffered input, so the loop body runs once
        # and the wedge-recovery branch is unreachable — both are kept as
        # defensive guards in case that ever changes. Only the mocked
        # tests in test_kernel_unit.py exercise the multi-iteration and
        # wedge paths; do not try to construct a live nested-debugger
        # test, it cannot be triggered.
        if result.state == MagmaState.DEBUGGER:
            saved_had_error = result.had_error
            saved_erp = result.erp
            attempts = 0
            while result.state == MagmaState.DEBUGGER and attempts < 10:
                try:
                    self.process.send_line("q")
                except OSError:
                    break
                result = self.process.process_until_ready(callbacks)
                attempts += 1

            if result.state == MagmaState.DEBUGGER:
                self.process.stop(force=True)
                on_stderr("Magma debugger could not be exited; restarting.\n")
                self._start_magma()
                return {
                    "status": "error",
                    "execution_count": self.execution_count,
                    "ename": "MagmaDebuggerStuck",
                    "evalue": "Could not exit Magma debugger after 10 attempts",
                    "traceback": [],
                }

            result.had_error = result.had_error or saved_had_error
            if saved_erp is not None:
                result.erp = saved_erp

        # Drain stale RDY from interrupt delivered while Magma was idle
        if result.interrupted:
            self.process.drain_stale_responses(self.log)

        if result.state == MagmaState.DEAD:
            on_stderr("Magma process died unexpectedly. Will restart on next execution.\n")
            stderr_text = "".join(stderr_parts)
            return {
                "status": "error",
                "execution_count": self.execution_count,
                "ename": "MagmaCrash",
                "evalue": "Magma process died unexpectedly",
                "traceback": [stderr_text] if stderr_text.strip() else [],
            }

        if result.interrupted:
            return {"status": "abort", "execution_count": self.execution_count}

        if result.had_error:
            stderr_text = "".join(stderr_parts)
            m = _ERROR_RE.search(stderr_text)
            ename = m.group(1) if m else "MagmaError"
            evalue = m.group(2) if m else ""
            tb_lines = [stderr_text] if stderr_text.strip() else []
            # Annotate with error position caret if available
            src = original_code if original_code is not None else code
            if result.erp is not None:
                erp = result.erp
                if _erp_col_offset and len(erp) >= 4:
                    sl, sc, el, ec = erp[:4]
                    if sl == 0:
                        sc = max(0, sc - _erp_col_offset)
                    if el == 0:
                        ec = max(0, ec - _erp_col_offset)
                    erp = (sl, sc, el, ec) + erp[4:]
                pos_text = _format_error_position(src, erp)
                if pos_text:
                    tb_lines.append(pos_text)
            return {
                "status": "error",
                "execution_count": self.execution_count,
                "ename": ename,
                "evalue": evalue,
                "traceback": tb_lines,
            }

        return self._ok_reply()

    def do_execute(
        self, code, silent, store_history=True, user_expressions=None, allow_stdin=False
    ):
        code = code.rstrip()

        if not code.lstrip():
            return self._ok_reply()

        # Record history
        if store_history and code.strip():
            self._history_count += 1
            self._history.append((0, self._history_count, code))

        if code.lstrip().startswith("?"):
            self._do_help(code.lstrip()[1:])
            return self._ok_reply()

        # Try line magic
        magic_result = self._handle_magic(code, silent, allow_stdin)
        if magic_result is not None:
            return magic_result

        original_code = code
        if not code.endswith(";"):
            code += ";"

        return self._execute_code(code, silent, allow_stdin, original_code=original_code)

    def do_complete(self, code, cursor_pos):
        default = {
            "matches": [],
            "cursor_start": 0,
            "cursor_end": cursor_pos,
            "metadata": {},
            "status": "ok",
        }
        token = _extract_token(code, cursor_pos)
        if not token:
            return default
        token_escaped = token.replace("\\", "\\\\").replace('"', '\\"')

        if not self.process.alive:
            return default

        output_parts = []
        cb = MagmaCallbacks(on_stdout=lambda s: output_parts.append(s))
        self.process.send_input(f'Completion("{token_escaped}", {len(token)});')
        result = self.process.process_until_ready(cb)
        if result.state == MagmaState.DEAD:
            self.log.warning("Magma process died during completion")
            return default

        raw_output = "".join(output_parts)
        if raw_output.strip() == "DIE":
            self.log.error(
                'Failed to complete, magma did not like our call: '
                'Completion("%s", %d);', token_escaped, len(token),
            )
            return default

        matches = raw_output.splitlines()
        try:
            matches_len = int(matches[0])
            if matches_len == 0:
                return default
            cursor_start = cursor_pos - len(token) + int(matches[1])
            cursor_end = cursor_pos - len(token) + int(matches[1]) + int(matches[2])
            matches = matches[3:]
            if matches_len != len(matches):
                self.log.warning(
                    "Completion count mismatch: expected %d, got %d",
                    matches_len, len(matches),
                )
                return default
        except Exception:
            self.log.error("Failed to complete:\n%s", traceback.format_exc())
            return default

        return {
            "matches": matches,
            "cursor_start": cursor_start,
            "cursor_end": cursor_end,
            "metadata": {},
            "status": "ok",
        }
