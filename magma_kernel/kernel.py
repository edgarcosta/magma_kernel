from ipykernel.kernelbase import Kernel
from pexpect import EOF, TIMEOUT, spawn
from tempfile import NamedTemporaryFile

from os import path, fpathconf
import re
import signal
import traceback

from codecs import open


def readfile(filename):
    with open(filename, encoding="utf-8") as f:
        return f.read()


__version__ = readfile(path.join(path.dirname(__file__), "VERSION"))
version_pat = re.compile(r"version (\d+(\.\d+)+)")


class MagmaKernel(Kernel):
    implementation = "magma_kernel"
    implementation_version = __version__
    _prompt = "$PEXPECT_PROMPT$"

    language_info = {
        "name": "magma",
        "codemirror_mode": "magma",
        "mimetype": "text/x-magma",
        "file_extension": ".m",
    }

    def __init__(self, **kwargs):
        Kernel.__init__(self, **kwargs)
        # sets child, banner, language_info, language_version
        self._start_magma()

    def _start_magma(self):
        # Signal handlers are inherited by forked processes, and we can't easily
        # reset it from the subprocess. Since kernelapp ignores SIGINT except in
        # message handlers, we need to temporarily reset the SIGINT handler here
        # so that bash and its children are interruptible.
        sig = signal.signal(signal.SIGINT, signal.SIG_DFL)
        try:
            magma = spawn(
                "magma",
                echo=False,
                encoding="utf-8",
                maxread=4194304,
                ignore_sighup=True,
            )
            magma.expect_exact("> ")
            banner = magma.before
            magma.sendline("SetColumns(0);")
            magma.expect_exact("> ")
            magma.sendline("SetAutoColumns(false);")
            magma.expect_exact("> ")
            magma.sendline("SetLineEditor(false);")
            magma.expect_exact("> ")
            magma.sendline(f'SetPrompt("{self._prompt}");')
            magma.expect_exact(self._prompt)
            self.child = magma
        finally:
            signal.signal(signal.SIGINT, sig)
        lang_version = re.search(r"Magma V(\d*.\d*-\d*)", banner).group(1)
        self.banner = "Magma kernel connected to Magma " + lang_version
        self.language_info["version"] = lang_version
        self.language_version = lang_version

    def do_help(self, keyword):
        URL = (
            "http://magma.maths.usyd.edu.au/magma/handbook/search?chapters=1&examples=1&intrinsics=1&query="
            + keyword
        )
        content = {
            "data": {
                "text/html": '<a href="{}" target="magma_help">Magma help on {}</a>'.format(
                    URL, keyword
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

        if code[0] == "?":
            self.do_help(code[1:])
            return {
                "status": "ok",
                "execution_count": self.execution_count,
                "payload": [],
                "user_expressions": {},
            }

        # add a semicolon if doesn't end with a semicolon
        if not code.endswith(";"):
            code += ";"

        interrupted = False
        read_characters = 0  # initializing read_characters before try block
        append_to_output = ""
        try:
            max_input_line_size = int(fpathconf(0, "PC_MAX_CANON")) - 10
        except OSError:
            # if we can't compute the system limits take something low
            max_input_line_size = 128
        try:
            #TODO: maybe don't splitlines and just use file if too long
            for line in code.splitlines():
                # working around buffer sizes
                tmpfile = None
                if len(line) > max_input_line_size:
                    # send the line via a temporary file
                    tmpfile = NamedTemporaryFile("w")
                    tmpfile.write(line)
                    self.child.sendline(f'load "{tmpfile.name}";')
                    # consume Loading message
                    s = self.child.readline()
                    # the newline character is not standard to check equality
                    assert s.startswith(
                        f'Loading "{tmpfile.name}"'
                    ), "Consumed the wrong line: " + repr(s)
                else:
                    self.child.sendline(line)
                # Use short timeout to update output whenever something is received
                initial_counter = counter = 10
                initial_timeout = timeout = 0.5
                read_characters = 0
                while True:
                    v = self.child.expect_exact(
                        [self._prompt, TIMEOUT], timeout=timeout
                    )
                    if not silent and len(self.child.before) > read_characters:
                        # something in output
                        self.send_response(
                            self.iopub_socket,
                            "stream",
                            {
                                "name": "stdout",
                                "text": self.child.before[read_characters:],
                            },
                        )
                        read_characters = len(self.child.before)
                        counter = initial_counter
                        timeout = initial_timeout
                    if v == 0:
                        # finished processing the line
                        # ready to send newline
                        break
                    counter -= 1
                    # increase timeout after default_counter attempts of processing line
                    if counter <= 0:
                        timeout = min(30, 2 * timeout)
                        counter = initial_counter

        except KeyboardInterrupt:
            self.child.sendintr()
            interrupted = True
            self.child.expect_exact(self._prompt)
        except EOF:
            append_to_output = "Restarting Magma"
            self._start_magma()

        if not silent:
            # Send standard output
            self.send_response(
                self.iopub_socket,
                "stream",
                {
                    "name": "stdout",
                    "text": self.child.before[read_characters:] + append_to_output,
                },
            )

        if interrupted:
            return {"status": "abort", "execution_count": self.execution_count}

        return {
            "status": "ok",
            "execution_count": self.execution_count,
            "payload": [],
            "user_expressions": {},
        }

    def do_complete(self, code, cursor_pos):
        begin, end = code[:cursor_pos], code[cursor_pos:]
        default = {
            "matches": [],
            "cursor_start": 0,
            "cursor_end": cursor_pos,
            "metadata": dict(),
            "status": "ok",
        }
        # optimizing to not send everything
        for sep in ["\n", ";", " "]:  # we just need the last chunk
            begin = begin.rpartition(sep)[-1]
            end = end.partition(sep)[0]
        token = begin + end
        if not token:
            return default
        token_escaped = token.replace('"', r"\"")
        self.child.sendline(f'Completion("{token_escaped}", {len(begin)});')
        self.child.expect_exact(self._prompt)
        if self.child.before == "DIE\n":
            return default
        matches = self.child.before.splitlines()
        try:
            # how many matches
            matches_len = int(matches[0])
            if matches_len == 0:
                return default
            # where Magma decided that the completion starts
            cursor_start = cursor_pos - len(begin) + int(matches[1])
            # where can place our cursor
            cursor_end = cursor_pos - len(begin) + int(matches[2])
            matches = matches[3:]
            assert matches_len == len(matches)
        except Exception:
            self.log.error("Failed to complete: \n" + traceback.format_exc())
            return default

        return {
            "matches": matches,
            "cursor_start": cursor_start,
            "cursor_end": cursor_end,
            "metadata": dict(),
            "status": "ok",
        }
