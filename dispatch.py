import ctypes as C
import time
from ctypes import wintypes as W
from winapi import SIZE, U, bind, user

TAG = 0x56524331
PROBE = 0x56524332


class Keyboard(C.Structure):
    _fields_ = [("vk", W.WORD), ("scan", W.WORD), ("flags", U), ("time", U), ("tag", SIZE)]


class Payload(C.Union):
    _fields_ = [("key", Keyboard), ("mouse_size", C.c_byte * 32)]


class Input(C.Structure):
    _fields_ = [("kind", U), ("data", Payload)]


send = bind(user, "SendInput", U, U, C.POINTER(Input), C.c_int)
state = bind(user, "GetAsyncKeyState", C.c_short, C.c_int)


def batch(events, tag=TAG):
    entries = (Input * len(events))()
    for entry, (vk, up) in zip(entries, events):
        entry.kind = 1
        entry.data.key = Keyboard(vk, 0, 2 if up else 0, 0, tag)
    return send(len(entries), entries, C.sizeof(Input))


def toggle(keys, physical):
    # The hook can enqueue this before Windows publishes the RightAlt release.
    # Also allow the right Ctrl used for switching to finish releasing.
    deadline = time.monotonic() + 0.45
    while any(state(vk) & 0x8000 for vk in range(0xA0, 0xA6)):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)
    previous = physical[:]
    pressed = []
    try:
        for vk in keys:
            if batch([(vk, False)]) != 1:
                return False
            pressed.append(vk)
            time.sleep(0.04)
    finally:
        remaining = [vk for vk in reversed(pressed) if previous[vk] or not physical[vk]]
        if remaining:
            released = batch([(vk, True) for vk in remaining])
            if released < len(remaining):
                batch([(vk, True) for vk in remaining[released:]])
    time.sleep(0.015)
    stuck = [vk for vk in reversed(keys[:-1]) if state(vk) & 0x8000 and not physical[vk]]
    if stuck:
        batch([(vk, True) for vk in stuck])
    return True
