import ctypes as C
import queue
import threading
from ctypes import wintypes as W
from dispatch import PROBE, TAG, state
from router import TYPELESS, WETYPE, engine_for
from winapi import (P, U, SIZE, EVENTPROC, HOOKPROC, bind, dispatch_message, foreground_window,
                    get_message, install, module, next_hook, pid_of, post, thread_id, unhook, user)

REHOOK = 0x8001
RECORDING_ENDED = 0x8002
CTRL = (0xA2, 0xA3)
SHIFT = (0xA0, 0xA1)
MODIFIERS = CTRL + SHIFT + (0xA4, 0xA5)
SWITCH_KEYS = MODIFIERS + (0x6D,)
set_win_event = bind(user, "SetWinEventHook", P, U, U, P, EVENTPROC, U, U, U)
remove_win_event = bind(user, "UnhookWinEvent", W.BOOL, P)
active = None


class Key(C.Structure):
    _fields_ = [("vk", U), ("scan", U), ("flags", U), ("time", U), ("extra", SIZE)]


@EVENTPROC
def focus_event(handle, event, hwnd, obj, child, tid, stamp):
    if active and hwnd:
        active.actions.put(("focus", hwnd))


@HOOKPROC
def keyboard(code, msg, address):
    if code >= 0 and active:
        try:
            key = Key.from_address(address)
            if key.extra == PROBE:
                active.probe.set()
                return 1
            if key.extra != TAG:
                down = msg in (0x100, 0x104)
                taken = active.key(key.vk, down)
                if active.rehook_pending and not down and key.vk in SWITCH_KEYS:
                    post(active.tid, REHOOK, 0, 0)
                if taken:
                    return 1
        except BaseException:
            post(active.tid, 0x12, 0, 0)
    return next_hook(None, code, msg, address)


class Hook:
    def __init__(self, threshold, records, s4=False):
        self.threshold = threshold
        self.records = records
        self.used = 0
        self.focus = (0, 0, "")
        self.current_pid = U()
        self.physical = bytearray(256)
        self.recording = None
        self.generation = 0
        self.alt_engine = None
        self.chord = False
        self.minus_down = self.minus_taken = False
        self.s4 = s4
        self.actions = queue.SimpleQueue()
        self.ready = threading.Event()
        self.probe = threading.Event()
        self.handle = self.tid = 0
        self.rehook_pending = False

    def engine(self, hwnd):
        window, pid, name = self.focus
        if hwnd != window:
            if not hwnd or not pid_of(hwnd, C.byref(self.current_pid)) or self.current_pid.value != pid:
                name = ""
        return engine_for(name, self.records, self.used, self.threshold)

    def remember_focus(self, hwnd, name):
        pid = U()
        pid_of(hwnd, C.byref(pid))
        self.focus = (hwnd, pid.value, name)

    def key(self, vk, down):
        if vk in MODIFIERS:
            self.physical[vk] = down
        if vk == 0x6D:
            if down and not self.minus_down:
                self.minus_down = True
                self.minus_taken = bool(any(self.physical[k] for k in CTRL) and not self.recording)
                if self.minus_taken:
                    action = "clear" if any(self.physical[k] for k in SHIFT) else "flip"
                    if self.used >= self.threshold:
                        action = "denied"
                    self.actions.put((action, foreground_window()))
            taken = self.minus_taken
            if not down:
                self.minus_down = self.minus_taken = False
            return taken
        if self.s4:
            return False
        if vk == 0xA5:
            if down and self.alt_engine is None:
                self.alt_engine = self.recording or self.engine(foreground_window())
                self.chord = bool(self.physical[0xA1])
            engine = self.alt_engine
            if not down:
                if engine == WETYPE or (engine == TYPELESS and not self.chord):
                    self.generation += 1
                    self.recording = None if self.recording else engine
                    if engine == WETYPE:
                        self.actions.put(("dispatch", (self.generation, self.recording)))
                    if self.recording:
                        self.actions.put(("check_recording", (self.generation, engine)))
                self.alt_engine = None
            return engine == WETYPE
        if self.alt_engine == TYPELESS and down and vk in (0x20, 0xA1):
            self.chord = True
        return False

    def reinstall(self):
        if self.handle:
            unhook(self.handle)
            self.handle = 0
        self.handle = install(13, keyboard, module(None), 0)
        if not self.handle:
            raise C.WinError(C.get_last_error())

    def run(self):
        global active
        active = self
        self.tid = thread_id()
        listener = None
        try:
            self.reinstall()
            if not self.s4:
                listener = set_win_event(3, 3, None, focus_event, 0, 0, 0)
                if not listener:
                    raise C.WinError(C.get_last_error())
                self.actions.put(("focus", foreground_window()))
            self.ready.set()
            msg = W.MSG()
            while True:
                result = get_message(C.byref(msg), None, 0, 0)
                if result == -1:
                    raise C.WinError(C.get_last_error())
                if not result:
                    break
                if msg.message == REHOOK:
                    # Keep both halves of an in-flight switching chord on one hook.
                    if msg.wParam:
                        # The probe missed the hook. Releases may also have gone unseen.
                        self.minus_down = self.minus_taken = False
                        self.alt_engine = None
                        for vk in MODIFIERS:
                            self.physical[vk] = bool(state(vk) & 0x8000)
                    self.rehook_pending = bool(self.minus_down or self.alt_engine or
                                               any(self.physical[k] for k in CTRL + SHIFT))
                    if msg.wParam or not self.rehook_pending:
                        self.rehook_pending = False
                        self.reinstall()
                elif msg.message == RECORDING_ENDED:
                    if self.generation == msg.wParam:
                        self.recording = None
                else:
                    dispatch_message(C.byref(msg))
        finally:
            if listener:
                remove_win_event(listener)
            if self.handle:
                unhook(self.handle)
                self.handle = 0
            active = None

    def stop(self):
        if self.tid:
            post(self.tid, 0x12, 0, 0)
