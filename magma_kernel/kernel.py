from ipykernel.kernelbase import Kernel
from pexpect import replwrap, EOF, spawn

from subprocess import check_output
from os import unlink

import base64
import imghdr
import re
import signal
import urllib

__version__ = '0.0.1dev1'

version_pat = re.compile(r'version (\d+(\.\d+)+)')

from .images import (
    extract_image_filenames, display_data_for_image, image_setup_cmd
)


class MagmaKernel(Kernel):
    implementation = 'magma_kernel'
    implementation_version = __version__

    '''
    @property
    def language_version(self):
        m = version_pat.search(self.banner)
        return m.group(1)

    _banner = None

    @property
    def banner(self):
        if self._banner is None:
            self._banner = check_output(['bash', '--version']).decode('utf-8')
        return self._banner
    '''
    
    @property
    def banner(self):
        return ""

    language_info = {'name': 'magma',
                     'codemirror_mode': 'magma',
                     'mimetype': 'text/x-sh',
                     'file_extension': '.mgm'}

    def __init__(self, **kwargs):
        Kernel.__init__(self, **kwargs)
        self._start_magma()

    def _start_magma(self):
        # Signal handlers are inherited by forked processes, and we can't easily
        # reset it from the subprocess. Since kernelapp ignores SIGINT except in
        # message handlers, we need to temporarily reset the SIGINT handler here
        # so that bash and its children are interruptible.
        sig = signal.signal(signal.SIGINT, signal.SIG_DFL)
        try:
            magma = spawn('magma', echo=False, encoding='utf-8')
            magma.expect('> ')
            magma.sendline('SetLineEditor(false);')
            magma.expect('> ')
            magma.sendline('')
            self.magmawrapper = replwrap.REPLWrapper(magma, '> ', 'SetPrompt("{}");')
        finally:
            signal.signal(signal.SIGINT, sig)

        # Register Bash function to write image data to temporary file
        # self.magmawrapper.run_command(image_setup_cmd)

    def do_execute(self, code, silent, store_history=True,
                   user_expressions=None, allow_stdin=False):
        if not code.strip():
            return {'status': 'ok', 'execution_count': self.execution_count,
                    'payload': [], 'user_expressions': {}}

        interrupted = False
        try:
            output = self.magmawrapper.run_command(code.rstrip(), timeout=None)
        except KeyboardInterrupt:
            self.magmawrapper.child.sendintr()
            interrupted = True
            self.magmawrapper._expect_prompt()
            output = self.magmawrapper.child.before
        except EOF:
            output = self.magmawrapper.child.before + 'Restarting Bash'
            self._start_magma()

        if not silent:
            #image_filenames, output = extract_image_filenames(output)

            # Send standard output
            stream_content = {'name': 'stdout', 'text': output}
            self.send_response(self.iopub_socket, 'stream', stream_content)

            # Send images, if any
            '''
            for filename in image_filenames:
                try:
                    data = display_data_for_image(filename)
                except ValueError as e:
                    message = {'name': 'stdout', 'text': str(e)}
                    self.send_response(self.iopub_socket, 'stream', message)
                else:
                    self.send_response(self.iopub_socket, 'display_data', data)
            '''

        if interrupted:
            return {'status': 'abort', 'execution_count': self.execution_count}

        '''
        try:
            exitcode = int(self.bashwrapper.run_command('echo $?').rstrip())
        except Exception:
            exitcode = 1
        
        if exitcode:
            error_content = {'execution_count': self.execution_count,
                             'ename': '', 'evalue': str(exitcode), 'traceback': []}

            self.send_response(self.iopub_socket, 'error', error_content)
            error_content['status'] = 'error'
            return error_content
        else:
        '''
        return {'status': 'ok', 'execution_count': self.execution_count,
                'payload': [], 'user_expressions': {}}
