# magma_kernel

A simple IPython kernel for magma.

## Features:

- Auto adds semicolons at the end of code blocks
- Uses magma's built-in tab completion
- Supports long lines

<p align="center">
<img src="https://raw.githubusercontent.com/edgarcosta/i/master/magma_kernel.gif" height="800">
</p>

## Installation

You must have [Jupyter](https://jupyter.org/) installed in your system. For example, it comes with
[SageMath](http://www.sagemath.org/).
If are using [SageMath](http://www.sagemath.org/), you can install `magma_kernel` by doing:

```
sage -pip install git+https://github.com/edgarcosta/magma_kernel.git
```

if you are using [Jupyter](https://jupyter.org/) as a standalone, you can install `magma_kernel` by doing

```
pip install git+https://github.com/edgarcosta/magma_kernel.git
```

Consider adding the flag `--user` if you do not have permissions to install it system-wide.



## Credit & Others
Based on [takluyver/bash_kernel](https://github.com/takluyver/bash_kernel) and [cgranade/magma_kernel](https://github.com/cgranade/magma_kernel).

For details of how this works, see the Jupyter docs on 
[wrapper kernels](http://jupyter-client.readthedocs.org/en/latest/wrapperkernels.html), and
Pexpect's docs on the [replwrap module](http://pexpect.readthedocs.org/en/latest/api/replwrap.html)
