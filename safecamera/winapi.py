"""Thin ctypes wrappers around the Windows APIs SafeCamera needs."""

import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.windll.user32


def enable_dpi_awareness():
    """Screen coordinates must match screenshot pixels (DPI scaling)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (OSError, AttributeError):
        user32.SetProcessDPIAware()


def lock_workstation():
    user32.LockWorkStation()


class _WTSINFOEX_LEVEL1(ctypes.Structure):
    _fields_ = [("SessionId", wintypes.ULONG), ("SessionState", ctypes.c_int),
                ("SessionFlags", wintypes.LONG), ("WinStationName", wintypes.WCHAR * 33),
                ("UserName", wintypes.WCHAR * 21), ("DomainName", wintypes.WCHAR * 18),
                ("LogonTime", ctypes.c_longlong), ("ConnectTime", ctypes.c_longlong),
                ("DisconnectTime", ctypes.c_longlong), ("LastInputTime", ctypes.c_longlong),
                ("CurrentTime", ctypes.c_longlong), ("IncomingBytes", wintypes.DWORD),
                ("OutgoingBytes", wintypes.DWORD), ("IncomingFrames", wintypes.DWORD),
                ("OutgoingFrames", wintypes.DWORD), ("IncomingCompressedBytes", wintypes.DWORD),
                ("OutgoingCompressedBytes", wintypes.DWORD)]


class _WTSINFOEX(ctypes.Structure):
    _fields_ = [("Level", wintypes.DWORD), ("Data", _WTSINFOEX_LEVEL1)]


def is_session_locked():
    """
    True while the real Windows lock (Win+L / LockWorkStation) is active.
    The Ctrl+Alt+Del menu or a UAC prompt do not count as "locked" here.
    """
    wtsapi = ctypes.windll.wtsapi32
    buf, size = ctypes.c_void_p(), wintypes.DWORD()
    # WTS_CURRENT_SESSION = -1, WTSSessionInfoEx = 25
    if not wtsapi.WTSQuerySessionInformationW(None, wintypes.DWORD(0xFFFFFFFF), 25,
                                              ctypes.byref(buf), ctypes.byref(size)):
        return is_workstation_locked()
    try:
        info = ctypes.cast(buf, ctypes.POINTER(_WTSINFOEX)).contents
        return info.Data.SessionFlags == 0  # WTS_SESSIONSTATE_LOCK
    finally:
        wtsapi.WTSFreeMemory(buf)


def is_workstation_locked():
    """
    True when the input desktop cannot be entered: the real lock, the Ctrl+Alt+Del
    menu, a UAC prompt or any other secure desktop.
    """
    DESKTOP_SWITCHDESKTOP = 0x0100
    hdesk = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not hdesk:
        return True
    switched = user32.SwitchDesktop(hdesk)
    user32.CloseDesktop(hdesk)
    return not switched


def virtual_screen_rect():
    """Rectangle covering all monitors: (x, y, w, h)."""
    return (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77),
            user32.GetSystemMetrics(78), user32.GetSystemMetrics(79))


def already_running():
    """Allow a single instance only (autostart + manual launch)."""
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\SafeCameraSingleInstance")
    return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS


_HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
ctypes.windll.kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class InputBlocker:
    """
    While locked, swallows every key press and mouse click (Win, Alt+Tab,
    Ctrl+Shift+Esc too). Ctrl+Alt+Del cannot be blocked by Windows design, so when it
    is pressed SafeCamera escalates to the real Windows lock instead.
    """
    WM_MOUSEMOVE = 0x0200

    def __init__(self):
        self.thread_id = None
        self._thread = None

    def start(self):
        if self._thread is not None:
            return
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        ready.wait(2)

    def stop(self):
        if self._thread is not None and self.thread_id:
            user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)  # WM_QUIT
            self._thread.join(2)
        self._thread = None

    def _run(self, ready):
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

        def kb_proc(code, wparam, lparam):
            if code < 0:
                return user32.CallNextHookEx(None, code, wparam, lparam)
            return 1  # swallow the key

        def mouse_proc(code, wparam, lparam):
            if code < 0 or wparam == self.WM_MOUSEMOVE:
                return user32.CallNextHookEx(None, code, wparam, lparam)
            return 1  # swallow clicks and wheel

        # keep references so the callbacks are not garbage collected
        self._procs = (_HOOKPROC(kb_proc), _HOOKPROC(mouse_proc))
        hmod = ctypes.windll.kernel32.GetModuleHandleW(None)
        hooks = [user32.SetWindowsHookExW(13, self._procs[0], hmod, 0),   # WH_KEYBOARD_LL
                 user32.SetWindowsHookExW(14, self._procs[1], hmod, 0)]   # WH_MOUSE_LL
        ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        for h in hooks:
            if h:
                user32.UnhookWindowsHookEx(h)
