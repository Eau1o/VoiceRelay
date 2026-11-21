"""Observe visible Typeless notification candidates without storing window text."""
import ctypes as C
import logging
from ctypes import wintypes as W

import quota_uia as uia
from foreground import process_name
from winapi import P

EVENTS = {0x0002: "alert", 0x8002: "show", 0x8019: "live_region"}
LABELS = (("已达到每周限制", "weekly_limit"), ("免费字数用完了", "free_words_used"))


class Variant(C.Structure):
    _fields_ = [("type", W.WORD), ("reserved", W.WORD * 3), ("value", P),
                ("padding", P)]


def inspect(hwnd, event):
    if not hwnd or process_name(hwnd) != "typeless.exe" or not uia.visible(hwnd):
        return
    client, root = P(), P()
    uia.ole.CoInitializeEx(None, 0)
    try:
        uia.new(uia.guid("FF48DBA4-60EF-4201-AA87-54103EEF594E"), None, 1,
                uia.guid("30CBE57D-D9D0-452A-AB13-7AC5AC4825EE"), C.byref(client))
        uia.call(client, 6, (P, P), hwnd, C.byref(root))
        for text, label in LABELS:
            cond, found = P(), P()
            alloc = uia.auto.SysAllocString
            alloc.argtypes, alloc.restype = [W.LPCWSTR], P
            value = Variant(type=8, value=alloc(text))
            try:
                uia.call(client, 23, (C.c_int, Variant, P), 30005, value, C.byref(cond))
                uia.call(root, 5, (C.c_int, P, P), 7, cond, C.byref(found))
                if found:
                    logging.info("typeless_notice_candidate %s %s", EVENTS[event], label)
                    return
            finally:
                uia.release(found)
                uia.release(cond)
                uia.clear(C.byref(value))
        logging.info("typeless_notice_event %s", EVENTS[event])
    except OSError:
        logging.info("typeless_notice_unreadable %s", EVENTS[event])
    finally:
        uia.release(root)
        uia.release(client)
        uia.ole.CoUninitialize()
