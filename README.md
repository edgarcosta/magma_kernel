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

You must have [Jupyter](https://jupyter.org/) installed in your system. 



If you are using [Jupyter](https://jupyter.org/) as a standalone, you can install `magma_kernel` by doing

```
pip install git+https://github.com/edgarcosta/magma_kernel.git
```


Alternatively, if you have 
[SageMath](http://www.sagemath.org/) (which includes [Jupyter](https://jupyter.org/) as one of its packages), then you can install `magma_kernel` by doing:

```
sage -pip install git+https://github.com/edgarcosta/magma_kernel.git
```
This way you will have automatically the kernels for `magma` and `sage` in the same jupyter environment.

Consider adding the flag `--user` if you do not have permissions to install it system-wide.



## Credit & Others
Based on [takluyver/bash_kernel](https://github.com/takluyver/bash_kernel) and [cgranade/magma_kernel](https://github.com/cgranade/magma_kernel).
Reporting partial output and processing of help requests by returning an appropriate help query URL for Magma online documentation provided by [nbruin/magma_kernel](https://github.com/nbruin/magma_kernel).

For details of how this works, see the Jupyter docs on 
[wrapper kernels](http://jupyter-client.readthedocs.org/en/latest/wrapperkernels.html), and
Pexpect's docs on the [spawn class](https://pexpect.readthedocs.io/en/latest/api/pexpect.html#spawn-class)
