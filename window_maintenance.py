"""Restore and hide the Typeless window without operating Explorer's tray."""
import ctypes as C
import logging
import time
from ctypes import wintypes as W

from foreground import process_name
from quota_uia import main_windows, read, valid, visible
from winapi import P, U, SIZE, SIGN, bind, foreground_window, user

show = bind(user, "ShowWindow", W.BOOL, P, C.c_int)
iconic = bind(user, "IsIconic", W.BOOL, P)
find_next = bind(user, "FindWindowExW", P, P, P, W.LPCWSTR, W.LPCWSTR)
notify = bind(user, "SendNotifyMessageW", W.BOOL, P, U, SIZE, SIGN)
set_foreground = bind(user, "SetForegroundWindow", W.BOOL, P)


class IconIdentifier(C.Structure):
    _fields_ = [("size", U), ("owner", P), ("icon_id", U), ("guid", C.c_ubyte * 16)]


icon_rect = bind(C.WinDLL("shell32"), "Shell_NotifyIconGetRect", W.LONG,
                 C.POINTER(IconIdentifier), C.POINTER(W.RECT))


def request_main_window():
    # Typeless 2.12 uses Electron's first registered icon (ID 3, independent
    # of tray order). WM_APP+1 carries the app's activation notification.
    # The rect query validates registration; its coordinates are never used.
    owner = None
    while owner := find_next(None, owner, "Electron_NotifyIconHostWindow", None):
        if process_name(owner) == "typeless.exe":
            icon = IconIdentifier(size=C.sizeof(IconIdentifier), owner=owner, icon_id=3)
            if icon_rect(C.byref(icon), C.byref(W.RECT())) >= 0:
                return bool(notify(owner, 0x8001, icon.icon_id, 0x0201))
    return False


def wait_for(check, seconds):
    deadline = time.monotonic() + seconds
    while True:
        result = check()
        if result or time.monotonic() >= deadline:
            return result
        time.sleep(.08)


def hide_restorable(hwnd):
    # Electron's native tray handler restores iconic windows. SW_HIDE alone
    # leaves an existing window that its handler can focus but cannot reveal.
    show(hwnd, 7)  # SW_SHOWMINNOACTIVE
    show(hwnd, 0)  # SW_HIDE
    return valid(hwnd) and not visible(hwnd)


class WindowMaintenance:
    def __init__(self):
        self.hwnd = 0
        self.loading = 0
        self.observation = None
        self.retry_at = 0

    def hidden(self):
        return self.hwnd and valid(self.hwnd) and not visible(self.hwnd)

    def adopt(self):
        self.hwnd = next(iter(main_windows()), 0)
        if self.hidden() and not iconic(self.hwnd):
            hide_restorable(self.hwnd)

    def ensure_hidden(self, starting=True, microphone_busy=lambda: False):
        self.observation = None
        try:
            if self.hidden():
                logging.info("window_hidden")
                return False
            windows = main_windows()
            if not windows:
                self.hwnd = 0
                if not starting or time.monotonic() < self.retry_at or microphone_busy():
                    logging.info("window_missing_deferred")
                    return False
                self.retry_at = time.monotonic() + 1800
                return self.rebuild()
            self.hwnd = next((h for h in windows if visible(h)), windows[0])
            if not visible(self.hwnd):
                logging.info("window_hidden")
                return False
            self.observation = read([self.hwnd])
            if self.loading == self.hwnd and not self.observation:
                logging.info("quota_loading")
                return False
            if not hide_restorable(self.hwnd):
                logging.warning("window_hide_failed")
                return False
            logging.info("window_visible_hidden")
            self.loading = 0
            return "hidden"
        except OSError:
            logging.warning("window_maintenance_failed")
            return False

    def rebuild(self):
        previous = foreground_window()
        if not request_main_window():
            logging.info("window_activation_unavailable")
            return False
        windows = wait_for(main_windows, 3)
        if not windows:
            logging.info("window_create_timeout")
            return False
        self.loading = self.hwnd = windows[0]
        def loaded_window():
            for hwnd in main_windows():
                self.observation = read([hwnd])
                if self.observation is not None:
                    return hwnd

        loaded = wait_for(loaded_window, 5)
        if not loaded:
            if previous and valid(previous) and foreground_window() in main_windows():
                set_foreground(previous)
            logging.info("window_quota_timeout")
            return False
        self.hwnd = loaded
        active = foreground_window() == loaded
        if not hide_restorable(loaded):
            logging.warning("window_hide_failed")
            return False
        if active and previous and valid(previous) and foreground_window() != previous:
            set_foreground(previous)
        self.retry_at = self.loading = 0
        logging.info("window_rebuilt_hidden")
        return "rebuilt"
