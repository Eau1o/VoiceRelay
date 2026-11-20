import ctypes as C
import re
import uuid
from ctypes import wintypes as W
from foreground import process_name
from winapi import P, bind, user

ole = C.OleDLL("ole32")
auto = C.WinDLL("oleaut32")
clear = bind(auto, "VariantClear", W.LONG, P)
new = bind(ole, "CoCreateInstance", W.LONG, P, P, W.DWORD, P, C.POINTER(P))
enum_proc = C.WINFUNCTYPE(W.BOOL, P, W.LPARAM)
enum_windows = bind(user, "EnumWindows", W.BOOL, enum_proc, W.LPARAM)
class_name = bind(user, "GetClassNameW", C.c_int, P, W.LPWSTR, C.c_int)
pattern = re.compile(r"([\d][\d,\s]*)\s*/\s*([\d][\d,\s]*)\s*字")


def guid(value):
    return C.create_string_buffer(uuid.UUID(value).bytes_le)


def method(obj, index, *args):
    table = C.cast(obj, C.POINTER(C.POINTER(P))).contents
    return C.WINFUNCTYPE(W.LONG, P, *args)(table[index])


def call(obj, index, types, *args):
    if method(obj, index, *types)(obj, *args) < 0:
        raise OSError("UIA")


def release(obj):
    if obj:
        method(obj, 2)(obj)


def prop(element, key):
    # x64 VARIANT, value at offset 8. Copy BSTR contents before VariantClear.
    value = (C.c_uint64 * 3)()
    call(element, 10, (C.c_int, P), key, C.byref(value))
    try:
        vt = value[0] & 0xffff
        if vt == 3:
            return value[1] & 0xffffffff
        if vt == 8 and value[1]:
            return C.wstring_at(value[1])
    finally:
        clear(C.byref(value))


def scan(client, hwnd):
    root, condition, elements = P(), P(), P()
    try:
        call(client, 6, (P, P), hwnd, C.byref(root))
        call(client, 21, (P,), C.byref(condition))
        call(root, 6, (C.c_int, P, P), 4, condition, C.byref(elements))
        count = C.c_int()
        call(elements, 3, (P,), C.byref(count))
        for i in range(count.value):
            item = P()
            try:
                call(elements, 4, (C.c_int, P), i, C.byref(item))
                if prop(item, 30003) == 50020:  # UIA_TextControlTypeId
                    match = pattern.fullmatch((prop(item, 30005) or "").strip())
                    if match:
                        return tuple(int(re.sub(r"[,\s]", "", s)) for s in match.groups())
            finally:
                release(item)
    finally:
        for obj in (elements, condition, root):
            release(obj)


def read():
    windows = []
    name = C.create_unicode_buffer(128)

    @enum_proc
    def visit(hwnd, unused):
        class_name(hwnd, name, len(name))
        if "Chrome_WidgetWin" in name.value and process_name(hwnd) == "typeless.exe":
            windows.append(hwnd)
        return True

    enum_windows(visit, 0)
    if not windows:
        return None
    ole.CoInitializeEx(None, 0)
    client = P()
    try:
        new(guid("FF48DBA4-60EF-4201-AA87-54103EEF594E"), None, 1,
            guid("30CBE57D-D9D0-452A-AB13-7AC5AC4825EE"), C.byref(client))
        for hwnd in windows:
            try:
                result = scan(client, hwnd)
                if result:
                    return result
            except OSError:
                continue
    finally:
        release(client)
        ole.CoUninitialize()
