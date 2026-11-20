"""S4: 对独立 Edge 窗口比较相同组合键在挂钩前后的页面缩放。"""
import ctypes as C
import os
import subprocess
import tempfile
import threading
import time
from ctypes import wintypes as W
from pathlib import Path
from uuid import uuid4

from dispatch import batch, state
from hook import Hook
from quota_uia import enum_proc, enum_windows
from winapi import P, bind, foreground_window, user

title = bind(user, "GetWindowTextW", C.c_int, P, W.LPWSTR, C.c_int)
send_close = bind(user, "PostMessageW", W.BOOL, P, W.UINT, W.WPARAM, W.LPARAM)


def run():
    marker = "VoiceS4" + uuid4().hex
    exe = Path(os.environ["ProgramFiles(x86)"]) / "Microsoft/Edge/Application/msedge.exe"
    with tempfile.TemporaryDirectory(prefix="voice-s4-", ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        page = root / "s4.html"
        page.write_text("<h1>S4</h1><script>function update(){document.title='" + marker +
                        " '+devicePixelRatio+' END'}update();onresize=update;</script>", encoding="utf-8")
        browser = subprocess.Popen([str(exe), "--user-data-dir=" + str(root / "profile"),
            "--no-first-run", "--disable-sync", "--disable-background-networking",
            "--no-default-browser-check", "--new-window", page.as_uri()])
        hwnd = None
        hook = Hook(1980, {}, s4=True)
        thread = None

        def ratio(window):
            buf = C.create_unicode_buffer(256)
            title(window, buf, len(buf))
            if buf.value.startswith(marker + " "):
                return float(buf.value.split()[1])

        @enum_proc
        def find(window, unused):
            nonlocal hwnd
            if ratio(window) is not None:
                hwnd = window
                return False
            return True

        def press():
            if foreground_window() != hwnd:
                raise RuntimeError("S4 窗口未获焦点，测试已停止")
            if any(state(v) & 0x8000 for v in (0x11, 0x12, 0x10)):
                raise RuntimeError("请松开修饰键")
            keys = [(0xA2, False), (0x6D, False), (0x6D, True), (0xA2, True)]
            if batch(keys, tag=0x5344) != 4:
                raise RuntimeError("测试按键发送失败")
            time.sleep(0.8)

        try:
            until = time.monotonic() + 18
            while not hwnd and time.monotonic() < until:
                enum_windows(find, 0)
                time.sleep(0.1)
            if not hwnd:
                raise RuntimeError("独立 Edge 测试页未就绪")
            before = ratio(hwnd)
            press()
            baseline = ratio(hwnd)
            if baseline >= before:
                raise RuntimeError("未挂钩时页面没有缩小，缺少阳性对照")
            thread = threading.Thread(target=hook.run)
            thread.start()
            if not hook.ready.wait(3):
                raise RuntimeError("S4 钩子启动失败")
            press()
            action, window = hook.actions.get(timeout=2)
            after = ratio(hwnd)
            if action != "flip" or window != hwnd or after != baseline:
                raise RuntimeError("S4 拦截失败")
            print(f"S4 PASS: {before} -> {baseline}; hooked {baseline} -> {after}")
        finally:
            if thread:
                hook.stop()
                thread.join(3)
            if hwnd:
                send_close(hwnd, 0x10, 0, 0)
            if browser.poll() is None:
                try:
                    browser.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    browser.terminate()


if __name__ == "__main__":
    run()
