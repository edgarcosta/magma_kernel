#!/usr/bin/env python
## -*- encoding: utf-8 -*-

import sys
from setuptools import setup
from setuptools.command.install import install as _install
from codecs import open # To open the README file with proper encoding
#from setuptools.command.test import test as TestCommand # for tests
#from setuptools.extension import Extension

# Get information from separate files (README, VERSION)
def readfile(filename):
    with open(filename,  encoding='utf-8') as f:
        return f.read()

class install(_install):
    def run(self):
        # run from distutils install
        _install.run(self)
        from magma_kernel.install import main
        main(argv=sys.argv)

setup(
    name="magma_kernel",
    author="Edgar Costa",
    author_email="edgarcosta@math.dartmouth.edu",
    url="https://github.com/edgarcosta/magma_kernel",
    license="BSD 3-Clause License",
    description="A magma kernel for Jupyter",
    long_description = readfile("README.rst"), # get the long description from the README
    version = readfile("VERSION"),
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
    install_requires=['pexpect>=4.0'],
    packages=["magma_kernel"],
    package_dir={"magma_kernel": "magma_kernel"}
           , package_data={"magma_kernel": ["*"]},
    include_package_data = True,
    cmdclass={'install': install},
)


