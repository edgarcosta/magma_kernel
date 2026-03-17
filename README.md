# magma_kernel

A Jupyter kernel for the [Magma computer algebra system](http://magma.maths.usyd.edu.au/).

## Features

- **Structured `-x` protocol** — communicates with Magma via pipes, no PTY hacks or temp files
- **Errors to stderr** — runtime, parse, and user errors are routed to stderr with structured error replies and caret position annotations
- **Tab completion** — via Magma's built-in `Completion()` intrinsic
- **Shift-tab inspection** — shows intrinsic signatures, falls back to handbook links
- **Streaming output** — output is delivered line-by-line as it is produced, not buffered
- **Syntax highlighting** — Pygments lexer powered by [tree-sitter-magma](https://github.com/edgarcosta/tree-sitter-magma) for accurate context-sensitive highlighting in `nbconvert` exports
- **`?keyword`** — opens a search link to Magma's online handbook
- **Automatic semicolon appending** for bare statements
- **No input size limit** — code is piped directly (the old PTY approach had a ~64KB limit)
- **Multi-line input support** with keyword balancing (`for`/`end for`, `if`/`end if`, etc.)
- **Interrupt handling** — Ctrl-C sends SIGINT to the Magma process group
- **Crash recovery** — auto-restarts Magma if the process dies
- **Debugger auto-exit** — if `SetDebugOnError(true)` triggers the debugger, the kernel exits it automatically
- **`read`/`readi` support** — interactive input via Jupyter's stdin; clean error in non-interactive contexts
- **Execution history** — up-arrow history in `jupyter console`
- **Line magics**: `%time`, `%load`, `%who`, `%reset`
- **Help menu links** to the Magma Handbook and Tutorial

## Prerequisites

- [Magma](http://magma.maths.usyd.edu.au/) installed and available on your `PATH` (or set `MAGMA_PATH`)
- Python 3.9+
- [Jupyter](https://jupyter.org/)

## Installation

```
pip install git+https://github.com/edgarcosta/magma_kernel.git
```

With [SageMath](http://www.sagemath.org/) (which includes Jupyter):

```
sage -pip install git+https://github.com/edgarcosta/magma_kernel.git
```

This gives you both the `magma` and `sage` kernels in the same Jupyter environment.

Add `--user` if you do not have permissions to install system-wide.

## Configuration

Set the `MAGMA_PATH` environment variable to use a Magma binary not on your `PATH`:

```
MAGMA_PATH=/opt/magma/magma jupyter notebook
```

## Verify installation

```
jupyter kernelspec list
```

You should see `magma` in the output. Then:

```
jupyter console --kernel magma
```

## Line magics

| Magic | Description |
|-------|-------------|
| `%time <code>` | Report CPU time for a computation |
| `%load <file>` | Read and execute a `.m` file |
| `%who` | List user-defined identifiers |
| `%reset` | Restart the Magma process (clears all state) |

## Troubleshooting

- **Kernel won't start**: check that `which magma` (or `$MAGMA_PATH`) returns a valid path.
- **Kernel hangs on startup**: Magma must respond during startup. Check that `magma -x` starts correctly in a terminal.

## Development

```bash
pip install -e ".[test]"
pytest tests/ -v
```

Tests are split into three files:
- `tests/test_protocol.py` — protocol parser, accumulator, buffering, and live `MagmaProcess` tests
- `tests/test_kernel_direct.py` — in-process kernel tests (calls `do_execute` etc. directly)
- `tests/test_kernel.py` — full Jupyter integration tests via `KernelManager`
- `tests/test_lexer.py` — Pygments lexer tests

Tests that require Magma are skipped automatically when it is not on `PATH`.

## Credits

Based on [takluyver/bash_kernel](https://github.com/takluyver/bash_kernel) and [cgranade/magma_kernel](https://github.com/cgranade/magma_kernel).
Streaming output and help-link processing from [nbruin/magma_kernel](https://github.com/nbruin/magma_kernel).
The `-x` protocol implementation is based on the specification and reference C implementation by Geoff Bailey (see [`docs/xmagma-reference/`](docs/xmagma-reference/)).
Syntax highlighting grammar from [tree-sitter-magma](https://github.com/edgarcosta/tree-sitter-magma).
