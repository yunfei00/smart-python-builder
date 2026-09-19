from __future__ import annotations

import contextlib
import os
import subprocess
import threading
import time
from typing import Protocol


class ExecutionBackend(Protocol):
    """Replace with an ephemeral VM backend before accepting untrusted users."""
    def run(self, command, cwd, log, timeout): ...
    def cancel(self): ...


class LocalWindowsBackend:
    def __init__(self):
        self._lock = threading.Lock()
        self._process = None
        self._cancel_requested = False

    def cancel(self):
        with self._lock:
            self._cancel_requested = True
            process = self._process
        if process is not None and process.poll() is None:
            self._stop_process_tree(process)

    def _stop_process_tree(self, process):
        try:
            if os.name == 'nt':
                subprocess.run(
                    ['taskkill', '/PID', str(process.pid), '/T', '/F'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                    check=False,
                )
            else:
                process.kill()
        except (OSError, subprocess.SubprocessError):
            with contextlib.suppress(OSError):
                process.kill()

    def run(self, command, cwd, log, timeout):
        env = os.environ.copy()
        env.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', UV_CONCURRENT_BUILDS='1', UV_CONCURRENT_INSTALLS='1')
        with self._lock:
            if self._cancel_requested:
                raise RuntimeError('Build cancelled by user')
            process = subprocess.Popen(
                command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            self._process = process
        deadline = time.monotonic() + timeout
        try:
            while True:
                with self._lock:
                    cancelled = self._cancel_requested
                if cancelled:
                    self._stop_process_tree(process)
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=15)
                    raise RuntimeError('Build cancelled by user')
                returncode = process.poll()
                if returncode is not None:
                    return returncode
                if time.monotonic() >= deadline:
                    self._stop_process_tree(process)
                    process.wait(timeout=15)
                    raise TimeoutError('Build command timed out; process tree stopped')
                time.sleep(0.2)
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None
