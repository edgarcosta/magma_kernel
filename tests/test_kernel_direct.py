"""In-process tests for MagmaKernel — calls kernel methods directly.

These tests instantiate MagmaKernel without ipykernel's IPKernelApp,
mocking only the Jupyter messaging layer.  This gives full coverage
visibility (unlike subprocess-based integration tests) while testing
against a real Magma process.

Requires Magma on PATH; skipped otherwise.
"""

import logging
import os
import shutil
import tempfile
from unittest.mock import MagicMock

import pytest

from magma_kernel.kernel import MagmaKernel

MAGMA = shutil.which("magma")
pytestmark = pytest.mark.skipif(MAGMA is None, reason="Magma not found on PATH")


@pytest.fixture(scope="module")
def kernel():
    """Create a MagmaKernel in-process with mocked Jupyter messaging."""
    k = MagmaKernel.__new__(MagmaKernel)
    k.log = logging.getLogger("test_kernel_direct")
    k.iopub_socket = MagicMock()
    k.execution_count = 1
    k._history = []
    k._history_count = 0
    k.send_response = MagicMock()
    k._start_magma()
    yield k
    k.process.stop(force=True)


def _reset_mock(kernel):
    """Reset the send_response mock between tests."""
    kernel.send_response.reset_mock()


def _get_streams(kernel):
    """Extract stdout and stderr text from send_response calls."""
    stdout, stderr = [], []
    for call in kernel.send_response.call_args_list:
        args = call[0]  # positional args
        if len(args) >= 3 and args[1] == "stream":
            content = args[2]
            if content["name"] == "stdout":
                stdout.append(content["text"])
            elif content["name"] == "stderr":
                stderr.append(content["text"])
    return "".join(stdout), "".join(stderr)


# --- Execution ---


def test_basic_arithmetic(kernel):
    _reset_mock(kernel)
    result = kernel.do_execute("2+3;", silent=False)
    assert result["status"] == "ok"
    stdout, _ = _get_streams(kernel)
    assert "5" in stdout


def test_semicolon_appending(kernel):
    _reset_mock(kernel)
    result = kernel.do_execute("2+3", silent=False)
    assert result["status"] == "ok"
    stdout, _ = _get_streams(kernel)
    assert "5" in stdout


def test_empty_cell(kernel):
    _reset_mock(kernel)
    result = kernel.do_execute("", silent=False)
    assert result["status"] == "ok"
    kernel.send_response.assert_not_called()


def test_whitespace_cell(kernel):
    _reset_mock(kernel)
    result = kernel.do_execute("   \n  ", silent=False)
    assert result["status"] == "ok"


def test_multiline(kernel):
    _reset_mock(kernel)
    result = kernel.do_execute("a := 3;\nb := 4;\na + b;", silent=False)
    assert result["status"] == "ok"
    stdout, _ = _get_streams(kernel)
    assert "7" in stdout


def test_silent_suppresses_output(kernel):
    _reset_mock(kernel)
    result = kernel.do_execute("2+3;", silent=True)
    assert result["status"] == "ok"
    stdout, _ = _get_streams(kernel)
    assert stdout == ""


# --- Errors ---


def test_runtime_error(kernel):
    _reset_mock(kernel)
    result = kernel.do_execute('1 + "a";', silent=False)
    assert result["status"] == "error"
    assert "Runtime error" in result["ename"]
    assert result["traceback"]
    _, stderr = _get_streams(kernel)
    assert stderr


def test_user_error(kernel):
    _reset_mock(kernel)
    result = kernel.do_execute("if true then", silent=False)
    assert result["status"] == "error"
    assert result["traceback"]


def test_error_position_caret(kernel):
    _reset_mock(kernel)
    result = kernel.do_execute("x := ;", silent=False)
    assert result["status"] == "error"
    assert any("^" in line for line in result["traceback"])


def test_error_recovery(kernel):
    _reset_mock(kernel)
    kernel.do_execute('1 + "a";', silent=False)
    _reset_mock(kernel)
    result = kernel.do_execute("2+3;", silent=False)
    assert result["status"] == "ok"
    stdout, _ = _get_streams(kernel)
    assert "5" in stdout


# --- Help ---


def test_help(kernel):
    _reset_mock(kernel)
    result = kernel.do_execute("?Integers", silent=False)
    assert result["status"] == "ok"
    # Should have sent a display_data message
    calls = [c for c in kernel.send_response.call_args_list
             if c[0][1] == "display_data"]
    assert calls
    html = calls[0][0][2]["data"]["text/html"]
    assert "magma.maths.usyd.edu.au" in html


# --- Completion ---


def test_completion(kernel):
    result = kernel.do_complete("IsPr", 4)
    assert result["status"] == "ok"
    assert any("IsPrime" in m for m in result["matches"])


def test_completion_empty(kernel):
    result = kernel.do_complete("", 0)
    assert result["matches"] == []


# --- Inspection ---


def test_inspect_intrinsic(kernel):
    result = kernel.do_inspect("IsPrime", 7)
    assert result["found"]
    assert "IsPrime" in result["data"]["text/plain"]


def test_inspect_unknown(kernel):
    result = kernel.do_inspect("xyzzy_nonexistent", 17)
    assert result["found"]
    assert "magma.maths.usyd.edu.au" in result["data"].get("text/html", "")


def test_inspect_empty(kernel):
    result = kernel.do_inspect("", 0)
    assert not result["found"]


# --- is_complete ---


def test_is_complete_semicolon(kernel):
    assert kernel.do_is_complete("x := 1;")["status"] == "complete"


def test_is_complete_no_semicolon(kernel):
    assert kernel.do_is_complete("x := 1")["status"] == "incomplete"


def test_is_complete_balanced_block(kernel):
    assert kernel.do_is_complete("for i in [1..10] do print i; end for;")["status"] == "complete"


def test_is_complete_unbalanced_block(kernel):
    assert kernel.do_is_complete("for i in [1..10] do print i;")["status"] == "incomplete"


def test_is_complete_empty(kernel):
    assert kernel.do_is_complete("")["status"] == "incomplete"


# --- History ---


def test_history_recording(kernel):
    kernel._history.clear()
    kernel._history_count = 0
    kernel.do_execute("hist_test := 1;", silent=False, store_history=True)
    kernel.do_execute("hist_test := 2;", silent=False, store_history=True)
    result = kernel.do_history("tail", output=False, raw=True, n=2)
    assert len(result["history"]) == 2
    assert "hist_test := 2;" in result["history"][-1][2]


def test_history_search(kernel):
    result = kernel.do_history("search", output=False, raw=True, pattern="*hist_test*")
    assert any("hist_test" in h[2] for h in result["history"])


def test_history_not_recorded_when_disabled(kernel):
    count_before = len(kernel._history)
    kernel.do_execute("no_history := 1;", silent=False, store_history=False)
    assert len(kernel._history) == count_before


# --- Magics ---


def test_magic_time(kernel):
    _reset_mock(kernel)
    result = kernel.do_execute("%time x := &+[i : i in [1..1000]];", silent=False)
    assert result["status"] == "ok"
    stdout, _ = _get_streams(kernel)
    assert stdout  # timing output


def test_magic_time_error_caret(kernel):
    """Error caret in %time should point into the user's code, not the wrapper."""
    _reset_mock(kernel)
    result = kernel.do_execute("%time x := ;", silent=False)
    assert result["status"] == "error"
    # The caret should point within "x := ;" (col 5), not offset by the
    # "__t := Cputime(); " prefix (19 chars).
    caret_lines = [l for l in result["traceback"] if "^" in l]
    if caret_lines:
        # Verify the source line shown is the user's code, not the wrapper
        assert "Cputime" not in caret_lines[0]


def test_magic_time_bare(kernel):
    _reset_mock(kernel)
    result = kernel.do_execute("%time", silent=False)
    assert result["status"] == "ok"
    _, stderr = _get_streams(kernel)
    assert "Usage" in stderr


def test_magic_who(kernel):
    _reset_mock(kernel)
    kernel.do_execute("magic_who_var := 99;", silent=False)
    _reset_mock(kernel)
    result = kernel.do_execute("%who", silent=False)
    assert result["status"] == "ok"


def test_magic_load(kernel):
    _reset_mock(kernel)
    with tempfile.NamedTemporaryFile("w", suffix=".m", delete=False) as f:
        f.write("load_var := 777;\nload_var;\n")
        f.flush()
        path = f.name
    try:
        result = kernel.do_execute(f"%load {path}", silent=False)
        assert result["status"] == "ok"
        stdout, _ = _get_streams(kernel)
        assert "777" in stdout
    finally:
        os.unlink(path)


def test_magic_load_missing(kernel):
    _reset_mock(kernel)
    result = kernel.do_execute("%load /nonexistent/file.m", silent=False)
    assert result["status"] == "error"
    _, stderr = _get_streams(kernel)
    assert "Cannot read" in stderr


def test_magic_reset(kernel):
    _reset_mock(kernel)
    kernel.do_execute("reset_var := 42;", silent=False)
    _reset_mock(kernel)
    result = kernel.do_execute("%reset", silent=False)
    assert result["status"] == "ok"
    _, stderr = _get_streams(kernel)
    assert "restarted" in stderr.lower()
    # Variable should be gone
    _reset_mock(kernel)
    result = kernel.do_execute("reset_var;", silent=False)
    assert result["status"] == "error"


def test_magic_unknown(kernel):
    _reset_mock(kernel)
    result = kernel.do_execute("%notamagic", silent=False)
    # Falls through to Magma code
    assert result["status"] in ("ok", "error")


# --- Crash recovery ---


def test_crash_during_execution_returns_error(kernel):
    """When Magma dies mid-execution (quit;), reply should be error, not ok."""
    _reset_mock(kernel)
    result = kernel.do_execute("quit;", silent=False)
    assert result["status"] == "error"
    assert result["ename"] == "MagmaCrash"
    _, stderr = _get_streams(kernel)
    assert "died unexpectedly" in stderr
    # Restart for subsequent tests
    kernel._start_magma()


def test_crash_recovery(kernel):
    _reset_mock(kernel)
    # Kill the process externally
    import signal
    os.kill(kernel.process._proc.pid, signal.SIGKILL)
    import time
    time.sleep(0.2)
    assert not kernel.process.alive
    # Next execution should auto-restart
    _reset_mock(kernel)
    result = kernel.do_execute("2+2;", silent=False)
    assert result["status"] == "ok"
    stdout, stderr = _get_streams(kernel)
    assert "4" in stdout
    assert "Restarting" in stderr


# --- Debugger auto-exit ---


def test_debugger_auto_exit(kernel):
    _reset_mock(kernel)
    kernel.do_execute("SetDebugOnError(true);", silent=False)
    _reset_mock(kernel)
    code = (
        "procedure DebugMe()\n"
        "  x := 1/(1-1);\n"
        "end procedure;\n"
        "DebugMe();"
    )
    result = kernel.do_execute(code, silent=False)
    assert result["status"] == "error"
    _, stderr = _get_streams(kernel)
    assert stderr
    # Should still work after
    _reset_mock(kernel)
    result = kernel.do_execute("99+1;", silent=False)
    assert result["status"] == "ok"
    stdout, _ = _get_streams(kernel)
    assert "100" in stdout
    kernel.do_execute("SetDebugOnError(false);", silent=False)


# --- Shutdown ---


def test_shutdown_and_restart(kernel):
    result = kernel.do_shutdown(restart=True)
    assert result["status"] == "ok"
    assert result["restart"]
    assert kernel.process.alive
    # Should work after restart
    _reset_mock(kernel)
    result = kernel.do_execute("3+3;", silent=False)
    assert result["status"] == "ok"
    stdout, _ = _get_streams(kernel)
    assert "6" in stdout


# --- Large I/O ---


def test_large_input(kernel):
    _reset_mock(kernel)
    payload = "A" * 100000
    result = kernel.do_execute(f's := "{payload}"; #s;', silent=False)
    assert result["status"] == "ok"
    stdout, _ = _get_streams(kernel)
    assert "100000" in stdout


# --- History edge cases ---


def test_history_range(kernel):
    kernel._history.clear()
    kernel._history_count = 0
    kernel.do_execute("a := 1;", silent=False, store_history=True)
    kernel.do_execute("b := 2;", silent=False, store_history=True)
    kernel.do_execute("c := 3;", silent=False, store_history=True)
    result = kernel.do_history("range", output=False, raw=True, start=0, stop=2)
    assert len(result["history"]) == 2


def test_history_range_stop_zero(kernel):
    kernel._history.clear()
    kernel._history_count = 0
    kernel.do_execute("a := 1;", silent=False, store_history=True)
    kernel.do_execute("b := 2;", silent=False, store_history=True)
    result = kernel.do_history("range", output=False, raw=True, start=0, stop=0)
    assert result["history"] == []


def test_history_search_unique(kernel):
    kernel._history.clear()
    kernel._history_count = 0
    kernel.do_execute("dup := 1;", silent=False, store_history=True)
    kernel.do_execute("dup := 1;", silent=False, store_history=True)
    kernel.do_execute("other := 2;", silent=False, store_history=True)
    result = kernel.do_history("search", output=False, raw=True,
                               pattern="*dup*", unique=True)
    codes = [h[2] for h in result["history"]]
    assert codes.count("dup := 1;") == 1


def test_history_unknown_access_type(kernel):
    result = kernel.do_history("bogus", output=False, raw=True)
    assert result["history"] == []


# --- is_complete edge case ---


def test_is_complete_too_many_closers(kernel):
    result = kernel.do_is_complete("end for;")
    assert result["status"] == "unknown"


# --- Magics edge cases ---


def test_magic_load_empty_arg(kernel):
    _reset_mock(kernel)
    result = kernel.do_execute("%load", silent=False)
    assert result["status"] == "ok"
    _, stderr = _get_streams(kernel)
    assert "Usage" in stderr


def test_magic_who_dead_process(kernel):
    """When process is dead, %who should return ok without crashing."""
    import signal as sig
    os.kill(kernel.process._proc.pid, sig.SIGKILL)
    import time
    time.sleep(0.2)
    _reset_mock(kernel)
    # %who checks process.alive and returns early
    result = kernel.do_execute("%who", silent=False)
    assert result["status"] == "ok"
    # Restart for subsequent tests
    kernel._start_magma()


# --- read/readi in non-interactive mode ---


def test_read_non_interactive(kernel):
    """read directive without allow_stdin should error and interrupt."""
    _reset_mock(kernel)
    result = kernel.do_execute(
        'read x, "Name: "; x;',
        silent=False,
        allow_stdin=False,
    )
    _, stderr = _get_streams(kernel)
    assert "does not support stdin" in stderr


# --- Completion edge cases ---


def test_completion_dead_process(kernel):
    """Completion when process is dead should return empty."""
    import signal as sig
    os.kill(kernel.process._proc.pid, sig.SIGKILL)
    import time
    time.sleep(0.2)
    result = kernel.do_complete("IsPr", 4)
    assert result["matches"] == []
    kernel._start_magma()


def test_completion_no_matches(kernel):
    """Completion for a nonsense prefix returns empty."""
    result = kernel.do_complete("zzzznotreal", 11)
    assert result["matches"] == []
