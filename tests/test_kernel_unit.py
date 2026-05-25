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
