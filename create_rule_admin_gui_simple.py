#!/usr/bin/env python3
"""
create_rule_admin_gui_simple.py

Single-file-ready GUI to manage a Windows Firewall rule and provide global hotkeys.

Build with PyInstaller to name the final exe Solo_Public_Lobby_V-Online:
py -3 -m PyInstaller --onefile --name Solo_Public_Lobby_V-Online --uac-admin --windowed --icon=GTAO.ico --add-data "GTAO_active.ico;." create_rule_admin_gui_simple.py

Notes:
- Place GTAO.ico and GTAO_active.ico in the same folder as this script before building.
- For production set NO_ELEV = False so the app requests elevation.
"""
from __future__ import annotations
import os
import sys
import ctypes
import subprocess
import threading
import queue
import time
import tkinter as tk
from tkinter import ttk, messagebox
import json
import tempfile
import stat
import traceback as _traceback
from ctypes import wintypes
import atexit

# Debug flag: set to True when debugging to avoid relaunching as admin
# For normal usage keep False so the app requests UAC and runs elevated.
NO_ELEV = False

# ----------------- CONFIG -----------------
RULE_NAME = "GTA Online Rule"
REMOTE_PORTS = "6672,61455,61456,61457,61458"
HOTKEYS_FILE = "hotkeys.json"
VERSION = "1.0.0"

# icons
INACTIVE_ICON = "GTAO.ico"
ACTIVE_ICON = "GTAO_active.ico"

# embedded helper filenames used by the app
SUSPEND_ENH_BAT = "suspend_resume_GTA5_Enhanced.bat"
SUSPEND_GTA5_BAT = "suspend_resume_GTA5.bat"
SUSPEND_GENERIC_PS1 = "suspend_resume_generic.ps1"
TOGGLE_BAT = "toggle_rule.bat"
TOGGLE_PS1 = "toggle_rule.ps1"

# ----------------- small helpers -----------------
def exe_dir() -> str:
    """
    Return a directory for config/log files:
    - When running from a normal Python environment -> script folder
    - When running a packaged onedir (dist/<name>/) -> exe folder (so files live next to exe)
    - When running a onefile bundle (PyInstaller extracts to a temporary folder) -> %APPDATA%/SPL_GTAVO
    """
    if getattr(sys, "frozen", False):
        exe_parent = os.path.dirname(sys.executable)
        tmpdir = tempfile.gettempdir()
        # If running from a temporary extraction folder (onefile), use %APPDATA%\SPL_GTAVO
        if exe_parent.startswith(tmpdir):
            appdata = os.getenv("APPDATA") or os.path.expanduser("~")
            p = os.path.join(appdata, "SPL_GTAVO")
            try:
                os.makedirs(p, exist_ok=True)
            except Exception:
                pass
            return p
        # Otherwise (onedir) keep files next to the exe
        return exe_parent
    # not frozen: use source file directory
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name: str) -> str:
    """
    Return a path to a resource file (icon, helper).

    Resolution order:
    1) If PyInstaller onefile extracted resources are available (sys._MEIPASS) and the file exists there,
       return that path.
    2) Otherwise return a file next to the script/exe using exe_dir().
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        p = os.path.join(meipass, name)
        if os.path.exists(p):
            return p
    return os.path.join(exe_dir(), name)

# --- Windows icon / AppID helpers (safe no-ops on non-Windows)
if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    _shell32 = ctypes.windll.shell32

    WM_SETICON = 0x0080
    ICON_SMALL = 0
    ICON_BIG = 1
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x00000010

    def set_taskbar_appid(appid: str):
        """Set the current process AppUserModelID so Windows taskbar uses the app's icon/grouping.
        Call this before creating the first Tk window."""
        try:
            _shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(appid))
            dbg(f"Set AppUserModelID: {appid}")
        except Exception:
            dbg("Failed to set AppUserModelID")

    def _load_icon_from_file(path: str):
        """Load an HICON from an .ico file using LoadImageW(LR_LOADFROMFILE)."""
        try:
            hicon = _user32.LoadImageW(0, ctypes.c_wchar_p(path), IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
            if not hicon:
                return None
            return int(hicon)
        except Exception:
            return None

    def set_window_icon(tk_root: tk.Tk, ico_path: str) -> bool:
        """Set the window icon (big & small) from an .ico file. Returns True on success."""
        try:
            if not os.path.exists(ico_path):
                dbg(f"set_window_icon: icon not found: {ico_path}")
                return False
            # Tk fallback (many platforms)
            try:
                tk_root.iconbitmap(ico_path)
            except Exception:
                pass
            tk_root.update_idletasks()
            hwnd = tk_root.winfo_id()
            if not hwnd:
                dbg("set_window_icon: no hwnd")
                return False
            hicon = _load_icon_from_file(ico_path)
            if not hicon:
                dbg(f"set_window_icon: LoadImage failed for {ico_path}")
                return False
            _user32.SendMessageW(wintypes.HWND(hwnd), WM_SETICON, ICON_BIG, hicon)
            _user32.SendMessageW(wintypes.HWND(hwnd), WM_SETICON, ICON_SMALL, hicon)
            dbg(f"set_window_icon: icon set for hwnd={hwnd} from {ico_path}")
            return True
        except Exception:
            dbg("set_window_icon: exception")
            return False
else:
    def set_taskbar_appid(appid: str):
        return

    def set_window_icon(tk_root: tk.Tk, ico_path: str) -> bool:
        try:
            tk_root.iconbitmap(ico_path)
            return True
        except Exception:
            return False

# debug logging and hotkey thread native id
DEBUG_LOG = os.path.join(exe_dir(), "debug_log.txt")
HOTKEY_THREAD_NATIVE_ID = 0

def dbg(msg: str):
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")
    except Exception:
        pass

def log_exc(context: str = ""):
    try:
        tb = _traceback.format_exc()
        dbg(f"EXCEPTION ({context}):\n{tb}")
    except Exception:
        pass

def _ex_hook(exc_type, exc, tb):
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - Unhandled exception:\n")
            _traceback.print_exception(exc_type, exc, tb, file=f)
    except Exception:
        pass

sys.excepthook = _ex_hook

# thread-level exception hook (Python 3.8+)
def _thread_ex_hook(args):
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - Unhandled thread exception:\n")
            _traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=f)
    except Exception:
        pass

try:
    threading.excepthook = _thread_ex_hook
    dbg("threading.excepthook installed")
except Exception:
    dbg("threading.excepthook not available")

# atexit marker
def _at_exit():
    try:
        dbg("atexit: process exiting normally")
    except Exception:
        pass

atexit.register(_at_exit)

# Modifier masks for RegisterHotKey
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

# Hotkey action IDs (stable)
ACTION_IDS = {
    "create": 1,
    "toggle": 2,
    "delete": 3,
    "suspend_enh": 4
}

# Default bindings
DEFAULT_HOTKEYS = {
    "create": "Ctrl+Alt+C",
    "toggle": "Ctrl+Alt+T",
    "delete": "Ctrl+Alt+D",
    "suspend_enh": "Ctrl+Alt+E"
}

user32 = ctypes.windll.user32
WM_HOTKEY = 0x0312
WM_USER = 0x0400
WAKE_MSG = WM_USER + 100
RECORDING_PAUSE_HOTKEYS = threading.Event()

# Set function prototypes to help ctypes marshal arguments correctly (best-effort).
# Wrapped in try/except so this file is still importable on exotic environments.
try:
    user32.GetMessageW.restype = ctypes.c_int
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint]
except Exception:
    pass

try:
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
except Exception:
    pass

try:
    user32.PostThreadMessageW.restype = wintypes.BOOL
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
except Exception:
    pass

try:
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
except Exception:
    pass

NAMED_VK = {
    0x20: "Space", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc",
    0x26: "Up", 0x28: "Down", 0x25: "Left", 0x27: "Right",
    0x2D: "Ins", 0x2E: "Del", 0x24: "Home", 0x23: "End",
    0x21: "PageUp", 0x22: "PageDown",
}

# ----------------- embedded helper files -----------------
# (unchanged, not truncated here for brevity; keep your existing EMBEDDED_FILES dict content)
EMBEDDED_FILES = {
    # ... existing embedded scripts ...
}

def ensure_embedded_file(name: str) -> str:
    """
    Ensure the helper file exists next to exe or write it to %TEMP%\SPL_GTAVO.
    Returns the path to the helper file.
    """
    base = exe_dir()
    path_next = os.path.join(base, name)
    if os.path.exists(path_next):
        return path_next
    tmpdir = os.path.join(tempfile.gettempdir(), "SPL_GTAVO")
    os.makedirs(tmpdir, exist_ok=True)
    path = os.path.join(tmpdir, name)
    content = EMBEDDED_FILES.get(name)
    if content is None:
        raise FileNotFoundError(name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content.lstrip("\n"))
    try:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    except Exception:
        pass
    return path

def launch_bat(bat_or_name: str):
    """
    Launch a .bat file. Accepts either an absolute path or one of the embedded names
    (it will ensure the embedded file and any dependent PS1 helpers exist and return its path).
    """
    # If absolute path given, just run it
    if os.path.isabs(bat_or_name) and os.path.exists(bat_or_name):
        path = bat_or_name
    else:
        # Ensure the requested embedded file exists (writes to %TEMP%\SPL_GTAVO)
        path = ensure_embedded_file(bat_or_name)

        # If this is one of the BATs that expects a PS1 next to it, ensure the PS1 is also written.
        try:
            if bat_or_name == SUSPEND_ENH_BAT:
                ensure_embedded_file("suspend_resume_GTA5_Enhanced.ps1")
            elif bat_or_name == SUSPEND_GTA5_BAT:
                ensure_embedded_file("suspend_resume_GTA5.ps1")
            elif bat_or_name == TOGGLE_BAT:
                ensure_embedded_file(TOGGLE_PS1)
        except Exception:
            dbg(f"launch_bat: failed ensuring dependent PS1 for {bat_or_name}")

    try:
        subprocess.Popen([path], shell=False)
        return True, "Launched"
    except Exception as e:
        return False, str(e)

# ----------------- hotkey parsing and formatting -----------------
def load_hotkeys() -> dict:
    path = os.path.join(exe_dir(), HOTKEYS_FILE)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                h = json.load(f)
            for k, v in DEFAULT_HOTKEYS.items():
                if k not in h:
                    h[k] = v
            return h
        except Exception:
            return DEFAULT_HOTKEYS.copy()
    return DEFAULT_HOTKEYS.copy()

def save_hotkeys(h: dict) -> None:
    path = os.path.join(exe_dir(), HOTKEYS_FILE)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(h, f, indent=2)
    except Exception:
        pass

def parse_hotkey_string(s: str):
    s = s.strip()
    if not s:
        raise ValueError("Empty hotkey")
    parts = [p.strip() for p in s.split('+') if p.strip()]
    mods = 0
    key = None
    for p in parts:
        pp = p.lower()
        if pp in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif pp in ("alt",):
            mods |= MOD_ALT
        elif pp in ("shift",):
            mods |= MOD_SHIFT
        elif pp in ("win", "windows"):
            mods |= MOD_WIN
        else:
            key = p
    if key is None:
        raise ValueError("No key specified")
    if key.upper().startswith("F") and key[1:].isdigit():
        n = int(key[1:])
        if 1 <= n <= 24:
            vk = 0x70 + (n - 1)
        else:
            raise ValueError("Invalid function key")
    elif len(key) == 1:
        vk = ord(key.upper())
    else:
        name = key.lower()
        named = {
            "space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
            "esc": 0x1B, "escape": 0x1B, "up": 0x26, "down": 0x28,
            "left": 0x25, "right": 0x27, "ins": 0x2D, "del": 0x2E,
            "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
        }
        if name in named:
            vk = named[name]
        else:
            raise ValueError(f"Unknown key name: {key}")
    return mods, vk

def hotkey_to_string(mods: int, vk: int) -> str:
    parts = []
    if mods & MOD_CONTROL:
        parts.append("Ctrl")
    if mods & MOD_ALT:
        parts.append("Alt")
    if mods & MOD_SHIFT:
        parts.append("Shift")
    if mods & MOD_WIN:
        parts.append("Win")
    if vk in NAMED_VK:
        parts.append(NAMED_VK[vk])
    elif 0x70 <= vk <= 0x87:
        parts.append(f"F{vk - 0x6F}")
    else:
        try:
            parts.append(chr(vk).upper())
        except Exception:
            parts.append(str(vk))
    return "+".join(parts)

# ----------------- hotkey thread -----------------
def hotkey_thread_func(cmd_queue: "queue.Queue", event_queue: "queue.Queue", ready_event: threading.Event):
    """
    Dedicated thread that owns RegisterHotKey / UnregisterHotKey and runs GetMessage.
    It processes registration commands from cmd_queue and emits ("hotkey", id) in event_queue.
    """
    try:
        msg = wintypes.MSG()
        registered_ids = []
        PM_NOREMOVE = 0x0000
        try:
            # create this thread's message queue (non-blocking)
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)
        except Exception:
            dbg("hotkey_thread: PeekMessageW failed during startup (non-fatal)")
        # publish native thread id
        try:
            kernel32 = ctypes.windll.kernel32
            native_tid = kernel32.GetCurrentThreadId()
            globals()["HOTKEY_THREAD_NATIVE_ID"] = int(native_tid)
            dbg(f"Hotkey thread started (native tid={native_tid})")
        except Exception:
            dbg("Hotkey thread: failed to get native tid")
        ready_event.set()

        while True:
            # process pending commands (registration/stop)
            while True:
                try:
                    cmd = cmd_queue.get_nowait()
                except queue.Empty:
                    cmd = None
                    break
                if not cmd:
                    continue
                if cmd[0] == "register":
                    hotmap = cmd[1]
                    resp_q = cmd[2] if len(cmd) > 2 else None
                    # unregister previous
                    for aid in registered_ids:
                        try:
                            user32.UnregisterHotKey(None, aid)
                        except Exception:
                            pass
                    registered_ids.clear()
                    failed = None
                    for action, hk_str in hotmap.items():
                        aid = ACTION_IDS.get(action)
                        if aid is None:
                            failed = (action, "Unknown action id")
                            break
                        try:
                            mods, vk = parse_hotkey_string(hk_str)
                        except Exception as e:
                            failed = (action, str(e))
                            break
                        ok = bool(user32.RegisterHotKey(None, aid, mods, vk))
                        dbg(f"RegisterHotKey action={action} id={aid} hk={hk_str} ok={ok}")
                        if not ok:
                            failed = (action, f"RegisterHotKey failed for {hk_str}")
                            break
                        registered_ids.append(aid)
                    if failed:
                        # rollback
                        for aid in registered_ids:
                            try:
                                user32.UnregisterHotKey(None, aid)
                            except Exception:
                                pass
                        registered_ids.clear()
                        if resp_q:
                            resp_q.put(("failed", failed[0], failed[1]))
                    else:
                        if resp_q:
                            resp_q.put(("ok",))
                elif cmd[0] == "stop":
                    # unregister and respond
                    for aid in registered_ids:
                        try:
                            user32.UnregisterHotKey(None, aid)
                        except Exception:
                            pass
                    registered_ids.clear()
                    if len(cmd) > 1 and isinstance(cmd[1], queue.Queue):
                        cmd[1].put(("stopped",))
                    # post WM_QUIT to wake any GetMessageW
                    try:
                        tid = globals().get("HOTKEY_THREAD_NATIVE_ID") or threading.get_native_id()
                        user32.PostThreadMessageW(int(tid), 0x0012, 0, 0)
                    except Exception:
                        pass
                    return

            # block waiting for Windows messages
            res = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if res == 0:
                # WM_QUIT received
                break
            if res == -1:
                try:
                    event_queue.put(("error", "GetMessageW returned -1 in hotkey thread"))
                except Exception:
                    pass
                continue

            if msg.message == WM_HOTKEY:
                try:
                    dbg(f"hotkey msg received wParam={int(msg.wParam)}")
                    event_queue.put(("hotkey", int(msg.wParam)))
                except Exception:
                    pass

            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    except Exception:
        tb = _traceback.format_exc()
        try:
            event_queue.put(("error", tb))
        except Exception:
            pass
        for aid in registered_ids:
            try:
                user32.UnregisterHotKey(None, aid)
            except Exception:
                pass
        dbg("Hotkey thread exiting due to exception")

# ----------------- capture hotkey (by-press) -----------------
GetAsyncKeyState = user32.GetAsyncKeyState
VK_MIN = 1
VK_MAX = 254

def capture_hotkey_dialog(parent, timeout=12, entry_widget=None) -> list | None:
    """
    Record multiple captures during one recording session.

    - Each time a non-modifier key is pressed and then released, the combo is saved.
    - Saved combos are appended (comma-separated) to the provided entry_widget (if given).
    - The dialog stays open until Save, Cancel or timeout. Save/Cancel both close the dialog;
      already-saved combos are NOT reverted — use Reset to clear.
    - Returns a list of captured combos (possibly empty) or None on immediate abort.
    """
    top = tk.Toplevel(parent)
    top.title("Capture hotkey")
    top.geometry("+300+300")
    top.grab_set()
    tk.Label(top, text="Hold modifiers, press a key, then release to save that combo.\nRepeat to add more. Press Reset in the Hotkeys dialog to clear.").pack(padx=12, pady=(10,6))
    info = tk.StringVar(value="Waiting...")
    lbl = tk.Label(top, textvariable=info, fg="blue")
    lbl.pack(padx=12, pady=(0,8))
    btn_frame = tk.Frame(top)
    btn_frame.pack(pady=(0,10))

    captures: list[str] = []
    state = {
        "last_non_mod_vk": None,
        "last_mods": 0,
        "done": False,
        "pressed_non_mod": False
    }

    def close_and_return():
        state["done"] = True
        top.destroy()

    def on_save():
        close_and_return()

    def on_cancel():
        # Per your request, do not revert already-saved combos.
        close_and_return()

    ttk.Button(btn_frame, text="Save", command=on_save).pack(side="left", padx=6)
    ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side="left", padx=6)

    start = time.time()
    prev_non_mod = set()

    def commit_capture(vk, mods):
        hk = hotkey_to_string(mods, vk)
        if not captures or captures[-1] != hk:
            captures.append(hk)
            try:
                if entry_widget is not None:
                    # overwrite entry with comma-separated captures
                    entry_widget.delete(0, tk.END)
                    entry_widget.insert(0, ", ".join(captures))
            except Exception:
                pass
            info.set(f"Saved: {hk}  (continue recording or press Save/Cancel)")
            dbg(f"capture_hotkey_dialog: saved {hk}")

    def poll():
        if state["done"]:
            return
        elapsed = time.time() - start
        if elapsed > timeout:
            state["done"] = True
            top.destroy()
            return
        mods = 0
        if GetAsyncKeyState(0x11) & 0x8000:
            mods |= MOD_CONTROL
        if GetAsyncKeyState(0x12) & 0x8000:
            mods |= MOD_ALT
        if GetAsyncKeyState(0x10) & 0x8000:
            mods |= MOD_SHIFT
        if GetAsyncKeyState(0x5B) & 0x8000 or GetAsyncKeyState(0x5C) & 0x8000:
            mods |= MOD_WIN

        current_non_mod = set()
        for vk in range(VK_MIN, VK_MAX + 1):
            if vk in (0x11, 0x12, 0x10, 0x5B, 0x5C):
                continue
            if GetAsyncKeyState(vk) & 0x8000:
                current_non_mod.add(vk)

        # Detect press start
        if current_non_mod and not prev_non_mod:
            # first non-mod key pressed
            vk = next(iter(current_non_mod))
            state["last_non_mod_vk"] = vk
            state["last_mods"] = mods
            state["pressed_non_mod"] = True
            info.set(f"Captured (press+release to save): {hotkey_to_string(mods, vk)}")
        # Detect release -> commit the last captured key if any
        elif not current_non_mod and prev_non_mod:
            if state.get("pressed_non_mod") and state.get("last_non_mod_vk"):
                commit_capture(state["last_non_mod_vk"], state["last_mods"])
            state["pressed_non_mod"] = False
            state["last_non_mod_vk"] = None
        else:
            # update modifiers-only display
            display = []
            if mods & MOD_CONTROL:
                display.append("Ctrl")
            if mods & MOD_ALT:
                display.append("Alt")
            if mods & MOD_SHIFT:
                display.append("Shift")
            if mods & MOD_WIN:
                display.append("Win")
            if display:
                info.set("Modifiers: " + "+".join(display) + " — press and release a non-mod key to save")
            else:
                info.set("Waiting... (press Cancel to finish)")

        # store current state for next poll
        prev_non_mod.clear()
        prev_non_mod.update(current_non_mod)
        top.after(50, poll)

    top.bind("<Return>", lambda e: on_save())
    top.bind("<Escape>", lambda e: on_cancel())
    top.after(50, poll)
    parent.wait_window(top)
    return captures if captures else None

# ----------------- netsh helpers -----------------
def run_cmd(args, timeout=15):
    try:
        proc = subprocess.run(args, capture_output=True, text=True, shell=False, timeout=timeout)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return -1, "", str(e)

def create_rule():
    args = [
        "netsh", "advfirewall", "firewall", "add", "rule",
        f"name={RULE_NAME}", "dir=out", "action=block",
        "profile=any", "protocol=UDP", f"remoteport={REMOTE_PORTS}", "enable=yes"
    ]
    return run_cmd(args)

def show_rule():
    return run_cmd(["netsh", "advfirewall", "firewall", "show", "rule", f"name={RULE_NAME}"])

def set_rule_enable(enable: bool):
    val = "yes" if enable else "no"
    return run_cmd(["netsh", "advfirewall", "firewall", "set", "rule", f"name={RULE_NAME}", "new", f"enable={val}"])

def delete_rule():
    return run_cmd(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={RULE_NAME}"])

# ----------------- GUI -----------------
class App:
    def __init__(self, root: tk.Tk):
        # save the tkinter root
        self.root = root

        # try to set initial icon (both Tk and Win32)
        try:
            set_window_icon(self.root, resource_path(INACTIVE_ICON))
        except Exception:
            pass

        self.inactive_icon = resource_path(INACTIVE_ICON)
        self.active_icon = resource_path(ACTIVE_ICON) if os.path.exists(resource_path(ACTIVE_ICON)) else self.inactive_icon

        # bind focus changes to toggle the icon (use Win32 setter when possible)
        try:
            self.root.bind("<FocusIn>", lambda e: set_window_icon(self.root, self.active_icon))
            self.root.bind("<FocusOut>", lambda e: set_window_icon(self.root, self.inactive_icon))
        except Exception:
            pass

        # window title and sizing
        self.root.title("Solo Public Lobby V -Online")
        self.root.resizable(False, False)

        frm = ttk.Frame(self.root, padding=10)
        frm.grid()

        self.status = tk.StringVar(value="Starting...")
        ttk.Label(frm, text="Firewall Rule Status:").grid(column=0, row=0, sticky="w")
        ttk.Label(frm, textvariable=self.status, foreground="blue").grid(column=0, row=1, sticky="w")

        btns = ttk.Frame(frm)
        btns.grid(column=0, row=2, pady=(6,0))
        ttk.Button(btns, text="Create Rule", command=self.create).grid(column=0, row=0, padx=4)
        ttk.Button(btns, text="Toggle Enable", command=self.toggle).grid(column=1, row=0, padx=4)
        ttk.Button(btns, text="Delete Rule", command=self.delete).grid(column=2, row=0, padx=4)
        ttk.Button(btns, text="Hotkeys...", command=self.open_hotkeys_dialog).grid(column=3, row=0, padx=6)

        ttk.Separator(frm, orient="horizontal").grid(column=0, row=3, sticky="ew", pady=8)
        ttk.Button(frm, text="Suspend Enhanced (E)", command=self.suspend_enh).grid(column=0, row=4, sticky="ew", pady=(4,0))
        ttk.Button(frm, text="Suspend Legacy (S)", command=self.suspend_gta5).grid(column=0, row=5, sticky="ew", pady=(4,0))
        ttk.Separator(frm, orient="horizontal").grid(column=0, row=6, sticky="ew", pady=8)
        ctrl = ttk.Frame(frm)
        ctrl.grid(column=0, row=7, sticky="ew")
        ttk.Button(ctrl, text="Refresh", command=self.refresh).grid(column=0, row=0, padx=4)
        ttk.Button(ctrl, text="Quit", command=self.quit).grid(column=1, row=0, padx=4)
        ttk.Button(ctrl, text="About", command=self.show_about).grid(column=2, row=0, padx=4)

        # queues and hotkey thread
        self.event_q = queue.Queue()
        self.cmd_q = queue.Queue()
        self.hready = threading.Event()
        self.hk_thread = threading.Thread(target=hotkey_thread_func, args=(self.cmd_q, self.event_q, self.hready), daemon=True)
        self.hk_thread.start()
        if not self.hready.wait(timeout=3.0):
            messagebox.showwarning("Hotkeys", "Hotkey thread did not start correctly.")
            dbg("Hotkey thread did not signal ready within timeout")

        # load hotkeys and register them
        self.hotkeys = load_hotkeys()
        self.register_all_hotkeys()

        # start checking events and refresh UI
        self.root.after(100, self.check_queue)
        self.refresh()

    def set_active_icon(self, active: bool):
        try:
            ico = self.active_icon if active else self.inactive_icon
            if ico and os.path.exists(ico):
                self.root.iconbitmap(ico)
        except Exception:
            pass

    def check_queue(self):
        dbg("check_queue: checking event_q")
        try:
            while True:
                item = self.event_q.get_nowait()
                dbg(f"check_queue: got item {item}")
                if item[0] == "hotkey":
                    # If a recorder is active, ignore global hotkeys so they don't affect the main window.
                    if RECORDING_PAUSE_HOTKEYS.is_set():
                        dbg(f"check_queue: hotkey {item[1]} ignored due to recording in progress")
                        # drop the event
                        continue
                    try:
                        self.handle_hotkey(item[1])
                    except Exception:
                        tb = _traceback.format_exc()
                        try:
                            with open(os.path.join(exe_dir(), "crash_log.txt"), "a", encoding="utf-8") as f:
                                f.write(f"\n\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Exception in handle_hotkey:\n")
                                f.write(tb)
                        except Exception:
                            pass
                        messagebox.showerror("Error", "An exception occurred handling a hotkey. See crash_log.txt")
                elif item[0] == "error":
                    dbg(f"Hotkey thread error: {item[1]}")
        except queue.Empty:
            pass
        self.root.after(100, self.check_queue)

    def handle_hotkey(self, id_):
        dbg(f"handle_hotkey called with id={id_}")
        try:
            if id_ == ACTION_IDS["create"]:
                try:
                    self.create()
                except Exception:
                    log_exc("create")
                    messagebox.showerror("Create", "Error while creating rule. See crash_log.txt")
            elif id_ == ACTION_IDS["toggle"]:
                try:
                    self.toggle()
                except Exception:
                    log_exc("toggle")
                    messagebox.showerror("Toggle", "Error while toggling rule. See crash_log.txt")
            elif id_ == ACTION_IDS["delete"]:
                try:
                    if messagebox.askyesno("Confirm", "Delete the firewall rule?"):
                        self.delete()
                except Exception:
                    log_exc("delete")
                    messagebox.showerror("Delete", "Error while deleting rule. See crash_log.txt")
            elif id_ == ACTION_IDS["suspend_enh"]:
                try:
                    self.suspend_enh()
                except Exception:
                    log_exc("suspend_enh")
                    messagebox.showerror("Suspend", "Error while suspending. See crash_log.txt")
            else:
                dbg(f"handle_hotkey: unknown id {id_}")
        except Exception:
            raise

    def refresh(self):
        rc, out, err = show_rule()
        if rc != 0 or not out:
            self.status.set("Rule not present")
            return
        enabled = "Unknown"
        port = ""
        for line in out.splitlines():
            if line.strip().startswith("Enabled:"):
                enabled = line.split(":",1)[1].strip()
            if line.strip().startswith("RemotePort:"):
                port = line.split(":",1)[1].strip()
        self.status.set(f"Exists — Enabled: {enabled} — RemotePort: {port}")

    def create(self):
        rc, out, err = create_rule()
        if rc == 0:
            messagebox.showinfo("Create Rule", "Rule created.")
        else:
            messagebox.showerror("Create Rule", f"Failed (rc {rc})\n{err or out}")
        self.refresh()

    def toggle(self):
        rc, out, err = show_rule()
        if rc != 0 or not out:
            messagebox.showwarning("Toggle", "Rule not present. Create it first.")
            return
        enabled = None
        for line in out.splitlines():
            if line.strip().startswith("Enabled:"):
                enabled = line.split(":", 1)[1].strip().lower()
                break
        if enabled is None:
            messagebox.showwarning("Toggle", "Cannot parse rule state.")
            return
        target = not (enabled in ("yes", "true"))
        rc2, out2, err2 = set_rule_enable(target)
        if rc2 == 0:
            messagebox.showinfo("Toggle", f"Rule {'enabled' if target else 'disabled'}.")
        else:
            messagebox.showerror("Toggle", f"Failed (rc {rc2})\n{err2 or out2}")
        self.refresh()

    def delete(self):
        rc, out, err = delete_rule()
        if rc == 0:
            messagebox.showinfo("Delete Rule", "Rule deleted (if existed).")
        else:
            messagebox.showerror("Delete Rule", f"Failed (rc {rc})\n{err or out}")
        self.refresh()

    def suspend_enh(self):
        ok, msg = launch_bat(SUSPEND_ENH_BAT)
        if not ok:
            messagebox.showerror("Suspend", f"Failed to launch: {msg}")
        else:
            messagebox.showinfo("Suspend", "Suspend launched (check the script window).")

    def suspend_gta5(self):
        ok, msg = launch_bat(SUSPEND_GTA5_BAT)
        if not ok:
            messagebox.showerror("Suspend", f"Failed to launch: {msg}")
        else:
            messagebox.showinfo("Suspend", "Suspend launched (check the script window).")

    def show_about(self):
        """Show About dialog with version and diagnostic hints."""
        try:
            exe_location = exe_dir()
            txt = (
                f"Solo Public Lobby V -Online\n"
                f"Version: {VERSION}\n\n"
                "Notes:\n"
                "- If you report a bug, please include debug_log.txt and crash_log.txt\n"
                f"  (logs directory: {exe_location})\n"
                "- If you built a onefile EXE, include whether you used the distributed EXE or ran from Python.\n\n"
                "GitHub: https://github.com/NineO1/GTA-online-Solo-Public-Lobby.git"
            )
            messagebox.showinfo("About", txt)
        except Exception:
            try:
                messagebox.showinfo("About", f"Solo Public Lobby V -Online\nVersion: {VERSION}")
            except Exception:
                pass

    def quit(self):
        resp = queue.Queue()
        self.cmd_q.put(("stop", resp))
        try:
            tid = globals().get("HOTKEY_THREAD_NATIVE_ID") or getattr(self.hk_thread, "ident", 0)
            if tid:
                user32.PostThreadMessageW(int(tid), WAKE_MSG, 0, 0)
        except Exception:
            pass
        try:
            resp.get(timeout=1.0)
        except Exception:
            pass
        self.root.destroy()

    def register_all_hotkeys(self):
        resp = queue.Queue()
        self.cmd_q.put(("register", self.hotkeys.copy(), resp))
        try:
            tid = globals().get("HOTKEY_THREAD_NATIVE_ID") or getattr(self.hk_thread, "ident", 0)
            if tid:
                user32.PostThreadMessageW(int(tid), WAKE_MSG, 0, 0)
        except Exception:
            pass
        try:
            r = resp.get(timeout=3.0)
            dbg(f"register_all_hotkeys response: {r}")
        except Exception:
            dbg("register_all_hotkeys: no response from hotkey thread")
            messagebox.showwarning("Hotkeys", "No response from hotkey thread.")
            return False
        if r[0] == "ok":
            return True
        else:
            _, action, msg = r
            messagebox.showerror("Hotkey registration failed", f"Failed for {action}: {msg}")
            self.hotkeys = load_hotkeys()
            return False

    def open_hotkeys_dialog(self):
        dlg = HotkeysDialog(self.root, self.hotkeys)
        self.root.wait_window(dlg.top)
        if dlg.result:
            new_map = dlg.result
            old_map = self.hotkeys.copy()
            self.hotkeys = new_map
            ok = self.register_all_hotkeys()
            if ok:
                save_hotkeys(self.hotkeys)
                messagebox.showinfo("Hotkeys", "Hotkeys updated and saved.")
            else:
                self.hotkeys = old_map
                self.register_all_hotkeys()

# (HotkeysDialog and the rest remain unchanged)
# ----------------- elevation and main -----------------
def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def elevate_if_needed() -> None:
    if globals().get("NO_ELEV"):
        return
    if not is_admin():
        params = " ".join(f'"{a}"' for a in [os.path.abspath(__file__)] + sys.argv[1:])
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        sys.exit(0)

def main():
    elevate_if_needed()
    # set AppUserModelID early so Windows uses the correct taskbar grouping/icon
    try:
        set_taskbar_appid("com.solo_public_lobby.v.online")
    except Exception:
        pass

    if not is_admin():
        tk.Tk().withdraw()
        messagebox.showerror("Privileges", "This program must be run as Administrator.")
        return
    root = tk.Tk()
    app = App(root)
    root.mainloop()

if __name__ == "__main__":
    main()