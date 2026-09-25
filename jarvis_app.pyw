"""
Jarvis desktop launcher (run with pythonw.exe: no console window).

Starts the server hidden, opens Jarvis in its own Edge app window, and shuts the
server down when that window is closed. The desktop/Start-menu shortcuts point here.
"""

import ctypes
import os
import subprocess
import sys
import time
import urllib.request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
URL = "http://localhost:8340"
PYTHON = os.path.join(APP_DIR, ".venv", "Scripts", "python.exe")
LOG_PATH = os.path.join(APP_DIR, "jarvis.log")
# Separate Edge profile: keeps Jarvis's window, microphone permission and settings
# apart from the user's normal browsing, and lets us wait for exactly this window to close
PROFILE_DIR = os.path.join(os.environ["LOCALAPPDATA"], "JarvisApp", "edge-profile")
EDGE_CANDIDATES = [
    os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), r"Microsoft\Edge\Application\msedge.exe"),
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), r"Microsoft\Edge\Application\msedge.exe"),
]
CREATE_NO_WINDOW = 0x08000000
STARTUP_TIMEOUT_SECONDS = 60


def message(text: str, error: bool = True):
    ctypes.windll.user32.MessageBoxW(None, text, "Jarvis", 0x10 if error else 0x40)


def server_is_up() -> bool:
    try:
        urllib.request.urlopen(URL, timeout=2)
        return True
    except Exception:
        return False


def start_server() -> subprocess.Popen:
    log = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    log.write(f"\n===== Jarvis started {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    # python.exe with CREATE_NO_WINDOW gets an invisible console, which the PowerShell
    # commands Jarvis runs inherit, so no console windows flash up
    return subprocess.Popen(
        [PYTHON, "-u", "server.py"], cwd=APP_DIR,
        stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def stop_server(proc: subprocess.Popen):
    # /T also ends the server's children (e.g. the browser used for web searches)
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                   capture_output=True, creationflags=CREATE_NO_WINDOW)


def open_window() -> subprocess.Popen:
    edge = next((p for p in EDGE_CANDIDATES if os.path.exists(p)), None)
    if not edge:
        raise FileNotFoundError("Microsoft Edge was not found.")
    os.makedirs(PROFILE_DIR, exist_ok=True)
    return subprocess.Popen([
        edge,
        f"--app={URL}",
        f"--user-data-dir={PROFILE_DIR}",
        "--window-size=520,780",
        "--no-first-run",
        "--no-default-browser-check",
        # Let Jarvis's greeting and replies play without clicking the page first
        "--autoplay-policy=no-user-gesture-required",
        # Keep listening at full speed when the window is minimised or behind other windows.
        # Otherwise Edge treats it as hidden and throttles timers (down to once a minute),
        # so speech recognition restarts stall and the microphone seems to stop.
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion,IntensiveWakeUpThrottling",
    ])


def main():
    server = None
    if not server_is_up():
        if not os.path.exists(PYTHON):
            message(f"Jarvis's Python environment is missing:\n{PYTHON}")
            return
        server = start_server()
        deadline = time.time() + STARTUP_TIMEOUT_SECONDS
        while not server_is_up():
            if server.poll() is not None:
                message(f"The Jarvis server stopped while starting.\n\nDetails are in:\n{LOG_PATH}")
                return
            if time.time() > deadline:
                stop_server(server)
                message(f"The Jarvis server didn't start within {STARTUP_TIMEOUT_SECONDS} seconds.\n\nDetails are in:\n{LOG_PATH}")
                return
            time.sleep(0.5)

    try:
        window = open_window()
    except Exception as e:
        if server:
            stop_server(server)
        message(f"Couldn't open the Jarvis window: {e}")
        return

    # Only the launcher that started the server shuts it down, once its window closes.
    # (A second launch while Jarvis is open hands its window to the running Edge profile and exits.)
    window.wait()
    if server:
        stop_server(server)


if __name__ == "__main__":
    main()
