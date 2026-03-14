# magma_kernel

A Jupyter kernel for the [Magma computer algebra system](http://magma.maths.usyd.edu.au/).

## Features

- Error detection with proper cell status reporting
- Tab completion via Magma's built-in `Completion()` intrinsic
- `?keyword` opens a search link to Magma's online handbook
- Streaming output for long-running computations
- Automatic semicolon appending for bare statements
- Handles arbitrarily long cells (code is sent via temp files)
- Multi-line input support in `jupyter console`

## Prerequisites

- [Magma](http://magma.maths.usyd.edu.au/) installed and available on your `PATH`
- Python 3.8+
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

## Verify installation

```
jupyter kernelspec list
```

You should see `magma` in the output. Then:

```
jupyter console --kernel magma
```

## Troubleshooting

- **Kernel won't start**: check that `which magma` returns a valid path.
- **Kernel hangs on startup**: Magma must respond within 30 seconds. Check that `magma -b` starts correctly in a terminal.

## Credits

Based on [takluyver/bash_kernel](https://github.com/takluyver/bash_kernel) and [cgranade/magma_kernel](https://github.com/cgranade/magma_kernel).
Streaming output and help-link processing from [nbruin/magma_kernel](https://github.com/nbruin/magma_kernel).

For details of how this works, see the Jupyter docs on
[wrapper kernels](https://jupyter-client.readthedocs.io/en/latest/wrapperkernels.html) and
Pexpect's docs on the [spawn class](https://pexpect.readthedocs.io/en/latest/api/pexpect.html#spawn-class).
