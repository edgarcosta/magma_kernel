import html
import re
import traceback
from urllib.parse import quote

from ipykernel.kernelbase import Kernel

from . import __version__
from .protocol import (
    ExecutionResult,
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

# Regex to strip strings and comments for keyword balancing
_STRING_OR_COMMENT_RE = re.compile(r'"[^"]*"|//[^\n]*')

# Regex to find keywords (whole words only)
_KEYWORD_RE = re.compile(
    r"\b(end\s+for|end\s+if|end\s+while|end\s+function|end\s+procedure|"
    r"end\s+try|end\s+case|until|for|if|while|function|procedure|try|case|repeat)\b",
    re.IGNORECASE,
)


# Parse "Runtime error in 'foo': message" style errors
_ERROR_RE = re.compile(
    r"^((?:Runtime|User|Internal) error[^:\n]*):\s*(.*)",
    re.MULTILINE,
)

_HANDBOOK_BASE = (
    "http://magma.maths.usyd.edu.au/magma/handbook/search?"
    "chapters=1&examples=1&intrinsics=1&query="
)


def _extract_token(code, cursor_pos):
    """Extract the token at cursor_pos for completion/inspection."""
    token = code[:cursor_pos]
    for sep in ["\n", ";", " ", "(", ",", ":"]:
        token = token.rpartition(sep)[-1]
    return token


class MagmaKernel(Kernel):
    implementation = "magma_kernel"
    implementation_version = __version__

    language_info = {
        "name": "magma",
        "codemirror_mode": "pascal",
        "mimetype": "text/x-pascal",
        "file_extension": ".m",
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
        self.process = MagmaProcess(logger=self.log)
        banner_text = self.process.start()

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
        """Send code to Magma and return (stdout, stderr) strings."""
        out, err = [], []
        self.process.send_input(code)
        self.process.process_until_ready(MagmaCallbacks(
            on_stdout=lambda s: out.append(s),
            on_stderr=lambda s: err.append(s),
        ))
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
            entries = self._history[(start or 0):(stop or len(self._history))]
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
        stripped = _STRING_OR_COMMENT_RE.sub("", code)
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

    def _execute_code(self, code, silent, allow_stdin):
        """Execute Magma code and return a Jupyter reply dict."""
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
                return ""

        callbacks = MagmaCallbacks(
            on_stdout=on_stdout,
            on_stderr=on_stderr,
            on_input_request=on_input_request,
        )

        try:
            self.process.send_input(code)
            result = self.process.process_until_ready(callbacks)
        except KeyboardInterrupt:
            self.process.interrupt()
            result = self.process.process_until_ready(callbacks)

        # Auto-exit debugger, preserving the error state
        if result.state == MagmaState.DEBUGGER:
            had_error = result.had_error
            self.process.send_line("q")
            result = self.process.process_until_ready(callbacks)
            result.had_error = result.had_error or had_error

        if result.state == MagmaState.DEAD:
            on_stderr("Magma process died unexpectedly. Will restart on next execution.\n")

        if result.interrupted:
            return {"status": "abort", "execution_count": self.execution_count}

        if result.had_error:
            stderr_text = "".join(stderr_parts)
            m = _ERROR_RE.search(stderr_text)
            ename = m.group(1) if m else "MagmaError"
            evalue = m.group(2) if m else ""
            return {
                "status": "error",
                "execution_count": self.execution_count,
                "ename": ename,
                "evalue": evalue,
                "traceback": [stderr_text] if stderr_text.strip() else [],
            }

        return {
            "status": "ok",
            "execution_count": self.execution_count,
            "payload": [],
            "user_expressions": {},
        }

    def do_execute(
        self, code, silent, store_history=True, user_expressions=None, allow_stdin=False
    ):
        code = code.rstrip()

        if not code.lstrip():
            return {
                "status": "ok",
                "execution_count": self.execution_count,
                "payload": [],
                "user_expressions": {},
            }

        # Record history
        if store_history and code.strip():
            self._history_count += 1
            self._history.append((0, self._history_count, code))

        if code.lstrip().startswith("?"):
            self._do_help(code.lstrip()[1:])
            return {
                "status": "ok",
                "execution_count": self.execution_count,
                "payload": [],
                "user_expressions": {},
            }

        if not code.endswith(";"):
            code += ";"

        return self._execute_code(code, silent, allow_stdin)

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
        self.process.process_until_ready(cb)

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
