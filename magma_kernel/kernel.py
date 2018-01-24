from ipykernel.kernelbase import Kernel
from pexpect import replwrap, EOF, spawn

from subprocess import check_output

import re
import signal
import bisect

__version__ = '0.0.1.dev1'

version_pat = re.compile(r'version (\d+(\.\d+)+)')



class MagmaKernel(Kernel):
    implementation = 'magma_kernel'
    implementation_version = __version__



    language_info = {'name': 'magma',
                     'codemirror_mode': 'magma',
                     'mimetype': 'text/x-sh',
                     'file_extension': '.mgm'}
    _banner = None

    @property
    def banner(self):
        if self._banner is None:
            self._banner = check_output('magma').decode('utf-8').split('\n')[0]
        return self._banner

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
            magma.expect(u'> ')
            magma.sendline(u'SetLineEditor(false);')
            magma.expect(u'> ')
            magma.sendline(u'')
            self.magmawrapper = replwrap.REPLWrapper(magma, u'> ', u'SetPrompt("{}");')
        finally:
            signal.signal(signal.SIGINT, sig)


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
            output = self.magmawrapper.child.before + 'Restarting Magma'
            self._start_magma()

        if not silent:
            # Send standard output
            stream_content = {'name': 'stdout', 'text': output}
            self.send_response(self.iopub_socket, 'stream', stream_content)

        if interrupted:
            return {'status': 'abort', 'execution_count': self.execution_count}

        return {'status': 'ok', 'execution_count': self.execution_count,
                'payload': [], 'user_expressions': {}}

    _magma_builtins = None;
    def do_complete(self, code, cursor_pos):
        code = code[:cursor_pos];
        default = {'matches': [], 'cursor_start': 0,
                   'cursor_end': cursor_pos, 'metadata': dict(),
                   'status': 'ok'};
        if not code or code[-1] == ' ':
            return default;

        if self._magma_builtins is None:
            from os import path
            F = open(path.join(path.dirname(__file__), "magma-builtins"), 'r');
            self._magma_builtins = F.read().split('\n');
            F.close();

        low = bisect.bisect_left(self._magma_builtins, code);
        high = bisect.bisect_right(self._magma_builtins, code+chr(127), low); #very hacky
        matches = self._magma_builtins[low:high];
        if not matches:
            return default
        return  {'matches': matches, 'cursor_start': 0,
                   'cursor_end': cursor_pos, 'metadata': dict(),
                   'status': 'ok'};
