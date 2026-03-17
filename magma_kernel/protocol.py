"""Magma -x protocol: subprocess management, parser, and state machine.

This module has zero ipykernel dependency. It manages a ``magma -x`` child
process, parses the tagged binary protocol, and exposes a callback-based API
that ``kernel.py`` wires to Jupyter messages.
"""

import logging
import os
import signal
import subprocess
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TAG_MARKER = 0x81       # 129 - tag line marker byte
EOT_BYTE = 0x04         # end-of-input-set byte
CONT_BYTE = ord("C")    # continuation flag
INDENT_WIDTH = 4        # spaces per indent level
_BUF_SIZE = 4096        # read buffer size

# ---------------------------------------------------------------------------
# Enums and tag table
# ---------------------------------------------------------------------------


class Tag(Enum):
    OUT = auto()
    RDY = auto()
    IR = auto()
    RUN = auto()
    QUIT = auto()
    TB = auto()
    EPO = auto()
    ER = auto()
    ERP = auto()
    POS = auto()
    EU = auto()
    EI = auto()
    LST = auto()
    SIG = auto()
    INT = auto()
    RES = auto()
    ENE = auto()
    DRDY = auto()
    DTB = auto()
    DE = auto()
    RD_PR = auto()
    RD_IN = auto()
    RDI_PR = auto()
    RDI_IN = auto()
    RDI_ER = auto()


class TagKind(Enum):
    OUTPUT = auto()
    STATUS = auto()
    DATA = auto()


# tag name string -> (Tag, TagKind, nargs)
TAG_INFO: dict[str, tuple[Tag, TagKind, int]] = {
    "OUT":    (Tag.OUT,    TagKind.OUTPUT, 0),
    "RDY":    (Tag.RDY,    TagKind.DATA,   5),
    "IR":     (Tag.IR,     TagKind.STATUS, 0),
    "RUN":    (Tag.RUN,    TagKind.DATA,   6),
    "QUIT":   (Tag.QUIT,   TagKind.STATUS, 0),
    "TB":     (Tag.TB,     TagKind.OUTPUT, 0),
    "EPO":    (Tag.EPO,    TagKind.OUTPUT, 0),
    "ER":     (Tag.ER,     TagKind.OUTPUT, 0),
    "ERP":    (Tag.ERP,    TagKind.DATA,   4),
    "POS":    (Tag.POS,    TagKind.DATA,   2),
    "EU":     (Tag.EU,     TagKind.OUTPUT, 0),
    "EI":     (Tag.EI,     TagKind.OUTPUT, 0),
    "LST":    (Tag.LST,    TagKind.OUTPUT, 0),
    "SIG":    (Tag.SIG,    TagKind.OUTPUT, 0),
    "INT":    (Tag.INT,    TagKind.STATUS, 0),
    "RES":    (Tag.RES,    TagKind.STATUS, 0),
    "ENE":    (Tag.ENE,    TagKind.STATUS, 0),
    "DRDY":   (Tag.DRDY,   TagKind.STATUS, 0),
    "DTB":    (Tag.DTB,    TagKind.OUTPUT, 0),
    "DE":     (Tag.DE,     TagKind.OUTPUT, 0),
    "RD_PR":  (Tag.RD_PR,  TagKind.OUTPUT, 0),
    "RD_IN":  (Tag.RD_IN,  TagKind.STATUS, 0),
    "RDI_PR": (Tag.RDI_PR, TagKind.OUTPUT, 0),
    "RDI_IN": (Tag.RDI_IN, TagKind.STATUS, 0),
    "RDI_ER": (Tag.RDI_ER, TagKind.OUTPUT, 0),
}

# Tags whose text goes to stderr
_STDERR_TAGS = frozenset({Tag.ER, Tag.EU, Tag.EI, Tag.TB, Tag.EPO, Tag.DTB, Tag.DE, Tag.RDI_ER})

# Tags whose text goes to stdout
_STDOUT_TAGS = frozenset({Tag.OUT, Tag.LST, Tag.SIG})

# Tags that indicate an error occurred
_ERROR_TAGS = frozenset({Tag.ER, Tag.EU, Tag.EI})

# Prompt tags (text accumulated, flushed when read-input status arrives)
_PROMPT_TAGS = frozenset({Tag.RD_PR, Tag.RDI_PR})

# ---------------------------------------------------------------------------
# ParsedLine and parse_line
# ---------------------------------------------------------------------------


class ParseError(Exception):
    """Raised when a tagged line cannot be parsed."""


@dataclass
class ParsedLine:
    tag: Tag
    kind: TagKind
    text: str = ""
    is_continuation: bool = False
    indent_level: int = 0
    args: tuple[int, ...] = ()


def parse_line(raw: bytes) -> ParsedLine:
    """Parse one tagged output line from ``magma -x``.

    Port of ``parse_magma_line`` from ``xmagma.c:438-501``.
    """
    if not raw:
        raise ParseError("Empty line")
    if raw[0] != TAG_MARKER:
        raise ParseError(f"No tag marker (first byte {raw[0]!r} != 0x81)")

    # Extract tag name (uppercase ASCII + underscore)
    pos = 1
    tag_start = pos
    while pos < len(raw) and (raw[pos] in range(ord("A"), ord("Z") + 1) or raw[pos] == ord("_")):
        pos += 1
    tag_name = raw[tag_start:pos].decode("ascii")
    if not tag_name:
        raise ParseError("No tag found")

    info = TAG_INFO.get(tag_name)
    if info is None:
        raise ParseError(f"Unknown tag: {tag_name!r}")

    tag, kind, nargs = info

    if kind == TagKind.OUTPUT:
        # Expect: <space> then C|<digits> then <0x81> then text
        if pos >= len(raw) or raw[pos] != ord(" "):
            raise ParseError(f"Bad format: expected space after tag {tag_name}")
        pos += 1

        is_continuation = False
        indent_level = 0

        if pos < len(raw) and raw[pos] == CONT_BYTE:
            is_continuation = True
            pos += 1
        else:
            # Parse decimal indent level
            digit_start = pos
            while pos < len(raw) and ord("0") <= raw[pos] <= ord("9"):
                pos += 1
            if pos == digit_start:
                raise ParseError(f"Bad format: expected C or indent digits for {tag_name}")
            indent_level = int(raw[digit_start:pos].decode("ascii"))

        if pos >= len(raw) or raw[pos] != TAG_MARKER:
            raise ParseError(f"Bad format: expected 0x81 before text for {tag_name}")
        pos += 1

        text = raw[pos:].decode("utf-8", errors="replace")
        return ParsedLine(tag=tag, kind=kind, text=text,
                          is_continuation=is_continuation, indent_level=indent_level)

    elif kind == TagKind.STATUS:
        if pos != len(raw):
            raise ParseError(f"Extra data after status tag {tag_name}")
        return ParsedLine(tag=tag, kind=kind)

    else:  # DATA
        args = []
        for _ in range(nargs):
            if pos >= len(raw) or raw[pos] != ord(" "):
                raise ParseError(f"Bad format: expected space before arg in {tag_name}")
            pos += 1
            digit_start = pos
            while pos < len(raw) and ord("0") <= raw[pos] <= ord("9"):
                pos += 1
            if pos == digit_start:
                raise ParseError(f"Bad format: expected integer arg in {tag_name}")
            args.append(int(raw[digit_start:pos].decode("ascii")))
        if pos != len(raw):
            raise ParseError(f"Extra data after data tag {tag_name}")
        return ParsedLine(tag=tag, kind=kind, args=tuple(args))


# ---------------------------------------------------------------------------
# OutputAccumulator
# ---------------------------------------------------------------------------


class OutputAccumulator:
    """Assembles continuation/indent lines into complete text blocks.

    Port of ``process_output_tag`` from ``xmagma.c:537-549``.
    """

    def __init__(self):
        self._parts: list[str] = []
        self._has_content = False

    @property
    def has_content(self) -> bool:
        return self._has_content

    def append(self, parsed: ParsedLine) -> None:
        if parsed.is_continuation:
            self._parts.append(parsed.text)
        else:
            if self._has_content:
                self._parts.append("\n")
            if parsed.indent_level > 0:
                self._parts.append(" " * (parsed.indent_level * INDENT_WIDTH))
            self._parts.append(parsed.text)
        self._has_content = True

    def flush(self) -> str:
        text = "".join(self._parts)
        self._parts.clear()
        self._has_content = False
        return text


# ---------------------------------------------------------------------------
# State, result, callbacks
# ---------------------------------------------------------------------------


class MagmaState(Enum):
    STARTING = auto()
    READY = auto()
    RUNNING = auto()
    DEBUGGER = auto()
    READ_INPUT = auto()
    DEAD = auto()


@dataclass
class ExecutionResult:
    state: MagmaState
    had_error: bool = False
    interrupted: bool = False
    incomplete: bool = False
    erp: Optional[tuple[int, ...]] = None


@dataclass
class MagmaCallbacks:
    on_stdout: Callable[[str], None] = lambda s: None
    on_stderr: Callable[[str], None] = lambda s: None
    on_input_request: Callable[[str], str] = lambda s: ""


# ---------------------------------------------------------------------------
# MagmaProcess
# ---------------------------------------------------------------------------


class MagmaProcess:
    """Manages a ``magma -x`` child process and the tagged protocol."""

    def __init__(self, magma_path: str = "magma", logger: Optional[logging.Logger] = None):
        self._magma_path = magma_path
        self._log = logger or logging.getLogger(__name__)
        self._proc: Optional[subprocess.Popen] = None
        self._buf = b""
        self._state = MagmaState.STARTING

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> str:
        """Spawn ``magma -x``, read until first RDY, return banner text."""
        sig = signal.signal(signal.SIGINT, signal.SIG_DFL)
        try:
            self._proc = subprocess.Popen(
                [self._magma_path, "-x"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        finally:
            signal.signal(signal.SIGINT, sig)

        self._buf = b""
        self._state = MagmaState.STARTING

        # Read startup output until first RDY
        banner_acc = OutputAccumulator()
        while True:
            raw = self._read_line()
            if raw is None:
                self._state = MagmaState.DEAD
                raise RuntimeError(
                    "Magma process died during startup. "
                    "Ensure 'magma' is on your PATH and functioning."
                )
            try:
                parsed = parse_line(raw)
            except ParseError as exc:
                self._log.warning("Parse error during startup: %s", exc)
                continue

            if parsed.kind == TagKind.OUTPUT:
                # Apply TB indent heuristic
                if parsed.tag == Tag.TB:
                    _apply_tb_indent_heuristic(parsed)
                banner_acc.append(parsed)
            elif parsed.tag == Tag.RDY:
                self._state = MagmaState.READY
                break
            # Ignore other tags during startup

        return banner_acc.flush()

    def _read_line(self) -> Optional[bytes]:
        """Read one newline-terminated line from the child's stdout.

        Uses manual buffering with ``os.read`` to avoid issues with
        Python's ``BufferedReader`` around signal interruption.
        Returns ``None`` on EOF.
        """
        assert self._proc is not None
        fd = self._proc.stdout.fileno()
        while True:
            idx = self._buf.find(b"\n")
            if idx != -1:
                line = self._buf[:idx]
                self._buf = self._buf[idx + 1:]
                return line
            try:
                chunk = os.read(fd, _BUF_SIZE)
            except OSError:
                return None
            if not chunk:
                # EOF — return partial line if any
                if self._buf:
                    line = self._buf
                    self._buf = b""
                    return line
                return None
            self._buf += chunk

    def send_input(self, code: str) -> None:
        """Send an input set (code + EOT) to Magma."""
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(code.encode("utf-8") + bytes([EOT_BYTE]))
        self._proc.stdin.flush()

    def send_line(self, line: str) -> None:
        """Send a newline-terminated line (debugger/read directives)."""
        assert self._proc is not None and self._proc.stdin is not None
        data = line if line.endswith("\n") else line + "\n"
        self._proc.stdin.write(data.encode("utf-8"))
        self._proc.stdin.flush()

    def interrupt(self) -> None:
        """Send SIGINT to the Magma process group."""
        if self._proc is not None and self.alive:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGINT)
            except (ProcessLookupError, PermissionError):
                pass

    def process_until_ready(self, callbacks: MagmaCallbacks) -> ExecutionResult:
        """Core tag dispatch loop.

        Reads and dispatches tagged lines until a terminal state
        (RDY, DRDY, QUIT, or EOF) is reached.

        Returns an ``ExecutionResult`` describing the outcome.
        """
        stdout_acc = OutputAccumulator()
        stderr_acc = OutputAccumulator()
        prompt_acc = OutputAccumulator()

        result = ExecutionResult(state=MagmaState.RUNNING)

        def flush_stdout():
            if stdout_acc.has_content:
                callbacks.on_stdout(stdout_acc.flush() + "\n")

        def flush_stderr():
            if stderr_acc.has_content:
                callbacks.on_stderr(stderr_acc.flush() + "\n")

        def flush_both():
            flush_stdout()
            flush_stderr()

        while True:
            raw = self._read_line()
            if raw is None:
                flush_both()
                self._state = MagmaState.DEAD
                result.state = MagmaState.DEAD
                return result

            try:
                parsed = parse_line(raw)
            except ParseError as exc:
                self._log.warning("Parse error: %s (line: %r)", exc, raw)
                continue

            tag = parsed.tag

            # --- Output tags ---
            if parsed.kind == TagKind.OUTPUT:
                # Apply TB indent heuristic (xmagma.c:558-567)
                if tag == Tag.TB:
                    _apply_tb_indent_heuristic(parsed)

                if tag in _STDOUT_TAGS:
                    # Flush stderr before switching to stdout
                    flush_stderr()
                    # Stream on every non-continuation line
                    if not parsed.is_continuation and stdout_acc.has_content:
                        flush_stdout()
                    stdout_acc.append(parsed)
                elif tag in _PROMPT_TAGS:
                    prompt_acc.append(parsed)
                elif tag in _STDERR_TAGS:
                    # Flush stdout before switching to stderr
                    flush_stdout()
                    if not parsed.is_continuation and stderr_acc.has_content:
                        flush_stderr()
                    stderr_acc.append(parsed)
                    if tag in _ERROR_TAGS:
                        result.had_error = True
                    # RDI_ER: accumulate the error text, then an RDI_IN
                    # will follow — keep looping
                continue

            # --- Status tags ---
            if tag == Tag.IR or tag == Tag.RES:
                continue

            if tag == Tag.INT:
                flush_both()
                result.interrupted = True
                continue

            if tag == Tag.ENE:
                flush_both()
                result.had_error = True
                result.incomplete = True
                callbacks.on_stderr("Incomplete or unparseable code at end of input\n")
                continue

            if tag == Tag.DRDY:
                flush_both()
                self._state = MagmaState.DEBUGGER
                result.state = MagmaState.DEBUGGER
                return result

            if tag == Tag.RD_IN or tag == Tag.RDI_IN:
                flush_both()
                prompt = prompt_acc.flush()
                response = callbacks.on_input_request(prompt)
                self.send_line(response)
                continue

            if tag == Tag.QUIT:
                flush_both()
                self._state = MagmaState.DEAD
                result.state = MagmaState.DEAD
                return result

            # --- Data tags ---
            if tag == Tag.RDY:
                flush_both()
                self._state = MagmaState.READY
                result.state = MagmaState.READY
                return result

            if tag == Tag.RUN:
                continue

            if tag == Tag.ERP:
                result.erp = parsed.args
                result.had_error = True
                continue

            if tag == Tag.POS:
                continue

    def stop(self, force: bool = False) -> None:
        """Stop the Magma process."""
        if self._proc is None:
            return
        if force:
            try:
                self._proc.kill()
            except OSError:
                pass
            self._proc.wait()
        else:
            try:
                if self._proc.stdin and not self._proc.stdin.closed:
                    self._proc.stdin.close()
            except OSError:
                pass
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._state = MagmaState.DEAD
        self._proc = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_tb_indent_heuristic(parsed: ParsedLine) -> None:
    """Apply the traceback indent heuristic from xmagma.c:558-567.

    TB lines with indent 0 that don't start with ')' or end with '('
    get bumped to indent 1.
    """
    if (parsed.indent_level == 0
            and parsed.text
            and not parsed.text.startswith(")")
            and not parsed.text.endswith("(")):
        parsed.indent_level = 1
