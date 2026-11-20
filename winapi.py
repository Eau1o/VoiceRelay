import ctypes as C
from ctypes import wintypes as W

user = C.WinDLL("user32", use_last_error=True)
kernel = C.WinDLL("kernel32", use_last_error=True)
P = C.c_void_p
U = W.DWORD
SIZE = C.c_size_t
SIGN = C.c_ssize_t
HOOKPROC = C.WINFUNCTYPE(SIGN, C.c_int, SIZE, SIGN)
EVENTPROC = C.WINFUNCTYPE(None, P, U, P, W.LONG, W.LONG, U, U)


def bind(lib, name, result, *args):
    fn = getattr(lib, name)
    fn.argtypes = args
    fn.restype = result
    return fn


next_hook = bind(user, "CallNextHookEx", SIGN, P, C.c_int, SIZE, SIGN)
install = bind(user, "SetWindowsHookExW", P, C.c_int, HOOKPROC, P, U)
unhook = bind(user, "UnhookWindowsHookEx", W.BOOL, P)
module = bind(kernel, "GetModuleHandleW", P, W.LPCWSTR)
close = bind(kernel, "CloseHandle", W.BOOL, P)
post = bind(user, "PostThreadMessageW", W.BOOL, U, U, SIZE, SIGN)
thread_id = bind(kernel, "GetCurrentThreadId", U)
get_message = bind(user, "GetMessageW", W.BOOL, C.POINTER(W.MSG), P, U, U)
dispatch_message = bind(user, "DispatchMessageW", SIGN, C.POINTER(W.MSG))
foreground_window = bind(user, "GetForegroundWindow", P)
pid_of = bind(user, "GetWindowThreadProcessId", U, P, C.POINTER(U))
wait = bind(kernel, "WaitForSingleObject", U, P, U)
set_event = bind(kernel, "SetEvent", W.BOOL, P)
create_event = bind(kernel, "CreateEventW", P, P, W.BOOL, W.BOOL, W.LPCWSTR)
