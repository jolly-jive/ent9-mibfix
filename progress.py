# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cayenne Ryo
"""A status line on stderr, rewritten in place, shared by the scripts."""
import os
import sys
import time


def enable_vt(stream):
    """True if stream's terminal handles escape sequences (on Windows, turn them on)."""
    if os.name != 'nt':
        return True
    try:
        import ctypes
        import msvcrt
        kernel32 = ctypes.windll.kernel32
        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = ctypes.c_ulong()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return bool(mode.value & 4 or kernel32.SetConsoleMode(handle, mode.value | 4))
    except Exception:
        return False


class Progress:
    """One status line on stderr, rewritten in place. Silent unless stderr is a tty."""

    def __init__(self, stream=None, quiet=False):
        self.stream = sys.stderr if stream is None else stream
        self.on = not quiet and self.stream.isatty()
        self.vt = self.on and enable_vt(self.stream)
        self.last = 0
        self.width = 0  # length of the line shown, to blank it without escapes

    def show(self, msg, force=True):
        if not self.on:
            return
        now = time.monotonic()
        if not force and now - self.last < 0.2:
            return
        self.last = now
        if self.vt:
            self.stream.write('\r\033[K' + msg)
        else:
            self.stream.write('\r' + msg.ljust(self.width))
            self.width = len(msg)
        self.stream.flush()

    def clear(self):
        if self.on:
            if self.vt:
                self.stream.write('\r\033[K')
            else:
                self.stream.write('\r' + ' ' * self.width + '\r')
                self.width = 0
            self.stream.flush()


QUIET = Progress(quiet=True)
