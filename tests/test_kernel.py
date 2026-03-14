"""Integration tests for the Magma Jupyter kernel.

These tests start a real Magma kernel process and require Magma to be
available on PATH.  They are skipped automatically when Magma is absent.

Run with:  pytest tests/test_kernel.py -v
"""

import shutil

import pytest
from jupyter_client.manager import KernelManager

MAGMA = shutil.which("magma")
pytestmark = pytest.mark.skipif(MAGMA is None, reason="Magma not found on PATH")


@pytest.fixture(scope="module")
def kc():
    """Start a Magma kernel and yield a blocking client."""
    km = KernelManager(kernel_name="magma")
    km.start_kernel()
    client = km.client()
    client.start_channels()
    client.wait_for_ready(timeout=60)
    yield client
    client.stop_channels()
    km.shutdown_kernel(now=True)


def _execute(kc, code, timeout=30):
    """Execute *code* and return (reply_content, stdout, display_data)."""
    msg_id = kc.execute(code)
    reply = kc.get_shell_msg(timeout=timeout)
    assert reply["parent_header"]["msg_id"] == msg_id

    stdout_parts = []
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
        elif mtype == "display_data":
            display_parts.append(msg["content"])
        elif mtype == "status" and msg["content"]["execution_state"] == "idle":
            break

    return reply["content"], "".join(stdout_parts), display_parts


# --- Execution ---


def test_basic_arithmetic(kc):
    reply, stdout, _ = _execute(kc, "1+1;")
    assert reply["status"] == "ok"
    assert "2" in stdout


def test_semicolon_appending(kc):
    """Bare statements (no trailing ;) should still execute."""
    reply, stdout, _ = _execute(kc, "1+1")
    assert reply["status"] == "ok"
    assert "2" in stdout


def test_multiline_cell(kc):
    code = "a := 3;\nb := 4;\na + b;"
    reply, stdout, _ = _execute(kc, code)
    assert reply["status"] == "ok"
    assert "7" in stdout


def test_empty_cell(kc):
    reply, stdout, _ = _execute(kc, "")
    assert reply["status"] == "ok"
    assert stdout == ""


def test_whitespace_only_cell(kc):
    reply, stdout, _ = _execute(kc, "   \n  ")
    assert reply["status"] == "ok"
    assert stdout == ""


# --- Error detection ---


def test_runtime_error(kc):
    reply, stdout, _ = _execute(kc, '1 + "a";')
    assert reply["status"] == "error"
    assert "Runtime error" in reply["ename"]


def test_user_error(kc):
    """Syntax errors are reported as User error in Magma."""
    reply, stdout, _ = _execute(kc, "if true then")
    assert reply["status"] == "error"
    assert "error" in reply["ename"].lower()


def test_error_does_not_break_subsequent_cells(kc):
    """After an error, the kernel should still work."""
    _execute(kc, '1 + "a";')
    reply, stdout, _ = _execute(kc, "2+3;")
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


# --- Help ---


def test_help_link(kc):
    reply, _, display = _execute(kc, "?Integers")
    assert reply["status"] == "ok"
    assert len(display) > 0
    html = display[0]["data"].get("text/html", "")
    assert "magma.maths.usyd.edu.au" in html
    assert "Integers" in html
