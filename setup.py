#!/usr/bin/env python
## -*- encoding: utf-8 -*-

import sys
from setuptools import setup
from setuptools.command.install import install as _install

class install(_install):
    def run(self):
        # run from distutils install
        _install.run(self)
        from .magma_kernel.install import main

        main(argv=sys.argv)


setup(
    cmdclass={"install": install},
)
