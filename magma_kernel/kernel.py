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


class MagmaKernel(Kernel):
    implementation = "magma_kernel"
    implementation_version = __version__

    language_info = {
        "name": "magma",
        "codemirror_mode": "pascal",
        "mimetype": "text/x-pascal",
        "file_extension": ".m",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
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

    def do_shutdown(self, restart):
        self.process.stop(force=True)
        if restart:
            self._start_magma()
        return {"status": "ok", "restart": restart}

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
        URL = (
            "http://magma.maths.usyd.edu.au/magma/handbook/search?"
            "chapters=1&examples=1&intrinsics=1&query=" + url_keyword
        )
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

        if code.lstrip().startswith("?"):
            self._do_help(code.lstrip()[1:])
            return {
                "status": "ok",
                "execution_count": self.execution_count,
                "payload": [],
                "user_expressions": {},
            }

        # Auto-restart if dead
        if not self.process.alive:
            self.send_response(
                self.iopub_socket, "stream",
                {"name": "stderr", "text": "Magma process died. Restarting...\n"},
            )
            self._start_magma()

        # Auto-append semicolon
        if not code.endswith(";"):
            code += ";"

        def on_stdout(text):
            if not silent:
                self.send_response(
                    self.iopub_socket, "stream",
                    {"name": "stdout", "text": text},
                )

        def on_stderr(text):
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
            # Continue reading until RDY
            result = self.process.process_until_ready(callbacks)

        # Auto-exit debugger, preserving the error state from the execution
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
            return {
                "status": "error",
                "execution_count": self.execution_count,
                "ename": "MagmaError",
                "evalue": "",
                "traceback": [],
            }

        return {
            "status": "ok",
            "execution_count": self.execution_count,
            "payload": [],
            "user_expressions": {},
        }

    def do_complete(self, code, cursor_pos):
        default = {
            "matches": [],
            "cursor_start": 0,
            "cursor_end": cursor_pos,
            "metadata": {},
            "status": "ok",
        }
        token = code[:cursor_pos]
        for sep in ["\n", ";", " ", "("]:
            token = token.rpartition(sep)[-1]
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
