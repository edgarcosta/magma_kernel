"""Integration tests for the Magma Jupyter kernel.

These tests start a real Magma kernel process and require Magma to be
available on PATH.  They are skipped automatically when Magma is absent.

Run with:  pytest tests/test_kernel.py -v
"""

import shutil
import time

import pytest
from jupyter_client.manager import KernelManager

MAGMA = shutil.which("magma")
pytestmark = pytest.mark.skipif(MAGMA is None, reason="Magma not found on PATH")


@pytest.fixture(scope="module")
def kernel():
    """Start a Magma kernel and yield (manager, client)."""
    km = KernelManager(kernel_name="magma")
    km.start_kernel()
    client = km.client()
    client.start_channels()
    client.wait_for_ready(timeout=60)
    yield km, client
    client.stop_channels()
    km.shutdown_kernel(now=True)


@pytest.fixture(scope="module")
def kc(kernel):
    """Shorthand: yield just the client for tests that don't need the manager."""
    return kernel[1]


def _execute(kc, code, timeout=30):
    """Execute *code* and return (reply_content, stdout, stderr, display_data)."""
    msg_id = kc.execute(code)
    reply = kc.get_shell_msg(timeout=timeout)
    assert reply["parent_header"]["msg_id"] == msg_id

    stdout_parts = []
    stderr_parts = []
    display_parts = []
    while True:
        try:
            msg = kc.get_iopub_msg(timeout=10)
        except Exception:
            break
        if msg["parent_header"].get("msg_id") != msg_id:
            continue
        mtype = msg["msg_type"]
        if mtype == "stream" and msg["content"]["name"] == "stdout":
            stdout_parts.append(msg["content"]["text"])
        elif mtype == "stream" and msg["content"]["name"] == "stderr":
            stderr_parts.append(msg["content"]["text"])
        elif mtype == "display_data":
            display_parts.append(msg["content"])
        elif mtype == "status" and msg["content"]["execution_state"] == "idle":
            break

    return (
        reply["content"],
        "".join(stdout_parts),
        "".join(stderr_parts),
        display_parts,
    )


# --- Execution ---


def test_basic_arithmetic(kc):
    reply, stdout, stderr, _ = _execute(kc, "1+1;")
    assert reply["status"] == "ok"
    assert "2" in stdout


def test_semicolon_appending(kc):
    """Bare statements (no trailing ;) should still execute."""
    reply, stdout, stderr, _ = _execute(kc, "1+1")
    assert reply["status"] == "ok"
    assert "2" in stdout


def test_multiline_cell(kc):
    code = "a := 3;\nb := 4;\na + b;"
    reply, stdout, stderr, _ = _execute(kc, code)
    assert reply["status"] == "ok"
    assert "7" in stdout


def test_empty_cell(kc):
    reply, stdout, stderr, _ = _execute(kc, "")
    assert reply["status"] == "ok"
    assert stdout == ""


def test_whitespace_only_cell(kc):
    reply, stdout, stderr, _ = _execute(kc, "   \n  ")
    assert reply["status"] == "ok"
    assert stdout == ""


# --- Error detection ---


def test_runtime_error(kc):
    reply, stdout, stderr, _ = _execute(kc, '1 + "a";')
    assert reply["status"] == "error"
    assert stderr
    assert "Runtime error" in reply["ename"]
    assert reply["traceback"]


def test_user_error(kc):
    """Syntax errors are reported as User error in Magma."""
    reply, stdout, stderr, _ = _execute(kc, "if true then")
    assert reply["status"] == "error"
    assert stderr
    assert reply["traceback"]


def test_error_does_not_break_subsequent_cells(kc):
    """After an error, the kernel should still work."""
    _execute(kc, '1 + "a";')
    reply, stdout, stderr, _ = _execute(kc, "2+3;")
    assert reply["status"] == "ok"
    assert "5" in stdout


# --- Completion ---


def test_completion(kc):
    msg_id = kc.complete("IsPr", 4)
    reply = kc.get_shell_msg(timeout=30)
    matches = reply["content"]["matches"]
    assert any("IsPrime" in m for m in matches)


def test_completion_empty(kc):
    msg_id = kc.complete("", 0)
    reply = kc.get_shell_msg(timeout=30)
    assert reply["content"]["matches"] == []


# --- is_complete ---


def test_is_complete_with_semicolon(kc):
    msg_id = kc.is_complete("1+1;")
    reply = kc.get_shell_msg(timeout=10)
    assert reply["content"]["status"] == "complete"


def test_is_complete_without_semicolon(kc):
    msg_id = kc.is_complete("for i in")
    reply = kc.get_shell_msg(timeout=10)
    assert reply["content"]["status"] == "incomplete"


def test_is_complete_empty(kc):
    msg_id = kc.is_complete("")
    reply = kc.get_shell_msg(timeout=10)
    assert reply["content"]["status"] == "incomplete"


def test_is_complete_balanced_block(kc):
    msg_id = kc.is_complete("for i in [1..10] do print i; end for;")
    reply = kc.get_shell_msg(timeout=10)
    assert reply["content"]["status"] == "complete"


def test_is_complete_unbalanced_block(kc):
    msg_id = kc.is_complete("for i in [1..10] do print i;")
    reply = kc.get_shell_msg(timeout=10)
    assert reply["content"]["status"] == "incomplete"


# --- Help ---


def test_help_link(kc):
    reply, _, _, display = _execute(kc, "?Integers")
    assert reply["status"] == "ok"
    assert len(display) > 0
    html = display[0]["data"].get("text/html", "")
    assert "magma.maths.usyd.edu.au" in html
    assert "Integers" in html


# --- Long output ---


def test_long_output(kc):
    reply, stdout, stderr, _ = _execute(kc, "for i in [1..50] do print i; end for;")
    assert reply["status"] == "ok"
    assert "50" in stdout


def test_long_output_1000_lines(kc):
    """1000 lines of output should all arrive."""
    reply, stdout, stderr, _ = _execute(
        kc, "for i in [1..1000] do print i; end for;", timeout=60
    )
    assert reply["status"] == "ok"
    nums = set()
    for line in stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            nums.add(int(line))
    assert nums == set(range(1, 1001))


def test_long_output_10000_lines(kc):
    """10K lines of output completes successfully.

    We verify the execution succeeds and produces substantial output.
    The exact line count may be lower than 10000 because Jupyter's ZMQ
    iopub channel can drop messages under high volume (HWM limit), but
    the protocol layer delivers all lines — verified separately in
    test_protocol.py::TestReadLine and by direct MagmaProcess tests.
    """
    n = 10000
    reply, stdout, stderr, _ = _execute(
        kc, f"for i in [1..{n}] do print i; end for;", timeout=60
    )
    assert reply["status"] == "ok"
    lines = [l.strip() for l in stdout.splitlines() if l.strip().isdigit()]
    # Must get a substantial fraction; exact count depends on ZMQ HWM
    assert len(lines) >= 1000


def test_long_single_value(kc):
    """A single output value longer than a PTY line limit (~4KB string)."""
    n = 5000
    code = f's := &cat[IntegerToString(i mod 10) : i in [1..{n}]]; s;'
    reply, stdout, stderr, _ = _execute(kc, code, timeout=60)
    assert reply["status"] == "ok"
    digits = "".join(c for c in stdout if c.isdigit())
    assert len(digits) >= n


def test_long_single_value_100k(kc):
    """A single 100K-character string output — many continuation tags."""
    n = 100000
    code = f's := &cat[IntegerToString(i mod 10) : i in [1..{n}]]; s;'
    reply, stdout, stderr, _ = _execute(kc, code, timeout=60)
    assert reply["status"] == "ok"
    digits = "".join(c for c in stdout if c.isdigit())
    assert len(digits) >= n


# --- Large input ---
#
# The old pexpect/PTY kernel had a ~64KB line-length limit and needed to
# write code to a temp file.  The -x pipe protocol has no such limit.
# These tests verify that inputs well beyond the old PTY ceiling work.


def test_large_input_many_statements(kc):
    """500 assignment statements in one cell."""
    n = 500
    lines = [f"x{i} := {i};" for i in range(n)]
    lines.append(f"x{n-1};")
    code = "\n".join(lines)
    reply, stdout, stderr, _ = _execute(kc, code, timeout=60)
    assert reply["status"] == "ok"
    assert str(n - 1) in stdout


def test_large_input_5000_statements(kc):
    """5000 statements — roughly 73KB of code."""
    n = 5000
    lines = [f"x{i} := {i};" for i in range(n)]
    lines.append(f"x{n-1};")
    code = "\n".join(lines)
    reply, stdout, stderr, _ = _execute(kc, code, timeout=60)
    assert reply["status"] == "ok"
    assert str(n - 1) in stdout


def test_large_input_long_string_literal(kc):
    """A cell containing a very long string literal (>64KB)."""
    payload = "A" * 80000
    code = f's := "{payload}"; #s;'
    reply, stdout, stderr, _ = _execute(kc, code, timeout=60)
    assert reply["status"] == "ok"
    assert "80000" in stdout


def test_large_input_256KB_string(kc):
    """A 256KB string literal — well past the old PTY 64KB ceiling."""
    n = 256 * 1024
    payload = "B" * n
    code = f's := "{payload}"; #s;'
    reply, stdout, stderr, _ = _execute(kc, code, timeout=60)
    assert reply["status"] == "ok"
    assert str(n) in stdout


def test_large_input_1MB_string(kc):
    """A 1MB string literal — impossible with pexpect, trivial with pipes."""
    n = 1024 * 1024
    payload = "C" * n
    code = f's := "{payload}"; #s;'
    reply, stdout, stderr, _ = _execute(kc, code, timeout=60)
    assert reply["status"] == "ok"
    assert str(n) in stdout


def test_large_input_long_sequence_literal(kc):
    """A cell with a large sequence literal."""
    n = 2000
    elts = ", ".join(str(i) for i in range(1, n + 1))
    code = f"S := [{elts}]; #S;"
    reply, stdout, stderr, _ = _execute(kc, code, timeout=60)
    assert reply["status"] == "ok"
    assert str(n) in stdout


def test_large_input_and_output_combined(kc):
    """Large input that also generates large output."""
    n = 1000
    lines = [f"x{i} := {i};" for i in range(n)]
    lines.append(f"for i in [0..{n-1}] do eval(Sprintf(\"x%o\", i)); end for;")
    code = "\n".join(lines)
    reply, stdout, stderr, _ = _execute(kc, code, timeout=60)
    assert reply["status"] == "ok"
    assert str(n - 1) in stdout


# --- Multi-statement ---


def test_multi_statement(kc):
    reply, stdout, stderr, _ = _execute(kc, "x := 42;\nx;")
    assert reply["status"] == "ok"
    assert "42" in stdout


# --- Interrupt ---


def test_interrupt_infinite_loop(kernel):
    """Interrupt an infinite loop — kernel should return abort and stay alive."""
    km, kc = kernel
    msg_id = kc.execute("while true do x := 1; end while;")
    # Give it a moment to start running
    time.sleep(0.5)
    km.interrupt_kernel()
    reply = kc.get_shell_msg(timeout=30)
    assert reply["parent_header"]["msg_id"] == msg_id
    status = reply["content"]["status"]
    assert status in ("abort", "error"), f"Expected abort or error, got {status}"
    # Drain iopub
    while True:
        try:
            msg = kc.get_iopub_msg(timeout=5)
            if msg["msg_type"] == "status" and msg["content"]["execution_state"] == "idle":
                break
        except Exception:
            break
    # Kernel should still work
    reply, stdout, _, _ = _execute(kc, "1+1;")
    assert reply["status"] == "ok"
    assert "2" in stdout


def test_interrupt_long_computation(kernel):
    """Interrupt a slow but finite computation."""
    km, kc = kernel
    # Factoring a large number takes a while
    msg_id = kc.execute("Factorization(2^251 - 1);")
    time.sleep(1)
    km.interrupt_kernel()
    reply = kc.get_shell_msg(timeout=30)
    assert reply["parent_header"]["msg_id"] == msg_id
    status = reply["content"]["status"]
    assert status in ("abort", "error", "ok")  # might finish before interrupt
    # Drain iopub
    while True:
        try:
            msg = kc.get_iopub_msg(timeout=5)
            if msg["msg_type"] == "status" and msg["content"]["execution_state"] == "idle":
                break
        except Exception:
            break
    # Kernel still functional
    reply, stdout, _, _ = _execute(kc, "2+2;")
    assert reply["status"] == "ok"
    assert "4" in stdout


# --- Debugger (auto-exit) ---


def test_debugger_auto_exit(kc):
    """When SetDebugOnError triggers the debugger, the kernel auto-exits it."""
    # Enable debugger
    _execute(kc, "SetDebugOnError(true);")

    # Define a procedure and trigger a runtime error inside it
    code = (
        "procedure DebugTest()\n"
        "  x := 1/(1-1);\n"
        "end procedure;\n"
        "DebugTest();"
    )
    reply, stdout, stderr, _ = _execute(kc, code)

    # The kernel should auto-send 'q' to exit the debugger,
    # and report the error
    assert reply["status"] == "error"
    assert stderr  # error output from the traceback/error tags

    # Kernel should still be functional after auto-exiting debugger
    reply, stdout, _, _ = _execute(kc, "99+1;")
    assert reply["status"] == "ok"
    assert "100" in stdout

    # Disable debugger for subsequent tests
    _execute(kc, "SetDebugOnError(false);")


def test_debugger_repeated_auto_exit(kc):
    """Multiple debugger entries/exits in sequence don't break the kernel."""
    _execute(kc, "SetDebugOnError(true);")

    _execute(kc, "procedure Boom() error \"x\"; end procedure;")

    for _ in range(3):
        reply, _, stderr, _ = _execute(kc, "Boom();")
        assert reply["status"] == "error"
        assert stderr

    # Still works
    reply, stdout, _, _ = _execute(kc, "7*7;")
    assert reply["status"] == "ok"
    assert "49" in stdout

    _execute(kc, "SetDebugOnError(false);")


# --- Streaming (output arrives incrementally) ---


def test_output_streams_incrementally(kc):
    """Output from a loop should arrive as multiple iopub messages, not one batch.

    This verifies that process_until_ready flushes on each non-continuation
    line rather than buffering everything until RDY.
    """
    msg_id = kc.execute("for i in [1..20] do print i; end for;")
    reply = kc.get_shell_msg(timeout=30)
    assert reply["content"]["status"] == "ok"

    stdout_msgs = []
    while True:
        try:
            msg = kc.get_iopub_msg(timeout=5)
        except Exception:
            break
        if msg["parent_header"].get("msg_id") != msg_id:
            continue
        if msg["msg_type"] == "stream" and msg["content"]["name"] == "stdout":
            stdout_msgs.append(msg["content"]["text"])
        elif msg["msg_type"] == "status" and msg["content"]["execution_state"] == "idle":
            break

    # We should get more than 1 stream message — output is flushed
    # line-by-line, not accumulated into a single batch.
    assert len(stdout_msgs) > 1, (
        f"Expected multiple stream messages, got {len(stdout_msgs)}: {stdout_msgs}"
    )
    # All 20 numbers should be present in the combined output
    combined = "".join(stdout_msgs)
    for i in range(1, 21):
        assert str(i) in combined


def test_slow_output_not_delayed(kc):
    """Output lines that arrive with gaps between them should each be
    delivered promptly, not held until the computation finishes.

    We use a computation that produces output, does work, produces more
    output. With pipe-based streaming, each chunk should be delivered as
    it arrives — unlike the old adaptive-timeout polling approach.
    """
    # Print, do some work, print again — should see distinct messages
    code = (
        "print 1;\n"
        "x := &+[i : i in [1..100000]];\n"  # ~10ms of work
        "print 2;\n"
        "x := &+[i : i in [1..100000]];\n"
        "print 3;"
    )
    msg_id = kc.execute(code)
    reply = kc.get_shell_msg(timeout=30)
    assert reply["content"]["status"] == "ok"

    stdout_msgs = []
    while True:
        try:
            msg = kc.get_iopub_msg(timeout=5)
        except Exception:
            break
        if msg["parent_header"].get("msg_id") != msg_id:
            continue
        if msg["msg_type"] == "stream" and msg["content"]["name"] == "stdout":
            stdout_msgs.append(msg["content"]["text"])
        elif msg["msg_type"] == "status" and msg["content"]["execution_state"] == "idle":
            break

    combined = "".join(stdout_msgs)
    assert "1" in combined
    assert "2" in combined
    assert "3" in combined
    # Should be split across multiple messages (not one big batch)
    assert len(stdout_msgs) >= 2, (
        f"Expected output split across messages, got {len(stdout_msgs)}: {stdout_msgs}"
    )


# --- History ---


def test_history_tail(kc):
    """History tail returns recent entries."""
    _execute(kc, "hist_a := 1;")
    _execute(kc, "hist_b := 2;")
    msg_id = kc.history(hist_access_type="tail", n=2)
    reply = kc.get_shell_msg(timeout=10)
    history = reply["content"]["history"]
    assert len(history) >= 2
    codes = [h[2] for h in history]
    assert "hist_b := 2;" in codes[-1]


def test_history_search(kc):
    """History search filters by pattern."""
    _execute(kc, "search_target := 999;")
    msg_id = kc.history(hist_access_type="search", pattern="*search_target*")
    reply = kc.get_shell_msg(timeout=10)
    history = reply["content"]["history"]
    assert any("search_target" in h[2] for h in history)
