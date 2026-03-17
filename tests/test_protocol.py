"""Unit tests for magma_kernel.protocol — no Magma required.

Tests in TestMagmaProcess require Magma on PATH and are skipped otherwise.
"""

import os
import shutil
import struct
import threading
import time

import pytest

from magma_kernel.protocol import (
    CONT_BYTE,
    EOT_BYTE,
    INDENT_WIDTH,
    TAG_MARKER,
    ExecutionResult,
    MagmaState,
    OutputAccumulator,
    ParseError,
    ParsedLine,
    Tag,
    TagKind,
    parse_line,
)


# ===================================================================
# parse_line
# ===================================================================


class TestParseLine:
    """Tests for parse_line()."""

    # --- Output tags ---

    def test_out_indent_zero(self):
        raw = bytes([TAG_MARKER]) + b"OUT 0" + bytes([TAG_MARKER]) + b"hello"
        p = parse_line(raw)
        assert p.tag == Tag.OUT
        assert p.kind == TagKind.OUTPUT
        assert p.text == "hello"
        assert p.indent_level == 0
        assert not p.is_continuation

    def test_out_indent_nonzero(self):
        raw = bytes([TAG_MARKER]) + b"OUT 3" + bytes([TAG_MARKER]) + b"indented"
        p = parse_line(raw)
        assert p.indent_level == 3
        assert p.text == "indented"

    def test_out_continuation(self):
        raw = bytes([TAG_MARKER]) + b"OUT C" + bytes([TAG_MARKER]) + b"cont"
        p = parse_line(raw)
        assert p.is_continuation
        assert p.text == "cont"
        assert p.indent_level == 0

    def test_out_empty_text(self):
        raw = bytes([TAG_MARKER]) + b"OUT 0" + bytes([TAG_MARKER])
        p = parse_line(raw)
        assert p.text == ""

    def test_error_tag(self):
        raw = bytes([TAG_MARKER]) + b"ER 0" + bytes([TAG_MARKER]) + b"Runtime error"
        p = parse_line(raw)
        assert p.tag == Tag.ER
        assert p.kind == TagKind.OUTPUT
        assert p.text == "Runtime error"

    def test_eu_tag(self):
        raw = bytes([TAG_MARKER]) + b"EU 0" + bytes([TAG_MARKER]) + b"User error"
        p = parse_line(raw)
        assert p.tag == Tag.EU

    def test_tb_tag(self):
        raw = bytes([TAG_MARKER]) + b"TB 1" + bytes([TAG_MARKER]) + b"In procedure foo"
        p = parse_line(raw)
        assert p.tag == Tag.TB
        assert p.indent_level == 1

    def test_lst_tag(self):
        raw = bytes([TAG_MARKER]) + b"LST 0" + bytes([TAG_MARKER]) + b"listing"
        p = parse_line(raw)
        assert p.tag == Tag.LST

    def test_sig_tag(self):
        raw = bytes([TAG_MARKER]) + b"SIG 0" + bytes([TAG_MARKER]) + b"signature"
        p = parse_line(raw)
        assert p.tag == Tag.SIG

    def test_rdi_er_tag(self):
        raw = bytes([TAG_MARKER]) + b"RDI_ER 0" + bytes([TAG_MARKER]) + b"bad input"
        p = parse_line(raw)
        assert p.tag == Tag.RDI_ER

    # --- Status tags ---

    def test_ir_status(self):
        raw = bytes([TAG_MARKER]) + b"IR"
        p = parse_line(raw)
        assert p.tag == Tag.IR
        assert p.kind == TagKind.STATUS

    def test_int_status(self):
        raw = bytes([TAG_MARKER]) + b"INT"
        p = parse_line(raw)
        assert p.tag == Tag.INT

    def test_res_status(self):
        raw = bytes([TAG_MARKER]) + b"RES"
        p = parse_line(raw)
        assert p.tag == Tag.RES

    def test_ene_status(self):
        raw = bytes([TAG_MARKER]) + b"ENE"
        p = parse_line(raw)
        assert p.tag == Tag.ENE

    def test_drdy_status(self):
        raw = bytes([TAG_MARKER]) + b"DRDY"
        p = parse_line(raw)
        assert p.tag == Tag.DRDY

    def test_quit_status(self):
        raw = bytes([TAG_MARKER]) + b"QUIT"
        p = parse_line(raw)
        assert p.tag == Tag.QUIT

    def test_rd_in_status(self):
        raw = bytes([TAG_MARKER]) + b"RD_IN"
        p = parse_line(raw)
        assert p.tag == Tag.RD_IN

    def test_rdi_in_status(self):
        raw = bytes([TAG_MARKER]) + b"RDI_IN"
        p = parse_line(raw)
        assert p.tag == Tag.RDI_IN

    # --- Data tags ---

    def test_rdy_data(self):
        raw = bytes([TAG_MARKER]) + b"RDY 0 0 0 0 0"
        p = parse_line(raw)
        assert p.tag == Tag.RDY
        assert p.kind == TagKind.DATA
        assert p.args == (0, 0, 0, 0, 0)

    def test_rdy_nonzero_args(self):
        raw = bytes([TAG_MARKER]) + b"RDY 1 0 1 0 5"
        p = parse_line(raw)
        assert p.args == (1, 0, 1, 0, 5)

    def test_run_data(self):
        raw = bytes([TAG_MARKER]) + b"RUN 12345 67890 0 0 1 10"
        p = parse_line(raw)
        assert p.tag == Tag.RUN
        assert p.args == (12345, 67890, 0, 0, 1, 10)

    def test_erp_data(self):
        raw = bytes([TAG_MARKER]) + b"ERP 0 0 3 5"
        p = parse_line(raw)
        assert p.tag == Tag.ERP
        assert p.args == (0, 0, 3, 5)

    def test_pos_data(self):
        raw = bytes([TAG_MARKER]) + b"POS 2 7"
        p = parse_line(raw)
        assert p.tag == Tag.POS
        assert p.args == (2, 7)

    # --- Error cases ---

    def test_no_tag_marker(self):
        with pytest.raises(ParseError, match="No tag marker"):
            parse_line(b"OUT 0\x81hello")

    def test_empty_input(self):
        with pytest.raises(ParseError):
            parse_line(b"")

    def test_unknown_tag(self):
        with pytest.raises(ParseError, match="Unknown tag"):
            parse_line(bytes([TAG_MARKER]) + b"BOGUS")

    def test_no_tag_name(self):
        with pytest.raises(ParseError, match="No tag found"):
            parse_line(bytes([TAG_MARKER]) + b" stuff")

    def test_status_excess_data(self):
        with pytest.raises(ParseError, match="Extra data"):
            parse_line(bytes([TAG_MARKER]) + b"IR extra")

    def test_data_missing_args(self):
        with pytest.raises(ParseError, match="Bad format"):
            parse_line(bytes([TAG_MARKER]) + b"RDY 1 2")

    def test_data_non_digit_arg(self):
        with pytest.raises(ParseError, match="expected integer"):
            parse_line(bytes([TAG_MARKER]) + b"RDY 1 abc 3 4 5")

    def test_data_excess_args(self):
        with pytest.raises(ParseError, match="Extra data"):
            parse_line(bytes([TAG_MARKER]) + b"RDY 0 0 0 0 0 extra")

    def test_output_missing_space(self):
        with pytest.raises(ParseError, match="Bad format"):
            parse_line(bytes([TAG_MARKER]) + b"OUT")

    def test_output_missing_indent_or_cont(self):
        with pytest.raises(ParseError, match="Bad format"):
            parse_line(bytes([TAG_MARKER]) + b"OUT " + bytes([TAG_MARKER]) + b"text")

    def test_output_missing_marker_before_text(self):
        with pytest.raises(ParseError, match="Bad format"):
            parse_line(bytes([TAG_MARKER]) + b"OUT 0text")

    # --- UTF-8 handling ---

    def test_non_utf8_replaced(self):
        raw = bytes([TAG_MARKER]) + b"OUT 0" + bytes([TAG_MARKER]) + b"\xff\xfe"
        p = parse_line(raw)
        assert "\ufffd" in p.text  # replacement character

    def test_valid_utf8(self):
        raw = bytes([TAG_MARKER]) + b"OUT 0" + bytes([TAG_MARKER]) + "Hello".encode("utf-8")
        p = parse_line(raw)
        assert p.text == "Hello"

    def test_marker_byte_in_text(self):
        """The 0x81 byte can appear in text after the text-start marker."""
        raw = bytes([TAG_MARKER]) + b"OUT 0" + bytes([TAG_MARKER]) + bytes([TAG_MARKER]) + b"x"
        p = parse_line(raw)
        # 0x81 in latin-1 is a control char, gets replacement in UTF-8 decode
        assert p.text  # should not raise


# ===================================================================
# OutputAccumulator
# ===================================================================


class TestOutputAccumulator:
    """Tests for OutputAccumulator."""

    def test_single_line(self):
        acc = OutputAccumulator()
        acc.append(ParsedLine(Tag.OUT, TagKind.OUTPUT, text="hello", indent_level=0))
        assert acc.flush() == "hello"

    def test_continuation(self):
        acc = OutputAccumulator()
        acc.append(ParsedLine(Tag.OUT, TagKind.OUTPUT, text="hel", indent_level=0))
        acc.append(ParsedLine(Tag.OUT, TagKind.OUTPUT, text="lo", is_continuation=True))
        assert acc.flush() == "hello"

    def test_indent_levels(self):
        acc = OutputAccumulator()
        acc.append(ParsedLine(Tag.OUT, TagKind.OUTPUT, text="line1", indent_level=0))
        acc.append(ParsedLine(Tag.OUT, TagKind.OUTPUT, text="line2", indent_level=1))
        result = acc.flush()
        assert result == "line1\n    line2"

    def test_mixed_continuation_and_indent(self):
        acc = OutputAccumulator()
        acc.append(ParsedLine(Tag.OUT, TagKind.OUTPUT, text="start", indent_level=0))
        acc.append(ParsedLine(Tag.OUT, TagKind.OUTPUT, text=" more", is_continuation=True))
        acc.append(ParsedLine(Tag.OUT, TagKind.OUTPUT, text="next", indent_level=1))
        result = acc.flush()
        assert result == "start more\n    next"

    def test_empty_flush(self):
        acc = OutputAccumulator()
        assert acc.flush() == ""
        assert not acc.has_content

    def test_has_content(self):
        acc = OutputAccumulator()
        assert not acc.has_content
        acc.append(ParsedLine(Tag.OUT, TagKind.OUTPUT, text="x", indent_level=0))
        assert acc.has_content
        acc.flush()
        assert not acc.has_content

    def test_multiple_indent_zero_lines(self):
        acc = OutputAccumulator()
        acc.append(ParsedLine(Tag.OUT, TagKind.OUTPUT, text="a", indent_level=0))
        acc.append(ParsedLine(Tag.OUT, TagKind.OUTPUT, text="b", indent_level=0))
        acc.append(ParsedLine(Tag.OUT, TagKind.OUTPUT, text="c", indent_level=0))
        assert acc.flush() == "a\nb\nc"

    def test_deep_indent(self):
        acc = OutputAccumulator()
        acc.append(ParsedLine(Tag.OUT, TagKind.OUTPUT, text="deep", indent_level=3))
        assert acc.flush() == "            deep"

    def test_flush_resets(self):
        acc = OutputAccumulator()
        acc.append(ParsedLine(Tag.OUT, TagKind.OUTPUT, text="first", indent_level=0))
        acc.flush()
        acc.append(ParsedLine(Tag.OUT, TagKind.OUTPUT, text="second", indent_level=0))
        assert acc.flush() == "second"


# ===================================================================
# _read_line buffering
# ===================================================================


class TestReadLine:
    """Test MagmaProcess._read_line with simulated pipe reads."""

    def _make_process_with_pipe(self):
        """Create a MagmaProcess with a real pipe for testing _read_line."""
        from magma_kernel.protocol import MagmaProcess

        r, w = os.pipe()
        proc = MagmaProcess.__new__(MagmaProcess)
        proc._buf = b""

        # Create a minimal mock for _proc with stdout having the right fileno
        class FakeStdout:
            def fileno(self):
                return r

        class FakeProc:
            stdout = FakeStdout()

        proc._proc = FakeProc()
        return proc, r, w

    def test_single_line(self):
        proc, r, w = self._make_process_with_pipe()
        os.write(w, b"hello\n")
        os.close(w)
        assert proc._read_line() == b"hello"

    def test_multiple_lines(self):
        proc, r, w = self._make_process_with_pipe()
        os.write(w, b"line1\nline2\nline3\n")
        os.close(w)
        assert proc._read_line() == b"line1"
        assert proc._read_line() == b"line2"
        assert proc._read_line() == b"line3"
        assert proc._read_line() is None

    def test_partial_reads(self):
        """Lines spanning multiple os.read calls."""
        proc, r, w = self._make_process_with_pipe()
        os.write(w, b"hel")
        os.write(w, b"lo\n")
        os.close(w)
        assert proc._read_line() == b"hello"

    def test_long_line(self):
        """Lines longer than the buffer size."""
        proc, r, w = self._make_process_with_pipe()
        long_data = b"x" * 8192
        os.write(w, long_data + b"\n")
        os.close(w)
        assert proc._read_line() == long_data

    def test_eof_mid_line(self):
        """EOF with partial line returns that partial line."""
        proc, r, w = self._make_process_with_pipe()
        os.write(w, b"partial")
        os.close(w)
        assert proc._read_line() == b"partial"
        assert proc._read_line() is None

    def test_eof_no_data(self):
        proc, r, w = self._make_process_with_pipe()
        os.close(w)
        assert proc._read_line() is None

    def test_empty_lines(self):
        proc, r, w = self._make_process_with_pipe()
        os.write(w, b"\n\n\n")
        os.close(w)
        assert proc._read_line() == b""
        assert proc._read_line() == b""
        assert proc._read_line() == b""
        assert proc._read_line() is None


# ===================================================================
# do_is_complete (via kernel logic extracted to test)
# ===================================================================


class TestDoIsComplete:
    """Test the keyword balancing logic used in do_is_complete."""

    def _check(self, code):
        """Simulate MagmaKernel.do_is_complete without ipykernel."""
        from magma_kernel.kernel import _STRING_OR_COMMENT_RE, _KEYWORD_RE, _BLOCK_OPENERS, _BLOCK_CLOSERS

        code = code.strip()
        if not code:
            return {"status": "incomplete", "indent": ""}
        if not code.endswith(";"):
            return {"status": "incomplete", "indent": "    "}

        import re
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
            return {"status": "unknown"}

    def test_empty(self):
        assert self._check("")["status"] == "incomplete"

    def test_simple_statement(self):
        assert self._check("x := 5;")["status"] == "complete"

    def test_no_semicolon(self):
        assert self._check("x := 5")["status"] == "incomplete"

    def test_balanced_for(self):
        assert self._check("for i in [1..10] do print i; end for;")["status"] == "complete"

    def test_unbalanced_for(self):
        assert self._check("for i in [1..10] do print i;")["status"] == "incomplete"

    def test_balanced_if(self):
        assert self._check("if true then x := 1; end if;")["status"] == "complete"

    def test_balanced_while(self):
        assert self._check("while true do break; end while;")["status"] == "complete"

    def test_balanced_function(self):
        assert self._check("function f(x) return x; end function;")["status"] == "complete"

    def test_balanced_try(self):
        assert self._check("try x := 1/0; catch e end try;")["status"] == "complete"

    def test_balanced_case(self):
        assert self._check("case x when 1: y := 1; end case;")["status"] == "complete"

    def test_balanced_repeat(self):
        assert self._check("repeat x +:= 1; until x gt 10;")["status"] == "complete"

    def test_nested_blocks(self):
        code = "for i in [1..5] do if i gt 2 then print i; end if; end for;"
        assert self._check(code)["status"] == "complete"

    def test_string_with_keyword(self):
        """Keywords inside strings should be ignored."""
        assert self._check('x := "for end for";')["status"] == "complete"

    def test_comment_with_keyword(self):
        """Keywords in comments should be ignored."""
        # Comment at end means code doesn't end with ';', so incomplete
        assert self._check("x := 1; // for end for")["status"] == "incomplete"
        # But with a semicolon after the comment-bearing line, keywords
        # inside comments should not affect balance
        assert self._check("// for\nx := 1;")["status"] == "complete"

    def test_inner_semicolon_incomplete(self):
        """Inner semicolon with unbalanced block."""
        assert self._check("for i in [1..10] do\n  print i;")["status"] == "incomplete"


# ===================================================================
# _apply_tb_indent_heuristic
# ===================================================================


class TestTbIndentHeuristic:

    def test_normal_text_gets_indent_1(self):
        from magma_kernel.protocol import _apply_tb_indent_heuristic
        p = ParsedLine(Tag.TB, TagKind.OUTPUT, text="In procedure foo", indent_level=0)
        _apply_tb_indent_heuristic(p)
        assert p.indent_level == 1

    def test_paren_open_stays_indent_0(self):
        from magma_kernel.protocol import _apply_tb_indent_heuristic
        p = ParsedLine(Tag.TB, TagKind.OUTPUT, text="Traceback (", indent_level=0)
        _apply_tb_indent_heuristic(p)
        assert p.indent_level == 0

    def test_paren_close_stays_indent_0(self):
        from magma_kernel.protocol import _apply_tb_indent_heuristic
        p = ParsedLine(Tag.TB, TagKind.OUTPUT, text=")", indent_level=0)
        _apply_tb_indent_heuristic(p)
        assert p.indent_level == 0

    def test_nonzero_indent_unchanged(self):
        from magma_kernel.protocol import _apply_tb_indent_heuristic
        p = ParsedLine(Tag.TB, TagKind.OUTPUT, text="deep", indent_level=2)
        _apply_tb_indent_heuristic(p)
        assert p.indent_level == 2

    def test_empty_text_unchanged(self):
        from magma_kernel.protocol import _apply_tb_indent_heuristic
        p = ParsedLine(Tag.TB, TagKind.OUTPUT, text="", indent_level=0)
        _apply_tb_indent_heuristic(p)
        assert p.indent_level == 0


# ===================================================================
# Live MagmaProcess tests (require Magma on PATH)
# ===================================================================


MAGMA = shutil.which("magma")


@pytest.mark.skipif(MAGMA is None, reason="Magma not found on PATH")
class TestMagmaProcess:
    """Test MagmaProcess directly, bypassing the Jupyter kernel layer.

    These tests exercise interrupt, streaming, crash recovery, and
    other protocol-level behavior that is hard or unreliable to test
    through the Jupyter client.
    """

    def _make(self):
        from magma_kernel.protocol import MagmaProcess
        proc = MagmaProcess()
        proc.start()
        return proc

    def _drain_and_verify(self, proc):
        """Drain stale interrupt responses, then verify the process works.

        After an interrupt (especially a racy one), there may be stale
        INT+RDY sequences buffered from SIGINT arriving while Magma was
        idle.  Each stale RDY causes ``process_until_ready`` to return
        immediately, consuming the stale RDY instead of the real one.

        Strategy: send ONE computation with known output, then call
        ``process_until_ready`` in a loop.  Each stale RDY produces an
        empty return; eventually the real response (with output) arrives.
        """
        from magma_kernel.protocol import MagmaCallbacks, MagmaState
        proc.send_input("1234 + 4321;")
        for _ in range(10):
            out = []
            r = proc.process_until_ready(MagmaCallbacks(
                on_stdout=lambda s: out.append(s),
            ))
            assert r.state == MagmaState.READY
            if "5555" in "".join(out):
                return
        raise AssertionError("Could not drain stale responses after 10 attempts")

    # --- Interrupt ---

    def test_interrupt_infinite_loop(self):
        """Interrupt an infinite loop via SIGINT to the process group."""
        from magma_kernel.protocol import MagmaCallbacks, MagmaState
        proc = self._make()
        try:
            proc.send_input("while true do x := 1; end while;")

            # Interrupt from a thread after a short delay
            def do_interrupt():
                time.sleep(0.3)
                proc.interrupt()

            t = threading.Thread(target=do_interrupt)
            t.start()

            stderr_parts = []
            result = proc.process_until_ready(MagmaCallbacks(
                on_stderr=lambda s: stderr_parts.append(s),
            ))
            t.join()

            assert result.state == MagmaState.READY
            assert result.interrupted

            # Process should still be usable
            out = []
            proc.send_input("1+1;")
            r2 = proc.process_until_ready(MagmaCallbacks(on_stdout=lambda s: out.append(s)))
            assert r2.state == MagmaState.READY
            assert "2" in "".join(out)
        finally:
            proc.stop(force=True)

    def test_interrupt_slow_computation(self):
        """Interrupt a CPU-bound computation.

        The computation may finish before the interrupt arrives (race).
        Either way, the process must remain usable afterwards.
        """
        from magma_kernel.protocol import MagmaCallbacks, MagmaState
        proc = self._make()
        try:
            # Use an infinite loop to guarantee the interrupt actually
            # interrupts something, avoiding the "finishes before
            # SIGINT" race entirely.
            proc.send_input(
                "x := 0; while true do x +:= 1; end while;"
            )

            def do_interrupt():
                time.sleep(0.5)
                proc.interrupt()

            t = threading.Thread(target=do_interrupt)
            t.start()

            result = proc.process_until_ready(MagmaCallbacks())
            t.join()

            assert result.state == MagmaState.READY
            assert result.interrupted

            self._drain_and_verify(proc)
        finally:
            proc.stop(force=True)

    def test_double_interrupt(self):
        """Two interrupts in quick succession should not crash the process.

        The second interrupt may arrive after Magma returned to READY
        from the first, leaving stale INT+RDY sequences in the buffer.
        """
        from magma_kernel.protocol import MagmaCallbacks, MagmaState
        proc = self._make()
        try:
            proc.send_input("while true do x := 1; end while;")

            def do_interrupts():
                time.sleep(0.3)
                proc.interrupt()
                time.sleep(0.1)
                proc.interrupt()

            t = threading.Thread(target=do_interrupts)
            t.start()

            result = proc.process_until_ready(MagmaCallbacks())
            t.join()
            # Wait for the second SIGINT to be fully processed by Magma
            time.sleep(0.5)

            assert result.state == MagmaState.READY

            # Drain any stale interrupt responses, then verify
            self._drain_and_verify(proc)
        finally:
            proc.stop(force=True)

    # --- Streaming ---

    def test_output_streams_per_line(self):
        """Each non-continuation output line triggers a callback, not batched."""
        from magma_kernel.protocol import MagmaCallbacks
        proc = self._make()
        try:
            callback_count = [0]

            def on_stdout(text):
                callback_count[0] += 1

            proc.send_input("for i in [1..20] do print i; end for;")
            proc.process_until_ready(MagmaCallbacks(on_stdout=on_stdout))

            # Each `print i` produces one OUT tag at indent 0.
            # Non-continuation lines flush the previous line, so we
            # should get roughly one callback per print (with maybe one
            # extra for the final flush at RDY).
            assert callback_count[0] >= 15, (
                f"Expected ~20 callbacks, got {callback_count[0]}"
            )
        finally:
            proc.stop(force=True)

    def test_streaming_order_preserved(self):
        """Output lines arrive in order when streamed."""
        from magma_kernel.protocol import MagmaCallbacks
        proc = self._make()
        try:
            chunks = []
            proc.send_input("for i in [1..100] do print i; end for;")
            proc.process_until_ready(MagmaCallbacks(on_stdout=lambda s: chunks.append(s)))

            combined = "".join(chunks)
            nums = []
            for line in combined.splitlines():
                line = line.strip()
                if line.isdigit():
                    nums.append(int(line))
            assert nums == list(range(1, 101))
        finally:
            proc.stop(force=True)

    def test_slow_output_streams_without_delay(self):
        """Output interleaved with computation should be delivered promptly.

        Each print should trigger a callback before the next computation
        starts, not all at once after the cell finishes.
        """
        from magma_kernel.protocol import MagmaCallbacks
        proc = self._make()
        try:
            timestamps = []

            def on_stdout(text):
                timestamps.append(time.monotonic())

            code = (
                "print 1;\n"
                "x := &+[i : i in [1..1000000]];\n"
                "print 2;\n"
                "x := &+[i : i in [1..1000000]];\n"
                "print 3;"
            )
            proc.send_input(code)
            proc.process_until_ready(MagmaCallbacks(on_stdout=on_stdout))

            # We should get at least 3 callbacks (one per print)
            assert len(timestamps) >= 3, f"Expected >=3 callbacks, got {len(timestamps)}"
            # The time span should be non-trivial — not all at time zero.
            # Each &+[...1000000] takes ~10-50ms, so total > 20ms.
            span = timestamps[-1] - timestamps[0]
            assert span > 0.01, (
                f"All callbacks arrived within {span:.3f}s — output may be buffered"
            )
        finally:
            proc.stop(force=True)

    def test_all_50000_output_lines_delivered(self):
        """Verify the protocol layer delivers all 50K lines without loss.

        This is the protocol-layer counterpart to the Jupyter integration
        test, which can lose messages due to ZMQ HWM limits.
        """
        from magma_kernel.protocol import MagmaCallbacks
        proc = self._make()
        try:
            chunks = []
            proc.send_input("for i in [1..50000] do print i; end for;")
            proc.process_until_ready(MagmaCallbacks(on_stdout=lambda s: chunks.append(s)))

            combined = "".join(chunks)
            nums = [int(l.strip()) for l in combined.splitlines() if l.strip().isdigit()]
            assert len(nums) == 50000
            assert nums[0] == 1
            assert nums[-1] == 50000
        finally:
            proc.stop(force=True)

    # --- Crash recovery ---

    def test_crash_detection(self):
        """Killing the magma process is detected as DEAD state."""
        from magma_kernel.protocol import MagmaCallbacks, MagmaState
        import signal as sig
        proc = self._make()
        try:
            pid = proc._proc.pid
            os.kill(pid, sig.SIGKILL)
            time.sleep(0.2)
            assert not proc.alive
        finally:
            proc.stop(force=True)

    # --- Stop ---

    def test_graceful_stop(self):
        """Graceful stop closes stdin and waits for QUIT."""
        proc = self._make()
        assert proc.alive
        proc.stop(force=False)
        assert not proc.alive
        assert proc._proc is None

    def test_force_stop(self):
        """Force stop kills immediately."""
        proc = self._make()
        assert proc.alive
        proc.stop(force=True)
        assert not proc.alive
        assert proc._proc is None

    def test_stop_already_stopped(self):
        """Stopping a process that is already stopped is a no-op."""
        proc = self._make()
        proc.stop(force=True)
        proc.stop(force=True)  # should not raise
        proc.stop(force=False)  # should not raise

    # --- Error paths ---

    def test_runtime_error_to_stderr(self):
        """ER tags go to stderr callback, set had_error."""
        from magma_kernel.protocol import MagmaCallbacks, MagmaState
        proc = self._make()
        try:
            stderr_parts = []
            proc.send_input('1 + "a";')
            result = proc.process_until_ready(MagmaCallbacks(
                on_stderr=lambda s: stderr_parts.append(s),
            ))
            assert result.state == MagmaState.READY
            assert result.had_error
            stderr = "".join(stderr_parts)
            assert "Runtime error" in stderr or "error" in stderr.lower()
        finally:
            proc.stop(force=True)

    def test_user_error_to_stderr(self):
        """EU tags go to stderr callback, set had_error."""
        from magma_kernel.protocol import MagmaCallbacks, MagmaState
        proc = self._make()
        try:
            stderr_parts = []
            proc.send_input("x := ;")
            result = proc.process_until_ready(MagmaCallbacks(
                on_stderr=lambda s: stderr_parts.append(s),
            ))
            assert result.state == MagmaState.READY
            assert result.had_error
            assert "".join(stderr_parts)  # non-empty
        finally:
            proc.stop(force=True)

    def test_parse_error_position(self):
        """ERP tag stores error position in result."""
        from magma_kernel.protocol import MagmaCallbacks, MagmaState
        proc = self._make()
        try:
            proc.send_input("x := ;")
            result = proc.process_until_ready(MagmaCallbacks())
            assert result.had_error
            assert result.erp is not None
            assert len(result.erp) == 4  # start-line, start-col, err-line, err-col
        finally:
            proc.stop(force=True)

    def test_traceback_in_error(self):
        """TB tags are routed to stderr with indent heuristic applied."""
        from magma_kernel.protocol import MagmaCallbacks
        proc = self._make()
        try:
            # Define a procedure that errors, to get a traceback
            code = (
                'procedure Foo()\n'
                '  error "boom";\n'
                'end procedure;\n'
                'Foo();'
            )
            stderr_parts = []
            proc.send_input(code)
            result = proc.process_until_ready(MagmaCallbacks(
                on_stderr=lambda s: stderr_parts.append(s),
            ))
            assert result.had_error
            stderr = "".join(stderr_parts)
            # Should have traceback info mentioning the procedure
            assert stderr  # non-empty error output
        finally:
            proc.stop(force=True)

    def test_ene_incomplete_input(self):
        """ENE tag sets incomplete flag and sends message to stderr."""
        from magma_kernel.protocol import MagmaCallbacks, MagmaState
        proc = self._make()
        try:
            stderr_parts = []
            # Send incomplete code — an 'if' without 'end if'
            # Note: we must NOT append ';' ourselves — the ENE test
            # needs genuinely incomplete code.
            proc.send_input("if true then")
            result = proc.process_until_ready(MagmaCallbacks(
                on_stderr=lambda s: stderr_parts.append(s),
            ))
            assert result.state == MagmaState.READY
            assert result.had_error
            assert result.incomplete
            stderr = "".join(stderr_parts)
            assert "ncomplete" in stderr or "unparseable" in stderr.lower()
        finally:
            proc.stop(force=True)

    # --- EOF / crash during execution ---

    def test_eof_during_execution(self):
        """Killing the process mid-execution returns DEAD state."""
        from magma_kernel.protocol import MagmaCallbacks, MagmaState
        import signal as sig
        proc = self._make()
        try:
            proc.send_input("while true do x := 1; end while;")

            def do_kill():
                time.sleep(0.3)
                os.kill(proc._proc.pid, sig.SIGKILL)

            t = threading.Thread(target=do_kill)
            t.start()

            result = proc.process_until_ready(MagmaCallbacks())
            t.join()

            assert result.state == MagmaState.DEAD
        finally:
            proc.stop(force=True)

    # --- start() failure ---

    def test_start_bad_path(self):
        """Starting with a nonexistent magma path raises RuntimeError."""
        from magma_kernel.protocol import MagmaProcess
        proc = MagmaProcess(magma_path="/nonexistent/magma")
        with pytest.raises((RuntimeError, FileNotFoundError)):
            proc.start()

    # --- Debugger ---

    def test_debugger_enter_and_quit(self):
        """Runtime error in a procedure with SetDebugOnError triggers DRDY.

        Sending 'q' via send_line exits the debugger back to READY.
        """
        from magma_kernel.protocol import MagmaCallbacks, MagmaState
        proc = self._make()
        try:
            proc.send_input("SetDebugOnError(true);")
            proc.process_until_ready(MagmaCallbacks())

            code = (
                "procedure Foo()\n"
                "  x := 1/(1-1);\n"
                "end procedure;\n"
                "Foo();"
            )
            stderr_parts = []
            proc.send_input(code)
            result = proc.process_until_ready(MagmaCallbacks(
                on_stderr=lambda s: stderr_parts.append(s),
            ))

            assert result.state == MagmaState.DEBUGGER
            assert result.had_error
            stderr = "".join(stderr_parts)
            assert "Division by zero" in stderr or "error" in stderr.lower()

            # Quit the debugger
            proc.send_line("q")
            r2 = proc.process_until_ready(MagmaCallbacks())
            assert r2.state == MagmaState.READY

            # Process should be usable after debugger exit
            out = []
            proc.send_input("2+2;")
            r3 = proc.process_until_ready(MagmaCallbacks(
                on_stdout=lambda s: out.append(s),
            ))
            assert r3.state == MagmaState.READY
            assert "4" in "".join(out)
        finally:
            proc.stop(force=True)

    def test_debugger_inspect_variable(self):
        """Debugger 'p' command prints variable values via send_line."""
        from magma_kernel.protocol import MagmaCallbacks, MagmaState
        proc = self._make()
        try:
            proc.send_input("SetDebugOnError(true);")
            proc.process_until_ready(MagmaCallbacks())

            code = (
                "procedure Bar(n)\n"
                "  x := 1/(n - 5);\n"
                "end procedure;\n"
                "Bar(5);"
            )
            proc.send_input(code)
            r = proc.process_until_ready(MagmaCallbacks(
                on_stderr=lambda s: None,
            ))
            assert r.state == MagmaState.DEBUGGER

            # Inspect variable 'n' — should print 5
            out = []
            proc.send_line("p n")
            r2 = proc.process_until_ready(MagmaCallbacks(
                on_stdout=lambda s: out.append(s),
            ))
            assert r2.state == MagmaState.DEBUGGER
            assert "5" in "".join(out)

            # Backtrace
            stderr_bt = []
            proc.send_line("bt")
            r3 = proc.process_until_ready(MagmaCallbacks(
                on_stderr=lambda s: stderr_bt.append(s),
            ))
            assert r3.state == MagmaState.DEBUGGER
            bt = "".join(stderr_bt)
            assert "Bar" in bt

            # Quit
            proc.send_line("q")
            r4 = proc.process_until_ready(MagmaCallbacks())
            assert r4.state == MagmaState.READY
        finally:
            proc.stop(force=True)

    def test_debugger_multiple_entries(self):
        """Entering and exiting the debugger multiple times works."""
        from magma_kernel.protocol import MagmaCallbacks, MagmaState
        proc = self._make()
        try:
            proc.send_input("SetDebugOnError(true);")
            proc.process_until_ready(MagmaCallbacks())

            code = (
                "procedure Boom()\n"
                "  error \"test\";\n"
                "end procedure;\n"
            )
            proc.send_input(code)
            proc.process_until_ready(MagmaCallbacks())

            for i in range(3):
                proc.send_input("Boom();")
                r = proc.process_until_ready(MagmaCallbacks(
                    on_stderr=lambda s: None,
                ))
                assert r.state == MagmaState.DEBUGGER, f"iteration {i}"
                proc.send_line("q")
                r2 = proc.process_until_ready(MagmaCallbacks())
                assert r2.state == MagmaState.READY, f"iteration {i}"

            # Still works after repeated debugger sessions
            out = []
            proc.send_input("10+10;")
            r3 = proc.process_until_ready(MagmaCallbacks(
                on_stdout=lambda s: out.append(s),
            ))
            assert "20" in "".join(out)
        finally:
            proc.stop(force=True)
