#!/usr/bin/env python
## -*- encoding: utf-8 -*-

import os
import sys
from setuptools import setup
from codecs import open # To open the README file with proper encoding
from setuptools.command.test import test as TestCommand # for tests
from setuptools.extension import Extension

# Get information from separate files (README, VERSION)
def readfile(filename):
    with open(filename,  encoding='utf-8') as f:
        return f.read()

from magma_kernel import __version__ as magma_kernel_version

setup(
    name="magma_kernel",
    author="Edgar Costa",
    author_email="edgarcosta@math.dartmouth.edu",
    url="https://github.com/edgarcosta/magma_kernel",
    license="BSD 3-Clause License",
    description="A magma kernel for Jupyter",
    long_description = readfile("README.rst"), # get the long description from the README
    version = magma_kernel_version,
    classifiers=[
      # How mature is this project? Common values are
      #   3 - Alpha
      #   4 - Beta
      #   5 - Production/Stable
      'Development Status :: 4 - Beta',
      'Intended Audience :: Science/Research',
      'Topic :: Scientific/Engineering :: Mathematics',
      'License :: OSI Approved :: BSD 3-Clause License',
      'Programming Language :: Python :: 2.7',
    ], # classifiers list: https://pypi.python.org/pypi?%3Aaction=list_classifiers
    keywords = "magma kernel jupyter",
    setup_requires=[], # currently useless, see https://www.python.org/dev/peps/pep-0518/
    install_requires=[],
    packages=["magma_kernel"],
    include_package_data = True,
)

from magma_kernel.install import main
main(argv=sys.argv)
