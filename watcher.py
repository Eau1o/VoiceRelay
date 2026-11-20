import ctypes as C
import struct
from ctypes import wintypes as W
from winapi import P, U, SIZE, bind, close, create_event, kernel


class Overlapped(C.Structure):
    _fields_ = [("internal", SIZE), ("length", SIZE), ("offset", C.c_uint64), ("event", P)]


open_dir = bind(kernel, "CreateFileW", P, W.LPCWSTR, U, U, P, U, U, P)
changes = bind(kernel, "ReadDirectoryChangesW", W.BOOL, P, P, U, W.BOOL, U, P, P, P)
completed = bind(kernel, "GetOverlappedResult", W.BOOL, P, P, C.POINTER(U), W.BOOL)
cancel = bind(kernel, "CancelIoEx", W.BOOL, P, P)
wait_many = bind(kernel, "WaitForMultipleObjects", U, U, C.POINTER(P), W.BOOL, U)


def watch(path, stop_handle, changed):
    directory = open_dir(str(path.parent), 1, 7, None, 3, 0x42000000, None)
    if directory == P(-1).value:
        raise C.WinError(C.get_last_error())
    event = create_event(None, False, False, None)
    operation = Overlapped(event=event)
    handles = (P * 2)(stop_handle, event)
    buffer = C.create_string_buffer(16384)
    length = U()
    try:
        while True:
            if not changes(directory, buffer, len(buffer), False, 0x19, None, C.byref(operation), None):
                raise C.WinError(C.get_last_error())
            outcome = wait_many(2, handles, False, 0xffffffff)
            if outcome != 1:
                cancel(directory, C.byref(operation))
                completed(directory, C.byref(operation), C.byref(length), True)
                return
            if not completed(directory, C.byref(operation), C.byref(length), False):
                raise C.WinError(C.get_last_error())
            offset = 0
            if not length.value:
                changed()
            while offset < length.value:
                step, _, size = struct.unpack_from("<III", buffer, offset)
                name = buffer[offset+12:offset+12+size].decode("utf-16-le")
                if name.lower() == path.name.lower():
                    changed()
                    break
                if not step:
                    break
                offset += step
    finally:
        close(directory)
        close(event)
