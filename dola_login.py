"""Dola 人工登录使用普通 Chrome，校验和生成复用相同的浏览器与 profile。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from constants import BUNDLED_CHROME


def resolve_dola_browser(profile_dir: Path, *, for_login: bool = False) -> Path:
    saved_path = profile_dir / "login_browser.json"
    if saved_path.is_file():
        try:
            executable = Path(json.loads(saved_path.read_text(encoding="utf-8"))["executablePath"])
            if executable.is_file():
                return executable.resolve()
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if not for_login:
            raise RuntimeError("Dola 登录使用的 Chrome 已不可用，请重新打开登录窗口")
    # 历史账号仍沿用内置浏览器；人工登录时才选择本机 Chrome。
    if sys.platform == "darwin":
        from macos_support import resolve_chrome

        return resolve_chrome()
    if for_login:
        candidates = []
        if os.name == "nt":
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                    try:
                        with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
                                            0, winreg.KEY_READ | view) as key:
                            candidates.append(Path(winreg.QueryValueEx(key, "")[0].strip('"')))
                    except OSError:
                        pass
        for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            if os.environ.get(name):
                candidates.append(Path(os.environ[name]) / "Google/Chrome/Application/chrome.exe")
        if found := shutil.which("chrome"):
            candidates.append(Path(found))
        for executable in candidates:
            if executable.is_file():
                return executable.resolve()
    if not BUNDLED_CHROME.is_file():
        raise RuntimeError("未找到 Google Chrome 或内置浏览器，请安装 Chrome 后重试")
    return BUNDLED_CHROME.resolve()


@dataclass
class DolaLoginBrowser:
    process: subprocess.Popen

    def request_close(self) -> None:
        if self.process.poll() is not None:
            return
        if os.name != "nt":
            self.process.terminate()
            return
        # WM_CLOSE 让 Chrome 正常落盘 Cookie；只关闭本次专用进程的窗口。
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL

        @callback_type
        def close_window(hwnd, _):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == self.process.pid:
                user32.PostMessageW(hwnd, 0x0010, 0, 0)
            return True

        user32.EnumWindows(close_window, 0)

    def close(self) -> None:
        self.request_close()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("请手动关闭此账号的 Dola 登录窗口，再点击“完成登录”") from exc


def _screen_center_position(width: int = 1100, height: int = 800) -> tuple[int, int]:
    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            sw = user32.GetSystemMetrics(0)
            sh = user32.GetSystemMetrics(1)
            if sw > 0 and sh > 0:
                return max(0, (sw - width) // 2), max(0, (sh - height) // 2)
        except Exception:
            pass
    return 100, 100


def _bring_pid_to_foreground(pid: int) -> None:
    if os.name != "nt":
        return
    import time
    pos_x, pos_y = _screen_center_position(1100, 800)
    for _ in range(15):
        time.sleep(0.2)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL

        target_hwnd = None

        @callback_type
        def enum_fn(hwnd, _):
            nonlocal target_hwnd
            window_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if window_pid.value == pid and user32.IsWindowVisible(hwnd):
                target_hwnd = hwnd
                return False
            return True

        user32.EnumWindows(enum_fn, 0)
        if target_hwnd:
            user32.SetWindowPos(target_hwnd, -1, pos_x, pos_y, 1100, 800, 0x0040)
            user32.SetWindowPos(target_hwnd, -2, pos_x, pos_y, 1100, 800, 0x0040)
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 0x02, 0)
            user32.ShowWindow(target_hwnd, 9)
            user32.ShowWindow(target_hwnd, 5)
            user32.SetForegroundWindow(target_hwnd)
            break


def launch_dola_login(profile_dir: Path, url: str) -> DolaLoginBrowser:
    executable = resolve_dola_browser(profile_dir, for_login=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    pos_x, pos_y = _screen_center_position(1100, 800)
    process = subprocess.Popen(
        [str(executable), f"--user-data-dir={profile_dir.resolve()}", "--no-first-run",
         "--no-default-browser-check", "--disable-background-mode", "--new-window",
         "--window-size=1100,800", f"--window-position={pos_x},{pos_y}", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    import threading
    threading.Thread(target=_bring_pid_to_foreground, args=(process.pid,), daemon=True).start()
    browser = DolaLoginBrowser(process)
    try:
        code = process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass
    else:
        raise RuntimeError(f"Chrome 登录窗口未能启动（退出码 {code}），请安装 Google Chrome 后重试")
    try:
        # 保持同一可执行文件，避免 Chrome 的 Cookie 加密导致登录态无法复用。
        (profile_dir / "login_browser.json").write_text(
            json.dumps({"executablePath": str(executable)}, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        browser.request_close()
        raise
    return browser
