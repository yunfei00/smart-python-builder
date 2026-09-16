from __future__ import annotations

import os
import subprocess
from typing import Protocol


class ExecutionBackend(Protocol):
    """Replace with an ephemeral VM backend before accepting untrusted users."""
    def run(self, command, cwd, log, timeout): ...


class LocalWindowsBackend:
    def run(self, command, cwd, log, timeout):
        env=os.environ.copy()
        env.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',UV_CONCURRENT_BUILDS='1',UV_CONCURRENT_INSTALLS='1')
        process=subprocess.Popen(command,cwd=cwd,stdout=log,stderr=subprocess.STDOUT,env=env,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name=='nt':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=log,stderr=log,timeout=15)
            else:process.kill()
            process.wait(timeout=15)
            raise TimeoutError('Build command timed out; process tree stopped')
