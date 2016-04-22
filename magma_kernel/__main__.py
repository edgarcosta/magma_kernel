from ipykernel.kernelapp import IPKernelApp
from .kernel import MagmaKernel
IPKernelApp.launch_instance(kernel_class=MagmaKernel)
