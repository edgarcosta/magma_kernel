import json
import os
import shutil
import sys

from jupyter_client.kernelspec import KernelSpecManager
from IPython.utils.tempdir import TemporaryDirectory

kernel_json = {
    "argv": [sys.executable, "-m", "magma_kernel", "-f", "{connection_file}"],
    "display_name": "Magma",
    "language": "magma",
    "codemirror_mode": "pascal",
    "env": {"PS1": "$"},
}


def install_my_kernel_spec(user=True, prefix=None):
    with TemporaryDirectory() as td:
        os.chmod(td, 0o755)  # Starts off as 700, not user readable
        with open(os.path.join(td, "kernel.json"), "w") as f:
            json.dump(kernel_json, f, sort_keys=True)
        # TODO: Copy resources once they're specified
        shutil.copy("magma_kernel/logo-64x64.png", td)

        print("Installing IPython kernel spec")
        KernelSpecManager().install_kernel_spec(td, "magma", user=user, replace=True, prefix=prefix)


def _is_root():
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False  # assume not an admin on non-Unix platforms


def main(argv=[]):
    user = "--user" in argv or not _is_root()
    install_my_kernel_spec(user=user)


if __name__ == "__main__":
    main(argv=sys.argv)
