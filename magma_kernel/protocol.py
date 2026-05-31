"""Magma -x protocol: subprocess management, parser, and state machine.

This module has zero ipykernel dependency. It manages a ``magma -x`` child
process, parses the tagged binary protocol, and exposes a callback-based API
that ``kernel.py`` wires to Jupyter messages.
"""

import logging
import os
import select
import signal
import subprocess
import threading
from dataclasses import dataclass
from enum import Enum, auto
from time import monotonic
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TAG_MARKER = 0x81       # 129 - tag line marker byte
EOT_BYTE = 0x04         # end-of-input-set byte
CONT_BYTE = ord("C")    # continuation flag
INDENT_WIDTH = 4        # spaces per indent level
_BUF_SIZE = 4096        # read buffer size
STARTUP_TIMEOUT = 30.0  # seconds to wait for first RDY during start()


class MagmaStartupTimeout(RuntimeError):
    """Raised when ``MagmaProcess.start()`` does not see RDY in time."""


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


class InputAborted(Exception):
    """Raised by on_input_request to abort without sending a response."""


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

    def __init__(
        self,
        magma_path: str = "magma",
        logger: Optional[logging.Logger] = None,
        startup_timeout: Optional[float] = None,
    ):
        self._magma_path = magma_path
        self._log = logger or logging.getLogger(__name__)
        self._proc: Optional[subprocess.Popen] = None
        self._buf = bytearray()
        self._state = MagmaState.STARTING
        self._stderr_thread: Optional[threading.Thread] = None
        self._startup_timeout = (
            STARTUP_TIMEOUT if startup_timeout is None else startup_timeout
        )

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

        self._buf = bytearray()
        self._state = MagmaState.STARTING

        # Drain stderr in background to prevent pipe buffer deadlock.
        # Magma's -x mode sends structured output to stdout (tagged),
        # but may write to stderr for catastrophic errors.  If the 64KB
        # pipe buffer fills, Magma blocks and we deadlock.
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True,
        )
        self._stderr_thread.start()

        # Read startup output until first RDY
        deadline = monotonic() + self._startup_timeout
        banner_acc = OutputAccumulator()
        while True:
            raw = self._read_line(deadline=deadline)
            if raw is None:
                if self.alive and monotonic() >= deadline:
                    self._state = MagmaState.DEAD
                    self.stop(force=True)
                    raise MagmaStartupTimeout(
                        f"Magma did not reach RDY within "
                        f"{self._startup_timeout:.1f}s. "
                        "Check license server, network, or "
                        "MAGMA_PATH."
                    )
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

    def _read_line(self, deadline: Optional[float] = None) -> Optional[bytes]:
        """Read one newline-terminated line from the child's stdout.

        Uses manual buffering with ``os.read`` to avoid issues with
        Python's ``BufferedReader`` around signal interruption.
        Returns ``None`` on EOF or, if ``deadline`` is set, on timeout
        (callers must check ``monotonic() >= deadline`` to
        distinguish).
        """
        if self._proc is None:
            return None
        fd = self._proc.stdout.fileno()
        while True:
            idx = self._buf.find(b"\n")
            if idx != -1:
                line = bytes(self._buf[:idx])
                del self._buf[:idx + 1]
                return line
            if deadline is not None:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return None
                rlist, _, _ = select.select([fd], [], [], remaining)
                if not rlist:
                    return None  # timeout
            try:
                chunk = os.read(fd, _BUF_SIZE)
            except OSError:
                return None
            if not chunk:
                # EOF — return partial line if any
                if self._buf:
                    line = bytes(self._buf)
                    self._buf.clear()
                    return line
                return None
            self._buf.extend(chunk)

    def send_input(self, code: str) -> None:
        """Send an input set (code + EOT) to Magma."""
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("Magma process is not running")
        self._proc.stdin.write(code.encode("utf-8") + bytes([EOT_BYTE]))
        self._proc.stdin.flush()

    def send_line(self, line: str) -> None:
        """Send a newline-terminated line (debugger/read directives)."""
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("Magma process is not running")
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
                    # RDI_ER: per spec, treat as implicit input request
                    if tag == Tag.RDI_ER:
                        flush_both()
                        prompt = prompt_acc.flush()
                        try:
                            response = callbacks.on_input_request(prompt)
                        except InputAborted:
                            pass  # interrupt sent; loop reads INT+RDY
                        else:
                            try:
                                self.send_line(response)
                            except OSError as exc:
                                self._log.warning(
                                    "Magma died while writing input response: %s", exc
                                )
                                self._state = MagmaState.DEAD
                                result.state = MagmaState.DEAD
                                return result
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
                try:
                    response = callbacks.on_input_request(prompt)
                except InputAborted:
                    continue  # interrupt sent; loop reads INT+RDY
                try:
                    self.send_line(response)
                except OSError as exc:
                    self._log.warning(
                        "Magma died while writing input response: %s", exc
                    )
                    self._state = MagmaState.DEAD
                    result.state = MagmaState.DEAD
                    return result
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

    def _drain_stderr(self) -> None:
        """Background thread: read and log Magma's stderr until EOF."""
        if self._proc is None:
            return
        try:
            for line in self._proc.stderr:
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    self._log.warning("Magma stderr: %s", text)
        except (OSError, ValueError):
            pass  # pipe closed

    def drain_stale_responses(self, log: Optional[logging.Logger] = None) -> None:
        """Drain stale INT+RDY sequences left by interrupts delivered while
        Magma was idle.

        After an interrupt, Magma may emit INT+RDY even if it was already
        in the READY state.  These stale responses cause the next
        ``process_until_ready`` to return immediately with no output.
        This method sends a no-op input and repeats until the response
        is non-interrupted, consuming all stale sequences.

        Safe to call on a dead or broken process: returns silently if the
        process is gone, and swallows ``OSError`` / ``RuntimeError`` from
        ``send_input`` (broken pipe, ``_proc is None``).
        """
        logger = log or self._log
        if not self.alive:
            return
        for _ in range(10):
            try:
                self.send_input("_ := 0;")
                r = self.process_until_ready(MagmaCallbacks())
            except (OSError, RuntimeError) as exc:
                logger.debug("drain_stale_responses: process gone (%s)", exc)
                return
            if not r.interrupted:
                return
            logger.debug("Drained stale interrupt response")

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
            # Drain stdout to prevent Magma blocking on a full pipe buffer.
            # Use select() with a deadline so we don't block forever if
            # Magma is slow to exit after stdin closes.
            try:
                if self._proc.stdout and not self._proc.stdout.closed:
                    fd = self._proc.stdout.fileno()
                    deadline = monotonic() + 2
                    while True:
                        remaining = deadline - monotonic()
                        if remaining <= 0:
                            break
                        ready, _, _ = select.select([fd], [], [], remaining)
                        if not ready:
                            break
                        if not os.read(fd, _BUF_SIZE):
                            break
            except OSError:
                pass
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=2)
            self._stderr_thread = None
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
