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
window_title = bind(user, "GetWindowTextW", C.c_int, P, W.LPWSTR, C.c_int)
valid = bind(user, "IsWindow", W.BOOL, P)
visible = bind(user, "IsWindowVisible", W.BOOL, P)
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


# Typeless 2.12 renders these two text controls consecutively in the subscription card.
CARD_TITLES = {"获取无限字数", "免费字数用完了"}
LIMIT_REACHED = (None, None)


def card_value(title, text):
    if title not in CARD_TITLES:
        return None
    if text == "已达到每周限制":
        return LIMIT_REACHED
    match = pattern.fullmatch(text)
    if match:
        used, total = (int(re.sub(r"[,\s]", "", s)) for s in match.groups())
        if total > 0:
            return used, total


def scan(client, hwnd):
    root, condition, elements = P(), P(), P()
    try:
        call(client, 6, (P, P), hwnd, C.byref(root))
        call(client, 21, (P,), C.byref(condition))
        call(root, 6, (C.c_int, P, P), 4, condition, C.byref(elements))
        count = C.c_int()
        call(elements, 3, (P,), C.byref(count))
        previous = ""
        for i in range(count.value):
            item = P()
            try:
                call(elements, 4, (C.c_int, P), i, C.byref(item))
                if prop(item, 30003) == 50020:  # UIA_TextControlTypeId
                    text = (prop(item, 30005) or "").strip()
                    if text == "历史记录":
                        return None
                    result = card_value(previous, text)
                    if result is not None or previous in CARD_TITLES:
                        return result
                    previous = text
            finally:
                release(item)
    finally:
        for obj in (elements, condition, root):
            release(obj)


def main_windows():
    windows = []
    name = C.create_unicode_buffer(128)

    @enum_proc
    def visit(hwnd, unused):
        class_name(hwnd, name, len(name))
        if not valid(hwnd) or "Chrome_WidgetWin_1" not in name.value:
            return True
        window_title(hwnd, name, len(name))
        if "typeless" in name.value.lower() and process_name(hwnd) == "typeless.exe":
            windows.append(hwnd)
        return True

    enum_windows(visit, 0)
    return windows


def read(windows=None):
    if windows is None:
        windows = main_windows()
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
