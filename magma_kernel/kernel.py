from ipykernel.kernelbase import Kernel
from pexpect import EOF, TIMEOUT, spawn
from tempfile import NamedTemporaryFile

from os import path, fpathconf, fsync
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
        "codemirror_mode": "pascal",
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
        # so that magma and its children are interruptible.
        sig = signal.signal(signal.SIGINT, signal.SIG_DFL)
        try:
            magma = spawn(
                "magma -b",
                echo=False,
                encoding="utf-8",
                maxread=4194304,
                ignore_sighup=True,
                codec_errors="ignore",
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

        # figure out the maximum length of a formatted input line
        try:
            # Linux 4096
            # OSX 1024
            # Solaris 256
            self.max_input_line_size = (
                int(fpathconf(self.child.child_fd, "PC_MAX_CANON")) - 1
            )
        except OSError:
            # if we can't compute the PTY limit take something minimum that we are aware of
            self.max_input_line_size = 255
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
        read_characters = [0]

        def wait_for_output(read_characters, filename=None):
            read_characters[0] = 0
            # this function will *modify* the read_characters[0]
            # If one send the code block via a temporary file one needs to
            # to remove temporary filename references from the output.
            # output output initially on intervals of 0.5 seconds
            # If no output is received, the interval slowly increases to 30 seconds over 5 min
            initial_counter = counter = 10
            initial_timeout = timeout = 0.1
            if filename:
                infile_line = f'In file "{filename}", '

            while True:
                v = self.child.expect_exact([self._prompt, TIMEOUT], timeout=timeout)

                # something in output
                if not silent and len(self.child.before) > read_characters[0]:
                    output = self.child.before[read_characters[0]:]
                    if read_characters[0] == 0 and filename:
                        # Remove the "Loading filename" line
                        assert output.startswith(
                            f'Loading "{filename}"'
                        ), "First line doesn't match expected outcome: " + repr(output)
                        output = output.partition("\n")[-1]  # consume first line
                    if filename:
                        # in case of error remove temporary filename from output
                        output = output.replace(infile_line, "In ", 1)

                    if output:
                        self.send_response(
                            self.iopub_socket,
                            "stream",
                            {
                                "name": "stdout",
                                "text": output,
                            },
                        )
                    read_characters[0] = len(self.child.before)
                    counter = initial_counter
                    timeout = initial_timeout
                counter -= 1
                # increase timeout after default_counter attempts of processing line
                if counter <= 0:
                    # timeout = min(30, 2 * timeout)
                    counter = initial_counter
                if v == 0:
                    # finished waiting for output
                    return

        append_to_output = ""

        try:
            # We use a temporary file to send each cell
            # this takes about as the same time as sending a single line, but has several benefits:
            # - handles long cells, I wasn't able to send a line longer than 2^16 character.
            # - catches lack of end statements
            # we check the length of the whole code block


            # send the line via a temporary file
            with NamedTemporaryFile("w+t") as tmpfile:
                tmpfile.write(code + "\n")
                tmpfile.flush()
                fsync(tmpfile.fileno())
                self.child.sendline(f'load "{tmpfile.name}";')
                wait_for_output(read_characters, tmpfile.name)

        except KeyboardInterrupt:
            self.child.sendintr()
            interrupted = True
            wait_for_output(read_characters)
            append_to_output = "Interrupted"
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
                    "text": self.child.before[read_characters[0]:] + append_to_output,
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
        default = {
            "matches": [],
            "cursor_start": 0,
            "cursor_end": cursor_pos,
            "metadata": dict(),
            "status": "ok",
        }
        # optimizing to not send everything
        token = code[:cursor_pos]
        for sep in ["\n", ";", " ", "("]:  # we just need the last chunk
            token = token.rpartition(sep)[-1]
        if not token:
            return default
        token_escaped = token.replace('"', r"\"")
        self.child.sendline(f'Completion("{token_escaped}", {len(token)});')
        self.child.expect_exact(self._prompt)
        if self.child.before == "DIE\n":
            self.log.error(
                f'Failed to complete, magma did not like our call:  Completion("{token_escaped}", {len(token)});'
            )
            return default
        matches = self.child.before.splitlines()
        try:
            # how many matches
            matches_len = int(matches[0])
            if matches_len == 0:
                return default
            # The range of text that should be replaced by the above matches when a completion is accepted.
            # typically cursor_end is the same as cursor_pos in the request.
            cursor_start = cursor_pos - len(token) + int(matches[1])
            cursor_end = cursor_pos - len(token) + int(matches[1]) + int(matches[2])
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
