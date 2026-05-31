"""Unit tests for MagmaKernel with a mocked Magma process.

These tests do not require Magma on PATH.  They construct a MagmaKernel
without invoking ``_start_magma`` and stub ``kernel.process`` with a
``MagicMock``, then drive the kernel's reply-handling logic by setting
``process_until_ready`` return values.
"""

import logging
from unittest.mock import MagicMock

import pytest

from magma_kernel.kernel import MagmaKernel
from magma_kernel.protocol import ExecutionResult, MagmaState


@pytest.fixture
def kernel():
    """Build a MagmaKernel with a mocked process — no Magma required."""
    k = MagmaKernel.__new__(MagmaKernel)
    k.log = logging.getLogger("test_kernel_unit")
    k.iopub_socket = MagicMock()
    k.execution_count = 1
    k._history = []
    k._history_count = 0
    k.send_response = MagicMock()
    k.process = MagicMock()
    k.process.alive = True
    return k


def test_execute_loops_through_nested_debugger(kernel):
    """If 'q' yields another DRDY, the kernel sends another 'q' and so on."""
    results = iter([
        ExecutionResult(state=MagmaState.DEBUGGER, had_error=True),
        ExecutionResult(state=MagmaState.DEBUGGER),
        ExecutionResult(state=MagmaState.READY),
    ])
    kernel.process.process_until_ready = lambda cb: next(results)

    reply = kernel._execute_code("DebugMe();", silent=False, allow_stdin=False)

    # First DEBUGGER's had_error must be preserved through to the final reply
    assert reply["status"] == "error"
    # send_line("q") should have been called exactly twice — once per DEBUGGER
    q_calls = [c for c in kernel.process.send_line.call_args_list
               if c.args == ("q",)]
    assert len(q_calls) == 2


def test_execute_gives_up_on_wedged_debugger(kernel):
    """If Magma stays in DEBUGGER indefinitely, the kernel must not loop forever."""
    kernel.process.process_until_ready = lambda cb: ExecutionResult(
        state=MagmaState.DEBUGGER, had_error=True,
    )
    # If stop/restart is needed, mock them so the kernel can recover cleanly.
    kernel.process.stop = MagicMock()
    kernel._start_magma = MagicMock(side_effect=lambda: setattr(
        kernel, "process", MagicMock(alive=True),
    ))

    reply = kernel._execute_code("DebugMe();", silent=False, allow_stdin=False)

    # The reply must be terminal (not stuck in a loop) — error or abort is fine,
    # but it must come back.
    assert reply["status"] in ("error", "abort")


def test_do_complete_warns_when_process_dies_mid_call(kernel, caplog):
    """do_complete should warn and return default when Magma dies during the call."""
    kernel.process.process_until_ready = lambda cb: ExecutionResult(
        state=MagmaState.DEAD,
    )

    with caplog.at_level(logging.WARNING, logger="test_kernel_unit"):
        result = kernel.do_complete("IsPr", 4)

    assert result["matches"] == []
    assert any("completion" in rec.message.lower()
               and ("died" in rec.message.lower() or "dead" in rec.message.lower())
               for rec in caplog.records)


def test_magma_eval_logs_when_process_dies(kernel, caplog):
    """_magma_eval should log a warning if process_until_ready returns DEAD."""
    kernel.process.process_until_ready = lambda cb: ExecutionResult(
        state=MagmaState.DEAD,
    )

    with caplog.at_level(logging.WARNING, logger="test_kernel_unit"):
        stdout, stderr = kernel._magma_eval("Foo;")

    # Should not raise; should produce a warning in the log.
    assert any("died" in rec.message.lower() or "dead" in rec.message.lower()
               for rec in caplog.records)


class TestDoCompleteSendInputRaises:
    """do_complete must return the default reply if send_input raises."""

    def _make_kernel(self):
        import logging
        from magma_kernel.kernel import MagmaKernel
        k = MagmaKernel.__new__(MagmaKernel)
        # Minimum viable wiring: process is replaced by a stub.
        class _StubProc:
            alive = True
            def send_input(self, payload):
                raise BrokenPipeError("pipe closed")
            def process_until_ready(self, cb):
                raise AssertionError("should not be called")
        k.process = _StubProc()
        k.log = logging.getLogger("test")
        return k

    def test_do_complete_returns_default_on_brokenpipe(self):
        k = self._make_kernel()
        reply = k.do_complete("IsPrime", 7)
        assert reply["status"] == "ok"
        assert reply["matches"] == []
        assert reply["cursor_start"] == 0
        assert reply["cursor_end"] == 7
