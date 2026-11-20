import argparse
import ctypes as C
import json
import logging
import os
import subprocess
import sys
import threading
import time
import winreg
from ctypes import wintypes as W
from datetime import timedelta
from pathlib import Path

import dispatch
import feedback
import overrides
import quota_uia
import store
import watcher
from foreground import process_name
from hook import Hook, REHOOK, RECORDING_ENDED
from router import TYPELESS, WETYPE
from winapi import (P, U, bind, close, create_event, foreground_window, kernel, post,
                    set_event, wait)

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ["APPDATA"]) / "Typeless.exe" / "typeless.db"
RECORDS = ROOT / "overrides.json"
NAME = r"Local\PersonalDualVoiceRouter_v1"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
mutex = bind(kernel, "CreateMutexW", P, P, W.BOOL, W.LPCWSTR)
open_event = bind(kernel, "OpenEventW", P, U, W.BOOL, W.LPCWSTR)
open_mutex = bind(kernel, "OpenMutexW", P, U, W.BOOL, W.LPCWSTR)
release_mutex = bind(kernel, "ReleaseMutex", W.BOOL, P)
WMI = """
$ErrorActionPreference = 'Stop'
$w = New-Object System.Management.ManagementEventWatcher
$w.Query = New-Object System.Management.WqlEventQuery("SELECT * FROM Win32_ProcessStartTrace WHERE ProcessName='Typeless.exe'")
try {
  try {
    $w.Start()
  } catch [System.Management.ManagementException] {
    'fallback'
    # Ordinary users can enumerate matching PIDs without a trace subscription.
    $previous = @(Get-Process -Name Typeless -ErrorAction SilentlyContinue | ForEach-Object Id)
    if ($previous.Count) { 'running' } else { 'ready' }
    while ($true) {
      Start-Sleep -Seconds 5
      $current = @(Get-Process -Name Typeless -ErrorAction SilentlyContinue | ForEach-Object Id)
      foreach ($processId in $current) {
        if ($previous -notcontains $processId) { 'started'; break }
      }
      $previous = $current
    }
  }
  if (Get-Process -Name Typeless -ErrorAction SilentlyContinue) { 'running' } else { 'ready' }
  while ($true) { $null = $w.WaitForNextEvent(); 'started' }
} finally { $w.Dispose() }
"""


def official():
    try:
        return quota_uia.read()
    except (OSError, ValueError):
        return None


def microphone_active(engine):
    folder = ("#tencent#wetype#" if engine == WETYPE else "#programs#typeless#")
    base = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone\NonPackaged"
    found = False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                name = winreg.EnumKey(root, i)
                if folder not in name.lower():
                    continue
                with winreg.OpenKey(root, name) as key:
                    started = winreg.QueryValueEx(key, "LastUsedTimeStart")[0]
                    stopped = winreg.QueryValueEx(key, "LastUsedTimeStop")[0]
                    if started > stopped:
                        return True
                    found = True
    except OSError:
        return None
    return False if found else None


class Service:
    def __init__(self, cfg, stop_handle):
        self.cfg = cfg
        self.stop_handle = stop_handle
        self.hook = Hook(cfg["threshold"], overrides.read(RECORDS))
        self.stop = threading.Event()
        self.quota_cv = threading.Condition()
        self.changed_at = None
        self.maintenance = threading.Condition()
        self.restart_at = None
        self.wetype = False
        self.monitor_job = None
        self.monitor = None
        self.workers = []
        self.record_check = threading.Event()

    def worker(self, fn):
        def guarded():
            try:
                fn()
            except Exception:
                logging.error("worker_failed_%s", fn.__name__)
                set_event(self.stop_handle)
        thread = threading.Thread(target=guarded, daemon=True)
        self.workers.append(thread)
        thread.start()

    def update_mode(self):
        with self.maintenance:
            mode = self.hook.engine(foreground_window()) == WETYPE
            if mode != self.wetype:
                self.wetype = mode
                if mode and self.hook.ready.is_set():
                    post(self.hook.tid, REHOOK, 0, 0)
                self.maintenance.notify()

    def actions(self):
        hook = self.hook
        while True:
            action, value = hook.actions.get()
            if action == "stop":
                return
            if action == "focus":
                if value == foreground_window():
                    hook.remember_focus(value, process_name(value))
                    self.update_mode()
            elif action == "dispatch":
                generation, recording = value
                if not dispatch.toggle(self.cfg["shadow_keys"], hook.physical):
                    if recording:
                        post(hook.tid, RECORDING_ENDED, generation, 0)
                    logging.error("dispatch_failed")
                    feedback.play("denied")
                else:
                    logging.info("wetype_hotkey_sent")
            elif action == "check_recording":
                self.record_check.set()
            elif action == "denied":
                feedback.play("denied")
            elif action in ("clear", "flip"):
                records = hook.records.copy()
                name = process_name(value)
                if action == "clear":
                    records.clear()
                    tone = TYPELESS
                elif name:
                    tone = WETYPE if records.get(name, TYPELESS) == TYPELESS else TYPELESS
                    records[name] = tone
                else:
                    feedback.play("denied")
                    continue
                try:
                    overrides.save(RECORDS, records)
                except OSError:
                    logging.error("override_write_failed")
                    feedback.play("denied")
                    continue
                hook.records = records
                if value == foreground_window():
                    hook.remember_focus(value, name)
                self.update_mode()
                feedback.play(tone)
                logging.info("override_%s_%s %s", action, tone, name)

    def check_microphone(self):
        hook = self.hook
        while not self.stop.is_set():
            self.record_check.wait()
            self.record_check.clear()
            generation, engine = hook.generation, hook.recording
            if not engine or self.stop.is_set():
                continue
            deadline = time.monotonic() + 1.5
            observed = False
            while hook.generation == generation and not self.stop.wait(0.25):
                active = microphone_active(engine)
                if active is None:
                    break
                if active:
                    observed = True
                elif observed or time.monotonic() >= deadline:
                    post(hook.tid, RECORDING_ENDED, generation, 0)
                    logging.info("microphone_closed" if observed else "microphone_start_unconfirmed")
                    break

    def changed(self):
        with self.quota_cv:
            self.changed_at = time.monotonic()
            self.quota_cv.notify()

    def quota(self):
        cache = previous = announced = warned = None
        periodic = 0
        while not self.stop.is_set():
            with self.quota_cv:
                while not self.stop.is_set():
                    now = time.monotonic()
                    due = float("inf") if self.changed_at is None else self.changed_at + max(
                        self.cfg["db_delay_ms"], self.cfg["debounce_ms"]) / 1000
                    if now >= min(periodic, due):
                        if now >= due:
                            self.changed_at = None
                        break
                    self.quota_cv.wait(min(periodic, due) - now)
            if self.stop.is_set():
                return
            result = official()
            if result is not None:
                cache = result
            if cache:
                used = cache[0]
            else:
                try:
                    used = store.estimate(DB)
                except (OSError, store.sqlite3.Error):
                    periodic = time.monotonic() + self.cfg["quota_interval_seconds"]
                    logging.info("quota_unavailable")
                    continue
            periodic = time.monotonic() + self.cfg["quota_interval_seconds"]
            self.hook.used = used
            self.update_mode()
            exhausted = used >= self.hook.threshold
            week = store.week_start()
            if exhausted and announced != week:
                announced = week
                feedback.play("exhausted")
            elif previous and not exhausted:
                feedback.play("restored")
            elif not exhausted and self.cfg["warn_threshold"] and used >= self.cfg["warn_threshold"] and warned != week:
                warned = week
                feedback.play("warning")
            previous = exhausted
            logging.info("quota_%s %d", "official" if cache else "local", used)

    def wmi(self):
        for line in self.monitor.stdout:
            if line.strip() == "started":
                with self.maintenance:
                    self.restart_at = time.monotonic() + 2
                    self.maintenance.notify()
        if not self.stop.is_set():
            raise RuntimeError("WMI stopped")

    def maintain(self):
        self.hook.ready.wait()
        if self.stop.is_set():
            return
        logging.info("router_ready")
        if sys.stdout:
            print("调度器已就绪。在目标窗口按 Ctrl + 小键盘减号切换，听到确认音后按右 Alt。", flush=True)
        probe_at = refresh_at = None
        while not self.stop.is_set():
            with self.maintenance:
                now = time.monotonic()
                if self.wetype:
                    if probe_at is None:
                        probe_at, refresh_at = now + 30, now + 300
                else:
                    probe_at = refresh_at = None
                deadlines = [t for t in (probe_at, refresh_at, self.restart_at) if t is not None]
                if not deadlines or min(deadlines) > now:
                    self.maintenance.wait(min(deadlines) - now if deadlines else None)
                    continue
                refresh = False
                if self.restart_at is not None and now >= self.restart_at:
                    self.restart_at = None
                    refresh = True
                if refresh_at is not None and now >= refresh_at:
                    refresh_at = now + 300
                    refresh = True
                probe = probe_at is not None and now >= probe_at
                if probe:
                    probe_at = now + 30
            missed = False
            if probe:
                self.hook.probe.clear()
                dispatch.batch([(0x87, True)], dispatch.PROBE)
                missed = not self.hook.probe.wait(0.3)
            if refresh or missed:
                post(self.hook.tid, REHOOK, int(missed), 0)

    def shutdown_wait(self):
        wait(self.stop_handle, 0xffffffff)
        self.hook.ready.wait()
        self.hook.stop()

    def run(self):
        try:
            self.monitor = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", WMI],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW)
            # A hard exit must also close the WMI subscriber process.
            self.monitor_job = bind(kernel, "CreateJobObjectW", P, P, W.LPCWSTR)(None, None)
            limits = C.create_string_buffer(144)  # x64 JOBOBJECT_EXTENDED_LIMIT_INFORMATION
            U.from_buffer(limits, 16).value = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            configure = bind(kernel, "SetInformationJobObject", W.BOOL, P, C.c_int, P, U)
            assign = bind(kernel, "AssignProcessToJobObject", W.BOOL, P, P)
            if (not self.monitor_job or not configure(self.monitor_job, 9, limits, len(limits))
                    or not assign(self.monitor_job, int(self.monitor._handle))):
                raise C.WinError(C.get_last_error())
            status = self.monitor.stdout.readline().strip()
            if status == "fallback":
                logging.info("typeless_pid_monitor")
                status = self.monitor.stdout.readline().strip()
            if status not in ("running", "ready"):
                logging.error("wmi_subscription_failed")
                raise RuntimeError("WMI 启动监听失败，请检查本用户的 WMI 事件订阅权限。")
            self.worker(self.wmi)
            if status == "running" and wait(self.stop_handle, 1000) == 0:
                return
            self.worker(self.actions)
            self.worker(self.check_microphone)
            self.worker(self.quota)
            self.worker(self.maintain)
            self.worker(lambda: watcher.watch(DB, self.stop_handle, self.changed))
            self.worker(self.shutdown_wait)
            self.hook.run()
        finally:
            self.stop.set()
            self.record_check.set()
            set_event(self.stop_handle)
            if self.monitor:
                self.monitor.terminate()
                self.monitor.wait()
            if self.monitor_job:
                close(self.monitor_job)
            self.hook.actions.put(("stop", None))
            self.hook.ready.set()
            for cv in (self.maintenance, self.quota_cv):
                with cv:
                    cv.notify_all()
            for thread in self.workers:
                thread.join(2)


def uninstall():
    handle = open_event(2, False, NAME + "_stop")
    if handle:
        owner = open_mutex(0x100000, False, NAME)
        try:
            set_event(handle)
            if owner and wait(owner, 15000) == 258:
                raise RuntimeError("等待调度器退出超时")
        finally:
            if owner:
                close(owner)
            close(handle)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        try:
            winreg.DeleteValue(key, "PersonalDualVoiceRouter")
        except FileNotFoundError:
            pass
    print("已停用。程序目录内保留配置与记忆。")


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    for option in ("status", "uninstall", "install"):
        group.add_argument("--" + option, action="store_true")
    args = parser.parse_args()
    if args.uninstall:
        uninstall()
        return
    if args.install:
        cmd = subprocess.list2cmdline([str(Path(sys.executable).with_name("pythonw.exe")), str(ROOT / "main.py")])
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, "PersonalDualVoiceRouter", 0, winreg.REG_SZ, cmd)
        print("已设置当前用户登录自启。")
        return
    if args.status:
        instance = open_mutex(0x100000, False, NAME)
        print("调度器", "正在运行" if instance else "未运行")
        if instance:
            close(instance)
        print(json.dumps(overrides.read(RECORDS), ensure_ascii=False, indent=2))
        result = official()
        print("官方额度", f"{result[0]} / {result[1]}" if result else "当前不可读")
        if not result:
            try:
                print("本机估算", store.estimate(DB))
            except store.sqlite3.Error:
                print("本机估算不可用")
        print("下次重置", (store.week_start() + timedelta(days=7)).isoformat())
        return
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
    if (cfg["threshold"] < 1 or cfg["quota_interval_seconds"] <= 0
            or min(cfg["debounce_ms"], cfg["db_delay_ms"]) < 0
            or cfg["shadow_keys"] not in ([162, 160, 123], [162, 164, 123])):
        parser.error("请检查 config.json 中的阈值、间隔和微信语音键")
    instance = mutex(None, True, NAME)
    if not instance:
        raise C.WinError(C.get_last_error())
    if C.get_last_error() == 183:
        close(instance)
        print("调度器已运行。")
        return
    stop_handle = create_event(None, True, False, NAME + "_stop")
    try:
        if not stop_handle:
            raise C.WinError(C.get_last_error())
        (ROOT / "logs").mkdir(exist_ok=True)
        logging.basicConfig(filename=ROOT / "logs/router.log", format="%(asctime)s %(message)s", level=logging.INFO)
        # Console control events must wake the native message pump.
        handler_type = C.WINFUNCTYPE(W.BOOL, U)
        handler = handler_type(lambda event: bool(set_event(stop_handle)))
        control = bind(kernel, "SetConsoleCtrlHandler", W.BOOL, handler_type, W.BOOL)
        control(handler, True)
        try:
            Service(cfg, stop_handle).run()
        finally:
            control(handler, False)
    finally:
        if stop_handle:
            close(stop_handle)
        release_mutex(instance)
        close(instance)


if __name__ == "__main__":
    main()
