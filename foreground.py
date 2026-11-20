import ctypes as C
import ntpath
from ctypes import wintypes as W
from winapi import P, U, bind, close, kernel, pid_of

open_process = bind(kernel, "OpenProcess", P, U, W.BOOL, U)
image_path = bind(kernel, "QueryFullProcessImageNameW", W.BOOL, P, U, W.LPWSTR, C.POINTER(U))


def process_name(hwnd):
    pid = U()
    pid_of(hwnd, C.byref(pid))
    handle = open_process(0x1000, False, pid.value) if pid.value else None
    if handle:
        try:
            size = U(32768)
            buffer = C.create_unicode_buffer(size.value)
            if image_path(handle, 0, buffer, C.byref(size)):
                return ntpath.basename(buffer.value).lower()
        finally:
            close(handle)
    return ""
